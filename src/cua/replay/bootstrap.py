from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cua.grounding import (
    CheckpointEvaluator,
    TargetResolver,
)
from cua.safety import ActionGate
from cua.surfaces import SurfaceSession


@dataclass(slots=True)
class SessionBootstrapContext:
    surface: SurfaceSession
    resolver: TargetResolver
    checkpoint_evaluator: CheckpointEvaluator
    action_gate: ActionGate
    base_url: str


class SessionBootstrap(Protocol):
    def prepare(
        self,
        context: SessionBootstrapContext,
    ) -> None:
        """Prepare an authenticated/ready live session."""


class NoopSessionBootstrap:
    def prepare(
        self,
        context: SessionBootstrapContext,
    ) -> None:
        del context