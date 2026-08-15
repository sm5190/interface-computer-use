from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cua.domain import ActionSpec, Observation


@dataclass(slots=True)
class SurfaceActionResult:
    """Result returned by a concrete surface action."""

    value: Any | None = None


@runtime_checkable
class SurfaceSession(Protocol):
    """Surface-independent computer-use session boundary."""

    @property
    def current_url(self) -> str:
        """Return the current surface location."""

    @property
    def is_started(self) -> bool:
        """Return whether the live surface session is active."""

    def start(self) -> None:
        """Start the concrete surface session."""

    def close(self) -> None:
        """Close the concrete surface session."""

    def observe(self) -> Observation:
        """Capture the current surface state."""

    def execute(
        self,
        action: ActionSpec,
        *,
        target_handle: Any | None = None,
    ) -> SurfaceActionResult:
        """Execute a typed action against the surface."""

    def capture_screenshot(
        self,
        name: str | None = None,
    ) -> str:
        """Capture screenshot evidence and return its path."""

    def start_trace(self) -> None:
        """Begin rich execution tracing."""

    def stop_trace(
        self,
        path: str | Path,
    ) -> str:
        """Stop tracing and persist the trace."""