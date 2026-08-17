from __future__ import annotations
import json

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter
from urllib.parse import urljoin
from uuid import uuid4

from cua.domain import (
    ActionSpec,
    ActionType,
    CapabilityArtifact,
    CheckpointSpec,
    CheckpointType,
    ControlOwner,
    ExecutionResult,
    ExecutionStatus,
    Observation,
    PolicyDecisionType,
    SchemaValueType,
    CapabilityStep,
    RiskLevel,
)
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
)
from cua.surfaces import SurfaceSession

from .bootstrap import (
    NoopSessionBootstrap,
    SessionBootstrap,
    SessionBootstrapContext,
)

_TARGETED_ACTIONS = {
    ActionType.CLICK,
    ActionType.INPUT_TEXT,
    ActionType.SELECT_OPTION,
    ActionType.READ,
    ActionType.EXTRACT,
}


def new_replay_run_id() -> str:
    return f"replay-{uuid4().hex[:12]}"


class ReplayEngine:
    """
    Deterministically execute a bound CapabilityArtifact.

    No discovery model or LLM dependency is permitted here.
    """

    def __init__(
        self,
        *,
        run_id: str,
        surface: SurfaceSession,
        resolver: TargetResolver,
        checkpoint_evaluator: CheckpointEvaluator,
        action_gate: ActionGate,
        evidence_dir: str | Path,
        bootstrap: SessionBootstrap | None = None,
    ) -> None:
        self._run_id = run_id
        self._surface = surface
        self._resolver = resolver
        self._checkpoint_evaluator = checkpoint_evaluator
        self._action_gate = action_gate
        self._evidence_dir = Path(evidence_dir)
        self._bootstrap = bootstrap or NoopSessionBootstrap()
        self._recovery_evidence: list[str] = []

    def _unexpected_dialog_result(
        self,
        artifact: CapabilityArtifact,
        *,
        observation: Observation,
        expected_checkpoint: CheckpointSpec | None,
        current_step: str | None,
        outputs: dict[str, object],
        started: float,
    ) -> ExecutionResult | None:
        if not observation.dialogs:
            return None

        # A capability may deliberately expect a dialog as the
        # result of the action that just executed.
        if (
            expected_checkpoint is not None
            and expected_checkpoint.type == CheckpointType.DIALOG_PRESENT
        ):
            return None

        evidence: list[str] = []

        try:
            evidence.append(
                self._surface.capture_screenshot(
                    "unexpected-dialog.png"
                )
            )
        except Exception:
            pass

        observed = [
            {
                "title": dialog.title,
                "text": dialog.text,
                "modal": dialog.modal,
            }
            for dialog in observation.dialogs
        ]

        return ExecutionResult(
            run_id=self._run_id,
            status=ExecutionStatus.WAITING_FOR_HUMAN,
            code="UNEXPECTED_DIALOG",
            capability_id=artifact.capability.id,
            capability_version=artifact.capability.version,
            outputs=outputs,
            current_step=current_step,
            expected="no unexpected modal/dialog",
            observed=observed,
            evidence=evidence,
            duration_ms=self._elapsed(started),
        )

    def run(
        self,
        artifact: CapabilityArtifact,
        *,
        base_url: str,
    ) -> ExecutionResult:
        started = perf_counter()
        self._recovery_evidence = []

        self._evidence_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        trace_path = self._evidence_dir / "trace.zip"

        trace_started = False
        result: ExecutionResult | None = None
        trace_ref: str | None = None

        try:
            self._surface.start()
            self._surface.start_trace()
            trace_started = True

            result = self._run_steps(
                artifact,
                base_url=base_url,
                started=started,
            )

        except Exception as exc:
            evidence: list[str] = []

            if self._surface.is_started:
                try:
                    evidence.append(
                        self._surface.capture_screenshot(
                            "replay-runtime-error.png"
                        )
                    )
                except Exception:
                    pass

            result = ExecutionResult(
                run_id=self._run_id,
                status=ExecutionStatus.FAILURE,
                code="REPLAY_RUNTIME_ERROR",
                capability_id=artifact.capability.id,
                capability_version=artifact.capability.version,
                outputs={},
                observed=str(exc),
                evidence=evidence,
                duration_ms=self._elapsed(started),
            )

        finally:
            if trace_started and self._surface.is_started:
                try:
                    trace_ref = self._surface.stop_trace(
                        trace_path
                    )
                except Exception:
                    trace_ref = None

            if self._surface.is_started:
                self._surface.close()

        assert result is not None, (
            "result should be set by _run_steps or exception handler"
        )

        if trace_ref is not None and trace_ref not in result.evidence:
            result = result.model_copy(
                update={
                    "evidence": [
                        *result.evidence,
                        trace_ref,
                    ]
                }
            )

        return result

    def _run_steps(
        self,
        artifact: CapabilityArtifact,
        *,
        base_url: str,
        started: float,
    ) -> ExecutionResult:
        outputs: dict[str, object] = {}

        # Session establishment is separate from the reusable
        # business capability.
        self._bootstrap.prepare(
            SessionBootstrapContext(
                surface=self._surface,
                resolver=self._resolver,
                checkpoint_evaluator=self._checkpoint_evaluator,
                action_gate=self._action_gate,
                base_url=base_url,
            )
        )

        entry_url = urljoin(
            base_url.rstrip("/") + "/",
            artifact.application.entry_point.lstrip("/"),
        )

        navigation = ActionSpec(
            type=ActionType.NAVIGATE,
            value=entry_url,
        )

        navigation_gate = self._action_gate.evaluate(
            GateContext(
                action=navigation,
                current_url=self._surface.current_url,
                control_owner=ControlOwner.AUTOMATION,
            )
        )

        if (
            navigation_gate.decision.decision
            != PolicyDecisionType.ALLOW
        ):
            return self._policy_result(
                artifact,
                navigation_gate.decision.decision,
                navigation_gate.decision.reason_code,
                started=started,
            )

        self._surface.execute(navigation)

        observation = self._surface.observe()

        # Check entry state before the first capability step.
        dialog_result = self._unexpected_dialog_result(
            artifact,
            observation=observation,
            expected_checkpoint=None,
            current_step=None,
            outputs=outputs,
            started=started,
        )
        if dialog_result is not None:
            return dialog_result

        hard_failure = self._hard_failure_result(
            artifact,
            outputs,
            observation,
            current_step=None,
            started=started,
        )
        if hard_failure is not None:
            return hard_failure

        outcome = self._business_outcome(
            artifact,
            outputs,
            observation,
            current_step=None,
            started=started,
        )
        if outcome is not None:
            return outcome

        for step in artifact.steps:
            # IMPORTANT:
            # Do not evaluate step.checkpoint here.
            #
            # A step checkpoint describes the expected state
            # AFTER this step's action executes. Evaluating it
            # before execution caused INPUT_TEXT steps to fail
            # against the still-empty field.

            # If the application is already in an unexpected
            # dialog state before the next action, stop rather
            # than interacting with controls underneath it.
            dialog_result = self._unexpected_dialog_result(
                artifact,
                observation=observation,
                expected_checkpoint=None,
                current_step=step.id,
                outputs=outputs,
                started=started,
            )
            if dialog_result is not None:
                return dialog_result

            hard_failure = self._hard_failure_result(
                artifact,
                outputs,
                observation,
                current_step=step.id,
                started=started,
            )
            if hard_failure is not None:
                return hard_failure

            outcome = self._business_outcome(
                artifact,
                outputs,
                observation,
                current_step=step.id,
                started=started,
            )
            if outcome is not None:
                return outcome

            resolved = None

            if step.target is not None:
                try:
                    resolved = self._resolver.resolve(
                        step.target
                    )

                except TargetAmbiguous as exc:
                    return self._failure(
                        artifact,
                        code="TARGET_AMBIGUOUS",
                        step_id=step.id,
                        expected=step.target.model_dump(
                            mode="json"
                        ),
                        observed=(
                            f"{exc.candidate_count} candidates"
                        ),
                        outputs=outputs,
                        started=started,
                    )

                except TargetNotFound:
                    return self._failure(
                        artifact,
                        code="TARGET_NOT_FOUND",
                        step_id=step.id,
                        expected=step.target.model_dump(
                            mode="json"
                        ),
                        observed="no candidate resolved",
                        outputs=outputs,
                        started=started,
                    )

            elif step.action.type in _TARGETED_ACTIONS:
                return self._failure(
                    artifact,
                    code="INVALID_CAPABILITY_TARGET",
                    step_id=step.id,
                    expected="target specification",
                    observed=None,
                    outputs=outputs,
                    started=started,
                )

            gate = self._action_gate.evaluate(
                GateContext(
                    action=step.action,
                    current_url=self._surface.current_url,
                    control_owner=ControlOwner.AUTOMATION,
                    target_confidence=(
                        resolved.confidence
                        if resolved is not None
                        else None
                    ),
                    has_checkpoint=(
                        step.checkpoint is not None
                    ),
                )
            )

            if gate.decision.decision != PolicyDecisionType.ALLOW:
                return self._policy_result(
                    artifact,
                    gate.decision.decision,
                    gate.decision.reason_code,
                    current_step=step.id,
                    outputs=outputs,
                    started=started,
                )

            # Replay independently checks policy risk rather than
            # trusting the artifact blindly.
            if (
                gate.risk.level != step.risk.level
                or gate.risk.reversible != step.risk.reversible
            ):
                return self._failure(
                    artifact,
                    code="RISK_CLASSIFICATION_MISMATCH",
                    step_id=step.id,
                    expected=step.risk.model_dump(
                        mode="json"
                    ),
                    observed=gate.risk.model_dump(
                        mode="json"
                    ),
                    outputs=outputs,
                    started=started,
                )

            # Execute EVERY accepted capability action.
            try:
                action_result = self._surface.execute(
                    step.action,
                    target_handle=(
                        resolved.surface_handle
                        if resolved is not None
                        else None
                    ),
                )
            except Exception as exc:
                return self._failure(
                    artifact,
                    code="ACTION_EXECUTION_FAILED",
                    step_id=step.id,
                    expected=step.action.model_dump(
                        mode="json"
                    ),
                    observed=str(exc),
                    outputs=outputs,
                    started=started,
                )

            # Only output handling is conditional on EXTRACT.
            if step.action.type == ActionType.EXTRACT:
                if step.output is None:
                    return self._failure(
                        artifact,
                        code="INVALID_OUTPUT_BINDING",
                        step_id=step.id,
                        expected="declared output binding",
                        observed=None,
                        outputs=outputs,
                        started=started,
                    )

                try:
                    outputs[step.output] = self._coerce_output(
                        artifact,
                        step.output,
                        action_result.value,
                    )
                except Exception as exc:
                    return self._failure(
                        artifact,
                        code="OUTPUT_EXTRACTION_FAILED",
                        step_id=step.id,
                        expected=step.output,
                        observed=str(exc),
                        outputs=outputs,
                        started=started,
                    )

            # Re-observe only after the action has executed.
            observation = self._surface.observe()

            # Unexpected modal/dialog state takes precedence over
            # happy-path controls that may still be visible beneath
            # an overlay.
            dialog_result = self._unexpected_dialog_result(
                artifact,
                observation=observation,
                expected_checkpoint=step.checkpoint,
                current_step=step.id,
                outputs=outputs,
                started=started,
            )
            if dialog_result is not None:
                return dialog_result

            # Known hard failures take precedence over business
            # outcomes and normal happy-path checkpoint failures.
            hard_failure = self._hard_failure_result(
                artifact,
                outputs,
                observation,
                current_step=step.id,
                started=started,
            )
            if hard_failure is not None:
                return hard_failure

            # Known business outcomes also take precedence over
            # normal happy-path checkpoint failures.
            outcome = self._business_outcome(
                artifact,
                outputs,
                observation,
                current_step=step.id,
                started=started,
            )
            if outcome is not None:
                return outcome

            # A checkpoint is the postcondition of the action, so
            # it is evaluated here, after action + fresh observe.
            observation, recovery_result = (
                self._checkpoint_with_recovery(
                    artifact,
                    step=step,
                    observation=observation,
                    outputs=outputs,
                    started=started,
                )
            )

            if recovery_result is not None:
                return recovery_result

            final_observation = self._surface.observe()

            final_dialog_result = self._unexpected_dialog_result(
                artifact,
                observation=final_observation,
                expected_checkpoint=artifact.success_condition,
                current_step=(
                    artifact.steps[-1].id
                    if artifact.steps
                    else None
                ),
                outputs=outputs,
                started=started,
            )
            if final_dialog_result is not None:
                return final_dialog_result

        final_hard_failure = self._hard_failure_result(
            artifact,
            outputs,
            final_observation,
            current_step=(
                artifact.steps[-1].id
                if artifact.steps
                else None
            ),
            started=started,
        )
        if final_hard_failure is not None:
            return final_hard_failure

        final_outcome = self._business_outcome(
            artifact,
            outputs,
            final_observation,
            current_step=(
                artifact.steps[-1].id
                if artifact.steps
                else None
            ),
            started=started,
        )
        if final_outcome is not None:
            return final_outcome

        final_checkpoint = self._checkpoint_evaluator.evaluate(
            artifact.success_condition,
            context=CheckpointContext(
                outputs=outputs,
                observation=final_observation,
            ),
        )

        if not final_checkpoint.passed:
            return self._failure(
                artifact,
                code="SUCCESS_CONDITION_FAILED",
                step_id=(
                    artifact.steps[-1].id
                    if artifact.steps
                    else None
                ),
                expected=final_checkpoint.expected,
                observed=final_checkpoint.observed,
                outputs=outputs,
                started=started,
            )

        return ExecutionResult(
            run_id=self._run_id,
            status=ExecutionStatus.SUCCESS,
            capability_id=artifact.capability.id,
            capability_version=artifact.capability.version,
            outputs=outputs,
            evidence=list(
                self._recovery_evidence
            ),
            duration_ms=self._elapsed(started),
        )

    def _record_recovery_event(
        self,
        *,
        step_id: str,
        condition: str,
        attempt: int,
        max_attempts: int,
        delay_ms: int,
        passed: bool,
        expected: object,
        observed: object,
    ) -> None:
        path = (
            self._evidence_dir
            / "recovery_events.jsonl"
        )

        payload = {
            "run_id": self._run_id,
            "step_id": step_id,
            "condition": condition,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "delay_ms": delay_ms,
            "passed": passed,
            "expected": expected,
            "observed": observed,
        }

        with path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    payload,
                    default=str,
                )
                + "\n"
            )

        reference = str(path)

        if reference not in self._recovery_evidence:
            self._recovery_evidence.append(
                reference
            )

    def _checkpoint_with_recovery(
        self,
        artifact: CapabilityArtifact,
        *,
        step: CapabilityStep,
        observation: Observation,
        outputs: dict[str, object],
        started: float,
    ) -> tuple[
        Observation,
        ExecutionResult | None,
    ]:
        if step.checkpoint is None:
            return observation, None

        checkpoint_result = (
            self._checkpoint_evaluator.evaluate(
                step.checkpoint,
                context=CheckpointContext(
                    outputs=outputs,
                    observation=observation,
                ),
            )
        )

        if checkpoint_result.passed:
            return observation, None

        retry = step.retry

        retryable = (
            retry.max_attempts > 1
            and "CHECKPOINT_FAILED"
            in retry.retry_on
        )

        if not retryable:
            return (
                observation,
                self._failure(
                    artifact,
                    code="CHECKPOINT_FAILED",
                    step_id=step.id,
                    expected=(
                        checkpoint_result.expected
                    ),
                    observed=(
                        checkpoint_result.observed
                    ),
                    outputs=outputs,
                    started=started,
                ),
            )

        # Defense in depth. The compiler also rejects this.
        if (
            step.risk.level != RiskLevel.SAFE
            or not step.risk.reversible
        ):
            return (
                observation,
                self._failure(
                    artifact,
                    code="UNSAFE_RETRY_BLOCKED",
                    step_id=step.id,
                    expected=(
                        "retry only for safe, "
                        "reversible steps"
                    ),
                    observed=(
                        step.risk.model_dump(
                            mode="json"
                        )
                    ),
                    outputs=outputs,
                    started=started,
                ),
            )

        last_result = checkpoint_result

        # max_attempts includes the original checkpoint
        # evaluation. Therefore attempt 2 is one retry.
        for attempt in range(
            2,
            retry.max_attempts + 1,
        ):
            if retry.delay_ms > 0:
                wait_action = ActionSpec(
                    type=ActionType.WAIT,
                    value=retry.delay_ms,
                )

                wait_gate = (
                    self._action_gate.evaluate(
                        GateContext(
                            action=wait_action,
                            current_url=(
                                self._surface.current_url
                            ),
                            control_owner=(
                                ControlOwner.AUTOMATION
                            ),
                        )
                    )
                )

                if (
                    wait_gate.decision.decision
                    != PolicyDecisionType.ALLOW
                ):
                    return (
                        observation,
                        self._policy_result(
                            artifact,
                            wait_gate.decision.decision,
                            wait_gate.decision.reason_code,
                            current_step=step.id,
                            outputs=outputs,
                            started=started,
                        ),
                    )

                self._surface.execute(
                    wait_action
                )

            observation = self._surface.observe()

            dialog_result = (
                self._unexpected_dialog_result(
                    artifact,
                    observation=observation,
                    expected_checkpoint=(
                        step.checkpoint
                    ),
                    current_step=step.id,
                    outputs=outputs,
                    started=started,
                )
            )

            if dialog_result is not None:
                return observation, dialog_result

            hard_failure = (
                self._hard_failure_result(
                    artifact,
                    outputs,
                    observation,
                    current_step=step.id,
                    started=started,
                )
            )

            if hard_failure is not None:
                return observation, hard_failure

            outcome = self._business_outcome(
                artifact,
                outputs,
                observation,
                current_step=step.id,
                started=started,
            )

            if outcome is not None:
                return observation, outcome

            last_result = (
                self._checkpoint_evaluator.evaluate(
                    step.checkpoint,
                    context=CheckpointContext(
                        outputs=outputs,
                        observation=observation,
                    ),
                )
            )

            self._record_recovery_event(
                step_id=step.id,
                condition="CHECKPOINT_FAILED",
                attempt=attempt,
                max_attempts=(
                    retry.max_attempts
                ),
                delay_ms=retry.delay_ms,
                passed=last_result.passed,
                expected=last_result.expected,
                observed=last_result.observed,
            )

            if last_result.passed:
                return observation, None

        return (
            observation,
            self._failure(
                artifact,
                code="CHECKPOINT_FAILED",
                step_id=step.id,
                expected=last_result.expected,
                observed=last_result.observed,
                outputs=outputs,
                started=started,
            ),
        )

    def _hard_failure_result(
        self,
        artifact: CapabilityArtifact,
        outputs: dict[str, object],
        observation: Observation,
        *,
        current_step: str | None,
        started: float,
    ) -> ExecutionResult | None:
        for rule in artifact.hard_failures:
            result = self._checkpoint_evaluator.evaluate(
                rule.detect,
                context=CheckpointContext(
                    outputs=outputs,
                    observation=observation,
                ),
            )

            if not result.passed or not rule.terminal:
                continue

            evidence: list[str] = []

            try:
                evidence.append(
                    self._surface.capture_screenshot(
                        f"{rule.code.lower()}.png"
                    )
                )
            except Exception:
                pass

            return ExecutionResult(
                run_id=self._run_id,
                status=ExecutionStatus.FAILURE,
                code=rule.code,
                capability_id=artifact.capability.id,
                capability_version=artifact.capability.version,
                outputs=outputs,
                current_step=current_step,
                expected=result.expected,
                observed=result.observed,
                evidence=evidence,
                duration_ms=self._elapsed(started),
            )

        return None


    def _business_outcome(
        self,
        artifact: CapabilityArtifact,
        outputs: dict[str, object],
        observation: Observation,
        *,
        current_step: str | None = None,
        started: float,
    ) -> ExecutionResult | None:
        for rule in artifact.business_outcomes:
            result = self._checkpoint_evaluator.evaluate(
                rule.detect,
                context=CheckpointContext(
                    outputs=outputs,
                    observation=observation,
                ),
            )

            if result.passed and rule.terminal:
                return ExecutionResult(
                    run_id=self._run_id,
                    status=ExecutionStatus.BUSINESS_OUTCOME,
                    code=rule.code,
                    capability_id=artifact.capability.id,
                    capability_version=artifact.capability.version,
                    outputs=outputs,
                    current_step=current_step,
                    expected=result.expected,
                    observed=result.observed,
                    evidence=[],
                    duration_ms=self._elapsed(started),
                )

        return None

    
    def _failure(
        self,
        artifact: CapabilityArtifact,
        *,
        code: str,
        step_id: str | None,
        expected: object,
        observed: object,
        outputs: dict[str, object],
        started: float,
    ) -> ExecutionResult:
        evidence: list[str] = list(
            self._recovery_evidence
        )

        try:
            evidence.append(
                self._surface.capture_screenshot(
                    f"{code.lower()}.png"
                )
            )
        except Exception:
            pass

        return ExecutionResult(
            run_id=self._run_id,
            status=ExecutionStatus.FAILURE,
            code=code,
            capability_id=artifact.capability.id,
            capability_version=artifact.capability.version,
            outputs=outputs,
            current_step=step_id,
            expected=expected,
            observed=observed,
            evidence=evidence,
            duration_ms=self._elapsed(started),
        )

    def _policy_result(
        self,
        artifact: CapabilityArtifact,
        decision: PolicyDecisionType,
        code: str | None,
        *,
        current_step: str | None = None,
        outputs: dict[str, object] | None = None,
        started: float,
    ) -> ExecutionResult:
        if decision == PolicyDecisionType.APPROVAL_REQUIRED:
            status = ExecutionStatus.WAITING_FOR_APPROVAL

        elif decision == PolicyDecisionType.TAKEOVER_REQUIRED:
            status = ExecutionStatus.WAITING_FOR_HUMAN

        else:
            status = ExecutionStatus.REJECTED

        return ExecutionResult(
            run_id=self._run_id,
            status=status,
            code=(
                code
                if status == ExecutionStatus.REJECTED
                else None
            ),
            capability_id=artifact.capability.id,
            capability_version=artifact.capability.version,
            outputs=outputs or {},
            current_step=current_step,
            evidence=[],
            duration_ms=self._elapsed(started),
        )

    def _coerce_output(
        self,
        artifact: CapabilityArtifact,
        output_name: str,
        raw: object,
    ) -> object:
        definition = artifact.outputs[output_name]

        if raw is None:
            return None

        if definition.type == SchemaValueType.STRING:
            return str(raw).strip()

        if definition.type == SchemaValueType.INTEGER:
            return int(
                str(raw)
                .strip()
                .replace(",", "")
            )

        if definition.type == SchemaValueType.NUMBER:
            return float(
                str(raw)
                .strip()
                .replace(",", "")
            )

        if definition.type == SchemaValueType.DECIMAL:
            text = str(raw).strip()

            match = re.search(
                r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
                r"(?:\.\d+)?",
                text,
            )

            if match is None:
                raise ValueError(
                    f"Cannot parse decimal output "
                    f"{output_name!r} from {text!r}"
                )

            try:
                return Decimal(
                    match.group(0).replace(
                        ",",
                        "",
                    )
                )
            except InvalidOperation as exc:
                raise ValueError(
                    f"Invalid decimal output "
                    f"{output_name!r}"
                ) from exc

        if definition.type == SchemaValueType.BOOLEAN:
            normalized = str(raw).strip().casefold()

            if normalized in {
                "true",
                "yes",
                "1",
            }:
                return True

            if normalized in {
                "false",
                "no",
                "0",
            }:
                return False

            raise ValueError(
                f"Cannot parse boolean output "
                f"{output_name!r}"
            )

        return raw

    @staticmethod
    def _elapsed(started: float) -> int:
        return int(
            (perf_counter() - started) * 1000
        )