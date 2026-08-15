from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Literal

from google import genai
from pydantic import Field, model_validator

from cua.domain import (
    ActionProposal,
    ActionSpec,
    ActionType,
    AgentDecision,
    AgentDecisionState,
    AttributeStrategy,
    CheckpointSpec,
    CheckpointType,
    ExpectedEffect,
    SemanticStrategy,
    TargetSpec,
    TextAnchorStrategy,
    Uncertainty,
)
from cua.domain.base import DomainModel

from .model import DiscoveryModelContext


class DiscoveryModelError(RuntimeError):
    """Provider or structured-response failure."""


class GeminiStrategyPayload(DomainModel):
    kind: Literal[
        "semantic",
        "attribute",
        "text_anchor",
    ]

    role: str | None = None
    accessible_name: str | None = None

    attribute: str | None = None
    value: str | None = None

    anchor: str | None = None
    relation: str | None = None


class GeminiTargetPayload(DomainModel):
    logical_name: str = Field(min_length=1)

    strategies: list[GeminiStrategyPayload] = Field(
        min_length=1
    )


class GeminiActionPayload(DomainModel):
    type: Literal[
        "navigate",
        "click",
        "input_text",
        "select_option",
        "press_key",
        "read",
        "extract",
        "scroll",
        "wait",
    ]

    value: str | None = None
    option: str | None = None


class GeminiCheckpointPayload(DomainModel):
    type: Literal[
        "control_present",
        "control_value",
        "text_present",
        "url_matches",
        "dialog_present",
        "output_extractable",
    ]

    value: str | None = None
    expected: str | None = None
    pattern: str | None = None
    output: str | None = None


class GeminiActionProposalPayload(DomainModel):
    action: GeminiActionPayload

    target: GeminiTargetPayload | None = None

    output: str | None = None

    expected_effect: str = Field(min_length=1)

    checkpoint: GeminiCheckpointPayload | None = None


class GeminiOutputPayload(DomainModel):
    name: str = Field(min_length=1)
    value: str


class GeminiDecisionPayload(DomainModel):
    state: Literal[
        "CONTINUE",
        "GOAL_COMPLETE",
        "NEEDS_HUMAN",
        "BLOCKED",
    ]

    intent: str = Field(min_length=1)

    proposal: GeminiActionProposalPayload | None = None

    outputs: list[GeminiOutputPayload] = Field(
        default_factory=list
    )

    uncertainty_reasons: list[str] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_state_contract(
        self,
    ) -> GeminiDecisionPayload:
        if (
            self.state == "CONTINUE"
            and self.proposal is None
        ):
            raise ValueError(
                "CONTINUE requires proposal"
            )

        if (
            self.state != "CONTINUE"
            and self.proposal is not None
        ):
            raise ValueError(
                "Only CONTINUE may contain proposal"
            )

        return self

    def to_domain(self) -> AgentDecision:
        proposal = (
            self._proposal_to_domain()
            if self.proposal is not None
            else None
        )

        output_values = {
            item.name: item.value
            for item in self.outputs
        }

        return AgentDecision(
            state=AgentDecisionState(self.state),
            intent=self.intent,
            action=proposal,
            expected_effect=(
                self._expected_effect(proposal)
                if proposal is not None
                else None
            ),
            outputs=output_values or None,
            uncertainty=Uncertainty(
                reasons=self.uncertainty_reasons
            ),
        )

    def _proposal_to_domain(
        self,
    ) -> ActionProposal:
        assert self.proposal is not None

        action_payload = self.proposal.action

        action = ActionSpec(
            type=ActionType(action_payload.type),
            value=action_payload.value,
            option=action_payload.option,
        )

        target = (
            _target_to_domain(
                self.proposal.target
            )
            if self.proposal.target is not None
            else None
        )

        return ActionProposal(
            action=action,
            target=target,
            output=self.proposal.output,
        )

    def _expected_effect(
        self,
        proposal: ActionProposal,
    ) -> ExpectedEffect:
        assert self.proposal is not None

        checkpoint = _checkpoint_to_domain(
            self.proposal.checkpoint,
            target=proposal.target,
            extract_output=proposal.output,
        )

        return ExpectedEffect(
            summary=self.proposal.expected_effect,
            checkpoint=checkpoint,
        )


