from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .policy import ApplicationPolicy

REDACTED = "[REDACTED]"


class Redactor:
    def __init__(self, policy: ApplicationPolicy) -> None:
        self._sensitive_fields = {
            field.casefold()
            for field in (
                policy
                .redaction
                .sensitive_input_fields
            )
        }

        self._never_persist = {
            field.casefold()
            for field in policy.redaction.never_persist
        }

    def redact(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            output: dict[str, Any] = {}

            for key, nested_value in value.items():
                key_text = str(key)
                normalized_key = key_text.casefold()

                if normalized_key in self._never_persist:
                    continue

                if normalized_key in self._sensitive_fields:
                    output[key_text] = REDACTED
                    continue

                output[key_text] = self.redact(nested_value)

            return output

        if isinstance(value, list):
            return [self.redact(item) for item in value]

        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)

        return value

    def redact_text(
        self,
        text: str,
        *,
        sensitive_values: Iterable[str],
    ) -> str:
        redacted = text

        unique_values = {
            str(value)
            for value in sensitive_values
            if str(value)
        }

        for value in sorted(
            unique_values,
            key=len,
            reverse=True,
        ):
            redacted = redacted.replace(
                value,
                REDACTED,
            )

        return redacted

    def sensitive_values_from_inputs(
        self,
        inputs: Mapping[str, Any],
    ) -> list[str]:
        values: list[str] = []

        for key, value in inputs.items():
            if key.casefold() not in self._sensitive_fields:
                continue

            if value is None:
                continue

            values.append(str(value))

        return values