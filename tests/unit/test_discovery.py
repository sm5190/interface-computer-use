from __future__ import annotations

from pathlib import Path
from typing import Any

from cua.discovery import DiscoveryEngine
from cua.discovery.gemini import GeminiDecisionPayload
from cua.domain import (
    ActionProposal,
    ActionSpec,
    ActionType,
    AgentDecision,
    AgentDecisionState,
    AttributeStrategy,
    ExecutionStatus,
    GoalRequest,
    Observation,
    SurfaceKind,
    SurfaceLocation,
    TargetSpec,
    TextAnchorStrategy,
)
from cua.evidence import DiscoveryEvidenceRecorder
from cua.grounding import (
    CheckpointEvaluator,
    GroundingCandidate,
    TargetResolver,
)
from cua.safety import (
    ActionGate,
    GoalGateway,
    load_policy,
)
from cua.surfaces import SurfaceActionResult


def test_gemini_payload_converts_to_domain_decision() -> None:
    payload = GeminiDecisionPayload.model_validate(
        {
            "state": "CONTINUE",
            "intent": "Enter the member number",
            "proposal": {
                "action": {
                    "type": "input_text",
                    "value": "100001",
                },
                "target": {
                    "logical_name": "member_number_input",
                    "strategies": [
                        {
                            "kind": "attribute",
                            "attribute": "name",
                            "value": "f_14",
                        }
                    ],
                },
                "expected_effect": "Member number is entered",
                "checkpoint": {
                    "type": "control_value",
                    "expected": "100001",
                },
            },
        }
    )

    decision = payload.to_domain()

    assert decision.state == AgentDecisionState.CONTINUE
    assert decision.action is not None

    assert (
        decision.action.action.type
        == ActionType.INPUT_TEXT
    )

    assert decision.action.target is not None
    assert decision.expected_effect is not None
    assert decision.expected_effect.checkpoint is not None


def test_gemini_extract_payload_binds_output() -> None:
    payload = GeminiDecisionPayload.model_validate(
        {
            "state": "CONTINUE",
            "intent": "Extract the savings balance",
            "proposal": {
                "action": {
                    "type": "extract",
                },
                "target": {
                    "logical_name": "savings_balance",
                    "strategies": [
                        {
                            "kind": "text_anchor",
                            "anchor": "SAVINGS",
                            "relation": "same_row_last_cell",
                        }
                    ],
                },
                "output": "savings_balance",
                "expected_effect": (
                    "Savings balance is extracted"
                ),
                "checkpoint": {
                    "type": "output_extractable",
                    "output": "savings_balance",
                },
            },
        }
    )

    decision = payload.to_domain()

    assert decision.action is not None
    assert decision.action.output == "savings_balance"


