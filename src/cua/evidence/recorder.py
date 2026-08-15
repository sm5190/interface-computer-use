from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cua.domain import (
    ActionType,
    ExecutionResult,
    StepRecord,
)

REDACTED = "[REDACTED]"


class DiscoveryEvidenceRecorder:
    def __init__(
        self,
        *,
        run_id: str,
        run_dir: str | Path,
        sensitive_values: Iterable[str] = (),
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)

        self.run_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.log_path = (
            self.run_dir / "run.jsonl"
        )

        self._sensitive_values = {
            str(value)
            for value in sensitive_values
            if str(value)
        }

    def record_event(
        self,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        record = {
            "run_id": self.run_id,
            "event": event,
            **payload,
        }

        self._append_jsonl(
            self._redact(record)
        )

    def record_step(
        self,
        step: StepRecord,
    ) -> None:
        payload = step.model_dump(
            mode="json"
        )

        action = payload.get("action")

        if (
            isinstance(action, dict)
            and action.get("type")
            == ActionType.INPUT_TEXT.value
        ):
            action["value"] = REDACTED

        payload = self._redact(payload)

        self._append_jsonl(
            {
                "run_id": self.run_id,
                "event": "step",
                "step": payload,
            }
        )

    def finalize(
        self,
        *,
        trajectory: list[StepRecord],
        result: ExecutionResult,
        llm_calls: int,
    ) -> None:
        trajectory_payload = [
            self._sanitize_step(step)
            for step in trajectory
        ]

        self._write_json(
            self.run_dir / "trajectory.json",
            {
                "run_id": self.run_id,
                "steps": trajectory_payload,
            },
        )

        self._write_json(
            self.run_dir / "result.json",
            self._redact(
                {
                    **result.model_dump(
                        mode="json"
                    ),
                    "llm_calls": llm_calls,
                }
            ),
        )

    def _sanitize_step(
        self,
        step: StepRecord,
    ) -> dict[str, Any]:
        payload = step.model_dump(
            mode="json"
        )

        action = payload.get("action")

        if (
            isinstance(action, dict)
            and action.get("type")
            == ActionType.INPUT_TEXT.value
        ):
            action["value"] = REDACTED

        return self._redact(payload)

    def _redact(
        self,
        value: Any,
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._redact(nested)
                for key, nested in value.items()
            }

        if isinstance(value, list):
            return [
                self._redact(item)
                for item in value
            ]

        if isinstance(value, tuple):
            return tuple(
                self._redact(item)
                for item in value
            )

        if isinstance(value, str):
            redacted = value

            for sensitive in sorted(
                self._sensitive_values,
                key=len,
                reverse=True,
            ):
                redacted = redacted.replace(
                    sensitive,
                    REDACTED,
                )

            return redacted

        return value

    def _append_jsonl(
        self,
        payload: dict[str, Any],
    ) -> None:
        with self.log_path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                )
                + "\n"
            )

    @staticmethod
    def _write_json(
        path: Path,
        payload: Any,
    ) -> None:
        path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )