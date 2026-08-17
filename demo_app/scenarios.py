from __future__ import annotations

from enum import StrEnum

from starlette.requests import Request


class Scenario(StrEnum):
    NORMAL = "normal"
    NO_SAVINGS = "no_savings"
    SLOW_ONCE = "slow_once"
    PERMISSION_DENIED = "permission_denied"
    UNEXPECTED_DIALOG = "unexpected_dialog"


def consume_slow_once(
    request: Request,
    member_id: str,
) -> bool:
    """
    Return True once per browser session for the synthetic
    slow-once fixture.

    This does not block the server. The caller uses the result
    to expose a transient client-side loading state.
    """

    if member_id != "100004":
        return False

    seen = dict(
        request.session.get(
            "slow_once_seen",
            {},
        )
    )

    if seen.get(member_id):
        return False

    seen[member_id] = True

    request.session["slow_once_seen"] = seen

    return True