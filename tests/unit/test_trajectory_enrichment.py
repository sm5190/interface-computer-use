import pytest

from cua.compiler import (
    StepEnrichment,
    TrajectoryEnrichment,
    TrajectoryEnrichmentError,
    apply_trajectory_enrichment,
)
from cua.domain import (
    ActionSpec,
    ActionType,
    Actor,
    ExecutionMode,
    RiskLevel,
    RiskSpec,
    StepRecord,
)


def test_enrichment_does_not_mutate_original() -> None:
    original = StepRecord(
        run_id="run-1",
        step_index=4,
        actor=Actor.LLM,
        mode=ExecutionMode.DISCOVERY,
        action=ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="[REDACTED]",
        ),
        outcome_code="ACTION_COMPLETED",
        duration_ms=1,
    )

    enrichment = TrajectoryEnrichment(
        source_run_id="run-1",
        steps=[
            StepEnrichment(
                step_index=4,
                action=ActionSpec(
                    type=ActionType.INPUT_TEXT,
                    value="{{record_id}}",
                ),
                risk=RiskSpec(
                    level=RiskLevel.SAFE,
                    reversible=True,
                ),
            )
        ],
    )

    result = apply_trajectory_enrichment(
        [original],
        enrichment,
    )

    assert (
        original.action is not None
        and original.action.value
        == "[REDACTED]"
    )

    assert (
        result[0].action is not None
        and result[0].action.value
        == "{{record_id}}"
    )

    assert result[0].risk is not None


def test_enrichment_rejects_wrong_run() -> None:
    trajectory = [
        StepRecord(
            run_id="actual-run",
            step_index=0,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            duration_ms=1,
        )
    ]

    enrichment = TrajectoryEnrichment(
        source_run_id="different-run",
    )

    with pytest.raises(
        TrajectoryEnrichmentError,
        match="source_run_id",
    ):
        apply_trajectory_enrichment(
            trajectory,
            enrichment,
        )


def test_enrichment_rejects_missing_step() -> None:
    trajectory = [
        StepRecord(
            run_id="run-1",
            step_index=1,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            duration_ms=1,
        )
    ]

    enrichment = TrajectoryEnrichment(
        source_run_id="run-1",
        steps=[
            StepEnrichment(
                step_index=99,
            )
        ],
    )

    with pytest.raises(
        TrajectoryEnrichmentError,
        match="missing step",
    ):
        apply_trajectory_enrichment(
            trajectory,
            enrichment,
        )