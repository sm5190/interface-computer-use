from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from cua.domain.actions import TargetStrategy


@dataclass(slots=True)
class GroundingCandidate:
    """
    One deterministic candidate produced by a concrete
    surface grounding backend.
    """

    handle: Any
    confidence: float
    evidence: dict[str, Any]


class GroundingBackend(Protocol):
    """
    Surface-specific implementation boundary used by
    the surface-independent TargetResolver.
    """

    def resolve(
        self,
        strategy: TargetStrategy,
    ) -> list[GroundingCandidate]:
        """Resolve one deterministic targeting strategy."""


class TargetResolutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        logical_name: str,
        attempts: list[dict[str, Any]],
    ) -> None:
        super().__init__(message)

        self.logical_name = logical_name
        self.attempts = attempts


class TargetNotFound(TargetResolutionError):
    """No declared targeting strategy produced a candidate."""


class TargetAmbiguous(TargetResolutionError):
    """A strategy produced multiple plausible candidates."""

    def __init__(
        self,
        message: str,
        *,
        logical_name: str,
        attempts: list[dict[str, Any]],
        candidate_count: int,
    ) -> None:
        super().__init__(
            message,
            logical_name=logical_name,
            attempts=attempts,
        )

        self.candidate_count = candidate_count