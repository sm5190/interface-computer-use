from __future__ import annotations

from pydantic import Field, model_validator

from cua.domain import (
    ApplicationCompatibility,
    BusinessOutcomeRule,
    CapabilityIdentity,
    CapabilityPolicy,
    CheckpointSpec,
    InputDefinition,
    OutputDefinition,
    StepRecord,
)
from cua.domain.base import DomainModel


class DiscoveryTrajectory(DomainModel):
    run_id: str = Field(min_length=1)
    steps: list[StepRecord] = Field(default_factory=list)


class CompilationSpec(DomainModel):
    capability: CapabilityIdentity
    application: ApplicationCompatibility

    inputs: dict[str, InputDefinition]
    outputs: dict[str, OutputDefinition]

    # Ordered logical targets that define the reusable workflow.
    required_target_order: list[str] = Field(min_length=1)

    # Stable artifact step ID for each selected logical target.
    step_ids: dict[str, str]

    # target logical name -> capability input name
    input_bindings: dict[str, str] = Field(
        default_factory=dict
    )

    # target logical name -> capability output name
    output_bindings: dict[str, str] = Field(
        default_factory=dict
    )

    # Optional stronger checkpoints added during compilation.
    checkpoint_overrides: dict[
        str,
        CheckpointSpec,
    ] = Field(default_factory=dict)

    business_outcomes: list[BusinessOutcomeRule] = Field(
        default_factory=list
    )

    success_condition: CheckpointSpec

    policy: CapabilityPolicy

    @model_validator(mode="after")
    def validate_bindings(
        self,
    ) -> CompilationSpec:
        required_targets = set(
            self.required_target_order
        )

        if set(self.step_ids) != required_targets:
            raise ValueError(
                "step_ids must contain exactly one entry "
                "for every required target"
            )

        unknown_input_targets = (
            set(self.input_bindings)
            - required_targets
        )

        if unknown_input_targets:
            raise ValueError(
                "input bindings reference unknown targets: "
                f"{sorted(unknown_input_targets)}"
            )

        unknown_output_targets = (
            set(self.output_bindings)
            - required_targets
        )

        if unknown_output_targets:
            raise ValueError(
                "output bindings reference unknown targets: "
                f"{sorted(unknown_output_targets)}"
            )

        for input_name in self.input_bindings.values():
            if input_name not in self.inputs:
                raise ValueError(
                    f"Unknown capability input: {input_name}"
                )

        for output_name in self.output_bindings.values():
            if output_name not in self.outputs:
                raise ValueError(
                    f"Unknown capability output: {output_name}"
                )

        unknown_checkpoint_targets = (
            set(self.checkpoint_overrides)
            - required_targets
        )

        if unknown_checkpoint_targets:
            raise ValueError(
                "checkpoint overrides reference "
                "unknown targets: "
                f"{sorted(unknown_checkpoint_targets)}"
            )

        return self