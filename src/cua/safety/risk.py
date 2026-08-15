from __future__ import annotations

from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from cua.domain import (
    ActionSpec,
    ActionType,
    RiskLevel,
    RiskSpec,
)

from .policy import ApplicationPolicy


class RiskClassifier:
    """Classify action risk without relying on the discovery model."""

    def __init__(self, policy: ApplicationPolicy) -> None:
        self._policy = policy

    def classify(
        self,
        action: ActionSpec,
        *,
        current_url: str,
    ) -> RiskSpec:
        path = urlsplit(current_url).path or "/"

        on_irreversible_review = any(
            fnmatchcase(path, pattern)
            for pattern in (
                self._policy
                .risk_policy
                .irreversible_click_routes
            )
        )

        if (
            action.type == ActionType.CLICK
            and on_irreversible_review
        ):
            return RiskSpec(
                level=RiskLevel.IRREVERSIBLE,
                reversible=False,
            )

        if (
            action.type == ActionType.PRESS_KEY
            and on_irreversible_review
            and str(action.value).upper()
            in {"ENTER", "RETURN"}
        ):
            return RiskSpec(
                level=RiskLevel.IRREVERSIBLE,
                reversible=False,
            )

        if action.type in {
            ActionType.INPUT_TEXT,
            ActionType.SELECT_OPTION,
            ActionType.PRESS_KEY,
        }:
            return RiskSpec(
                level=RiskLevel.REVERSIBLE_WRITE,
                reversible=True,
            )

        return RiskSpec(
            level=RiskLevel.SAFE,
            reversible=True,
        )