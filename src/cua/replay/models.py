from __future__ import annotations

from typing import Any

from pydantic import Field

from cua.domain.base import DomainModel


class CapabilityInvocation(DomainModel):
    capability_path: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)