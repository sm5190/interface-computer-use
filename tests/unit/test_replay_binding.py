import pytest

from cua.domain import (
    ActionSpec,
    ActionType,
    ApplicationCompatibility,
    CapabilityArtifact,
    CapabilityIdentity,
    CapabilityMetadata,
    CapabilityPolicy,
    CapabilityStep,
    CheckpointSpec,
    CheckpointType,
    InputDefinition,
    OutputDefinition,
    RetrySpec,
    RiskLevel,
    RiskSpec,
    SchemaValueType,
    SurfaceKind,
)
from cua.replay import (
    InputBindingError,
    bind_capability_inputs,
)


def artifact() -> CapabilityArtifact:
    return CapabilityArtifact(
        capability=CapabilityIdentity(
            id="lookup_record",
            version="1.0.0",
            name="Lookup Record",
            description="Lookup a record",
        ),
        application=ApplicationCompatibility(
            family="example-app",
            surface=SurfaceKind.BROWSER,
            entry_point="/records",
        ),
        inputs={
            "record_id": InputDefinition(
                type=SchemaValueType.STRING,
                required=True,
                sensitive=True,
                pattern=r"^[A-Z]+-[0-9]+$",
            )
        },
        outputs={
            "status": OutputDefinition(
                type=SchemaValueType.STRING,
                nullable=False,
            )
        },
        steps=[
            CapabilityStep(
                id="enter-record",
                action=ActionSpec(
                    type=ActionType.INPUT_TEXT,
                    value="{{record_id}}",
                ),
                risk=RiskSpec(
                    level=RiskLevel.SAFE,
                    reversible=True,
                ),
                timeout_ms=5000,
                retry=RetrySpec(
                    max_attempts=1,
                ),
            )
        ],
        business_outcomes=[],
        success_condition=CheckpointSpec(
            type=CheckpointType.OUTPUT_EXTRACTABLE,
            output="status",
        ),
        policy=CapabilityPolicy(
            risk="read_only",
            requires_human_approval=False,
        ),
        metadata=CapabilityMetadata(
            created_from_run="run-1",
        ),
    )


def test_binds_exact_placeholder() -> None:
    bound = bind_capability_inputs(
        artifact(),
        {
            "record_id": "ORD-999",
        },
    )

    assert (
        bound.steps[0].action.value
        == "ORD-999"
    )


def test_missing_required_input_fails() -> None:
    with pytest.raises(
        InputBindingError,
        match="Missing required input",
    ):
        bind_capability_inputs(
            artifact(),
            {},
        )


def test_unknown_input_fails() -> None:
    with pytest.raises(
        InputBindingError,
        match="Unknown capability inputs",
    ):
        bind_capability_inputs(
            artifact(),
            {
                "record_id": "ORD-1",
                "unexpected": "value",
            },
        )


def test_pattern_is_enforced() -> None:
    with pytest.raises(
        InputBindingError,
        match="does not match",
    ):
        bind_capability_inputs(
            artifact(),
            {
                "record_id": "bad",
            },
        )


def test_original_artifact_stays_parameterized() -> None:
    original = artifact()

    bound = bind_capability_inputs(
        original,
        {
            "record_id": "ORD-100",
        },
    )

    assert (
        original.steps[0].action.value
        == "{{record_id}}"
    )

    assert (
        bound.steps[0].action.value
        == "ORD-100"
    )