from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from pydantic import Field

from cua.domain import (
    ActionProposal,
    ActionSpec,
    ActionType,
    Actor,
    AgentDecisionState,
    CheckpointSpec,
    CheckpointType,
    ExecutionMode,
    ExecutionResult,
    ExecutionStatus,
    GoalRequest,
    PolicyDecisionType,
    ResolutionEvidence,
    StepRecord,
)
from cua.domain.base import DomainModel
from cua.evidence import DiscoveryEvidenceRecorder
from cua.grounding import (
    CheckpointContext,
    CheckpointEvaluator,
    TargetAmbiguous,
    TargetNotFound,
    TargetResolver,
)
from cua.safety import (
    ActionGate,
    GateContext,
    GoalGateway,
)
from cua.surfaces import SurfaceSession

from .model import (
    DiscoveryModel,
    DiscoveryModelContext,
)


class DiscoveryRunResult(DomainModel):
    result: ExecutionResult

    trajectory: list[StepRecord] = Field(
        default_factory=list
    )

    llm_calls: int

    evidence_dir: str


def new_discovery_run_id() -> str:
    timestamp = datetime.now(
        UTC
    ).strftime("%Y%m%d-%H%M%S")

    suffix = uuid4().hex[:8]

    return (
        f"discovery-{timestamp}-{suffix}"
    )


