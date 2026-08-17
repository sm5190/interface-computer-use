from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from cua.domain import (
    ApplicationCompatibility,
    BusinessOutcomeRule,
    CapabilityIdentity,
    CheckpointSpec,
    HardFailureRule,
    InputDefinition,
    OutputDefinition,
    RetrySpec,
)
from cua.domain.base import DomainModel


class InputBinding(DomainModel):
    """
    Connects one invocation parameter to the concrete value
    used during discovery.

    This model is compiler input only. It is not persisted
    inside the generated capability artifact.
    """

    definition: InputDefinition

    discovery_value: str | int | float | bool

    # Allows:
    #   100001 -> {{member_id}}
    #   /members/100001 -> /members/{{member_id}}
    #
    # This is deterministic substitution, not inference.
    replace_inside_strings: bool = True


class TrajectoryWindow(DomainModel):
    """
    Defines which part of a discovery run belongs to the
    reusable capability.

    This lets session bootstrap/authentication remain outside
    the compiled workflow.
    """

    start_step_index: int = Field(default=0, ge=0)
    end_step_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_window(self) -> TrajectoryWindow:
        if (
            self.end_step_index is not None
            and self.end_step_index < self.start_step_index
        ):
            raise ValueError(
                "end_step_index must be >= start_step_index"
            )

        return self


class CapabilityRecipe(DomainModel):
    """
    Reviewable compiler input.

    Application-specific facts live here as data rather than
    being hard-coded in GenericCapabilityCompiler.
    """

    capability: CapabilityIdentity

    application: ApplicationCompatibility

    inputs: dict[str, InputBinding] = Field(
        default_factory=dict
    )

    outputs: dict[str, OutputDefinition] = Field(
        default_factory=dict
    )

    business_outcomes: list[BusinessOutcomeRule] = Field(
        default_factory=list
    )

    hard_failures: list[HardFailureRule] = Field(
        default_factory=list
    )

    success_condition: CheckpointSpec
    step_retries: dict[str, RetrySpec] = Field(
        default_factory=dict
    )

    trajectory: TrajectoryWindow = Field(
        default_factory=TrajectoryWindow
    )

    default_timeout_ms: int = Field(
        default=5000,
        ge=1,
        le=120_000,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )