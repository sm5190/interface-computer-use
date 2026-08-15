from __future__ import annotations

from typing import Any

from cua.domain import ResolvedTarget, TargetSpec

from .base import (
    GroundingBackend,
    TargetAmbiguous,
    TargetNotFound,
)


class TargetResolver:
    """
    Resolve a logical TargetSpec using its declared
    strategies in deterministic priority order.
    """

    def __init__(
        self,
        backend: GroundingBackend,
    ) -> None:
        self._backend = backend

    def resolve(
        self,
        target: TargetSpec,
    ) -> ResolvedTarget:
        attempts: list[dict[str, Any]] = []

        for strategy in target.strategies:
            candidates = self._backend.resolve(strategy)

            attempts.append(
                {
                    "strategy_kind": strategy.kind.value,
                    "candidate_count": len(candidates),
                }
            )

            if not candidates:
                continue

            if len(candidates) > 1:
                raise TargetAmbiguous(
                    (
                        f"Target {target.logical_name!r} "
                        f"is ambiguous using "
                        f"{strategy.kind.value!r}"
                    ),
                    logical_name=target.logical_name,
                    attempts=attempts,
                    candidate_count=len(candidates),
                )

            candidate = candidates[0]

            evidence = dict(candidate.evidence)
            evidence["attempts"] = attempts

            return ResolvedTarget(
                logical_name=target.logical_name,
                strategy_kind=strategy.kind,
                confidence=candidate.confidence,
                candidate_count=1,
                evidence=evidence,
                surface_handle=candidate.handle,
            )

        raise TargetNotFound(
            (
                f"No declared strategy resolved "
                f"target {target.logical_name!r}"
            ),
            logical_name=target.logical_name,
            attempts=attempts,
        )