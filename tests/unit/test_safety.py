from __future__ import annotations

from pathlib import Path

import pytest

from cua.domain import (
    ActionSpec,
    ActionType,
    ControlOwner,
    GoalRequest,
    PolicyDecisionType,
    RiskLevel,
)
from cua.safety import (
    ActionGate,
    ActionRule,
    GateContext,
    GoalGateway,
    Redactor,
    RiskClassifier,
    load_policy,
)

POLICY_PATH = Path("policies/legacy_bank.yaml")
BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def policy():
    return load_policy(POLICY_PATH)


def test_policy_loads_expected_action_rules(policy) -> None:
    assert policy.application == "legacy-bank"

    assert (
        policy.actions[ActionType.CLICK]
        == ActionRule.CONDITIONAL
    )

    assert (
        policy.actions[ActionType.EXTRACT]
        == ActionRule.ALLOW
    )


def test_policy_allows_only_configured_origin_and_routes(
    policy,
) -> None:
    assert policy.is_url_allowed(
        f"{BASE_URL}/members"
    )

    assert policy.is_url_allowed(
        f"{BASE_URL}/members/100001/accounts"
    )

    assert not policy.is_url_allowed(
        "https://example.com/members"
    )

    assert not policy.is_url_allowed(
        f"{BASE_URL}/admin"
    )


def test_goal_gateway_accepts_normal_goal(policy) -> None:
    request = GoalRequest(
        goal=(
            "Find member 100001 and return "
            "their savings balance"
        ),
        target_profile="legacy-bank",
        entry_point="/members",
    )

    decision = GoalGateway(policy).admit(
        request,
        base_url=BASE_URL,
    )

    assert decision.decision == PolicyDecisionType.ALLOW


def test_goal_gateway_rejects_external_entry_point(
    policy,
) -> None:
    request = GoalRequest(
        goal="Find a member",
        target_profile="legacy-bank",
        entry_point="https://example.com/members",
    )

    decision = GoalGateway(policy).admit(
        request,
        base_url=BASE_URL,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.reason_code == "ENTRY_POINT_NOT_ALLOWED"


def test_goal_gateway_rejects_wrong_target_profile(
    policy,
) -> None:
    request = GoalRequest(
        goal="Find a member",
        target_profile="some-other-app",
        entry_point="/members",
    )

    decision = GoalGateway(policy).admit(
        request,
        base_url=BASE_URL,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert (
        decision.reason_code
        == "TARGET_PROFILE_NOT_ALLOWED"
    )


def test_goal_gateway_rejects_prohibited_goal(
    policy,
) -> None:
    request = GoalRequest(
        goal="Bypass authentication and open member data",
        target_profile="legacy-bank",
        entry_point="/members",
    )

    decision = GoalGateway(policy).admit(
        request,
        base_url=BASE_URL,
    )

    assert decision.decision == PolicyDecisionType.DENY
    assert decision.reason_code == "PROHIBITED_GOAL"


def test_risk_classifier_marks_input_reversible(
    policy,
) -> None:
    classifier = RiskClassifier(policy)

    risk = classifier.classify(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="100001",
        ),
        current_url=f"{BASE_URL}/members",
    )

    assert risk.level == RiskLevel.REVERSIBLE_WRITE
    assert risk.reversible is True


def test_risk_classifier_marks_review_click_irreversible(
    policy,
) -> None:
    classifier = RiskClassifier(policy)

    risk = classifier.classify(
        ActionSpec(type=ActionType.CLICK),
        current_url=(
            f"{BASE_URL}"
            "/members/100001/accounts/new/review"
        ),
    )

    assert risk.level == RiskLevel.IRREVERSIBLE
    assert risk.reversible is False


def test_action_gate_allows_safe_high_confidence_read(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(type=ActionType.READ),
            current_url=f"{BASE_URL}/members/100001",
            target_confidence=0.99,
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.ALLOW
    )
    assert result.risk.level == RiskLevel.SAFE


def test_action_gate_requires_checkpoint_for_reversible_write(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value="100001",
            ),
            current_url=f"{BASE_URL}/members",
            target_confidence=0.99,
            has_checkpoint=False,
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.DENY
    )
    assert (
        result.decision.reason_code
        == "REVERSIBLE_WRITE_REQUIRES_CHECKPOINT"
    )

    allowed = gate.evaluate(
        GateContext(
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value="100001",
            ),
            current_url=f"{BASE_URL}/members",
            target_confidence=0.99,
            has_checkpoint=True,
        )
    )

    assert (
        allowed.decision.decision
        == PolicyDecisionType.ALLOW
    )


