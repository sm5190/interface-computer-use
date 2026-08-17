from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .actions import ActionSpec, RetrySpec, RiskSpec, TargetSpec
from .base import DomainModel
from .discovery import CheckpointSpec
from .enums import (
    ActionType,
    ApprovalState,
    CheckpointType,
    SchemaValueType,
    SurfaceKind,
)


class CapabilityIdentity(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class CompatibilitySpec(DomainModel):
    version_range: str | None = None


class ApplicationCompatibility(DomainModel):
    family: str = Field(min_length=1)
    surface: SurfaceKind
    entry_point: str = Field(min_length=1)
    compatibility: CompatibilitySpec = Field(
        default_factory=CompatibilitySpec
    )


class InputDefinition(DomainModel):
    type: SchemaValueType
    required: bool = True
    sensitive: bool = False
    pattern: str | None = None
    description: str | None = None
    default: Any | None = None


class OutputDefinition(DomainModel):
    type: SchemaValueType
    nullable: bool = False
    description: str | None = None


class CapabilityStep(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    action: ActionSpec
    target: TargetSpec | None = None

    # For extract actions, identifies which declared capability
    # output receives the extracted value.
    output: str | None = None

    risk: RiskSpec
    checkpoint: CheckpointSpec | None = None

    timeout_ms: int = Field(
        default=5000,
        ge=1,
        le=120_000,
    )

    retry: RetrySpec = Field(default_factory=RetrySpec)

    @model_validator(mode="after")
    def validate_output_binding(self) -> CapabilityStep:
        if (
            self.action.type == ActionType.EXTRACT
            and not self.output
        ):
            raise ValueError(
                "extract capability step requires output"
            )

        if (
            self.action.type != ActionType.EXTRACT
            and self.output is not None
        ):
            raise ValueError(
                "only extract capability steps may declare output"
            )

        return self


class BusinessOutcomeRule(DomainModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    detect: CheckpointSpec
    terminal: bool = True

class HardFailureRule(DomainModel):
    code: str
    detect: CheckpointSpec
    terminal: bool = True


class CapabilityPolicy(DomainModel):
    risk: Literal[
        "read_only",
        "reversible_write",
        "contains_irreversible",
    ]
    requires_human_approval: bool = False


class CapabilityMetadata(DomainModel):
    created_from_run: str = Field(min_length=1)
    approval_state: ApprovalState = ApprovalState.DRAFT
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class CapabilityArtifact(DomainModel):
    schema_version: Literal["1.0"] = "1.0"

    capability: CapabilityIdentity
    application: ApplicationCompatibility

    inputs: dict[str, InputDefinition]
    outputs: dict[str, OutputDefinition]

    steps: list[CapabilityStep] = Field(min_length=1)

    business_outcomes: list[BusinessOutcomeRule] = Field(
        default_factory=list
    )

    hard_failures: list[HardFailureRule] = Field(
        default_factory=list
    )

    success_condition: CheckpointSpec
    policy: CapabilityPolicy
    metadata: CapabilityMetadata

    @model_validator(mode="after")
    def validate_output_contract(self) -> CapabilityArtifact:
        declared_outputs = set(self.outputs)

        for step in self.steps:
            if (
                step.output is not None
                and step.output not in declared_outputs
            ):
                raise ValueError(
                    f"step {step.id!r} references undeclared "
                    f"output {step.output!r}"
                )

        if (
            self.success_condition.type
            == CheckpointType.OUTPUT_EXTRACTABLE
        ):
            output_name = self.success_condition.output

            if output_name not in declared_outputs:
                raise ValueError(
                    "success condition references "
                    "undeclared output"
                )

        return self