def _target_to_domain(
    payload: GeminiTargetPayload,
) -> TargetSpec:
    strategies = []

    for strategy in payload.strategies:
        if strategy.kind == "semantic":
            if not strategy.role:
                raise ValueError(
                    "semantic strategy requires role"
                )

            strategies.append(
                SemanticStrategy(
                    role=strategy.role,
                    accessible_name=(
                        strategy.accessible_name
                    ),
                )
            )

        elif strategy.kind == "attribute":
            if (
                not strategy.attribute
                or strategy.value is None
            ):
                raise ValueError(
                    "attribute strategy requires "
                    "attribute and value"
                )

            strategies.append(
                AttributeStrategy(
                    attribute=strategy.attribute,
                    value=strategy.value,
                )
            )

        elif strategy.kind == "text_anchor":
            if (
                not strategy.anchor
                or not strategy.relation
            ):
                raise ValueError(
                    "text_anchor strategy requires "
                    "anchor and relation"
                )

            strategies.append(
                TextAnchorStrategy(
                    anchor=strategy.anchor,
                    relation=strategy.relation,
                )
            )

    return TargetSpec(
        logical_name=payload.logical_name,
        strategies=strategies,
    )


def _checkpoint_to_domain(
    payload: GeminiCheckpointPayload | None,
    *,
    target: TargetSpec | None,
    extract_output: str | None,
) -> CheckpointSpec | None:
    if payload is None:
        return None

    checkpoint_type = CheckpointType(
        payload.type
    )

    if checkpoint_type == CheckpointType.CONTROL_PRESENT:
        if target is None:
            raise ValueError(
                "control_present requires target"
            )

        return CheckpointSpec(
            type=checkpoint_type,
            target=target,
        )

    if checkpoint_type == CheckpointType.CONTROL_VALUE:
        if target is None or payload.expected is None:
            raise ValueError(
                "control_value requires target "
                "and expected"
            )

        return CheckpointSpec(
            type=checkpoint_type,
            target=target,
            expected=payload.expected,
        )

    if checkpoint_type in {
        CheckpointType.TEXT_PRESENT,
        CheckpointType.DIALOG_PRESENT,
    }:
        if payload.value is None:
            raise ValueError(
                f"{checkpoint_type} requires value"
            )

        return CheckpointSpec(
            type=checkpoint_type,
            value=payload.value,
        )

    if checkpoint_type == CheckpointType.URL_MATCHES:
        if payload.pattern is None:
            raise ValueError(
                "url_matches requires pattern"
            )

        return CheckpointSpec(
            type=checkpoint_type,
            pattern=payload.pattern,
        )

    if (
        checkpoint_type
        == CheckpointType.OUTPUT_EXTRACTABLE
    ):
        output = payload.output or extract_output

        if not output:
            raise ValueError(
                "output_extractable requires output"
            )

        return CheckpointSpec(
            type=checkpoint_type,
            output=output,
        )

    raise ValueError(
        f"Unsupported checkpoint: {checkpoint_type}"
    )


class GeminiDiscoveryModel:
    def __init__(
        self,
        *,
        model: str = "gemini-3.6-flash",
        api_key: str | None = None,
    ) -> None:
        self._model = model

        self._client = (
            genai.Client(api_key=api_key)
            if api_key
            else genai.Client()
        )

        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def decide(
        self,
        context: DiscoveryModelContext,
    ) -> AgentDecision:
        screenshot_path = Path(
            context.observation.screenshot_ref
        )

        if not screenshot_path.exists():
            raise DiscoveryModelError(
                f"Screenshot does not exist: "
                f"{screenshot_path}"
            )

        image_data = base64.b64encode(
            screenshot_path.read_bytes()
        ).decode("utf-8")

        prompt = _build_prompt(context)

        self._call_count += 1

        try:
            interaction = (
                self._client.interactions.create(
                    model=self._model,
                    input=[
                        {
                            "type": "image",
                            "mime_type": "image/png",
                            "data": image_data,
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": (
                            GeminiDecisionPayload
                            .model_json_schema()
                        ),
                    },
                    store=False,
                )
            )
        except Exception as exc:
            raise DiscoveryModelError(
                f"Gemini request failed: {exc}"
            ) from exc

        if not interaction.output_text:
            raise DiscoveryModelError(
                "Gemini returned no structured output"
            )

        try:
            payload = (
                GeminiDecisionPayload
                .model_validate_json(
                    interaction.output_text
                )
            )

            return payload.to_domain()

        except Exception as exc:
            raise DiscoveryModelError(
                "Gemini response failed domain "
                f"validation: {exc}"
            ) from exc


