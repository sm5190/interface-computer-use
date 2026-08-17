from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from cua.domain import (
    ActionSpec,
    ActionType,
    ApprovalState,
    CapabilityArtifact,
    CapabilityMetadata,
    CapabilityPolicy,
    CapabilityStep,
    CheckpointSpec,
    CheckpointType,
    PolicyDecisionType,
    RetrySpec,
    RiskLevel,
    StepRecord,
    TargetSpec,
)

from .models import CapabilityRecipe, InputBinding


class CapabilityCompilationError(ValueError):
    pass


class GenericCapabilityCompiler:
    """
    Compile a successful discovery trajectory into a
    deterministic CapabilityArtifact.

    This class intentionally contains no application-specific
    business logic.
    """

    def compile(
        self,
        *,
        trajectory: list[StepRecord],
        recipe: CapabilityRecipe,
    ) -> CapabilityArtifact:
        selected = self._select_successful_steps(
            trajectory=trajectory,
            recipe=recipe,
        )

        if not selected:
            raise CapabilityCompilationError(
                "No successful discovery steps were selected "
                "for compilation"
            )

        run_ids = {step.run_id for step in selected}

        if len(run_ids) != 1:
            raise CapabilityCompilationError(
                "Capability steps must come from one discovery run"
            )

        compiled_steps: list[CapabilityStep] = []

        for index, step in enumerate(selected):
            next_step = (
                selected[index + 1]
                if index + 1 < len(selected)
                else None
            )

            compiled_steps.append(
                self._compile_step(
                    step=step,
                    next_step=next_step,
                    recipe=recipe,
                    artifact_index=index,
                )
            )

        self._validate_output_bindings(
            steps=compiled_steps,
            recipe=recipe,
        )

        parameterized_success = (
            self._parameterize_checkpoint(
                recipe.success_condition,
                recipe.inputs,
            )
        )

        parameterized_outcomes = [
            outcome.model_copy(
                update={
                    "detect": self._parameterize_checkpoint(
                        outcome.detect,
                        recipe.inputs,
                    )
                }
            )
            for outcome in recipe.business_outcomes
        ]

        parameterized_hard_failures = [
            rule.model_copy(
                update={
                    "detect": self._parameterize_checkpoint(
                        rule.detect,
                        recipe.inputs,
                    )
                }
            )
            for rule in recipe.hard_failures
        ]
        # print(
        #     "[DEBUG COMPILER recipe.hard_failures]",
        #     recipe.hard_failures,
        # )

        # print(
        #     "[DEBUG COMPILER parameterized_hard_failures]",
        #     parameterized_hard_failures,
        # )


        artifact = CapabilityArtifact(

            capability=recipe.capability,
            application=recipe.application,
            inputs={
                name: binding.definition
                for name, binding in recipe.inputs.items()
            },
            outputs=recipe.outputs,
            steps=compiled_steps,
            business_outcomes=parameterized_outcomes,
            hard_failures=parameterized_hard_failures,
            success_condition=parameterized_success,
            policy=self._derive_capability_policy(
                compiled_steps
            ),
            metadata=CapabilityMetadata(
                created_from_run=selected[0].run_id,
                approval_state=ApprovalState.DRAFT,
            ),
        )

        self._assert_parameterization(
            artifact=artifact,
            bindings=recipe.inputs,
        )
        # print(
        #     "[DEBUG COMPILER artifact.hard_failures]",
        #     artifact.hard_failures,
        # )

        return artifact

    def _select_successful_steps(
        self,
        *,
        trajectory: list[StepRecord],
        recipe: CapabilityRecipe,
    ) -> list[StepRecord]:
        window = recipe.trajectory

        selected: list[StepRecord] = []

        for step in trajectory:
            if step.step_index < window.start_step_index:
                continue

            if (
                window.end_step_index is not None
                and step.step_index > window.end_step_index
            ):
                continue

            # Failed/ambiguous discovery attempts are evidence,
            # not executable capability steps.
            if step.outcome_code != "ACTION_COMPLETED":
                continue

            if (
                step.policy_decision is not None
                and step.policy_decision.decision
                != PolicyDecisionType.ALLOW
            ):
                continue

            selected.append(step)

        return selected

    def _compile_step(
        self,
        *,
        step: StepRecord,
        next_step: StepRecord | None,
        recipe: CapabilityRecipe,
        artifact_index: int,
    ) -> CapabilityStep:
        if step.action is None:
            raise CapabilityCompilationError(
                f"Successful step {step.step_index} has no action"
            )

        if step.risk is None:
            raise CapabilityCompilationError(
                f"Successful step {step.step_index} has no "
                "recorded risk classification"
            )

        action = self._parameterize_action(
            step.action,
            recipe.inputs,
        )

        target = self._compile_target(
            step=step,
            bindings=recipe.inputs,
        )

        checkpoint = self._compile_checkpoint(
            step=step,
            next_step=next_step,
            bindings=recipe.inputs,
        )

        step_id = self._step_id(
            artifact_index=artifact_index,
            action=action,
            target=target,
        )

        retry = recipe.step_retries.get(
            step_id,
            RetrySpec(max_attempts=1),
        )

        # Bounded retries are only allowed for safe actions.
        if (
            retry.max_attempts > 1
            and step.risk.level != RiskLevel.SAFE
        ):
            raise CapabilityCompilationError(
                f"Step {step_id!r} declares retry "
                "but is not classified SAFE"
            )

        return CapabilityStep(
            id=step_id,
            action=action,
            target=target,
            output=step.output_binding,
            risk=step.risk,
            checkpoint=checkpoint,
            timeout_ms=recipe.default_timeout_ms,
            retry=retry,
        )

    def _compile_target(
        self,
        *,
        step: StepRecord,
        bindings: dict[str, InputBinding],
    ) -> TargetSpec | None:
        if step.target_summary is None:
            return None

        raw = self._parameterize_data(
            deepcopy(step.target_summary),
            bindings,
        )

        target = TargetSpec.model_validate(raw)

        # Discovery already told us which strategy genuinely
        # resolved the control. Prefer it during replay.
        if step.resolution is not None:
            resolved_kind = step.resolution.strategy_kind

            ordered = sorted(
                target.strategies,
                key=lambda strategy: (
                    0
                    if strategy.kind == resolved_kind
                    else 1
                ),
            )

            target = target.model_copy(
                update={"strategies": ordered}
            )

        return target

    def _compile_checkpoint(
        self,
        *,
        step: StepRecord,
        next_step: StepRecord | None,
        bindings: dict[str, InputBinding],
    ) -> CheckpointSpec | None:
        if step.checkpoint_spec is not None:
            return self._parameterize_checkpoint(
                step.checkpoint_spec,
                bindings,
            )

        # Generic evidence-based fallback:
        #
        # If action N succeeded and the following successful
        # observation resolved a target, the presence of that
        # next target is a deterministic checkpoint for action N.
        if (
            next_step is not None
            and next_step.target_summary is not None
        ):
            raw_target = self._parameterize_data(
                deepcopy(next_step.target_summary),
                bindings,
            )

            target = TargetSpec.model_validate(
                raw_target
            )

            return CheckpointSpec(
                type=CheckpointType.CONTROL_PRESENT,
                target=target,
            )

        # WAIT/SCROLL may legitimately have no useful state
        # assertion in v1.
        if step.action is not None and step.action.type in {
            ActionType.WAIT,
            ActionType.SCROLL,
        }:
            return None

        raise CapabilityCompilationError(
            f"Cannot derive deterministic checkpoint for "
            f"successful step {step.step_index}"
        )

    def _parameterize_action(
        self,
        action: ActionSpec,
        bindings: dict[str, InputBinding],
    ) -> ActionSpec:
        raw = action.model_dump(mode="python")

        raw = self._parameterize_data(
            raw,
            bindings,
        )

        return ActionSpec.model_validate(raw)

    def _parameterize_checkpoint(
        self,
        checkpoint: CheckpointSpec,
        bindings: dict[str, InputBinding],
    ) -> CheckpointSpec:
        raw = checkpoint.model_dump(mode="python")

        raw = self._parameterize_data(
            raw,
            bindings,
        )

        return CheckpointSpec.model_validate(raw)

    def _parameterize_data(
        self,
        value: Any,
        bindings: dict[str, InputBinding],
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._parameterize_data(
                    child,
                    bindings,
                )
                for key, child in value.items()
            }

        if isinstance(value, list):
            return [
                self._parameterize_data(
                    child,
                    bindings,
                )
                for child in value
            ]

        for name, binding in bindings.items():
            placeholder = "{{" + name + "}}"

            discovery_value = binding.discovery_value

            # Preserve type-independent exact replacement.
            if value == discovery_value:
                return placeholder

            if (
                isinstance(value, str)
                and binding.replace_inside_strings
            ):
                discovery_text = str(discovery_value)

                # Avoid dangerous substring replacement for tiny
                # values such as "1".
                if (
                    len(discovery_text) >= 3
                    and discovery_text in value
                ):
                    value = value.replace(
                        discovery_text,
                        placeholder,
                    )

        return value

    def _validate_output_bindings(
        self,
        *,
        steps: list[CapabilityStep],
        recipe: CapabilityRecipe,
    ) -> None:
        produced = {
            step.output
            for step in steps
            if step.output is not None
        }

        declared = set(recipe.outputs)

        undeclared = produced - declared

        if undeclared:
            raise CapabilityCompilationError(
                "Trajectory produced undeclared outputs: "
                f"{sorted(undeclared)}"
            )

        missing = {
            name
            for name, definition
            in recipe.outputs.items()
            if not definition.nullable
            and name not in produced
        }

        if missing:
            raise CapabilityCompilationError(
                "Required outputs were not grounded by "
                f"successful EXTRACT actions: {sorted(missing)}"
            )

    def _derive_capability_policy(
        self,
        steps: list[CapabilityStep],
    ) -> CapabilityPolicy:
        levels = {
            step.risk.level
            for step in steps
        }

        if RiskLevel.IRREVERSIBLE in levels:
            return CapabilityPolicy(
                risk="contains_irreversible",
                requires_human_approval=True,
            )

        if RiskLevel.REVERSIBLE_WRITE in levels:
            return CapabilityPolicy(
                risk="reversible_write",
                requires_human_approval=False,
            )

        return CapabilityPolicy(
            risk="read_only",
            requires_human_approval=False,
        )

    def _step_id(
        self,
        *,
        artifact_index: int,
        action: ActionSpec,
        target: TargetSpec | None,
    ) -> str:
        parts = [
            f"step-{artifact_index + 1:02d}",
            action.type.value,
        ]

        if target is not None:
            parts.append(target.logical_name)

        slug = "-".join(parts)

        slug = re.sub(
            r"[^a-z0-9_-]+",
            "-",
            slug.lower(),
        )

        return slug.strip("-")

    def _assert_parameterization(
        self,
        *,
        artifact: CapabilityArtifact,
        bindings: dict[str, InputBinding],
    ) -> None:
        serialized = artifact.model_dump_json()

        for name, binding in bindings.items():
            raw_value = str(binding.discovery_value)

            if (
                binding.definition.sensitive
                and len(raw_value) >= 3
                and raw_value in serialized
            ):
                raise CapabilityCompilationError(
                    f"Sensitive discovery value for input "
                    f"{name!r} remains in compiled artifact"
                )

            placeholder = "{{" + name + "}}"

            if placeholder not in serialized:
                raise CapabilityCompilationError(
                    f"Input {name!r} was declared but no "
                    "parameterized occurrence was compiled"
                )