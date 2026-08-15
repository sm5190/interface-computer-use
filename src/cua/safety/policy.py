from __future__ import annotations

from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import yaml
from pydantic import Field, field_validator

from cua.domain import ActionType
from cua.domain.base import DomainModel


class ActionRule(StrEnum):
    ALLOW = "allow"
    CONDITIONAL = "conditional"
    DENY = "deny"


class GoalPolicy(DomainModel):
    max_steps: int = Field(default=30, ge=1)
    max_timeout_seconds: int = Field(default=300, ge=1)
    forbidden_phrases: list[str] = Field(default_factory=list)


class RiskPolicy(DomainModel):
    safe: Literal["autonomous"] = "autonomous"
    reversible_write: Literal[
        "autonomous_with_checkpoint"
    ] = "autonomous_with_checkpoint"
    irreversible: Literal["human_approval"] = "human_approval"

    irreversible_click_routes: list[str] = Field(
        default_factory=list
    )


class ConfidencePolicy(DomainModel):
    low_risk_min_autonomous: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
    )
    high_risk: Literal[
        "human_approval_always"
    ] = "human_approval_always"
    below_minimum: Literal[
        "human_takeover"
    ] = "human_takeover"


class RedactionPolicy(DomainModel):
    sensitive_input_fields: list[str] = Field(
        default_factory=list
    )
    never_persist: list[str] = Field(default_factory=list)


class ApplicationPolicy(DomainModel):
    application: str = Field(min_length=1)

    allowed_origins: list[str] = Field(min_length=1)
    allowed_routes: list[str] = Field(min_length=1)

    actions: dict[ActionType, ActionRule]

    goal_policy: GoalPolicy = Field(default_factory=GoalPolicy)
    risk_policy: RiskPolicy = Field(default_factory=RiskPolicy)
    confidence_policy: ConfidencePolicy = Field(
        default_factory=ConfidencePolicy
    )
    redaction: RedactionPolicy = Field(
        default_factory=RedactionPolicy
    )

    @field_validator("allowed_origins")
    @classmethod
    def normalize_allowed_origins(
        cls,
        values: list[str],
    ) -> list[str]:
        normalized: list[str] = []

        for value in values:
            origin = origin_from_url(value)

            if origin is None:
                raise ValueError(
                    f"Invalid allowed origin: {value}"
                )

            if origin not in normalized:
                normalized.append(origin)

        return normalized

    def is_route_allowed(self, route: str) -> bool:
        path = urlsplit(route).path or "/"

        return any(
            fnmatchcase(path, pattern)
            for pattern in self.allowed_routes
        )

    def is_url_allowed(
        self,
        value: str,
        *,
        base_url: str | None = None,
    ) -> bool:
        resolved = resolve_url(
            value,
            base_url=base_url,
        )

        if resolved is None:
            return False

        origin = origin_from_url(resolved)

        if origin is None:
            return False

        if origin not in self.allowed_origins:
            return False

        path = urlsplit(resolved).path or "/"

        return self.is_route_allowed(path)


def origin_from_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    if not parsed.hostname:
        return None

    if parsed.username or parsed.password:
        return None

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()

    default_port = (
        (scheme == "http" and port in {None, 80})
        or (scheme == "https" and port in {None, 443})
    )

    if default_port:
        return f"{scheme}://{host}"

    return f"{scheme}://{host}:{port}"


def resolve_url(
    value: str,
    *,
    base_url: str | None = None,
) -> str | None:
    parsed = urlsplit(value)

    if parsed.scheme and parsed.netloc:
        return value

    if base_url is None:
        return None

    return urljoin(base_url, value)


def load_policy(path: str | Path) -> ApplicationPolicy:
    policy_path = Path(path)

    with policy_path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError(
            f"Policy must contain a YAML mapping: {policy_path}"
        )

    return ApplicationPolicy.model_validate(raw)