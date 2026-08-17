from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from cua.domain import (
    CheckpointSpec,
    CheckpointType,
    ExecutionStatus,
)
from cua.replay.engine import ReplayEngine


def test_unexpected_dialog_requires_human(
    tmp_path: Path,
) -> None:
    surface = MagicMock()

    surface.capture_screenshot.return_value = (
        str(tmp_path / "unexpected-dialog.png")
    )

    engine = ReplayEngine(
        run_id="replay-test",
        surface=surface,
        resolver=MagicMock(),
        checkpoint_evaluator=MagicMock(),
        action_gate=MagicMock(),
        evidence_dir=tmp_path,
    )

    # Generic synthetic application capability.
    artifact = MagicMock()
    artifact.capability.id = "lookup_record"
    artifact.capability.version = "1.0.0"

    # We deliberately do not use application-specific
    # wording such as LegacyBank or supervisor override.
    dialog = SimpleNamespace(
        title="Manual Review Required",
        text=(
            "A human operator must review "
            "this application state."
        ),
        modal=True,
    )

    observation = SimpleNamespace(
        dialogs=[dialog]
    )

    result = engine._unexpected_dialog_result(
        artifact,
        observation=observation,
        expected_checkpoint=None,
        current_step="step-03-click-details",
        outputs={},
        started=0.0,
    )

    assert result is not None

    assert (
        result.status
        == ExecutionStatus.WAITING_FOR_HUMAN
    )

    assert result.code == "UNEXPECTED_DIALOG"

    assert (
        result.current_step
        == "step-03-click-details"
    )

    assert result.outputs == {}

    assert result.observed == [
        {
            "title": "Manual Review Required",
            "text": (
                "A human operator must review "
                "this application state."
            ),
            "modal": True,
        }
    ]

    surface.capture_screenshot.assert_called_once_with(
        "unexpected-dialog.png"
    )

def test_no_dialog_does_not_require_human(
    tmp_path: Path,
) -> None:
    surface = MagicMock()

    engine = ReplayEngine(
        run_id="replay-test",
        surface=surface,
        resolver=MagicMock(),
        checkpoint_evaluator=MagicMock(),
        action_gate=MagicMock(),
        evidence_dir=tmp_path,
    )

    artifact = MagicMock()
    artifact.capability.id = "lookup_record"
    artifact.capability.version = "1.0.0"

    observation = SimpleNamespace(
        dialogs=[]
    )

    result = engine._unexpected_dialog_result(
        artifact,
        observation=observation,
        expected_checkpoint=None,
        current_step="step-02-click-search",
        outputs={},
        started=0.0,
    )

    assert result is None

    surface.capture_screenshot.assert_not_called()


def test_expected_dialog_is_not_treated_as_unexpected(
    tmp_path: Path,
) -> None:
    surface = MagicMock()

    engine = ReplayEngine(
        run_id="replay-test",
        surface=surface,
        resolver=MagicMock(),
        checkpoint_evaluator=MagicMock(),
        action_gate=MagicMock(),
        evidence_dir=tmp_path,
    )

    artifact = MagicMock()
    artifact.capability.id = "review_record"
    artifact.capability.version = "1.0.0"

    dialog = SimpleNamespace(
        title="Review",
        text="Please review before continuing.",
        modal=True,
    )

    observation = SimpleNamespace(
        dialogs=[dialog]
    )

    expected_checkpoint = CheckpointSpec(
        type=CheckpointType.DIALOG_PRESENT,
        value="Review",
    )

    result = engine._unexpected_dialog_result(
        artifact,
        observation=observation,
        expected_checkpoint=expected_checkpoint,
        current_step="step-04-open-review",
        outputs={},
        started=0.0,
    )

    assert result is None

    surface.capture_screenshot.assert_not_called()