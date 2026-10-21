"""Print what the record command is doing, so that a long wait for the cluster does not look like a hang."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from tests.e2e.demos.video import format_duration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

# How often a wait prints that it is still waiting.
HEARTBEAT_SECONDS = 60.0


def report(message: str) -> None:
    """Print ``message`` with the local time."""
    print(f"{time.strftime('%H:%M:%S')}  {message}", flush=True)


class Heartbeat:
    """Print a message every ``every`` seconds until ``stop()``.

    It runs on the event loop's timers, not on ``asyncio.sleep``, so it never delays the waiting code.
    """

    def __init__(self, message: Callable[[], str], every: float) -> None:
        self._loop = asyncio.get_running_loop()
        self._message = message
        self._every = every
        self._handle = self._loop.call_later(every, self._beat)

    def _beat(self) -> None:
        report(self._message())
        self._handle = self._loop.call_later(self._every, self._beat)

    def stop(self) -> None:
        self._handle.cancel()


@asynccontextmanager
async def waiting(
    what: str, *, limit: float | None = None, every: float = HEARTBEAT_SECONDS
) -> AsyncIterator[None]:
    """Print a line when the wait for ``what`` starts, every ``every`` seconds while it lasts, and when it ends.

    ``limit`` is the longest the caller waits, in seconds; the first line gives it.
    """
    report(
        f"Waiting: {what}" + (f" (at most {format_duration(limit)})" if limit else "")
    )
    start = time.monotonic()
    heartbeat = Heartbeat(
        lambda: (
            f"Still waiting after {format_duration(time.monotonic() - start)}: {what}"
        ),
        every,
    )
    try:
        yield
    finally:
        heartbeat.stop()
    report(f"Done after {format_duration(time.monotonic() - start)}: {what}")
