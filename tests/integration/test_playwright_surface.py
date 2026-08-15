from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from cua.domain import (
    ActionSpec,
    ActionType,
)
from cua.surfaces import PlaywrightSurface


def _free_port() -> int:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(
            sock.getsockname()[1]
        )


@pytest.fixture
def live_legacy_bank(
    tmp_path: Path,
) -> Iterator[str]:
    port = _free_port()

    base_url = (
        f"http://127.0.0.1:{port}"
    )

    environment = os.environ.copy()

    environment["LEGACYBANK_DB_PATH"] = str(
        tmp_path / "legacybank-playwright.db"
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "demo_app.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + 10

    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "LegacyBank server exited early"
                )

            try:
                response = httpx.get(
                    base_url,
                    timeout=0.5,
                )

                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass

            time.sleep(0.1)
        else:
            raise RuntimeError(
                "LegacyBank did not start within 10 seconds"
            )

        yield base_url

    finally:
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture
def surface(
    tmp_path: Path,
) -> Iterator[PlaywrightSurface]:
    browser = PlaywrightSurface(
        headless=True,
        evidence_dir=tmp_path / "evidence",
    )

    browser.start()

    try:
        yield browser
    finally:
        browser.close()


def _login(
    surface: PlaywrightSurface,
    base_url: str,
) -> None:
    surface.execute(
        ActionSpec(
            type=ActionType.NAVIGATE,
            value=base_url,
        )
    )

    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="OP100",
        ),
        target_handle=surface.playwright_locator(
            "input[name='op_id']"
        ),
    )

    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="2468",
        ),
        target_handle=surface.playwright_locator(
            "input[name='op_pin']"
        ),
    )

    surface.execute(
        ActionSpec(
            type=ActionType.CLICK
        ),
        target_handle=surface.playwright_locator(
            "input[name='cmd_login']"
        ),
    )

    assert surface.current_url.endswith(
        "/members"
    )


def _open_member(
    surface: PlaywrightSurface,
    member_id: str,
) -> None:
    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value=member_id,
        ),
        target_handle=surface.playwright_locator(
            "input[name='f_14']"
        ),
    )

    surface.execute(
        ActionSpec(
            type=ActionType.CLICK
        ),
        target_handle=surface.playwright_locator(
            "input[name='cmd_8']"
        ),
    )

    assert surface.current_url.endswith(
        f"/members/{member_id}"
    )


def test_surface_observes_real_login_ui(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    surface.execute(
        ActionSpec(
            type=ActionType.NAVIGATE,
            value=live_legacy_bank,
        )
    )

    observation = surface.observe()

    assert observation.surface == "browser"
    assert observation.page_title == (
        "LegacyBank Operator Login"
    )

    assert any(
        "OPERATOR SIGN ON" in line
        for line in observation.visible_text
    )

    names = {
        control.attributes.get("name")
        for control in observation.controls
    }

    assert "op_id" in names
    assert "op_pin" in names
    assert "cmd_login" in names

    assert Path(
        observation.screenshot_ref
    ).exists()


def test_surface_executes_real_login_and_member_search(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)
    _open_member(surface, "100001")

    observation = surface.observe()

    assert any(
        "MEMBER INQUIRY" in line
        for line in observation.visible_text
    )

    assert any(
        "100001" in line
        for line in observation.visible_text
    )


def test_surface_observes_nested_account_iframe(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)
    _open_member(surface, "100001")

    surface.execute(
        ActionSpec(
            type=ActionType.CLICK
        ),
        target_handle=surface.playwright_locator(
            "button[name='cmd_22']"
        ),
    )

    observation = surface.observe()

    assert any(
        "accounts/frame" in (
            frame.url or ""
        )
        for frame in observation.frame_contexts
    )

    assert any(
        "SAVINGS" in line
        for line in observation.visible_text
    )

    assert any(
        "CURRENT BALANCE" in line
        for line in observation.visible_text
    )


def test_surface_detects_supervisor_override_dialog(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)
    _open_member(surface, "100006")

    surface.execute(
        ActionSpec(
            type=ActionType.CLICK
        ),
        target_handle=surface.playwright_locator(
            "button[name='cmd_22']"
        ),
    )

    observation = surface.observe()

    assert any(
        "SUPERVISOR OVERRIDE REQUIRED"
        in dialog.text
        for dialog in observation.dialogs
    )


def test_surface_reads_and_extracts_control_values(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    surface.execute(
        ActionSpec(
            type=ActionType.NAVIGATE,
            value=live_legacy_bank,
        )
    )

    operator = surface.playwright_locator(
        "input[name='op_id']"
    )

    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="OP100",
        ),
        target_handle=operator,
    )

    result = surface.execute(
        ActionSpec(
            type=ActionType.EXTRACT
        ),
        target_handle=operator,
    )

    assert result.value == "OP100"


def test_observed_control_can_recover_runtime_handle(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    surface.execute(
        ActionSpec(
            type=ActionType.NAVIGATE,
            value=live_legacy_bank,
        )
    )

    observation = surface.observe()

    operator_control = next(
        control
        for control in observation.controls
        if control.attributes.get("name")
        == "op_id"
    )

    assert operator_control.control_id is not None

    handle = surface.control_handle(
        operator_control.control_id
    )

    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="OP100",
        ),
        target_handle=handle,
    )

    result = surface.execute(
        ActionSpec(
            type=ActionType.EXTRACT
        ),
        target_handle=handle,
    )

    assert result.value == "OP100"


def test_surface_captures_playwright_trace(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
    tmp_path: Path,
) -> None:
    trace_path = (
        tmp_path
        / "trace"
        / "surface-trace.zip"
    )

    surface.start_trace()

    surface.execute(
        ActionSpec(
            type=ActionType.NAVIGATE,
            value=live_legacy_bank,
        )
    )

    output = surface.stop_trace(
        trace_path
    )

    assert Path(output).exists()
    assert Path(output).stat().st_size > 0