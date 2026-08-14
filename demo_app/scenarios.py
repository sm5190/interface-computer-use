from __future__ import annotations

import time
from enum import StrEnum

from starlette.requests import Request


class Scenario(StrEnum):
    NORMAL = "normal"
    NO_SAVINGS = "no_savings"
    SLOW_ONCE = "slow_once"
    PERMISSION_DENIED = "permission_denied"
    UNEXPECTED_DIALOG = "unexpected_dialog"


def maybe_apply_slow_once(request: Request, member_id: str, delay_seconds: float = 2.5) -> bool:
    """Apply one deterministic delay per browser session for the designated member."""
    if member_id != "100004":
        return False

    seen = dict(request.session.get("slow_once_seen", {}))
    if seen.get(member_id):
        return False

    time.sleep(delay_seconds)
    seen[member_id] = True
    request.session["slow_once_seen"] = seen
    return True
