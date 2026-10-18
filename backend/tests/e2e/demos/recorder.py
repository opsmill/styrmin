"""Record one demo: the screencast, its step titles, its waits and the parts cut from the video (research R-001, R-016)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from tests.e2e.demos.encode import FfmpegError
from tests.e2e.demos.video import Cut, Wait, format_duration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from playwright.async_api import Page

CHAPTER_MS = 2500


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


class DemoRecorder:
    """Records one page's screencast and the waits and cuts the post-processor needs.

    Times are seconds since ``start()`` returned, measured with ``clock`` (``time.monotonic`` by default).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._page: Page | None = None
        self._raw_path: Path | None = None
        self._t0 = 0.0
        self._waits: list[Wait] = []
        self._cuts: list[Cut] = []
        self._current_step: str | None = None
        self._open_range: str | None = None

    @property
    def current_step(self) -> str | None:
        """The title of the last step that started, or ``None`` before the first step."""
        return self._current_step

    async def start(self, page: Page, raw_path: Path) -> None:
        if self._page is not None:
            raise RuntimeError("The recorder has already started")
        await page.screencast.start(path=raw_path, size={"width": 1920, "height": 1080})
        await page.screencast.show_actions(cursor="pointer", position="top")
        self._t0 = self._clock()
        self._page = page
        self._raw_path = raw_path

    @asynccontextmanager
    async def step(self, title: str) -> AsyncIterator[None]:
        """Show ``title`` as a chapter; it stays the current step after the block ends."""
        page = self._started_page()
        self._current_step = title
        print(f"Step: {title}", flush=True)
        await page.screencast.show_chapter(title, duration=CHAPTER_MS)
        yield

    @asynccontextmanager
    async def wait(self, label: str) -> AsyncIterator[None]:
        """Record the block as a wait for the cluster, which the final video speeds up."""
        self._started_page()
        start = self._open("wait")
        try:
            yield
        finally:
            self._open_range = None
        end = self._elapsed()
        print(f"Wait: {label} took {format_duration(end - start)}", flush=True)
        if end > start:
            self._waits.append(Wait(label, start, end))

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
            end = self._elapsed()
            if end > start:
                self._cuts.append(Cut(start, end))

    async def stop(self) -> tuple[list[Wait], list[Cut], float]:
        """Stop the screencast; return the waits, the cuts and the raw video's duration from ffprobe."""
        page = self._started_page()
        await page.screencast.stop()
        if self._raw_path is None:
            raise RuntimeError("The recorder has no raw video path")
        duration = await asyncio.to_thread(probe_duration, self._raw_path)
        return list(self._waits), list(self._cuts), duration

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