def _build_prompt(
    context: DiscoveryModelContext,
) -> str:
    observation = _compact_observation(
        context.observation
    )

    state = {
        "goal": context.goal,
        "known_outputs": context.known_outputs,
        "recent_steps": context.recent_steps[-6:],
        "target_notes": context.target_notes,
        "observation": observation,
    }

    return (
        """
You are the discovery planner inside a constrained computer-use
automation system.

Your job is to propose exactly ONE next action that advances the
user's goal on the currently visible application.

You DO NOT execute anything yourself. The runtime will independently:
1. validate your structured response,
2. resolve your logical target,
3. enforce policy and risk rules,
4. execute the action,
5. verify its checkpoint.

Rules:

- Use only evidence in the attached screenshot and observation.
- Never invent CSS selectors, XPath, JavaScript, coordinates, APIs,
  or controls that are not supported by the observation.
- Each target's FIRST strategy must be specific enough to identify
  exactly one visible control.
- Prefer semantic targeting when the role plus accessible_name
  uniquely identifies the control.
- NEVER use a broad role-only semantic strategy such as
  role="textbox" or role="button" when multiple visible controls
  share that role.
- If the semantic accessible name is uncertain but a unique stable
  observed attribute such as name or id exists, use the attribute
  strategy FIRST.
- Do not put an ambiguous semantic strategy before a unique
  attribute strategy. The runtime deliberately stops resolution
  when a strategy is ambiguous rather than guessing.
- Use text_anchor when neither semantic nor stable attributes can
  uniquely identify the logical control.
- Attributes must come from observed control attributes.
- Allowed text_anchor relations are:
  self,
  nearest_input_right,
  same_row_control,
  same_row_next_cell,
  same_row_last_cell.
- Use a short snake_case logical_name for targets.
- input_text and select_option should have a control_value checkpoint.
- Click actions should declare a deterministic checkpoint when the
  expected next state is apparent, preferably url_matches,
  text_present, or control_present.
- EXTRACT must declare output and should use output_extractable.
- Do not return GOAL_COMPLETE merely because a requested value is
  visually visible. First issue an EXTRACT action so the runtime
  obtains the value deterministically.
- GOAL_COMPLETE should only reference values already present in
  known_outputs.
- If recent_steps reports TARGET_NOT_FOUND or TARGET_AMBIGUOUS,
  inspect its feedback and the current observation and propose a
  DIFFERENT, more specific target strategy. Do not simply repeat
  the failed strategy.
- If policy or application state makes the goal impossible, return
  BLOCKED.
- Do not perform irreversible confirmation actions.
- intent is a concise operator-facing action explanation, not hidden
  chain-of-thought.

The screenshot attached to this request is the visual view of the
same state represented below.

CURRENT STATE:
"""
        + json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        )
    )


def _compact_observation(
    observation,
) -> dict:
    controls = []

    for control in observation.controls:
        if not control.visible:
            continue

        attributes = {
            key: value
            for key, value in control.attributes.items()
            if key
            in {
                "id",
                "name",
                "type",
                "href",
                "title",
                "placeholder",
                "aria-label",
                "class",
            }
        }

        bounds = None

        if control.bounds is not None:
            bounds = {
                "x": round(control.bounds.x),
                "y": round(control.bounds.y),
                "width": round(control.bounds.width),
                "height": round(control.bounds.height),
            }

        controls.append(
            {
                "role": control.role,
                "accessible_name": (
                    control.accessible_name
                ),
                "text": control.text,
                "attributes": attributes,
                "frame_path": control.frame_path,
                "bounds": bounds,
            }
        )

        if len(controls) >= 100:
            break

    return {
        "url": observation.location.uri,
        "page_title": observation.page_title,
        "visible_text": (
            observation.visible_text[:100]
        ),
        "controls": controls,
        "dialogs": [
            dialog.model_dump(mode="json")
            for dialog in observation.dialogs[:10]
        ],
        "frames": [
            frame.model_dump(mode="json")
            for frame in observation.frame_contexts[:20]
        ],
    }