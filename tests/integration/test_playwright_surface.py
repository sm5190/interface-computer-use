from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from cua.domain import (
    ActionSpec,
    ActionType,
    AttributeStrategy,
    CheckpointSpec,
    CheckpointType,
    ResolutionStrategyKind,
    SemanticStrategy,
    TargetSpec,
    TextAnchorStrategy,
)
from cua.grounding import (
    CheckpointContext,
    CheckpointEvaluator,
    PlaywrightGroundingBackend,
    TargetAmbiguous,
    TargetResolver,
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

def test_grounding_falls_back_to_stable_attribute(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)

    resolver = TargetResolver(
        PlaywrightGroundingBackend(surface)
    )

    target = TargetSpec(
        logical_name="member_number_input",
        strategies=[
            SemanticStrategy(
                role="textbox",
                accessible_name="MEMBER NUMBER",
            ),
            AttributeStrategy(
                attribute="name",
                value="f_14",
            ),
            TextAnchorStrategy(
                anchor="MEMBER NUMBER:",
                relation="nearest_input_right",
            ),
        ],
    )

    resolved = resolver.resolve(target)

    assert (
        resolved.strategy_kind
        == ResolutionStrategyKind.ATTRIBUTE
    )

    assert resolved.confidence == 0.95

    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="100001",
        ),
        target_handle=resolved.surface_handle,
    )

    extracted = surface.execute(
        ActionSpec(
            type=ActionType.EXTRACT
        ),
        target_handle=resolved.surface_handle,
    )

    assert extracted.value == "100001"


def test_grounding_uses_text_anchor_for_weak_button(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)
    _open_member(surface, "100001")

    resolver = TargetResolver(
        PlaywrightGroundingBackend(surface)
    )

    target = TargetSpec(
        logical_name="accounts_navigation",
        strategies=[
            SemanticStrategy(
                role="button",
                accessible_name="ACCOUNTS",
            ),
            TextAnchorStrategy(
                anchor="ACCOUNTS",
                relation="same_row_control",
            ),
        ],
    )

    resolved = resolver.resolve(target)

    assert (
        resolved.strategy_kind
        == ResolutionStrategyKind.TEXT_ANCHOR
    )

    assert resolved.confidence == 0.85

    surface.execute(
        ActionSpec(
            type=ActionType.CLICK
        ),
        target_handle=resolved.surface_handle,
    )

    assert urlsplit(surface.current_url).path == (
    "/members/100001/accounts"
)


def test_grounding_rejects_ambiguous_semantic_match(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)
    _open_member(surface, "100001")

    resolver = TargetResolver(
        PlaywrightGroundingBackend(surface)
    )

    target = TargetSpec(
        logical_name="generic_arrow_button",
        strategies=[
            SemanticStrategy(
                role="button",
                accessible_name=">",
            )
        ],
    )

    with pytest.raises(TargetAmbiguous) as error:
        resolver.resolve(target)

    assert error.value.candidate_count == 2

def test_grounding_extracts_savings_balance_from_iframe(
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

    resolver = TargetResolver(
        PlaywrightGroundingBackend(surface)
    )

    balance_target = TargetSpec(
        logical_name="savings_balance",
        strategies=[
            TextAnchorStrategy(
                anchor="SAVINGS",
                relation="same_row_last_cell",
            )
        ],
    )

    resolved = resolver.resolve(
        balance_target
    )

    assert (
        resolved.strategy_kind
        == ResolutionStrategyKind.TEXT_ANCHOR
    )

    assert (
        "accounts/frame"
        in resolved.evidence["frame_url"]
    )

    result = surface.execute(
        ActionSpec(
            type=ActionType.EXTRACT
        ),
        target_handle=resolved.surface_handle,
    )

    assert result.value == "$8431.20"


def test_checkpoint_evaluator_verifies_live_state(
    surface: PlaywrightSurface,
    live_legacy_bank: str,
) -> None:
    _login(surface, live_legacy_bank)

    resolver = TargetResolver(
        PlaywrightGroundingBackend(surface)
    )

    evaluator = CheckpointEvaluator(
        surface=surface,
        resolver=resolver,
    )

    member_input = TargetSpec(
        logical_name="member_number_input",
        strategies=[
            AttributeStrategy(
                attribute="name",
                value="f_14",
            )
        ],
    )

    resolved = resolver.resolve(member_input)

    surface.execute(
        ActionSpec(
            type=ActionType.INPUT_TEXT,
            value="100001",
        ),
        target_handle=resolved.surface_handle,
    )

    value_checkpoint = evaluator.evaluate(
        CheckpointSpec(
            type=CheckpointType.CONTROL_VALUE,
            target=member_input,
            expected="100001",
        )
    )

    assert value_checkpoint.passed is True

    _open_member(surface, "100001")

    text_checkpoint = evaluator.evaluate(
        CheckpointSpec(
            type=CheckpointType.TEXT_PRESENT,
            value="MEMBER INQUIRY",
        )
    )

    assert text_checkpoint.passed is True

    url_checkpoint = evaluator.evaluate(
        CheckpointSpec(
            type=CheckpointType.URL_MATCHES,
            pattern="/members/100001",
        )
    )

    assert url_checkpoint.passed is True

    output_checkpoint = evaluator.evaluate(
        CheckpointSpec(
            type=CheckpointType.OUTPUT_EXTRACTABLE,
            output="savings_balance",
        ),
        context=CheckpointContext(
            outputs={
                "savings_balance": "$8431.20"
            }
        ),
    )

    assert output_checkpoint.passed is True