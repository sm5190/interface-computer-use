from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import DomainModel
from .enums import ActionType, ResolutionStrategyKind, RiskLevel

ScalarValue = str | int | float | bool


class ActionSpec(DomainModel):
    type: ActionType
    value: ScalarValue | None = None
    option: str | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> ActionSpec:
        if self.type in {
            ActionType.NAVIGATE,
            ActionType.INPUT_TEXT,
            ActionType.PRESS_KEY,
        }:
            if self.value is None:
                raise ValueError(f"{self.type} requires value")

        if self.type == ActionType.SELECT_OPTION and not self.option:
            raise ValueError("select_option requires option")

        return self


class SemanticStrategy(DomainModel):
    kind: Literal[ResolutionStrategyKind.SEMANTIC] = ResolutionStrategyKind.SEMANTIC
    role: str = Field(min_length=1)
    accessible_name: str | None = None


class AttributeStrategy(DomainModel):
    kind: Literal[ResolutionStrategyKind.ATTRIBUTE] = ResolutionStrategyKind.ATTRIBUTE
    attribute: str = Field(min_length=1)
    value: str = Field(min_length=1)


class TextAnchorStrategy(DomainModel):
    kind: Literal[ResolutionStrategyKind.TEXT_ANCHOR] = ResolutionStrategyKind.TEXT_ANCHOR
    anchor: str = Field(min_length=1)
    relation: str = Field(min_length=1)


class VisualTemplateStrategy(DomainModel):
    kind: Literal[ResolutionStrategyKind.VISUAL_TEMPLATE] = (
        ResolutionStrategyKind.VISUAL_TEMPLATE
    )
    asset: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0)
    expected_region: str | None = None


TargetStrategy = Annotated[
    SemanticStrategy
    | AttributeStrategy
    | TextAnchorStrategy
    | VisualTemplateStrategy,
    Field(discriminator="kind"),
]


class TargetSpec(DomainModel):
    logical_name: str = Field(min_length=1)
    strategies: list[TargetStrategy] = Field(min_length=1)


class RiskSpec(DomainModel):
    level: RiskLevel
    reversible: bool


class RetrySpec(DomainModel):
    max_attempts: int = Field(default=1, ge=1, le=5)
    delay_ms: int = Field(default=0, ge=0, le=60_000)
    retry_on: list[str] = Field(default_factory=list)