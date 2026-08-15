from __future__ import annotations

from pydantic import Field

from cua.domain import (
    ActionSpec,
    ActionType,
    ControlOwner,
    GoalRequest,
    PolicyDecision,
    PolicyDecisionType,
    RiskLevel,
    RiskSpec,
)
from cua.domain.base import DomainModel

from .policy import ActionRule, ApplicationPolicy
from .risk import RiskClassifier

_TARGETED_ACTIONS = {
    ActionType.CLICK,
    ActionType.INPUT_TEXT,
    ActionType.SELECT_OPTION,
    ActionType.READ,
    ActionType.EXTRACT,
}


class GateContext(DomainModel):
    action: ActionSpec
    current_url: str

    control_owner: ControlOwner = ControlOwner.AUTOMATION

    target_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    has_checkpoint: bool = False
    human_approval_granted: bool = False


class ActionGateResult(DomainModel):
    risk: RiskSpec
    decision: PolicyDecision


class GoalGateway:
    def __init__(self, policy: ApplicationPolicy) -> None:
        self._policy = policy

    def admit(
        self,
        request: GoalRequest,
        *,
        base_url: str,
    ) -> PolicyDecision:
        if request.target_profile != self._policy.application:
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason_code="TARGET_PROFILE_NOT_ALLOWED",
                reason=(
                    f"Target profile {request.target_profile!r} "
                    "does not match configured application"
                ),
            )

        if (
            request.max_steps
            > self._policy.goal_policy.max_steps
        ):
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason_code="MAX_STEPS_EXCEEDS_POLICY",
                reason="Requested max_steps exceeds policy limit",
            )

        if (
            request.timeout_seconds
            > self._policy.goal_policy.max_timeout_seconds
        ):
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason_code="TIMEOUT_EXCEEDS_POLICY",
                reason=(
                    "Requested timeout_seconds exceeds "
                    "policy limit"
                ),
            )

        normalized_goal = request.goal.casefold()

        for phrase in self._policy.goal_policy.forbidden_phrases:
            if phrase.casefold() in normalized_goal:
                return PolicyDecision(
                    decision=PolicyDecisionType.DENY,
                    reason_code="PROHIBITED_GOAL",
                    reason=(
                        "Goal contains a prohibited policy phrase"
                    ),
                )

        if not self._policy.is_url_allowed(
            request.entry_point,
            base_url=base_url,
        ):
            return PolicyDecision(
                decision=PolicyDecisionType.DENY,
                reason_code="ENTRY_POINT_NOT_ALLOWED",
                reason="Goal entry point is outside the allowlist",
            )

        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason_code="GOAL_ADMITTED",
            reason="Goal satisfies configured admission policy",
        )


class ActionGate:
    def __init__(
        self,
        policy: ApplicationPolicy,
        risk_classifier: RiskClassifier | None = None,
    ) -> None:
        self._policy = policy
        self._risk_classifier = (
            risk_classifier or RiskClassifier(policy)
        )

    def evaluate(
        self,
        context: GateContext,
    ) -> ActionGateResult:
        risk = self._risk_classifier.classify(
            context.action,
            current_url=context.current_url,
        )

        if context.control_owner != ControlOwner.AUTOMATION:
            return self._result(
                risk,
                PolicyDecisionType.DENY,
                "CONTROL_NOT_OWNED_BY_AUTOMATION",
                "Automation does not currently own the session",
            )

        if context.current_url == "about:blank":
            if context.action.type != ActionType.NAVIGATE:
                return self._result(
                    risk,
                    PolicyDecisionType.DENY,
                    "ACTION_FROM_BLANK_SURFACE",
                    (
                        "Only allowlisted navigation is permitted "
                        "from about:blank"
                    ),
                )

        elif not self._policy.is_url_allowed(
            context.current_url
        ):
            return self._result(
                risk,
                PolicyDecisionType.DENY,
                "CURRENT_LOCATION_NOT_ALLOWED",
                "Current surface location is outside policy",
            )

        rule = self._policy.actions.get(
            context.action.type,
            ActionRule.DENY,
        )

        if rule == ActionRule.DENY:
            return self._result(
                risk,
                PolicyDecisionType.DENY,
                "ACTION_TYPE_NOT_ALLOWED",
                (
                    f"Action type {context.action.type} "
                    "is denied by policy"
                ),
            )

        if context.action.type == ActionType.NAVIGATE:
            destination = context.action.value

            if not isinstance(destination, str):
                return self._result(
                    risk,
                    PolicyDecisionType.DENY,
                    "INVALID_NAVIGATION_TARGET",
                    "Navigation target must be a URL string",
                )

            if not self._policy.is_url_allowed(
                destination,
                base_url=context.current_url
                if context.current_url != "about:blank"
                else self._policy.allowed_origins[0],
            ):
                return self._result(
                    risk,
                    PolicyDecisionType.DENY,
                    "NAVIGATION_NOT_ALLOWED",
                    "Navigation destination is outside policy",
                )

        if context.action.type in _TARGETED_ACTIONS:
            if context.target_confidence is None:
                return self._result(
                    risk,
                    PolicyDecisionType.DENY,
                    "MISSING_GROUNDING_EVIDENCE",
                    (
                        "Targeted action requires deterministic "
                        "grounding confidence"
                    ),
                )

            minimum = (
                self._policy
                .confidence_policy
                .low_risk_min_autonomous
            )

            if context.target_confidence < minimum:
                reason_code = (
                    "LOW_CONFIDENCE_HIGH_RISK"
                    if risk.level == RiskLevel.IRREVERSIBLE
                    else "LOW_TARGET_CONFIDENCE"
                )

                return self._result(
                    risk,
                    PolicyDecisionType.TAKEOVER_REQUIRED,
                    reason_code,
                    (
                        "Target confidence is below the "
                        "autonomous execution threshold"
                    ),
                )

        if risk.level == RiskLevel.IRREVERSIBLE:
            if not context.human_approval_granted:
                return self._result(
                    risk,
                    PolicyDecisionType.APPROVAL_REQUIRED,
                    "IRREVERSIBLE_ACTION_REQUIRES_APPROVAL",
                    (
                        "Irreversible action requires explicit "
                        "human approval"
                    ),
                )

            return self._result(
                risk,
                PolicyDecisionType.ALLOW,
                "HUMAN_APPROVAL_VERIFIED",
                (
                    "Irreversible action has explicit "
                    "human approval"
                ),
            )

        if risk.level == RiskLevel.REVERSIBLE_WRITE:
            if not context.has_checkpoint:
                return self._result(
                    risk,
                    PolicyDecisionType.DENY,
                    "REVERSIBLE_WRITE_REQUIRES_CHECKPOINT",
                    (
                        "Reversible write actions require "
                        "a checkpoint"
                    ),
                )

        return self._result(
            risk,
            PolicyDecisionType.ALLOW,
            "ACTION_ALLOWED",
            "Action satisfies configured policy",
        )

    @staticmethod
    def _result(
        risk: RiskSpec,
        decision: PolicyDecisionType,
        reason_code: str,
        reason: str,
    ) -> ActionGateResult:
        return ActionGateResult(
            risk=risk,
            decision=PolicyDecision(
                decision=decision,
                reason_code=reason_code,
                reason=reason,
            ),
        )