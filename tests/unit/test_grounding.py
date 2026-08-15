from __future__ import annotations

from typing import Any

import pytest

from cua.domain import (
    AttributeStrategy,
    ResolutionStrategyKind,
    SemanticStrategy,
    TargetSpec,
    TextAnchorStrategy,
)
from cua.domain.actions import TargetStrategy
from cua.grounding import (
    GroundingCandidate,
    TargetAmbiguous,
    TargetNotFound,
    TargetResolver,
)


class FakeGroundingBackend:
    def __init__(
        self,
        responses: dict[
            ResolutionStrategyKind,
            list[GroundingCandidate],
        ],
    ) -> None:
        self.responses = responses
        self.calls: list[
            ResolutionStrategyKind
        ] = []

    def resolve(
        self,
        strategy: TargetStrategy,
    ) -> list[GroundingCandidate]:
        self.calls.append(strategy.kind)

        return self.responses.get(
            strategy.kind,
            [],
        )


def candidate(
    *,
    confidence: float,
    handle: Any | None = None,
) -> GroundingCandidate:
    return GroundingCandidate(
        handle=(
            handle
            if handle is not None
            else object()
        ),
        confidence=confidence,
        evidence={"source": "test"},
    )


def test_resolver_uses_declared_strategy_order() -> None:
    backend = FakeGroundingBackend(
        {
            ResolutionStrategyKind.ATTRIBUTE: [
                candidate(confidence=0.95)
            ],
            ResolutionStrategyKind.TEXT_ANCHOR: [
                candidate(confidence=0.85)
            ],
        }
    )

    resolver = TargetResolver(backend)

    target = TargetSpec(
        logical_name="member_number_input",
        strategies=[
            SemanticStrategy(
                role="textbox",
                accessible_name="MEMBER NUMBER",
            ),
            AttributeStrategy(
                attribute="name",
                value="f_14",
            ),
            TextAnchorStrategy(
                anchor="MEMBER NUMBER:",
                relation="nearest_input_right",
            ),
        ],
    )

    resolved = resolver.resolve(target)

    assert (
        resolved.strategy_kind
        == ResolutionStrategyKind.ATTRIBUTE
    )

    assert resolved.confidence == 0.95

    assert backend.calls == [
        ResolutionStrategyKind.SEMANTIC,
        ResolutionStrategyKind.ATTRIBUTE,
    ]


def test_resolver_stops_on_ambiguity() -> None:
    backend = FakeGroundingBackend(
        {
            ResolutionStrategyKind.SEMANTIC: [
                candidate(confidence=0.99),
                candidate(confidence=0.99),
            ],
            ResolutionStrategyKind.ATTRIBUTE: [
                candidate(confidence=0.95)
            ],
        }
    )

    resolver = TargetResolver(backend)

    target = TargetSpec(
        logical_name="ambiguous_button",
        strategies=[
            SemanticStrategy(
                role="button"
            ),
            AttributeStrategy(
                attribute="name",
                value="some_button",
            ),
        ],
    )

    with pytest.raises(
        TargetAmbiguous
    ) as error:
        resolver.resolve(target)

    assert error.value.candidate_count == 2

    assert backend.calls == [
        ResolutionStrategyKind.SEMANTIC
    ]


def test_resolver_reports_target_not_found() -> None:
    backend = FakeGroundingBackend({})

    resolver = TargetResolver(backend)

    target = TargetSpec(
        logical_name="missing_target",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="does_not_exist",
            )
        ],
    )

    with pytest.raises(TargetNotFound):
        resolver.resolve(target)


def test_resolved_target_exposes_attempt_evidence() -> None:
    backend = FakeGroundingBackend(
        {
            ResolutionStrategyKind.TEXT_ANCHOR: [
                candidate(confidence=0.85)
            ]
        }
    )

    resolver = TargetResolver(backend)

    target = TargetSpec(
        logical_name="account_navigation",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="missing",
            ),
            TextAnchorStrategy(
                anchor="ACCOUNTS",
                relation="same_row_control",
            ),
        ],
    )

    resolved = resolver.resolve(target)

    attempts = resolved.evidence["attempts"]

    assert attempts == [
        {
            "strategy_kind": "attribute",
            "candidate_count": 0,
        },
        {
            "strategy_kind": "text_anchor",
            "candidate_count": 1,
        },
    ]