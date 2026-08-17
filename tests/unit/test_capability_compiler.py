from cua.compiler import (
    CapabilityRecipe,
    GenericCapabilityCompiler,
    InputBinding,
    TrajectoryWindow,
)
from cua.domain import (
    ActionSpec,
    ActionType,
    Actor,
    ApplicationCompatibility,
    AttributeStrategy,
    CapabilityIdentity,
    CheckpointSpec,
    CheckpointType,
    ExecutionMode,
    InputDefinition,
    OutputDefinition,
    PolicyDecision,
    PolicyDecisionType,
    ResolutionEvidence,
    ResolutionStrategyKind,
    RiskLevel,
    RiskSpec,
    SchemaValueType,
    SemanticStrategy,
    StepRecord,
    SurfaceKind,
    TargetSpec,
)


def safe_risk() -> RiskSpec:
    return RiskSpec(
        level=RiskLevel.SAFE,
        reversible=True,
    )


def allowed() -> PolicyDecision:
    return PolicyDecision(
        decision=PolicyDecisionType.ALLOW,
        reason_code="ACTION_ALLOWED",
    )


def test_compiler_is_application_agnostic() -> None:
    order_input = TargetSpec(
        logical_name="record_search_input",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="query",
            )
        ],
    )

    search_button = TargetSpec(
        logical_name="search_button",
        strategies=[
            SemanticStrategy(
                role="button",
                accessible_name="Search",
            )
        ],
    )

    status_value = TargetSpec(
        logical_name="status_value",
        strategies=[
            AttributeStrategy(
                attribute="data-field",
                value="status",
            )
        ],
    )

    trajectory = [
        # Pretend this is session/bootstrap activity.
        # It must not enter the capability.
        StepRecord(
            run_id="run-1",
            step_index=0,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            intent="Bootstrap session",
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value="temporary-secret",
            ),
            target_summary={
                "logical_name": "session_field",
                "strategies": [
                    {
                        "kind": "attribute",
                        "attribute": "name",
                        "value": "session",
                    }
                ],
            },
            risk=safe_risk(),
            policy_decision=allowed(),
            checkpoint_spec=CheckpointSpec(
                type=CheckpointType.CONTROL_VALUE,
                target=TargetSpec(
                    logical_name="session_field",
                    strategies=[
                        AttributeStrategy(
                            attribute="name",
                            value="session",
                        )
                    ],
                ),
                expected="temporary-secret",
            ),
            outcome_code="ACTION_COMPLETED",
            duration_ms=10,
        ),

        StepRecord(
            run_id="run-1",
            step_index=1,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            intent="Enter requested record ID",
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value="ORD-123",
            ),
            target_summary=order_input.model_dump(
                mode="json"
            ),
            risk=safe_risk(),
            policy_decision=allowed(),
            resolution=ResolutionEvidence(
                logical_name="record_search_input",
                strategy_kind=(
                    ResolutionStrategyKind.ATTRIBUTE
                ),
                confidence=0.95,
                candidate_count=1,
            ),
            checkpoint_spec=CheckpointSpec(
                type=CheckpointType.CONTROL_VALUE,
                target=order_input,
                expected="ORD-123",
            ),
            outcome_code="ACTION_COMPLETED",
            duration_ms=10,
        ),

        StepRecord(
            run_id="run-1",
            step_index=2,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            intent="Submit search",
            action=ActionSpec(
                type=ActionType.CLICK,
            ),
            target_summary=search_button.model_dump(
                mode="json"
            ),
            risk=safe_risk(),
            policy_decision=allowed(),
            resolution=ResolutionEvidence(
                logical_name="search_button",
                strategy_kind=(
                    ResolutionStrategyKind.SEMANTIC
                ),
                confidence=0.99,
                candidate_count=1,
            ),
            # Intentionally no checkpoint_spec.
            # Compiler should derive it from next step.
            outcome_code="ACTION_COMPLETED",
            duration_ms=10,
        ),

        StepRecord(
            run_id="run-1",
            step_index=3,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            intent="Extract requested status",
            action=ActionSpec(
                type=ActionType.EXTRACT,
            ),
            target_summary=status_value.model_dump(
                mode="json"
            ),
            output_binding="record_status",
            risk=safe_risk(),
            policy_decision=allowed(),
            resolution=ResolutionEvidence(
                logical_name="status_value",
                strategy_kind=(
                    ResolutionStrategyKind.ATTRIBUTE
                ),
                confidence=0.95,
                candidate_count=1,
            ),
            checkpoint_spec=CheckpointSpec(
                type=CheckpointType.OUTPUT_EXTRACTABLE,
                output="record_status",
            ),
            outcome_code="ACTION_COMPLETED",
            duration_ms=10,
        ),
    ]

    recipe = CapabilityRecipe(
        capability=CapabilityIdentity(
            id="lookup_record_status",
            version="1.0.0",
            name="Lookup Record Status",
            description=(
                "Return the status for a requested record"
            ),
        ),
        application=ApplicationCompatibility(
            family="example-record-system",
            surface=SurfaceKind.BROWSER,
            entry_point="/records",
        ),
        inputs={
            "record_id": InputBinding(
                definition=InputDefinition(
                    type=SchemaValueType.STRING,
                    required=True,
                    sensitive=True,
                ),
                discovery_value="ORD-123",
            )
        },
        outputs={
            "record_status": OutputDefinition(
                type=SchemaValueType.STRING,
                nullable=False,
            )
        },
        success_condition=CheckpointSpec(
            type=CheckpointType.OUTPUT_EXTRACTABLE,
            output="record_status",
        ),
        trajectory=TrajectoryWindow(
            start_step_index=1,
        ),
    )

    artifact = GenericCapabilityCompiler().compile(
        trajectory=trajectory,
        recipe=recipe,
    )

    assert len(artifact.steps) == 3

    # Session/bootstrap action was excluded.
    serialized = artifact.model_dump_json()

    assert "temporary-secret" not in serialized

    # Concrete discovery input became parameterized.
    assert "ORD-123" not in serialized
    assert "{{record_id}}" in serialized

    assert (
        artifact.steps[0].action.value
        == "{{record_id}}"
    )

    # Search click had no explicit checkpoint,
    # so compiler uses next grounded control.
    assert (
        artifact.steps[1].checkpoint is not None
    )
    assert (
        artifact.steps[1].checkpoint.type
        == CheckpointType.CONTROL_PRESENT
    )
    assert (
        artifact.steps[1]
        .checkpoint
        .target
        .logical_name
        == "status_value"
    )

    assert (
        artifact.steps[2].output
        == "record_status"
    )

    assert artifact.policy.risk == "read_only"