class FakeSurface:
    def __init__(
        self,
        tmp_path: Path,
    ) -> None:
        self._url = "about:blank"
        self._values: dict[str, str] = {}
        self._tmp_path = tmp_path

        screenshot = tmp_path / "observation.png"
        screenshot.write_bytes(b"fake")

        self._screenshot = str(screenshot)

    @property
    def current_url(self) -> str:
        return self._url

    @property
    def is_started(self) -> bool:
        return True

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def observe(self) -> Observation:
        return Observation(
            surface=SurfaceKind.BROWSER,
            location=SurfaceLocation(
                uri=self._url
            ),
            page_title="Fake Bank",
            screenshot_ref=self._screenshot,
        )

    def execute(
        self,
        action: ActionSpec,
        *,
        target_handle: Any | None = None,
    ) -> SurfaceActionResult:
        if action.type == ActionType.NAVIGATE:
            assert isinstance(action.value, str)

            self._url = action.value

            return SurfaceActionResult(
                value=self._url
            )

        if action.type == ActionType.INPUT_TEXT:
            assert target_handle is not None
            assert action.value is not None

            self._values[
                str(target_handle)
            ] = str(action.value)

            return SurfaceActionResult()

        if action.type == ActionType.EXTRACT:
            if target_handle == "member":
                return SurfaceActionResult(
                    value=self._values.get("member")
                )

            if target_handle == "balance":
                return SurfaceActionResult(
                    value="$10.00"
                )

        return SurfaceActionResult()

    def capture_screenshot(
        self,
        name: str | None = None,
    ) -> str:
        return self._screenshot

    def start_trace(self) -> None:
        pass

    def stop_trace(
        self,
        path: str | Path,
    ) -> str:
        output = Path(path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_bytes(b"fake-trace")

        return str(output)


class FakeGroundingBackend:
    def resolve(
        self,
        strategy: Any,
    ) -> list[GroundingCandidate]:
        if isinstance(
            strategy,
            AttributeStrategy,
        ):
            return [
                GroundingCandidate(
                    handle="member",
                    confidence=0.95,
                    evidence={
                        "attribute": strategy.attribute
                    },
                )
            ]

        if isinstance(
            strategy,
            TextAnchorStrategy,
        ):
            return [
                GroundingCandidate(
                    handle="balance",
                    confidence=0.85,
                    evidence={
                        "anchor": strategy.anchor
                    },
                )
            ]

        return []


class ScriptedModel:
    def __init__(self) -> None:
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def decide(
        self,
        context: Any,
    ) -> AgentDecision:
        self._call_count += 1

        if self._call_count == 1:
            return AgentDecision(
                state=AgentDecisionState.CONTINUE,
                intent="Enter member number",
                action=ActionProposal(
                    action=ActionSpec(
                        type=ActionType.INPUT_TEXT,
                        value="100001",
                    ),
                    target=TargetSpec(
                        logical_name="member_number_input",
                        strategies=[
                            AttributeStrategy(
                                attribute="name",
                                value="f_14",
                            )
                        ],
                    ),
                ),
            )

        if self._call_count == 2:
            return AgentDecision(
                state=AgentDecisionState.CONTINUE,
                intent="Extract savings balance",
                action=ActionProposal(
                    action=ActionSpec(
                        type=ActionType.EXTRACT,
                    ),
                    target=TargetSpec(
                        logical_name="savings_balance",
                        strategies=[
                            TextAnchorStrategy(
                                anchor="SAVINGS",
                                relation=(
                                    "same_row_last_cell"
                                ),
                            )
                        ],
                    ),
                    output="savings_balance",
                ),
            )

        assert (
            context.known_outputs[
                "savings_balance"
            ]
            == "$10.00"
        )

        return AgentDecision(
            state=AgentDecisionState.GOAL_COMPLETE,
            intent="Requested balance was extracted",
            outputs={
                "savings_balance": "$10.00"
            },
        )


def test_discovery_engine_requires_grounded_output(
    tmp_path: Path,
) -> None:
    surface = FakeSurface(tmp_path)

    resolver = TargetResolver(
        FakeGroundingBackend()
    )

    policy = load_policy(
        "policies/legacy_bank.yaml"
    )

    recorder = DiscoveryEvidenceRecorder(
        run_id="discovery-test",
        run_dir=tmp_path / "evidence",
        sensitive_values=[
            "100001",
        ],
    )

    engine = DiscoveryEngine(
        surface=surface,
        model=ScriptedModel(),
        resolver=resolver,
        action_gate=ActionGate(policy),
        goal_gateway=GoalGateway(policy),
        checkpoint_evaluator=(
            CheckpointEvaluator(
                surface=surface,
                resolver=resolver,
            )
        ),
        evidence=recorder,
        base_url="http://127.0.0.1:8000",
    )

    result = engine.run(
        GoalRequest(
            goal=(
                "Find member 100001 and return "
                "their current savings balance"
            ),
            target_profile="legacy-bank",
            entry_point="/members",
            max_steps=6,
        )
    )

    assert (
        result.result.status
        == ExecutionStatus.SUCCESS
    )

    assert result.result.outputs == {
        "savings_balance": "$10.00"
    }

    assert result.llm_calls == 3

    assert (
        tmp_path
        / "evidence"
        / "trajectory.json"
    ).exists()

    assert (
        tmp_path
        / "evidence"
        / "result.json"
    ).exists()