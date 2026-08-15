from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from cua.domain import (
    ActionProposal,
    ActionSpec,
    ActionType,
    AgentDecision,
    AgentDecisionState,
    ApplicationCompatibility,
    AttributeStrategy,
    BusinessOutcomeRule,
    CapabilityArtifact,
    CapabilityIdentity,
    CapabilityMetadata,
    CapabilityPolicy,
    CapabilityStep,
    CheckpointSpec,
    CheckpointType,
    CompatibilitySpec,
    ControlOwner,
    ExecutionResult,
    ExecutionStatus,
    GoalRequest,
    InputDefinition,
    InterventionKind,
    InterventionRequest,
    OutputDefinition,
    ResolvedTarget,
    RetrySpec,
    RiskLevel,
    RiskSpec,
    SchemaValueType,
    SemanticStrategy,
    SurfaceKind,
    TargetSpec,
)


def member_input_target() -> TargetSpec:
    return TargetSpec(
        logical_name="member_number_input",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="f_14",
            ),
        ],
    )


def test_goal_request_defaults_and_bounds() -> None:
    request = GoalRequest(
        goal=(
            "Find member 100001 and return "
            "their savings balance"
        ),
        target_profile="legacy-bank",
        entry_point="/members",
    )

    assert request.max_steps == 20
    assert request.timeout_seconds == 120

    with pytest.raises(ValidationError):
        GoalRequest(
            goal="lookup member",
            target_profile="legacy-bank",
            entry_point="/members",
            max_steps=0,
        )


def test_target_strategy_is_discriminated_and_ordered() -> None:
    target = TargetSpec(
        logical_name="search_button",
        strategies=[
            SemanticStrategy(
                role="button",
                accessible_name="F8 SEARCH",
            ),
            AttributeStrategy(
                attribute="name",
                value="cmd_8",
            ),
        ],
    )

    assert target.strategies[0].kind == "semantic"
    assert target.strategies[1].kind == "attribute"


def test_continue_decision_requires_action() -> None:
    with pytest.raises(ValidationError):
        AgentDecision(
            state=AgentDecisionState.CONTINUE,
            intent="Search for the member",
        )

    decision = AgentDecision(
        state=AgentDecisionState.CONTINUE,
        intent="Enter the member number",
        action=ActionProposal(
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value="100001",
            ),
            target=member_input_target(),
        ),
    )

    assert decision.action is not None


def test_checkpoint_rejects_missing_required_payload() -> None:
    with pytest.raises(ValidationError):
        CheckpointSpec(
            type=CheckpointType.CONTROL_VALUE
        )

    checkpoint = CheckpointSpec(
        type=CheckpointType.CONTROL_VALUE,
        target=member_input_target(),
        expected="{{member_id}}",
    )

    assert checkpoint.expected == "{{member_id}}"


def test_capability_round_trip_json_contract() -> None:
    artifact = CapabilityArtifact(
        capability=CapabilityIdentity(
            id="lookup_member_savings",
            version="1.0.0",
            name="Lookup Member Savings Balance",
            description=(
                "Return the current savings balance "
                "for a member"
            ),
        ),
        application=ApplicationCompatibility(
            family="legacy-bank-core",
            surface=SurfaceKind.BROWSER,
            entry_point="/members",
            compatibility=CompatibilitySpec(
                version_range="7.x"
            ),
        ),
        inputs={
            "member_id": InputDefinition(
                type=SchemaValueType.STRING,
                required=True,
                sensitive=True,
                pattern=r"^[0-9]{6}$",
            )
        },
        outputs={
            "savings_balance": OutputDefinition(
                type=SchemaValueType.DECIMAL,
                nullable=False,
            )
        },
        steps=[
            CapabilityStep(
                id="enter-member-number",
                action=ActionSpec(
                    type=ActionType.INPUT_TEXT,
                    value="{{member_id}}",
                ),
                target=member_input_target(),
                risk=RiskSpec(
                    level=RiskLevel.SAFE,
                    reversible=True,
                ),
                checkpoint=CheckpointSpec(
                    type=CheckpointType.CONTROL_VALUE,
                    target=member_input_target(),
                    expected="{{member_id}}",
                ),
                retry=RetrySpec(max_attempts=1),
            )
        ],
        business_outcomes=[
            BusinessOutcomeRule(
                code="MEMBER_NOT_FOUND",
                detect=CheckpointSpec(
                    type=CheckpointType.TEXT_PRESENT,
                    value="NO MEMBER FOUND",
                ),
            )
        ],
        success_condition=CheckpointSpec(
            type=CheckpointType.OUTPUT_EXTRACTABLE,
            output="savings_balance",
        ),
        policy=CapabilityPolicy(
            risk="read_only"
        ),
        metadata=CapabilityMetadata(
            created_from_run="discovery-test"
        ),
    )

    raw = artifact.model_dump_json()
    decoded = json.loads(raw)

    restored = CapabilityArtifact.model_validate_json(raw)

    assert decoded["schema_version"] == "1.0"

    assert (
        decoded["steps"][0]["action"]["value"]
        == "{{member_id}}"
    )

    assert restored == artifact


def test_artifact_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ActionSpec(
            type=ActionType.CLICK,
            unexpected="not allowed",
        )  # type: ignore[call-arg]


def test_business_outcome_result_requires_code() -> None:
    with pytest.raises(ValidationError):
        ExecutionResult(
            run_id="run-1",
            status=ExecutionStatus.BUSINESS_OUTCOME,
            duration_ms=10,
        )

    result = ExecutionResult(
        run_id="run-1",
        status=ExecutionStatus.BUSINESS_OUTCOME,
        code="MEMBER_NOT_FOUND",
        duration_ms=10,
    )

    assert result.code == "MEMBER_NOT_FOUND"


def test_intervention_request_transfers_control_to_human() -> None:
    request = InterventionRequest(
        intervention_id="int-1",
        run_id="run-1",
        kind=InterventionKind.TAKEOVER,
        reason_code="UNEXPECTED_DIALOG",
        goal_or_capability="lookup_member_savings",
        current_step="open-accounts",
        completed_steps=[
            "enter-member-number",
            "submit-member-search",
        ],
        state_summary=(
            "Unexpected supervisor override "
            "dialog is visible"
        ),
        screenshot_ref="evidence/run-1/before.png",
        requested_human_action=(
            "Resolve the dialog and signal resume"
        ),
    )

    assert request.control_owner == ControlOwner.HUMAN


def test_resolved_target_excludes_runtime_surface_handle() -> None:
    handle = object()

    resolved = ResolvedTarget(
        logical_name="search_button",
        strategy_kind="semantic",
        confidence=0.99,
        candidate_count=1,
        evidence={
            "role": "button",
            "name": "F8 SEARCH",
        },
        surface_handle=handle,
    )

    assert resolved.surface_handle is handle
    assert "surface_handle" not in resolved.model_dump()