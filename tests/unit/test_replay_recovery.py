from __future__ import annotations

from time import perf_counter
from types import SimpleNamespace
from unittest.mock import MagicMock

from cua.domain import (
    ActionType,
    PolicyDecisionType,
    RiskLevel,
)
from cua.replay import ReplayEngine


def _engine(
    tmp_path,
) -> tuple[
    ReplayEngine,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    surface = MagicMock()
    resolver = MagicMock()
    evaluator = MagicMock()
    gate = MagicMock()

    surface.current_url = (
        "http://localhost/members"
    )

    gate.evaluate.return_value = (
        SimpleNamespace(
            decision=SimpleNamespace(
                decision=(
                    PolicyDecisionType.ALLOW
                ),
                reason_code=None,
            )
        )
    )

    engine = ReplayEngine(
        run_id="replay-test",
        surface=surface,
        resolver=resolver,
        checkpoint_evaluator=evaluator,
        action_gate=gate,
        evidence_dir=tmp_path,
    )

    return (
        engine,
        surface,
        evaluator,
        gate,
    )


def test_checkpoint_recovery_waits_and_rechecks(
    tmp_path,
) -> None:
    (
        engine,
        surface,
        evaluator,
        _,
    ) = _engine(tmp_path)

    first_observation = MagicMock()
    first_observation.dialogs = []

    recovered_observation = MagicMock()
    recovered_observation.dialogs = []

    surface.observe.return_value = (
        recovered_observation
    )

    evaluator.evaluate.side_effect = [
        SimpleNamespace(
            passed=False,
            expected="control present",
            observed="not found",
        ),
        SimpleNamespace(
            passed=True,
            expected="control present",
            observed="control present",
        ),
    ]

    artifact = SimpleNamespace(
        capability=SimpleNamespace(
            id="generic_capability",
            version="1.0.0",
        ),
        hard_failures=[],
        business_outcomes=[],
    )

    step = SimpleNamespace(
        id="step-03-click-open",
        checkpoint=object(),
        retry=SimpleNamespace(
            max_attempts=2,
            delay_ms=250,
            retry_on=[
                "CHECKPOINT_FAILED"
            ],
        ),
        risk=SimpleNamespace(
            level=RiskLevel.SAFE,
            reversible=True,
        ),
    )

    observation, terminal = (
        engine._checkpoint_with_recovery(
            artifact,
            step=step,
            observation=first_observation,
            outputs={},
            started=perf_counter(),
        )
    )

    assert terminal is None
    assert observation is recovered_observation
    assert evaluator.evaluate.call_count == 2

    wait_action = (
        surface.execute.call_args.args[0]
    )

    assert wait_action.type == ActionType.WAIT
    assert wait_action.value == 250

    recovery_log = (
        tmp_path
        / "recovery_events.jsonl"
    )

    assert recovery_log.is_file()

    contents = recovery_log.read_text(
        encoding="utf-8"
    )

    assert '"condition": "CHECKPOINT_FAILED"' in contents
    assert '"passed": true' in contents


def test_unsafe_step_is_never_retried(
    tmp_path,
) -> None:
    (
        engine,
        surface,
        evaluator,
        _,
    ) = _engine(tmp_path)

    observation = MagicMock()
    observation.dialogs = []

    surface.capture_screenshot.return_value = (
        "unsafe-retry.png"
    )

    evaluator.evaluate.return_value = (
        SimpleNamespace(
            passed=False,
            expected="expected state",
            observed="missing",
        )
    )

    artifact = SimpleNamespace(
        capability=SimpleNamespace(
            id="generic_capability",
            version="1.0.0",
        ),
        hard_failures=[],
        business_outcomes=[],
    )

    step = SimpleNamespace(
        id="step-risky",
        checkpoint=object(),
        retry=SimpleNamespace(
            max_attempts=2,
            delay_ms=250,
            retry_on=[
                "CHECKPOINT_FAILED"
            ],
        ),
        risk=SimpleNamespace(
            level=(
                RiskLevel.REVERSIBLE_WRITE
            ),
            reversible=True,
            model_dump=lambda **_: {
                "level": "reversible_write",
                "reversible": True,
            },
        ),
    )

    _, terminal = (
        engine._checkpoint_with_recovery(
            artifact,
            step=step,
            observation=observation,
            outputs={},
            started=perf_counter(),
        )
    )

    assert terminal is not None
    assert terminal.status == "FAILURE"
    assert (
        terminal.code
        == "UNSAFE_RETRY_BLOCKED"
    )

    # No recovery WAIT was executed.
    surface.execute.assert_not_called()