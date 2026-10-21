"""Record one demo: the screencast, its step titles and caption, its waits and the parts cut from the video
(research R-001, R-016)."""

from __future__ import annotations

import asyncio
import html
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tests.e2e.demos.encode import FfmpegError
from tests.e2e.demos.progress import HEARTBEAT_SECONDS, Heartbeat, report
from tests.e2e.demos.video import Chapter, Cut, Wait, format_duration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from playwright.async_api import Page

CHAPTER_MS = 2500
# How long the highlight of each action stays on screen; Playwright waits this long after each action.
ACTION_MS = 800
# Playwright draws no highlight unless it gets a style, and its action title shows the locator.
ACTION_STYLE = {
    "highlight": (
        "outline: 3px solid rgba(37, 99, 235, 0.9); outline-offset: 2px;"
        " border-radius: 4px; background: rgba(37, 99, 235, 0.12)"
    ),
    "title": "display: none",
}
# How long the video shows a result, such as a finished task or a changed list, before the next action.
RESULT_HOLD_SECONDS = 5.0
# How long the video shows a list or a page before the demo changes it.
LIST_HOLD_SECONDS = 2.5
# Where the cursor rests while the video shows a result: at the right edge of the page, where it covers no
# text that the demos show.
CURSOR_REST = (1880, 600)
# The caption stays in the bottom left corner, where the sped-up labels (bottom centre) and the chapter titles
# (centre) never cover it.
_CAPTION_HTML = (
    '<div style="position: fixed; left: 24px; bottom: 24px; padding: 10px 20px; border-radius: 12px;'
    " background: rgba(17, 24, 39, 0.88); color: #f9fafb; font: 600 24px system-ui, sans-serif;"
    ' pointer-events: none">{text}</div>'
)


def probe_duration(path: Path) -> float:
    """Return the duration in seconds that ffprobe reads from the container of ``path``."""
    executable = shutil.which("ffprobe")
    if executable is None:
        raise FfmpegError("ffprobe is not on the PATH")
    result = subprocess.run(
        [
            executable,
            *("-v", "error", "-show_entries", "format=duration"),
            *("-of", "default=noprint_wrappers=1:nokey=1", str(path)),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise FfmpegError(
            f"ffprobe read no duration from {path} (exit code {result.returncode}): {result.stderr.strip()}"
        ) from None


@dataclass(frozen=True)
class Recording:
    """What the post-processor needs from a stopped recording; times are seconds since it started."""

    waits: tuple[Wait, ...]
    cuts: tuple[Cut, ...]
    chapters: tuple[Chapter, ...]
    raw_duration: float


class DemoRecorder:
    """Records one page's screencast and the waits, cuts and chapters the post-processor needs.

    Times are seconds since ``start()`` returned, measured with ``clock`` (``time.monotonic`` by default).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._page: Page | None = None
        self._raw_path: Path | None = None
        self._t0 = 0.0
        self._waits: list[Wait] = []
        self._cuts: list[Cut] = []
        self._chapters: list[Chapter] = []
        self._current_step: str | None = None
        self._open_range: str | None = None
        self._caption: Any = None

    @property
    def current_step(self) -> str | None:
        """The title of the last step that started, or ``None`` before the first step."""
        return self._current_step

    async def start(self, page: Page, raw_path: Path) -> None:
        if self._page is not None:
            raise RuntimeError("The recorder has already started")
        await page.screencast.start(path=raw_path, size={"width": 1920, "height": 1080})
        await page.screencast.show_actions(
            cursor="pointer", duration=ACTION_MS, style=ACTION_STYLE
        )
        self._t0 = self._clock()
        self._page = page
        self._raw_path = raw_path

    @asynccontextmanager
    async def step(self, title: str) -> AsyncIterator[None]:
        """Show ``title`` as a chapter; it stays the current step after the block ends."""
        page = self._started_page()
        self._current_step = title
        self._chapters.append(Chapter(title, self._elapsed()))
        report(f"Step: {title}")
        await page.screencast.show_chapter(title, duration=CHAPTER_MS)
        yield

    async def caption(self, text: str) -> None:
        """Show ``text`` in the corner of the video, in place of the previous caption, until the next caption.

        The caption names the environment and the application on screen; it stays across page loads.
        """
        page = self._started_page()
        if self._caption is not None:
            await self._caption.__aexit__(None, None, None)
        self._caption = await page.screencast.show_overlay(
            _CAPTION_HTML.format(text=html.escape(text))
        )

    async def hold(self, seconds: float = RESULT_HOLD_SECONDS) -> None:
        """Move the cursor to its resting place, then let the video show the page for ``seconds``."""
        page = self._started_page()
        await page.mouse.move(*CURSOR_REST)
        await asyncio.sleep(seconds)

    @asynccontextmanager
    async def wait(self, label: str) -> AsyncIterator[None]:
        """Record the block as a wait for the cluster, which the final video speeds up."""
        self._started_page()
        start = self._open("wait")
        report(f"Wait: {label}")
        heartbeat = Heartbeat(
            lambda: (
                f"Wait: {label} still runs after {format_duration(self._elapsed() - start)}"
            ),
            HEARTBEAT_SECONDS,
        )
        try:
            yield
        finally:
            heartbeat.stop()
            self._open_range = None
        end = self._elapsed()
        report(f"Wait: {label} took {format_duration(end - start)}")
        if end > start:
            self._waits.append(Wait(label, start, end))

    @asynccontextmanager
    async def cut(self) -> AsyncIterator[None]:
        """Cut the block's time from the video, for example a page that loads after a switch to another web
        application and shows white until it does."""
        self._started_page()
        start = self._open("cut")
        try:
            yield
        finally:
            self._open_range = None
            self._add_cut(start)

    @asynccontextmanager
    async def unrecorded(self) -> AsyncIterator[Page]:
        """Yield a new page of the recorded page's context; the block's time is cut from the video."""
        recorded = self._started_page()
        start = self._open("cut")
        try:
            page = await recorded.context.new_page()
            try:
                yield page
            finally:
                await page.close()
        finally:
            self._open_range = None
            self._add_cut(start)

    async def stop(self) -> Recording:
        """Stop the screencast; return the waits, cuts, chapters and the raw video's duration from ffprobe."""
        page = self._started_page()
        await page.screencast.stop()
        if self._raw_path is None:
            raise RuntimeError("The recorder has no raw video path")
        duration = await asyncio.to_thread(probe_duration, self._raw_path)
        return Recording(
            tuple(self._waits), tuple(self._cuts), tuple(self._chapters), duration
        )

    def _started_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("The recorder has not started")
        return self._page

    def _elapsed(self) -> float:
        return self._clock() - self._t0

    def _open(self, kind: str) -> float:
        # Waits and cuts must not overlap (data-model.md), so they cannot nest.
        if self._open_range is not None:
            raise RuntimeError(f"A {kind} cannot start inside a {self._open_range}")
        self._open_range = kind
        return self._elapsed()

    def _add_cut(self, start: float) -> None:
        end = self._elapsed()
        if end > start:
            self._cuts.append(Cut(start, end))
