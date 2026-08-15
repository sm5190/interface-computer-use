from __future__ import annotations

import json
import re
from typing import Any, cast

from playwright.sync_api import (
    Frame,
    Locator,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from cua.domain.actions import (
    AttributeStrategy,
    SemanticStrategy,
    TargetStrategy,
    TextAnchorStrategy,
    VisualTemplateStrategy,
)
from cua.surfaces import PlaywrightSurface

from .base import GroundingCandidate

_ATTRIBUTE_NAME = re.compile(
    r"^[A-Za-z_:][-A-Za-z0-9_:.]*$"
)


class PlaywrightGroundingBackend:
    """
    Deterministic browser grounding implementation.

    Strategy confidence is derived from the type and
    uniqueness of observed evidence, not an LLM score.
    """

    def __init__(
        self,
        surface: PlaywrightSurface,
        *,
        resolution_wait_ms: int = 1_000,
    ) -> None:
        self._surface = surface
        self._resolution_wait_ms = resolution_wait_ms

    def resolve(
        self,
        strategy: TargetStrategy,
    ) -> list[GroundingCandidate]:
        if isinstance(strategy, SemanticStrategy):
            return self._semantic(strategy)

        if isinstance(strategy, AttributeStrategy):
            return self._attribute(strategy)

        if isinstance(strategy, TextAnchorStrategy):
            return self._text_anchor(strategy)

        if isinstance(strategy, VisualTemplateStrategy):
            # Deterministic OpenCV implementation is added
            # later. TargetResolver already understands the
            # strategy and will continue/fail safely.
            return []

        raise TypeError(
            f"Unsupported target strategy: {type(strategy)!r}"
        )

    def _semantic(
        self,
        strategy: SemanticStrategy,
    ) -> list[GroundingCandidate]:
        candidates: list[GroundingCandidate] = []

        for frame in self._frames():
            role = cast(Any, strategy.role)

            if strategy.accessible_name is None:
                locator = frame.get_by_role(role)
            else:
                locator = frame.get_by_role(
                    role,
                    name=strategy.accessible_name,
                    exact=True,
                )

            candidates.extend(
                self._visible_candidates(
                    locator=locator,
                    confidence=0.99,
                    frame=frame,
                    evidence={
                        "role": strategy.role,
                        "accessible_name": (
                            strategy.accessible_name
                        ),
                    },
                )
            )

        return candidates
    def _frames(self) -> list[Frame]:
        return self._surface.playwright_frames(
            readiness_timeout_ms=self._resolution_wait_ms
        )
    def _attribute(
        self,
        strategy: AttributeStrategy,
    ) -> list[GroundingCandidate]:
        if not _ATTRIBUTE_NAME.fullmatch(
            strategy.attribute
        ):
            raise ValueError(
                "Unsafe or invalid attribute name "
                f"{strategy.attribute!r}"
            )

        selector = (
            f"[{strategy.attribute}="
            f"{json.dumps(strategy.value)}]"
        )

        candidates: list[GroundingCandidate] = []

        for frame in self._frames():
            locator = frame.locator(selector)

            candidates.extend(
                self._visible_candidates(
                    locator,
                    confidence=0.95,
                    frame=frame,
                    evidence={
                        "attribute": strategy.attribute,
                        "value": strategy.value,
                        "selector": selector,
                    },
                )
            )

        return candidates

    def _text_anchor(
        self,
        strategy: TextAnchorStrategy,
    ) -> list[GroundingCandidate]:
        candidates: list[GroundingCandidate] = []

        for frame in self._frames():
            locator = self._text_anchor_locator(
                frame,
                strategy,
            )

            candidates.extend(
                self._visible_candidates(
                    locator,
                    confidence=0.85,
                    frame=frame,
                    evidence={
                        "anchor": strategy.anchor,
                        "relation": strategy.relation,
                    },
                )
            )

        return candidates

    def _text_anchor_locator(
        self,
        frame: Frame,
        strategy: TextAnchorStrategy,
    ) -> Locator:
        relation = strategy.relation

        if relation == "self":
            return self._self_text_locator(
                frame,
                strategy.anchor,
            )

        anchor = frame.locator(
            "xpath=//*[normalize-space(string(.))="
            f"{_xpath_literal(strategy.anchor)}]"
        )

        if relation == "nearest_input_right":
            return anchor.locator(
                "xpath="
                "following-sibling::*[1]"
                "//*["
                "self::input or "
                "self::textarea or "
                "self::select or "
                "self::button"
                "][1]"
                " | "
                "following-sibling::*[1]"
                "["
                "self::input or "
                "self::textarea or "
                "self::select or "
                "self::button"
                "]"
            )

        if relation == "same_row_control":
            return anchor.locator(
                "xpath="
                "ancestor::tr[1]"
                "//*["
                "self::input or "
                "self::button or "
                "self::select or "
                "self::textarea or "
                "self::a[@href]"
                "]"
            )

        if relation == "same_row_next_cell":
            return anchor.locator(
                "xpath="
                "following-sibling::*"
                "[self::td or self::th][1]"
            )

        if relation == "same_row_last_cell":
            return anchor.locator(
                "xpath="
                "ancestor::tr[1]"
                "/*[self::td or self::th][last()]"
            )

        raise ValueError(
            f"Unsupported text-anchor relation: {relation!r}"
        )

    @staticmethod
    def _self_text_locator(
        frame: Frame,
        text: str,
    ) -> Locator:
        button = frame.get_by_role(
            cast(Any, "button"),
            name=text,
            exact=True,
        )

        if button.count() > 0:
            return button

        link = frame.get_by_role(
            cast(Any, "link"),
            name=text,
            exact=True,
        )

        if link.count() > 0:
            return link

        input_value = frame.locator(
            f"input[value={json.dumps(text)}]"
        )

        if input_value.count() > 0:
            return input_value

        return frame.get_by_text(
            text,
            exact=True,
        )

    
    def _visible_candidates(
        self,
        locator: Locator,
        *,
        confidence: float,
        frame: Frame,
        evidence: dict[str, Any],
    ) -> list[GroundingCandidate]:
        candidates: list[GroundingCandidate] = []

        # locator.count() observes what exists at that instant.
        # Give a newly loaded frame/control a small deterministic
        # readiness window before concluding that the strategy
        # produced no candidates.
        try:
            locator.first.wait_for(
                state="visible",
                timeout=self._resolution_wait_ms,
            )
        except PlaywrightTimeoutError:
            return candidates

        try:
            count = locator.count()
        except Exception:
            return candidates

        for index in range(count):
            candidate = locator.nth(index)

            try:
                if not candidate.is_visible():
                    continue
            except Exception:
                continue

            candidate_evidence = dict(evidence)

            candidate_evidence.update(
                {
                    "frame_name": frame.name or None,
                    "frame_url": frame.url or None,
                    "candidate_index": index,
                    "resolution_wait_ms": (
                        self._resolution_wait_ms
                    ),
                }
            )

            candidates.append(
                GroundingCandidate(
                    handle=candidate,
                    confidence=confidence,
                    evidence=candidate_evidence,
                )
            )

        return candidates


def _xpath_literal(value: str) -> str:
    """
    Safely represent arbitrary text as an XPath string literal.
    """

    if "'" not in value:
        return f"'{value}'"

    if '"' not in value:
        return f'"{value}"'

    parts = value.split("'")

    encoded: list[str] = []

    for index, part in enumerate(parts):
        if part:
            encoded.append(f"'{part}'")

        if index < len(parts) - 1:
            encoded.append('"\'"')

    return "concat(" + ", ".join(encoded) + ")"