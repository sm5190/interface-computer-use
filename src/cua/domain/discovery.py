from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field, model_validator

from .actions import ActionSpec, TargetSpec
from .base import DomainModel
from .enums import ActionType, AgentDecisionState, CheckpointType, SurfaceKind


class GoalRequest(DomainModel):
    goal: str = Field(min_length=1)
    target_profile: str = Field(min_length=1)
    entry_point: str = Field(min_length=1)
    max_steps: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    metadata: dict[str, str] = Field(default_factory=dict)


class BoundingBox(DomainModel):
    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class SurfaceLocation(DomainModel):
    uri: str
    frame_path: list[str] = Field(default_factory=list)


class ObservedControl(DomainModel):
    control_id: str | None = None
    role: str | None = None
    accessible_name: str | None = None
    text: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    visible: bool = True
    frame_path: list[str] = Field(default_factory=list)
    bounds: BoundingBox | None = None


class ObservedDialog(DomainModel):
    title: str | None = None
    text: str = ""
    modal: bool = True


class FrameObservation(DomainModel):
    name: str | None = None
    url: str | None = None
    frame_path: list[str] = Field(default_factory=list)


class Observation(DomainModel):
    surface: SurfaceKind
    location: SurfaceLocation
    page_title: str | None = None
    controls: list[ObservedControl] = Field(default_factory=list)
    visible_text: list[str] = Field(default_factory=list)
    dialogs: list[ObservedDialog] = Field(default_factory=list)
    screenshot_ref: str
    frame_contexts: list[FrameObservation] = Field(default_factory=list)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class CheckpointSpec(DomainModel):
    type: CheckpointType
    target: TargetSpec | None = None
    value: str | None = None
    expected: str | int | float | bool | None = None
    pattern: str | None = None
    output: str | None = None
    all_of: list[CheckpointSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_required_payload(self) -> CheckpointSpec:
        if self.type in {
            CheckpointType.CONTROL_PRESENT,
            CheckpointType.CONTROL_ABSENT,
        }:
            if self.target is None:
                raise ValueError(f"{self.type} requires target")

        elif self.type == CheckpointType.CONTROL_VALUE:
            if self.target is None or self.expected is None:
                raise ValueError(
                    "control_value requires target and expected"
                )

        elif self.type in {
            CheckpointType.TEXT_PRESENT,
            CheckpointType.DIALOG_PRESENT,
        }:
            if not self.value:
                raise ValueError(f"{self.type} requires value")

        elif self.type == CheckpointType.URL_MATCHES:
            if not self.pattern:
                raise ValueError("url_matches requires pattern")

        elif self.type == CheckpointType.OUTPUT_EXTRACTABLE:
            if not self.output:
                raise ValueError(
                    "output_extractable requires output"
                )

        elif self.type == CheckpointType.PAGE_STATE:
            if not self.all_of:
                raise ValueError(
                    "page_state requires at least one nested checkpoint"
                )

        return self


class ActionProposal(DomainModel):
    action: ActionSpec
    target: TargetSpec | None = None

    # Only EXTRACT actions declare where the extracted value
    # should be stored in the discovery output state.
    output: str | None = None

    @model_validator(mode="after")
    def validate_action_contract(self) -> ActionProposal:
        targeted_actions = {
            ActionType.CLICK,
            ActionType.INPUT_TEXT,
            ActionType.SELECT_OPTION,
            ActionType.READ,
            ActionType.EXTRACT,
        }

        if self.action.type in targeted_actions and self.target is None:
            raise ValueError(
                f"{self.action.type} requires target"
            )

        if (
            self.action.type == ActionType.EXTRACT
            and not self.output
        ):
            raise ValueError(
                "extract action requires output"
            )

        if (
            self.action.type != ActionType.EXTRACT
            and self.output is not None
        ):
            raise ValueError(
                "only extract actions may declare output"
            )

        return self


class ExpectedEffect(DomainModel):
    summary: str = Field(min_length=1)
    checkpoint: CheckpointSpec | None = None


class Uncertainty(DomainModel):
    reasons: list[str] = Field(default_factory=list)
    self_reported_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class AgentDecision(DomainModel):
    state: AgentDecisionState
    intent: str = Field(min_length=1)
    action: ActionProposal | None = None
    expected_effect: ExpectedEffect | None = None
    outputs: dict[str, Any] | None = None
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)

    @model_validator(mode="after")
    def validate_state_action_contract(self) -> AgentDecision:
        if (
            self.state == AgentDecisionState.CONTINUE
            and self.action is None
        ):
            raise ValueError(
                "CONTINUE requires an action proposal"
            )

        if (
            self.state != AgentDecisionState.CONTINUE
            and self.action is not None
        ):
            raise ValueError(
                "Only CONTINUE may include an action proposal"
            )

        return self