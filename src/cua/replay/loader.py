from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from cua.domain import CapabilityArtifact


class CapabilityLoadError(ValueError):
    pass


def load_capability(
    path: str | Path,
) -> CapabilityArtifact:
    capability_path = Path(
        path
    )

    if not capability_path.is_file():
        raise CapabilityLoadError(
            f"Capability file not found: "
            f"{capability_path}"
        )

    try:
        payload = json.loads(
            capability_path.read_text(
                encoding="utf-8"
            )
        )

        return (
            CapabilityArtifact
            .model_validate(
                payload
            )
        )

    except json.JSONDecodeError as exc:
        raise CapabilityLoadError(
            f"Invalid capability JSON: {exc}"
        ) from exc

    except ValidationError as exc:
        raise CapabilityLoadError(
            f"Capability schema validation failed: "
            f"{exc}"
        ) from exc