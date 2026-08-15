from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .actions import ActionSpec
from .base import DomainModel
from .enums import (
    Actor,
    ControlOwner,
    ExecutionMode,
    ExecutionStatus,
    InterventionKind,
    PolicyDecisionType,
    ResolutionStrategyKind,
    RunState,
)


class ResolutionEvidence(DomainModel):
    logical_name: str
    strategy_kind: ResolutionStrategyKind
    confidence: float = Field(ge=0.0, le=1.0)
    candidate_count: int = Field(ge=0)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ResolvedTarget(DomainModel):
    logical_name: str = Field(min_length=1)
    strategy_kind: ResolutionStrategyKind
    confidence: float = Field(ge=0.0, le=1.0)
    candidate_count: int = Field(ge=0)
    evidence: dict[str, Any] = Field(default_factory=dict)

    surface_handle: Any = Field(
        exclude=True,
        repr=False,
    )


class PolicyDecision(DomainModel):
    decision: PolicyDecisionType
    reason_code: str | None = None
    reason: str | None = None


class CheckpointResult(DomainModel):
    passed: bool
    expected: Any | None = None
    observed: Any | None = None
    details: str | None = None


class StepRecord(DomainModel):
    run_id: str = Field(min_length=1)
    step_index: int = Field(ge=0)
    actor: Actor
    mode: ExecutionMode

    intent: str | None = None
    action: ActionSpec | None = None
    target_summary: dict[str, Any] | None = None

    resolution: ResolutionEvidence | None = None
    policy_decision: PolicyDecision | None = None
    checkpoint_result: CheckpointResult | None = None

    outcome_code: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)


class ExecutionResult(DomainModel):
    run_id: str = Field(min_length=1)
    status: ExecutionStatus
    code: str | None = None

    capability_id: str | None = None
    capability_version: str | None = None

    outputs: dict[str, Any] = Field(default_factory=dict)

    current_step: str | None = None
    expected: Any | None = None
    observed: Any | None = None

    evidence: list[str] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_result_code(self) -> ExecutionResult:
        statuses_requiring_code = {
            ExecutionStatus.BUSINESS_OUTCOME,
            ExecutionStatus.FAILURE,
            ExecutionStatus.REJECTED,
        }

        if (
            self.status in statuses_requiring_code
            and not self.code
        ):
            raise ValueError(
                f"{self.status} requires code"
            )

        return self


class InterventionRequest(DomainModel):
    intervention_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)

    kind: InterventionKind
    reason_code: str = Field(min_length=1)

    goal_or_capability: str = Field(min_length=1)
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)

    state_summary: str = Field(min_length=1)
    screenshot_ref: str = Field(min_length=1)

    requested_human_action: str = Field(min_length=1)

    control_owner: ControlOwner = ControlOwner.HUMAN

    @model_validator(mode="after")
    def require_human_owner(self) -> InterventionRequest:
        if self.control_owner != ControlOwner.HUMAN:
            raise ValueError(
                "InterventionRequest must transfer control to HUMAN"
            )

        return self


class RunStateSnapshot(DomainModel):
    run_id: str = Field(min_length=1)

    state: RunState = RunState.CREATED
    control_owner: ControlOwner = ControlOwner.AUTOMATION

    completed_steps: list[str] = Field(default_factory=list)
    current_step: str | None = None