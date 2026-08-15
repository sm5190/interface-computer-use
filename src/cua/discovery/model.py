from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from cua.domain import AgentDecision, Observation
from cua.domain.base import DomainModel


class DiscoveryModelContext(DomainModel):
    goal: str

    observation: Observation

    recent_steps: list[dict[str, Any]] = Field(
        default_factory=list
    )

    known_outputs: dict[str, Any] = Field(
        default_factory=dict
    )

    target_notes: list[str] = Field(
        default_factory=list
    )


class DiscoveryModel(Protocol):
    @property
    def call_count(self) -> int:
        """Number of model decision calls made."""

    def decide(
        self,
        context: DiscoveryModelContext,
    ) -> AgentDecision:
        """Return one typed discovery decision."""