class DiscoveryEngine:
    def __init__(
        self,
        *,
        surface: SurfaceSession,
        model: DiscoveryModel,
        resolver: TargetResolver,
        action_gate: ActionGate,
        goal_gateway: GoalGateway,
        checkpoint_evaluator: CheckpointEvaluator,
        evidence: DiscoveryEvidenceRecorder,
        base_url: str,
        target_notes: list[str] | None = None,
    ) -> None:
        self._surface = surface
        self._model = model
        self._resolver = resolver

        self._action_gate = action_gate
        self._goal_gateway = goal_gateway

        self._checkpoints = checkpoint_evaluator

        self._evidence = evidence

        self._base_url = base_url.rstrip("/")

        self._target_notes = (
            target_notes or []
        )

    def run(
        self,
        request: GoalRequest,
    ) -> DiscoveryRunResult:
        run_id = self._evidence.run_id

        started = monotonic()

        trajectory: list[StepRecord] = []

        self._evidence.record_event(
            "run_started",
            {
                "mode": "discovery",
                "target_profile": (
                    request.target_profile
                ),
            },
        )

        trace_started = False

        try:
            admission = self._goal_gateway.admit(
                request,
                base_url=self._base_url,
            )

            if (
                admission.decision
                != PolicyDecisionType.ALLOW
            ):
                result = ExecutionResult(
                    run_id=run_id,
                    status=ExecutionStatus.REJECTED,
                    code=(
                        admission.reason_code
                        or "GOAL_REJECTED"
                    ),
                    outputs={},
                    duration_ms=_elapsed_ms(started),
                )

                return self._finalize(
                    result=result,
                    trajectory=trajectory,
                    trace_started=False,
                )

            self._surface.start_trace()
            trace_started = True

            entry_url = urljoin(
                f"{self._base_url}/",
                request.entry_point.lstrip("/"),
            )

            navigation = ActionSpec(
                type=ActionType.NAVIGATE,
                value=entry_url,
            )

            navigation_gate = (
                self._action_gate.evaluate(
                    GateContext(
                        action=navigation,
                        current_url=(
                            self._surface.current_url
                        ),
                    )
                )
            )

            if (
                navigation_gate.decision.decision
                != PolicyDecisionType.ALLOW
            ):
                result = ExecutionResult(
                    run_id=run_id,
                    status=ExecutionStatus.REJECTED,
                    code=(
                        navigation_gate
                        .decision
                        .reason_code
                        or "ENTRY_NAVIGATION_REJECTED"
                    ),
                    outputs={},
                    duration_ms=_elapsed_ms(started),
                )

                return self._finalize(
                    result=result,
                    trajectory=trajectory,
                    trace_started=trace_started,
                )

            self._surface.execute(navigation)

            self._evidence.record_event(
                "entry_navigation",
                {
                    "requested_url": entry_url,
                    "observed_url": (
                        self._surface.current_url
                    ),
                },
            )

            result = self._run_loop(
                request=request,
                trajectory=trajectory,
                started=started,
            )

            return self._finalize(
                result=result,
                trajectory=trajectory,
                trace_started=trace_started,
            )

        except Exception as exc:
            evidence_refs: list[str] = []

            try:
                screenshot = (
                    self._surface
                    .capture_screenshot(
                        "discovery-failure.png"
                    )
                )

                evidence_refs.append(screenshot)

            except Exception:
                pass

            result = ExecutionResult(
                run_id=run_id,
                status=ExecutionStatus.FAILURE,
                code="DISCOVERY_RUNTIME_ERROR",
                outputs={},
                expected=None,
                observed=str(exc),
                evidence=evidence_refs,
                duration_ms=_elapsed_ms(started),
            )

            return self._finalize(
                result=result,
                trajectory=trajectory,
                trace_started=trace_started,
            )

    def _run_loop(
        self,
        *,
        request: GoalRequest,
        trajectory: list[StepRecord],
        started: float,
    ) -> ExecutionResult:
        outputs: dict[str, Any] = {}

        recent_steps: list[dict[str, Any]] = []

        for step_index in range(
            request.max_steps
        ):
            if (
                monotonic() - started
                > request.timeout_seconds
            ):
                return ExecutionResult(
                    run_id=self._evidence.run_id,
                    status=ExecutionStatus.FAILURE,
                    code="DISCOVERY_TIMEOUT",
                    outputs=outputs,
                    current_step=str(step_index),
                    duration_ms=_elapsed_ms(started),
                )

            observation = self._surface.observe()

            decision_started = monotonic()

            decision = self._model.decide(
                DiscoveryModelContext(
                    goal=request.goal,
                    observation=observation,
                    recent_steps=recent_steps,
                    known_outputs=outputs,
                    target_notes=(
                        self._target_notes
                    ),
                )
            )

            if (
                decision.state
                == AgentDecisionState.GOAL_COMPLETE
            ):
                invalid_completion = (
                    self._completion_error(
                        decision.outputs,
                        outputs,
                    )
                )

                if invalid_completion is not None:
                    recent_steps.append(
                        {
                            "step": step_index,
                            "outcome": (
                                "INVALID_GOAL_COMPLETE"
                            ),
                            "feedback": (
                                invalid_completion
                            ),
                        }
                    )

                    self._evidence.record_event(
                        "invalid_goal_complete",
                        {
                            "step_index": step_index,
                            "reason": invalid_completion,
                        },
                    )

                    continue

                return ExecutionResult(
                    run_id=self._evidence.run_id,
                    status=ExecutionStatus.SUCCESS,
                    outputs=outputs,
                    duration_ms=_elapsed_ms(started),
                )

            if (
                decision.state
                == AgentDecisionState.NEEDS_HUMAN
            ):
                return ExecutionResult(
                    run_id=self._evidence.run_id,
                    status=(
                        ExecutionStatus
                        .WAITING_FOR_HUMAN
                    ),
                    code="MODEL_REQUESTED_HUMAN",
                    outputs=outputs,
                    current_step=str(step_index),
                    observed=decision.intent,
                    evidence=[
                        observation.screenshot_ref
                    ],
                    duration_ms=_elapsed_ms(started),
                )

            if (
                decision.state
                == AgentDecisionState.BLOCKED
            ):
                return ExecutionResult(
                    run_id=self._evidence.run_id,
                    status=ExecutionStatus.FAILURE,
                    code="DISCOVERY_BLOCKED",
                    outputs=outputs,
                    current_step=str(step_index),
                    observed=decision.intent,
                    evidence=[
                        observation.screenshot_ref
                    ],
                    duration_ms=_elapsed_ms(started),
                )

            proposal = decision.action

            assert proposal is not None

            resolved = None
            resolution = None

            if proposal.target is not None:
                try:
                    resolved = self._resolver.resolve(
                        proposal.target
                    )

                    resolution = ResolutionEvidence(
                        logical_name=(
                            resolved.logical_name
                        ),
                        strategy_kind=(
                            resolved.strategy_kind
                        ),
                        confidence=(
                            resolved.confidence
                        ),
                        candidate_count=(
                            resolved.candidate_count
                        ),
                        evidence=resolved.evidence,
                    )

                except TargetNotFound as exc:
                    step = StepRecord(
                        run_id=self._evidence.run_id,
                        step_index=step_index,
                        actor=Actor.LLM,
                        mode=ExecutionMode.DISCOVERY,
                        intent=decision.intent,
                        action=proposal.action,
                        target_summary=(
                            proposal.target.model_dump(
                                mode="json"
                            )
                        ),
                        outcome_code="TARGET_NOT_FOUND",
                        evidence_refs=[
                            observation.screenshot_ref
                        ],
                        duration_ms=_elapsed_ms(
                            decision_started
                        ),
                    )

                    trajectory.append(step)

                    self._evidence.record_step(step)

                    recent_steps.append(
                        {
                            "step": step_index,
                            "action": (
                                proposal.action.type.value
                            ),
                            "outcome": "TARGET_NOT_FOUND",
                            "feedback": exc.attempts,
                        }
                    )

                    continue

                except TargetAmbiguous as exc:
                    step = StepRecord(
                        run_id=self._evidence.run_id,
                        step_index=step_index,
                        actor=Actor.LLM,
                        mode=ExecutionMode.DISCOVERY,
                        intent=decision.intent,
                        action=proposal.action,
                        target_summary=(
                            proposal.target.model_dump(
                                mode="json"
                            )
                        ),
                        outcome_code="TARGET_AMBIGUOUS",
                        evidence_refs=[
                            observation.screenshot_ref
                        ],
                        duration_ms=_elapsed_ms(
                            decision_started
                        ),
                    )

                    trajectory.append(step)

                    self._evidence.record_step(step)

                    recent_steps.append(
                        {
                            "step": step_index,
                            "intent": decision.intent,
                            "action": (
                                proposal.action.type.value
                            ),
                            "target": (
                                proposal.target.logical_name
                            ),
                            "outcome": "TARGET_AMBIGUOUS",
                            "candidate_count": (
                                exc.candidate_count
                            ),
                            "attempts": exc.attempts,
                            "feedback": (
                                "The proposed target matched "
                                f"{exc.candidate_count} visible controls. "
                                "Do not repeat the same broad strategy. "
                                "Refine the target using a unique "
                                "accessible_name or a stable observed "
                                "attribute such as name or id."
                            ),
                        }
                    )

                    recent_steps = recent_steps[-6:]

                    continue
            checkpoint = (
                decision.expected_effect.checkpoint
                if (
                    decision.expected_effect is not None
                    and decision.expected_effect.checkpoint is not None
                )
                else _derive_checkpoint(proposal)
            )

            gate = self._action_gate.evaluate(
                GateContext(
                    action=proposal.action,
                    current_url=(
                        self._surface.current_url
                    ),
                    target_confidence=(
                        resolved.confidence
                        if resolved is not None
                        else None
                    ),
                    has_checkpoint=(
                        checkpoint is not None
                    ),
                )
            )

            if (
                gate.decision.decision
                != PolicyDecisionType.ALLOW
            ):
                step = StepRecord(
                    run_id=self._evidence.run_id,
                    step_index=step_index,
                    actor=Actor.LLM,
                    mode=ExecutionMode.DISCOVERY,
                    intent=decision.intent,
                    action=proposal.action,
                    target_summary=(
                        proposal.target.model_dump(
                            mode="json"
                        )
                        if proposal.target
                        else None
                    ),
                    resolution=resolution,
                    policy_decision=gate.decision,
                    outcome_code=(
                        gate.decision.reason_code
                    ),
                    evidence_refs=[
                        observation.screenshot_ref
                    ],
                    duration_ms=_elapsed_ms(
                        decision_started
                    ),
                )

                trajectory.append(step)

                self._evidence.record_step(step)

                status = ExecutionStatus.REJECTED

                if (
                    gate.decision.decision
                    == PolicyDecisionType
                    .APPROVAL_REQUIRED
                ):
                    status = (
                        ExecutionStatus
                        .WAITING_FOR_APPROVAL
                    )

                elif (
                    gate.decision.decision
                    == PolicyDecisionType
                    .TAKEOVER_REQUIRED
                ):
                    status = (
                        ExecutionStatus
                        .WAITING_FOR_HUMAN
                    )

                return ExecutionResult(
                    run_id=self._evidence.run_id,
                    status=status,
                    code=(
                        gate.decision.reason_code
                        or "ACTION_REJECTED"
                    ),
                    outputs=outputs,
                    current_step=str(step_index),
                    evidence=[
                        observation.screenshot_ref
                    ],
                    duration_ms=_elapsed_ms(started),
                )

            try:
                action_result = (
                    self._surface.execute(
                        proposal.action,
                        target_handle=(
                            resolved.surface_handle
                            if resolved is not None
                            else None
                        ),
                    )
                )

            except Exception as exc:
                step = StepRecord(
                    run_id=self._evidence.run_id,
                    step_index=step_index,
                    actor=Actor.LLM,
                    mode=ExecutionMode.DISCOVERY,
                    intent=decision.intent,
                    action=proposal.action,
                    target_summary=(
                        proposal.target.model_dump(
                            mode="json"
                        )
                        if proposal.target
                        else None
                    ),
                    resolution=resolution,
                    policy_decision=gate.decision,
                    outcome_code="ACTION_EXECUTION_FAILED",
                    evidence_refs=[
                        observation.screenshot_ref
                    ],
                    duration_ms=_elapsed_ms(
                        decision_started
                    ),
                )

                trajectory.append(step)

                self._evidence.record_step(step)

                return ExecutionResult(
                    run_id=self._evidence.run_id,
                    status=ExecutionStatus.FAILURE,
                    code="ACTION_EXECUTION_FAILED",
                    outputs=outputs,
                    current_step=str(step_index),
                    observed=str(exc),
                    evidence=[
                        observation.screenshot_ref
                    ],
                    duration_ms=_elapsed_ms(started),
                )

            if (
                proposal.action.type
                == ActionType.EXTRACT
            ):
                assert proposal.output is not None

                outputs[
                    proposal.output
                ] = action_result.value

            checkpoint_result = None

            if checkpoint is not None:
                checkpoint_result = (
                    self._checkpoints.evaluate(
                        checkpoint,
                        context=CheckpointContext(
                            outputs=outputs
                        ),
                    )
                )

            outcome_code = (
                "CHECKPOINT_FAILED"
                if (
                    checkpoint_result is not None
                    and not checkpoint_result.passed
                )
                else "ACTION_COMPLETED"
            )

            step = StepRecord(
                run_id=self._evidence.run_id,
                step_index=step_index,
                actor=Actor.LLM,
                mode=ExecutionMode.DISCOVERY,
                intent=decision.intent,
                action=proposal.action,
                target_summary=(
                    proposal.target.model_dump(mode="json")
                    if proposal.target
                    else None
                ),
                output_binding=proposal.output,
                risk=gate.risk,
                resolution=resolution,
                policy_decision=gate.decision,
                checkpoint_spec=checkpoint,
                outcome_code="ACTION_EXECUTION_FAILED",
                evidence_refs=[
                    observation.screenshot_ref
                ],
                duration_ms=_elapsed_ms(
                    decision_started
                ),
            )

            trajectory.append(step)

            self._evidence.record_step(step)

            recent_event: dict[str, Any] = {
                "step": step_index,
                "intent": decision.intent,
                "action": (
                    proposal.action.type.value
                ),
                "outcome": outcome_code,
            }

            if (
                proposal.action.type
                == ActionType.EXTRACT
            ):
                recent_event["extracted"] = {
                    proposal.output: (
                        action_result.value
                    )
                }

            if (
                checkpoint_result is not None
                and not checkpoint_result.passed
            ):
                recent_event["checkpoint_feedback"] = {
                    "expected": (
                        checkpoint_result.expected
                    ),
                    "observed": (
                        checkpoint_result.observed
                    ),
                }

            recent_steps.append(
                recent_event
            )

            recent_steps = recent_steps[-6:]

        return ExecutionResult(
            run_id=self._evidence.run_id,
            status=ExecutionStatus.FAILURE,
            code="MAX_STEPS_EXCEEDED",
            outputs=outputs,
            duration_ms=_elapsed_ms(started),
        )

    def _completion_error(
        self,
        proposed_outputs: dict[str, Any] | None,
        grounded_outputs: dict[str, Any],
    ) -> str | None:
        if not proposed_outputs:
            return None

        for name, value in proposed_outputs.items():
            if name not in grounded_outputs:
                return (
                    f"Output {name!r} was not obtained "
                    "through an EXTRACT action"
                )

            if (
                str(grounded_outputs[name]).strip()
                != str(value).strip()
            ):
                return (
                    f"Output {name!r} does not match "
                    "the grounded extracted value"
                )

        return None

    def _finalize(
        self,
        *,
        result: ExecutionResult,
        trajectory: list[StepRecord],
        trace_started: bool,
    ) -> DiscoveryRunResult:
        evidence_refs = list(result.evidence)

        if trace_started:
            try:
                trace_path = (
                    self._surface.stop_trace(
                        self._evidence.run_dir
                        / "trace.zip"
                    )
                )

                evidence_refs.append(
                    trace_path
                )

            except Exception as exc:
                self._evidence.record_event(
                    "trace_stop_failed",
                    {
                        "error": str(exc),
                    },
                )

        result = result.model_copy(
            update={
                "evidence": evidence_refs
            }
        )

        self._evidence.finalize(
            trajectory=trajectory,
            result=result,
            llm_calls=self._model.call_count,
        )

        self._evidence.record_event(
            "run_finished",
            {
                "status": result.status.value,
                "code": result.code,
                "llm_calls": (
                    self._model.call_count
                ),
            },
        )

        return DiscoveryRunResult(
            result=result,
            trajectory=trajectory,
            llm_calls=self._model.call_count,
            evidence_dir=str(
                self._evidence.run_dir
            ),
        )


def _derive_checkpoint(
    proposal: ActionProposal,
) -> CheckpointSpec | None:
    action = proposal.action

    if (
        action.type
        == ActionType.INPUT_TEXT
        and proposal.target is not None
    ):
        return CheckpointSpec(
            type=CheckpointType.CONTROL_VALUE,
            target=proposal.target,
            expected=action.value,
        )

    if (
        action.type
        == ActionType.SELECT_OPTION
        and proposal.target is not None
        and action.option is not None
    ):
        return CheckpointSpec(
            type=CheckpointType.CONTROL_VALUE,
            target=proposal.target,
            expected=action.option,
        )

    if (
        action.type == ActionType.EXTRACT
        and proposal.output is not None
    ):
        return CheckpointSpec(
            type=CheckpointType.OUTPUT_EXTRACTABLE,
            output=proposal.output,
        )

    return None


def _elapsed_ms(started: float) -> int:
    return max(
        0,
        round(
            (monotonic() - started) * 1000
        ),
    )