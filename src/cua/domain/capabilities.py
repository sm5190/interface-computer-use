from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from .actions import ActionSpec, RetrySpec, RiskSpec, TargetSpec
from .base import DomainModel
from .discovery import CheckpointSpec
from .enums import ApprovalState, SchemaValueType, SurfaceKind


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
    risk: RiskSpec
    checkpoint: CheckpointSpec | None = None
    timeout_ms: int = Field(
        default=5000,
        ge=1,
        le=120_000,
    )
    retry: RetrySpec = Field(default_factory=RetrySpec)


class BusinessOutcomeRule(DomainModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
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
    success_condition: CheckpointSpec
    policy: CapabilityPolicy
    metadata: CapabilityMetadata