def test_action_gate_escalates_low_confidence_target(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(type=ActionType.READ),
            current_url=f"{BASE_URL}/members/100001",
            target_confidence=0.50,
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.TAKEOVER_REQUIRED
    )


def test_irreversible_action_requires_human_approval(
    policy,
) -> None:
    gate = ActionGate(policy)

    review_url = (
        f"{BASE_URL}"
        "/members/100001/transfer/review"
    )

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(type=ActionType.CLICK),
            current_url=review_url,
            target_confidence=0.99,
        )
    )

    assert result.risk.level == RiskLevel.IRREVERSIBLE
    assert (
        result.decision.decision
        == PolicyDecisionType.APPROVAL_REQUIRED
    )

    approved = gate.evaluate(
        GateContext(
            action=ActionSpec(type=ActionType.CLICK),
            current_url=review_url,
            target_confidence=0.99,
            human_approval_granted=True,
        )
    )

    assert (
        approved.decision.decision
        == PolicyDecisionType.ALLOW
    )


def test_low_confidence_irreversible_action_requires_takeover(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(type=ActionType.CLICK),
            current_url=(
                f"{BASE_URL}"
                "/members/100001/withdraw/review"
            ),
            target_confidence=0.40,
            human_approval_granted=True,
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.TAKEOVER_REQUIRED
    )


def test_action_gate_blocks_external_navigation(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(
                type=ActionType.NAVIGATE,
                value="https://example.com",
            ),
            current_url=f"{BASE_URL}/members",
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.DENY
    )
    assert (
        result.decision.reason_code
        == "NAVIGATION_NOT_ALLOWED"
    )


def test_action_gate_blocks_automation_during_human_control(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(type=ActionType.READ),
            current_url=f"{BASE_URL}/members",
            target_confidence=0.99,
            control_owner=ControlOwner.HUMAN,
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.DENY
    )

    assert (
        result.decision.reason_code
        == "CONTROL_NOT_OWNED_BY_AUTOMATION"
    )


def test_action_gate_allows_initial_allowlisted_navigation(
    policy,
) -> None:
    gate = ActionGate(policy)

    result = gate.evaluate(
        GateContext(
            action=ActionSpec(
                type=ActionType.NAVIGATE,
                value=f"{BASE_URL}/",
            ),
            current_url="about:blank",
        )
    )

    assert (
        result.decision.decision
        == PolicyDecisionType.ALLOW
    )


def test_redactor_removes_never_persist_fields(
    policy,
) -> None:
    redactor = Redactor(policy)

    payload = {
        "member_id": "100001",
        "api_key": "super-secret-key",
        "nested": {
            "account_number": "123456789",
            "status": "ready",
        },
    }

    redacted = redactor.redact(payload)

    assert redacted["member_id"] == "[REDACTED]"
    assert "api_key" not in redacted

    assert (
        redacted["nested"]["account_number"]
        == "[REDACTED]"
    )

    assert redacted["nested"]["status"] == "ready"


def test_redactor_scrubs_sensitive_values_from_text(
    policy,
) -> None:
    redactor = Redactor(policy)

    inputs = {
        "member_id": "100001",
        "other": "safe",
    }

    sensitive_values = (
        redactor.sensitive_values_from_inputs(inputs)
    )

    result = redactor.redact_text(
        "Searching member 100001",
        sensitive_values=sensitive_values,
    )

    assert result == "Searching member [REDACTED]"