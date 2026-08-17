from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal
from typing import Any

from cua.domain import CapabilityArtifact


class InputBindingError(ValueError):
    pass


_PLACEHOLDER_RE = re.compile(
    r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}"
)


def _validate_input_type(
    name: str,
    value: Any,
    type_name: str,
) -> None:
    valid = True

    if type_name == "string":
        valid = isinstance(
            value,
            str,
        )

    elif type_name == "integer":
        valid = (
            isinstance(value, int)
            and not isinstance(value, bool)
        )

    elif type_name == "decimal":
        try:
            Decimal(
                str(value)
            )
        except Exception:
            valid = False

    elif type_name == "boolean":
        valid = isinstance(
            value,
            bool,
        )

    if not valid:
        raise InputBindingError(
            f"Input {name!r} must have "
            f"type {type_name}"
        )


def validate_invocation_inputs(
    artifact: CapabilityArtifact,
    inputs: dict[str, Any],
) -> None:
    declared = set(artifact.inputs)
    supplied = set(inputs)

    unknown = supplied - declared

    if unknown:
        raise InputBindingError(
            f"Unknown capability inputs: {sorted(unknown)}"
        )

    for name, definition in artifact.inputs.items():
        if definition.required and name not in inputs:
            raise InputBindingError(
                f"Missing required input: {name}"
            )

        if name not in inputs:
            continue

        _validate_input_type(
            name,
            inputs[name],
            definition.type.value,
        )

        if (
            definition.pattern is not None
            and isinstance(inputs[name], str)
        ):
            if re.fullmatch(
                definition.pattern,
                inputs[name],
            ) is None:
                raise InputBindingError(
                    f"Input {name!r} does not "
                    "match its declared pattern"
                )


def bind_capability_inputs(
    artifact: CapabilityArtifact,
    inputs: dict[str, Any],
) -> CapabilityArtifact:
    """
    Return a bound in-memory copy of the artifact.

    The stored capability artifact remains parameterized.
    """

    validate_invocation_inputs(
        artifact,
        inputs,
    )

    raw = artifact.model_dump(
        mode="python"
    )

    bound = _bind_value(
        deepcopy(raw),
        inputs,
    )

    try:
        return CapabilityArtifact.model_validate(
            bound
        )
    except Exception as exc:
        raise InputBindingError(
            f"Bound capability is invalid: {exc}"
        ) from exc


def _bind_value(
    value: Any,
    inputs: dict[str, Any],
) -> Any:
    if isinstance(value, dict):
        return {
            key: _bind_value(
                child,
                inputs,
            )
            for key, child in value.items()
        }

    if isinstance(value, list):
        return [
            _bind_value(
                child,
                inputs,
            )
            for child in value
        ]

    if not isinstance(value, str):
        return value

    # Exact placeholder preserves the invocation type.
    exact = _PLACEHOLDER_RE.fullmatch(
        value
    )

    if exact:
        name = exact.group(1)

        if name not in inputs:
            raise InputBindingError(
                f"Unbound capability parameter: {name}"
            )

        return inputs[name]

    # Embedded placeholders become strings.
    def replace(
        match: re.Match[str],
    ) -> str:
        name = match.group(1)

        if name not in inputs:
            raise InputBindingError(
                f"Unbound capability parameter: {name}"
            )

        return str(inputs[name])

    return _PLACEHOLDER_RE.sub(
        replace,
        value,
    )