from types import SimpleNamespace
from unittest.mock import MagicMock

from cua.domain import (
    AttributeStrategy,
    CheckpointSpec,
    CheckpointType,
    TargetSpec,
)
from cua.grounding import CheckpointEvaluator


def test_control_value_matches_expected_value() -> None:
    surface = MagicMock()
    resolver = MagicMock()

    target = TargetSpec(
        logical_name="record_id_input",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="record_id",
            )
        ],
    )

    resolved = MagicMock()
    resolved.surface_handle = object()

    resolver.resolve.return_value = resolved

    surface.execute.return_value = SimpleNamespace(
        value="ABC-123"
    )

    evaluator = CheckpointEvaluator(
        surface=surface,
        resolver=resolver,
    )

    checkpoint = CheckpointSpec(
        type=CheckpointType.CONTROL_VALUE,
        target=target,
        expected="ABC-123",
    )

    result = evaluator.evaluate(
        checkpoint
    )

    assert result.passed is True
    assert result.expected == "ABC-123"
    assert result.observed == "ABC-123"

    # Checkpoint evaluation performs one deterministic read.
    assert surface.execute.call_count == 1


def test_control_value_mismatch_fails() -> None:
    surface = MagicMock()
    resolver = MagicMock()

    target = TargetSpec(
        logical_name="record_id_input",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="record_id",
            )
        ],
    )

    resolved = MagicMock()
    resolved.surface_handle = object()

    resolver.resolve.return_value = resolved

    surface.execute.return_value = SimpleNamespace(
        value=""
    )

    evaluator = CheckpointEvaluator(
        surface=surface,
        resolver=resolver,
    )

    checkpoint = CheckpointSpec(
        type=CheckpointType.CONTROL_VALUE,
        target=target,
        expected="ABC-123",
    )

    result = evaluator.evaluate(
        checkpoint
    )

    assert result.passed is False
    assert result.expected == "ABC-123"
    assert result.observed == ""

    assert surface.execute.call_count == 1