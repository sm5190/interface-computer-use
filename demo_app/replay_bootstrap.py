from __future__ import annotations

import os

from cua.domain import (
    ActionSpec,
    ActionType,
    AttributeStrategy,
    CheckpointSpec,
    CheckpointType,
    ControlOwner,
    PolicyDecisionType,
    TargetSpec,
)
from cua.replay.bootstrap import (
    SessionBootstrapContext,
)
from cua.safety import GateContext


class LegacyBankDemoBootstrap:
    """
    Deterministic session establishment for the
    synthetic LegacyBank demo.

    This is intentionally outside the generic replay engine.
    """

    def prepare(
        self,
        context: SessionBootstrapContext,
    ) -> None:
        operator_id = os.getenv(
            "LEGACYBANK_OPERATOR_ID",
            "OP100",
        )

        operator_pin = os.getenv(
            "LEGACYBANK_OPERATOR_PIN",
            "2468",
        )

        self._navigate(
            context,
            context.base_url,
        )

        operator_target = TargetSpec(
            logical_name="operator_id_input",
            strategies=[
                AttributeStrategy(
                    attribute="name",
                    value="op_id",
                )
            ],
        )

        pin_target = TargetSpec(
            logical_name="operator_pin_input",
            strategies=[
                AttributeStrategy(
                    attribute="name",
                    value="op_pin",
                )
            ],
        )

        login_target = TargetSpec(
            logical_name="operator_sign_on_button",
            strategies=[
                AttributeStrategy(
                    attribute="name",
                    value="cmd_login",
                )
            ],
        )

        self._targeted_action(
            context,
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value=operator_id,
            ),
            target=operator_target,
            checkpoint=CheckpointSpec(
                type=CheckpointType.CONTROL_VALUE,
                target=operator_target,
                expected=operator_id,
            ),
        )

        self._targeted_action(
            context,
            action=ActionSpec(
                type=ActionType.INPUT_TEXT,
                value=operator_pin,
            ),
            target=pin_target,
            checkpoint=CheckpointSpec(
                type=CheckpointType.CONTROL_VALUE,
                target=pin_target,
                expected=operator_pin,
            ),
        )

        self._targeted_action(
            context,
            action=ActionSpec(
                type=ActionType.CLICK,
            ),
            target=login_target,
            checkpoint=CheckpointSpec(
                type=CheckpointType.URL_MATCHES,
                pattern="*/members",
            ),
        )

    @staticmethod
    def _navigate(
        context: SessionBootstrapContext,
        destination: str,
    ) -> None:
        action = ActionSpec(
            type=ActionType.NAVIGATE,
            value=destination,
        )

        gate = context.action_gate.evaluate(
            GateContext(
                action=action,
                current_url=(
                    context.surface.current_url
                ),
                control_owner=(
                    ControlOwner.AUTOMATION
                ),
            )
        )

        if (
            gate.decision.decision
            != PolicyDecisionType.ALLOW
        ):
            raise RuntimeError(
                "Session bootstrap navigation "
                f"rejected: "
                f"{gate.decision.reason_code}"
            )

        context.surface.execute(action)

    @staticmethod
    def _targeted_action(
        context: SessionBootstrapContext,
        *,
        action: ActionSpec,
        target: TargetSpec,
        checkpoint: CheckpointSpec,
    ) -> None:
        resolved = context.resolver.resolve(
            target
        )

        gate = context.action_gate.evaluate(
            GateContext(
                action=action,
                current_url=(
                    context.surface.current_url
                ),
                control_owner=(
                    ControlOwner.AUTOMATION
                ),
                target_confidence=(
                    resolved.confidence
                ),
                has_checkpoint=True,
            )
        )

        if (
            gate.decision.decision
            != PolicyDecisionType.ALLOW
        ):
            raise RuntimeError(
                "Session bootstrap action "
                f"rejected: "
                f"{gate.decision.reason_code}"
            )

        context.surface.execute(
            action,
            target_handle=(
                resolved.surface_handle
            ),
        )

        checkpoint_result = (
            context
            .checkpoint_evaluator
            .evaluate(checkpoint)
        )

        if not checkpoint_result.passed:
            raise RuntimeError(
                "Session bootstrap checkpoint "
                f"failed: expected "
                f"{checkpoint_result.expected!r}, "
                f"observed "
                f"{checkpoint_result.observed!r}"
            )