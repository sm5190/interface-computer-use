from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlsplit

from cua.domain import (
    ActionSpec,
    ActionType,
    CheckpointResult,
    CheckpointSpec,
    CheckpointType,
    Observation,
)
from cua.surfaces import SurfaceSession

from .base import (
    TargetAmbiguous,
    TargetNotFound,
)
from .resolver import TargetResolver


@dataclass(slots=True)
class CheckpointContext:
    outputs: dict[str, Any] = field(
        default_factory=dict
    )

    observation: Observation | None = None


class CheckpointEvaluator:
    """
    Deterministically evaluate capability checkpoints.
    """

    def __init__(
        self,
        *,
        surface: SurfaceSession,
        resolver: TargetResolver,
    ) -> None:
        self._surface = surface
        self._resolver = resolver

    def evaluate(
        self,
        checkpoint: CheckpointSpec,
        *,
        context: CheckpointContext | None = None,
    ) -> CheckpointResult:
        context = context or CheckpointContext()

        if checkpoint.type == CheckpointType.CONTROL_PRESENT:
            return self._control_present(
                checkpoint
            )

        if checkpoint.type == CheckpointType.CONTROL_ABSENT:
            return self._control_absent(
                checkpoint
            )

        if checkpoint.type == CheckpointType.CONTROL_VALUE:
            return self._control_value(
                checkpoint
            )

        if checkpoint.type == CheckpointType.TEXT_PRESENT:
            return self._text_present(
                checkpoint,
                context,
            )

        if checkpoint.type == CheckpointType.URL_MATCHES:
            return self._url_matches(
                checkpoint
            )

        if checkpoint.type == CheckpointType.DIALOG_PRESENT:
            return self._dialog_present(
                checkpoint,
                context,
            )

        if (
            checkpoint.type
            == CheckpointType.OUTPUT_EXTRACTABLE
        ):
            return self._output_extractable(
                checkpoint,
                context,
            )

        if checkpoint.type == CheckpointType.PAGE_STATE:
            return self._page_state(
                checkpoint,
                context,
            )

        return CheckpointResult(
            passed=False,
            expected=checkpoint.model_dump(
                mode="json"
            ),
            observed=None,
            details=(
                f"Unsupported checkpoint type: "
                f"{checkpoint.type}"
            ),
        )

    def _control_present(
        self,
        checkpoint: CheckpointSpec,
    ) -> CheckpointResult:
        assert checkpoint.target is not None

        try:
            resolved = self._resolver.resolve(
                checkpoint.target
            )
        except TargetNotFound:
            return CheckpointResult(
                passed=False,
                expected="control present",
                observed="not found",
            )
        except TargetAmbiguous as exc:
            return CheckpointResult(
                passed=False,
                expected="one resolvable control",
                observed=(
                    f"{exc.candidate_count} candidates"
                ),
                details="target is ambiguous",
            )

        return CheckpointResult(
            passed=True,
            expected="control present",
            observed={
                "logical_name": resolved.logical_name,
                "strategy": (
                    resolved.strategy_kind.value
                ),
            },
        )

    def _control_absent(
        self,
        checkpoint: CheckpointSpec,
    ) -> CheckpointResult:
        assert checkpoint.target is not None

        try:
            resolved = self._resolver.resolve(
                checkpoint.target
            )
        except TargetNotFound:
            return CheckpointResult(
                passed=True,
                expected="control absent",
                observed="not found",
            )
        except TargetAmbiguous as exc:
            return CheckpointResult(
                passed=False,
                expected="control absent",
                observed=(
                    f"{exc.candidate_count} candidates"
                ),
            )

        return CheckpointResult(
            passed=False,
            expected="control absent",
            observed={
                "logical_name": resolved.logical_name,
                "strategy": (
                    resolved.strategy_kind.value
                ),
            },
        )

    def _control_value(
        self,
        checkpoint: CheckpointSpec,
    ) -> CheckpointResult:
        assert checkpoint.target is not None

        try:
            resolved = self._resolver.resolve(
                checkpoint.target
            )

        except TargetNotFound:
            return CheckpointResult(
                passed=False,
                expected=checkpoint.expected,
                observed="target not found",
            )

        except TargetAmbiguous as exc:
            return CheckpointResult(
                passed=False,
                expected=checkpoint.expected,
                observed=(
                    f"{exc.candidate_count} candidates"
                ),
            )

        result = self._surface.execute(
            ActionSpec(
                type=ActionType.EXTRACT
            ),
            target_handle=resolved.surface_handle,
        )

        observed = result.value
        expected = checkpoint.expected

        return CheckpointResult(
            passed=(
                str(observed).strip()
                == str(expected).strip()
            ),
            expected=expected,
            observed=observed,
        )

    def _text_present(
        self,
        checkpoint: CheckpointSpec,
        context: CheckpointContext,
    ) -> CheckpointResult:
        assert checkpoint.value is not None

        observation = self._observation(context)

        combined = "\n".join(
            observation.visible_text
        )

        passed = checkpoint.value in combined

        return CheckpointResult(
            passed=passed,
            expected=checkpoint.value,
            observed=(
                checkpoint.value
                if passed
                else "text not present"
            ),
        )

    def _url_matches(
        self,
        checkpoint: CheckpointSpec,
    ) -> CheckpointResult:
        assert checkpoint.pattern is not None

        current = self._surface.current_url
        path = urlsplit(current).path or "/"

        passed = (
            fnmatchcase(
                current,
                checkpoint.pattern,
            )
            or fnmatchcase(
                path,
                checkpoint.pattern,
            )
        )

        return CheckpointResult(
            passed=passed,
            expected=checkpoint.pattern,
            observed=current,
        )

    def _dialog_present(
        self,
        checkpoint: CheckpointSpec,
        context: CheckpointContext,
    ) -> CheckpointResult:
        assert checkpoint.value is not None

        observation = self._observation(context)

        matches = [
            dialog
            for dialog in observation.dialogs
            if (
                checkpoint.value in dialog.text
                or (
                    dialog.title is not None
                    and checkpoint.value
                    in dialog.title
                )
            )
        ]

        return CheckpointResult(
            passed=bool(matches),
            expected=checkpoint.value,
            observed=(
                matches[0].text
                if matches
                else "dialog not present"
            ),
        )

    @staticmethod
    def _output_extractable(
        checkpoint: CheckpointSpec,
        context: CheckpointContext,
    ) -> CheckpointResult:
        assert checkpoint.output is not None

        exists = (
            checkpoint.output in context.outputs
            and context.outputs[
                checkpoint.output
            ]
            is not None
        )

        return CheckpointResult(
            passed=exists,
            expected=checkpoint.output,
            observed=(
                context.outputs.get(
                    checkpoint.output
                )
                if exists
                else "output unavailable"
            ),
        )

    def _page_state(
        self,
        checkpoint: CheckpointSpec,
        context: CheckpointContext,
    ) -> CheckpointResult:
        results = [
            self.evaluate(
                child,
                context=context,
            )
            for child in checkpoint.all_of
        ]

        passed = all(
            result.passed
            for result in results
        )

        return CheckpointResult(
            passed=passed,
            expected=[
                result.expected
                for result in results
            ],
            observed=[
                result.observed
                for result in results
            ],
            details=(
                "all nested checkpoints passed"
                if passed
                else "one or more nested checkpoints failed"
            ),
        )

    def _observation(
        self,
        context: CheckpointContext,
    ) -> Observation:
        if context.observation is not None:
            return context.observation

        return self._surface.observe()