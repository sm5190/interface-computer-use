import pytest
from pydantic import ValidationError

from cua.domain import (
    ActionSpec,
    ActionType,
    Actor,
    CheckpointSpec,
    CheckpointType,
    ExecutionMode,
    RiskLevel,
    RiskSpec,
    StepRecord,
)


def test_step_record_preserves_compiler_metadata() -> None:
    record = StepRecord(
        run_id="discovery-test",
        step_index=3,
        actor=Actor.LLM,
        mode=ExecutionMode.DISCOVERY,
        intent="Extract requested value",
        action=ActionSpec(
            type=ActionType.EXTRACT,
        ),
        output_binding="requested_value",
        risk=RiskSpec(
            level=RiskLevel.SAFE,
            reversible=True,
        ),
        checkpoint_spec=CheckpointSpec(
            type=CheckpointType.OUTPUT_EXTRACTABLE,
            output="requested_value",
        ),
        outcome_code="ACTION_COMPLETED",
        duration_ms=10,
    )

    assert record.output_binding == "requested_value"
    assert record.risk is not None
    assert record.risk.level == RiskLevel.SAFE
    assert record.checkpoint_spec is not None
    assert (
        record.checkpoint_spec.type
        == CheckpointType.OUTPUT_EXTRACTABLE
    )


def test_output_binding_requires_extract_action() -> None:
    with pytest.raises(
        ValidationError,
        match="output_binding may only be declared",
    ):
        StepRecord(
            run_id="discovery-test",
            step_index=0,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            intent="Click something",
            action=ActionSpec(
                type=ActionType.CLICK,
            ),
            output_binding="some_output",
            duration_ms=10,
        )