def test_parameterizes_input_inside_strings() -> None:
    target = TargetSpec(
        logical_name="record_link",
        strategies=[
            AttributeStrategy(
                attribute="href",
                value="/records/ABC-9001/details",
            )
        ],
    )

    trajectory = [
        StepRecord(
            run_id="run-2",
            step_index=0,
            actor=Actor.LLM,
            mode=ExecutionMode.DISCOVERY,
            intent="Open requested record",
            action=ActionSpec(
                type=ActionType.CLICK,
            ),
            target_summary=target.model_dump(
                mode="json"
            ),
            risk=safe_risk(),
            policy_decision=allowed(),
            checkpoint_spec=CheckpointSpec(
                type=CheckpointType.URL_MATCHES,
                pattern="/records/ABC-9001/details",
            ),
            outcome_code="ACTION_COMPLETED",
            duration_ms=10,
        )
    ]

    recipe = CapabilityRecipe(
        capability=CapabilityIdentity(
            id="open_record",
            version="1.0.0",
            name="Open Record",
            description="Open a requested record",
        ),
        application=ApplicationCompatibility(
            family="example-app",
            surface=SurfaceKind.BROWSER,
            entry_point="/records",
        ),
        inputs={
            "record_id": InputBinding(
                definition=InputDefinition(
                    type=SchemaValueType.STRING,
                ),
                discovery_value="ABC-9001",
            )
        },
        outputs={},
        success_condition=CheckpointSpec(
            type=CheckpointType.URL_MATCHES,
            pattern="/records/ABC-9001/details",
        ),
    )

    artifact = GenericCapabilityCompiler().compile(
        trajectory=trajectory,
        recipe=recipe,
    )

    serialized = artifact.model_dump_json()

    assert "ABC-9001" not in serialized
    assert "/records/{{record_id}}/details" in serialized