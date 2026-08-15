from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Frame,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)

from cua.domain import (
    ActionSpec,
    ActionType,
    BoundingBox,
    FrameObservation,
    Observation,
    ObservedControl,
    ObservedDialog,
    SurfaceKind,
    SurfaceLocation,
)

from .base import SurfaceActionResult

BrowserName = Literal["chromium", "firefox", "webkit"]


_CONTROL_SELECTOR = (
    "input, button, select, textarea, a[href], "
    "[role='button'], [role='link'], [role='textbox'], "
    "[role='checkbox'], [role='radio'], [role='combobox']"
)

_DIALOG_SELECTOR = (
    "[role='dialog'], dialog, "
    "[class*='dialog' i], [class*='modal' i]"
)


class PlaywrightSurface:
    """Browser implementation of the generic SurfaceSession boundary."""

    def __init__(
        self,
        *,
        browser_name: BrowserName = "chromium",
        headless: bool = False,
        evidence_dir: str | Path = "evidence/dev",
        default_timeout_ms: int = 5_000,
        viewport_width: int = 1440,
        viewport_height: int = 1000,
        slow_mo_ms: int = 0,
    ) -> None:
        self._browser_name = browser_name
        self._headless = headless
        self._evidence_dir = Path(evidence_dir)

        self._default_timeout_ms = default_timeout_ms
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._slow_mo_ms = slow_mo_ms

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        self._trace_active = False
        self._observation_counter = 0

        # Ephemeral runtime mapping only.
        # These handles never belong in serialized domain contracts.
        self._control_handles: dict[str, Locator] = {}

    @property
    def is_started(self) -> bool:
        return self._page is not None

    @property
    def current_url(self) -> str:
        if self._page is None:
            return "about:blank"

        return self._page.url

    def start(self) -> None:
        if self.is_started:
            return

        self._evidence_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._playwright = sync_playwright().start()

        browser_type = getattr(
            self._playwright,
            self._browser_name,
        )

        self._browser = browser_type.launch(
            headless=self._headless,
            slow_mo=self._slow_mo_ms,
        )

        self._context = self._browser.new_context(
            viewport={
                "width": self._viewport_width,
                "height": self._viewport_height,
            }
        )

        self._page = self._context.new_page()
        self._page.set_default_timeout(
            self._default_timeout_ms
        )

    def close(self) -> None:
        if self._context is not None and self._trace_active:
            self._context.tracing.stop()
            self._trace_active = False

        if self._context is not None:
            self._context.close()

        if self._browser is not None:
            self._browser.close()

        if self._playwright is not None:
            self._playwright.stop()

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._control_handles.clear()

    def __enter__(self) -> PlaywrightSurface:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    def observe(self) -> Observation:
        page = self._require_page()

        self._control_handles.clear()

        screenshot_ref = self.capture_screenshot(
            f"observation-{self._observation_counter:04d}.png"
        )
        self._observation_counter += 1

        controls: list[ObservedControl] = []
        visible_text: list[str] = []
        dialogs: list[ObservedDialog] = []
        frame_contexts: list[FrameObservation] = []

        for frame_index, frame in enumerate(page.frames):
            frame_path = self._frame_path(frame)

            if frame != page.main_frame:
                frame_contexts.append(
                    FrameObservation(
                        name=frame.name or None,
                        url=frame.url or None,
                        frame_path=frame_path,
                    )
                )

            controls.extend(
                self._observe_frame_controls(
                    frame,
                    frame_index=frame_index,
                    frame_path=frame_path,
                )
            )

            visible_text.extend(
                self._observe_frame_text(frame)
            )

            dialogs.extend(
                self._observe_frame_dialogs(frame)
            )

        return Observation(
            surface=SurfaceKind.BROWSER,
            location=SurfaceLocation(
                uri=page.url,
                frame_path=[],
            ),
            page_title=page.title(),
            controls=controls,
            visible_text=self._unique_nonempty(
                visible_text
            ),
            dialogs=self._deduplicate_dialogs(dialogs),
            screenshot_ref=screenshot_ref,
            frame_contexts=frame_contexts,
            timestamp=datetime.now(UTC),
        )

    def execute(
        self,
        action: ActionSpec,
        *,
        target_handle: Any | None = None,
    ) -> SurfaceActionResult:
        page = self._require_page()

        if action.type == ActionType.NAVIGATE:
            destination = self._navigation_destination(
                action.value
            )

            page.goto(
                destination,
                wait_until="domcontentloaded",
                timeout=self._default_timeout_ms,
            )

            return SurfaceActionResult(
                value=page.url
            )

        if action.type == ActionType.CLICK:
            locator = self._require_locator(target_handle)
            locator.click(
                timeout=self._default_timeout_ms
            )

            return SurfaceActionResult()

        if action.type == ActionType.INPUT_TEXT:
            locator = self._require_locator(target_handle)

            if action.value is None:
                raise ValueError(
                    "input_text requires a value"
                )

            locator.fill(
                str(action.value),
                timeout=self._default_timeout_ms,
            )

            return SurfaceActionResult()

        if action.type == ActionType.SELECT_OPTION:
            locator = self._require_locator(target_handle)

            if action.option is None:
                raise ValueError(
                    "select_option requires option"
                )

            locator.select_option(
                label=action.option,
                timeout=self._default_timeout_ms,
            )

            return SurfaceActionResult()

        if action.type == ActionType.PRESS_KEY:
            if action.value is None:
                raise ValueError(
                    "press_key requires a key"
                )

            key = str(action.value)

            if target_handle is not None:
                locator = self._require_locator(
                    target_handle
                )
                locator.press(
                    key,
                    timeout=self._default_timeout_ms,
                )
            else:
                page.keyboard.press(key)

            return SurfaceActionResult()

        if action.type == ActionType.READ:
            locator = self._require_locator(target_handle)

            return SurfaceActionResult(
                value=locator.inner_text(
                    timeout=self._default_timeout_ms
                )
            )

        if action.type == ActionType.EXTRACT:
            locator = self._require_locator(target_handle)

            value = locator.evaluate(
                """
                element => {
                    if (
                        element instanceof HTMLInputElement ||
                        element instanceof HTMLTextAreaElement ||
                        element instanceof HTMLSelectElement
                    ) {
                        return element.value;
                    }

                    return (
                        element.innerText ||
                        element.textContent ||
                        ""
                    ).trim();
                }
                """
            )

            return SurfaceActionResult(value=value)

        if action.type == ActionType.SCROLL:
            amount = (
                float(action.value)
                if action.value is not None
                else 500.0
            )

            page.mouse.wheel(0, amount)

            return SurfaceActionResult()

        if action.type == ActionType.WAIT:
            milliseconds = (
                float(action.value)
                if action.value is not None
                else 500.0
            )

            if milliseconds < 0:
                raise ValueError(
                    "wait duration cannot be negative"
                )

            page.wait_for_timeout(milliseconds)

            return SurfaceActionResult()

        raise ValueError(
            f"Unsupported action type: {action.type}"
        )

    def capture_screenshot(
        self,
        name: str | None = None,
    ) -> str:
        page = self._require_page()

        screenshots_dir = (
            self._evidence_dir / "screenshots"
        )
        screenshots_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        if name is None:
            timestamp = datetime.now(
                UTC
            ).strftime("%Y%m%dT%H%M%S%f")

            name = f"screenshot-{timestamp}.png"

        safe_name = self._safe_filename(name)

        path = screenshots_dir / safe_name

        page.screenshot(
            path=str(path),
            full_page=True,
        )

        return str(path)

    def start_trace(self) -> None:
        context = self._require_context()

        if self._trace_active:
            raise RuntimeError(
                "Playwright tracing is already active"
            )

        context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )

        self._trace_active = True

    def stop_trace(
        self,
        path: str | Path,
    ) -> str:
        context = self._require_context()

        if not self._trace_active:
            raise RuntimeError(
                "Playwright tracing is not active"
            )

        output_path = Path(path)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        context.tracing.stop(
            path=str(output_path)
        )

        self._trace_active = False

        return str(output_path)

    def playwright_locator(
        self,
        selector: str,
        *,
        frame_url_contains: str | None = None,
    ) -> Locator:
        """
        Adapter-level locator hook.

        This is intentionally not part of SurfaceSession.
        Step 5's TargetResolver will replace direct selector use
        in production execution paths.
        """

        page = self._require_page()

        if frame_url_contains is None:
            return page.locator(selector)

        for frame in page.frames:
            if frame_url_contains in frame.url:
                return frame.locator(selector)

        raise LookupError(
            f"No frame URL contains {frame_url_contains!r}"
        )

    def control_handle(
        self,
        control_id: str,
    ) -> Locator:
        """
        Return the ephemeral locator backing an observed control.

        Observation IDs are valid only for the current observation.
        """

        try:
            return self._control_handles[control_id]
        except KeyError as exc:
            raise LookupError(
                f"Unknown observation control: {control_id}"
            ) from exc

    def _observe_frame_controls(
        self,
        frame: Frame,
        *,
        frame_index: int,
        frame_path: list[str],
    ) -> list[ObservedControl]:
        locator = frame.locator(_CONTROL_SELECTOR)

        try:
            count = locator.count()
        except Exception:
            return []

        controls: list[ObservedControl] = []

        for index in range(count):
            candidate = locator.nth(index)

            try:
                metadata = candidate.evaluate(
                    """
                    element => {
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();

                        const visible =
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            rect.width > 0 &&
                            rect.height > 0;

                        const tag = element.tagName.toLowerCase();
                        const type = (
                            element.getAttribute("type") || ""
                        ).toLowerCase();

                        let role = element.getAttribute("role");

                        if (!role) {
                            if (
                                tag === "button" ||
                                (
                                    tag === "input" &&
                                    [
                                        "submit",
                                        "button",
                                        "reset"
                                    ].includes(type)
                                )
                            ) {
                                role = "button";
                            } else if (tag === "a") {
                                role = "link";
                            } else if (
                                tag === "textarea" ||
                                (
                                    tag === "input" &&
                                    ![
                                        "submit",
                                        "button",
                                        "reset",
                                        "checkbox",
                                        "radio",
                                        "hidden"
                                    ].includes(type)
                                )
                            ) {
                                role = "textbox";
                            } else if (tag === "select") {
                                role = "combobox";
                            } else if (type === "checkbox") {
                                role = "checkbox";
                            } else if (type === "radio") {
                                role = "radio";
                            }
                        }

                        const text = (
                            element.innerText ||
                            element.textContent ||
                            ""
                        ).trim();

                        const accessibleName =
                            element.getAttribute("aria-label") ||
                            (
                                element instanceof HTMLInputElement &&
                                [
                                    "submit",
                                    "button",
                                    "reset"
                                ].includes(type)
                                    ? element.value
                                    : null
                            ) ||
                            element.getAttribute("title") ||
                            element.getAttribute("placeholder") ||
                            text ||
                            element.getAttribute("name");

                        const attributes = {};

                        for (const name of [
                            "id",
                            "name",
                            "type",
                            "value",
                            "href",
                            "title",
                            "placeholder",
                            "aria-label",
                            "class"
                        ]) {
                            const value =
                                element.getAttribute(name);

                            if (value !== null) {
                                attributes[name] = value;
                            }
                        }

                        return {
                            role,
                            accessibleName,
                            text,
                            attributes,
                            enabled:
                                !element.disabled &&
                                element.getAttribute(
                                    "aria-disabled"
                                ) !== "true",
                            visible,
                            bounds: {
                                x: rect.x,
                                y: rect.y,
                                width: rect.width,
                                height: rect.height
                            }
                        };
                    }
                    """
                )
            except Exception:
                continue

            control_id = (
                f"frame-{frame_index}:control-{index}"
            )

            self._control_handles[
                control_id
            ] = candidate

            controls.append(
                ObservedControl(
                    control_id=control_id,
                    role=metadata.get("role"),
                    accessible_name=metadata.get(
                        "accessibleName"
                    ),
                    text=metadata.get("text"),
                    attributes=metadata.get(
                        "attributes",
                        {},
                    ),
                    enabled=bool(
                        metadata.get("enabled", True)
                    ),
                    visible=bool(
                        metadata.get("visible", True)
                    ),
                    frame_path=frame_path,
                    bounds=BoundingBox(
                        x=float(
                            metadata["bounds"]["x"]
                        ),
                        y=float(
                            metadata["bounds"]["y"]
                        ),
                        width=float(
                            metadata["bounds"]["width"]
                        ),
                        height=float(
                            metadata["bounds"]["height"]
                        ),
                    ),
                )
            )

        return controls

    def _observe_frame_text(
        self,
        frame: Frame,
    ) -> list[str]:
        try:
            body = frame.locator("body")

            if body.count() == 0:
                return []

            text = body.inner_text(
                timeout=self._default_timeout_ms
            )
        except Exception:
            return []

        return [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

    def _observe_frame_dialogs(
        self,
        frame: Frame,
    ) -> list[ObservedDialog]:
        candidates = frame.locator(
            _DIALOG_SELECTOR
        )

        try:
            count = candidates.count()
        except Exception:
            return []

        dialogs: list[ObservedDialog] = []

        for index in range(count):
            candidate = candidates.nth(index)

            try:
                if not candidate.is_visible():
                    continue

                data = candidate.evaluate(
                    """
                    element => {
                        const text = (
                            element.innerText ||
                            element.textContent ||
                            ""
                        ).trim();

                        const titleElement =
                            element.querySelector(
                                "[class*='title' i], " +
                                "h1, h2, h3, legend"
                            );

                        return {
                            text,
                            title:
                                element.getAttribute(
                                    "aria-label"
                                ) ||
                                (
                                    titleElement
                                        ? (
                                            titleElement.innerText ||
                                            titleElement.textContent ||
                                            ""
                                        ).trim()
                                        : null
                                )
                        };
                    }
                    """
                )
            except Exception:
                continue

            text = str(
                data.get("text") or ""
            ).strip()

            if not text:
                continue

            dialogs.append(
                ObservedDialog(
                    title=data.get("title"),
                    text=text,
                    modal=True,
                )
            )

        return dialogs

    def _frame_path(
        self,
        frame: Frame,
    ) -> list[str]:
        parts: list[str] = []

        current = frame

        while current.parent_frame is not None:
            identifier = (
                current.name
                or current.url
                or "unnamed-frame"
            )

            parts.append(identifier)
            current = current.parent_frame

        parts.reverse()

        return parts

    def _navigation_destination(
        self,
        value: object,
    ) -> str:
        if not isinstance(value, str):
            raise ValueError(
                "navigate requires a URL string"
            )

        if "://" in value:
            return value

        current_url = self.current_url

        if current_url == "about:blank":
            raise ValueError(
                "Relative navigation requires "
                "an existing base URL"
            )

        return urljoin(current_url, value)

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError(
                "PlaywrightSurface has not been started"
            )

        return self._page

    def _require_context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError(
                "PlaywrightSurface has not been started"
            )

        return self._context

    @staticmethod
    def _require_locator(
        target_handle: Any | None,
    ) -> Locator:
        if not isinstance(target_handle, Locator):
            raise TypeError(
                "This browser action requires "
                "a Playwright Locator target"
            )

        return target_handle

    @staticmethod
    def _safe_filename(name: str) -> str:
        safe = re.sub(
            r"[^A-Za-z0-9._-]",
            "-",
            name,
        )

        if not safe.lower().endswith(".png"):
            safe += ".png"

        return safe

    @staticmethod
    def _unique_nonempty(
        values: list[str],
    ) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []

        for value in values:
            normalized = value.strip()

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            output.append(normalized)

        return output

    @staticmethod
    def _deduplicate_dialogs(
        dialogs: list[ObservedDialog],
    ) -> list[ObservedDialog]:
        seen: set[str] = set()
        output: list[ObservedDialog] = []

        for dialog in dialogs:
            key = dialog.text.strip()

            if key in seen:
                continue

            seen.add(key)
            output.append(dialog)

        return output