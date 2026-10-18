"""Encode a demo's raw screencast into the final MP4: label images from the browser, then ffmpeg (research R-003)."""

from __future__ import annotations

import asyncio
import html
import shutil
import subprocess
from typing import TYPE_CHECKING

from tests.e2e.demos.video import ffmpeg_arguments

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from playwright.async_api import BrowserContext

    from tests.e2e.demos.video import Segment

STDERR_LINES = 20
_LABEL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; background: transparent; }}
  #label {{
    display: inline-block; padding: 16px 32px; border-radius: 16px;
    background: rgba(17, 24, 39, 0.9); color: #f9fafb;
    font: 600 30px system-ui, sans-serif; white-space: nowrap;
  }}
</style></head><body><div id="label">{text}</div></body></html>
"""


class FfmpegError(RuntimeError):
    """ffmpeg is missing or exited with an error."""


async def render_label(context: BrowserContext, text: str, path: Path) -> None:
    """Render ``text`` as a dark rounded card into a PNG with a transparent background.

    The page is new, so the screencast of the recorded page does not show it.
    """
    page = await context.new_page()
    try:
        await page.set_content(_LABEL_HTML.format(text=html.escape(text)))
        await page.locator("#label").screenshot(
            path=path, omit_background=True, scale="css"
        )
    finally:
        await page.close()


def run_ffmpeg(arguments: Sequence[str]) -> None:
    """Run ffmpeg with ``arguments``; raise ``FfmpegError`` with the last lines of its stderr when it fails."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise FfmpegError("ffmpeg is not on the PATH")
    result = subprocess.run(
        [executable, *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        tail = "\n".join(result.stderr.splitlines()[-STDERR_LINES:])
        raise FfmpegError(f"ffmpeg exited with code {result.returncode}:\n{tail}")


async def encode_video(
    context: BrowserContext,
    raw_path: Path,
    segments: Sequence[Segment],
    output_path: Path,
    work_dir: Path,
) -> None:
    """Encode ``segments`` of ``raw_path`` into ``output_path``, which changes only when ffmpeg succeeds."""
    label_paths: list[Path] = []
    for segment in segments:
        if segment.kind != "sped_up":
            continue
        if segment.label is None:
            raise ValueError(f"A sped-up segment needs a label: {segment}")
        label_path = work_dir / f"label-{len(label_paths)}.png"
        await render_label(context, segment.label, label_path)
        label_paths.append(label_path)

    partial_path = work_dir / f"{output_path.stem}.partial.mp4"
    try:
        await asyncio.to_thread(
            run_ffmpeg, ffmpeg_arguments(raw_path, segments, label_paths, partial_path)
        )
    except BaseException:
        partial_path.unlink(missing_ok=True)
        raise
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(partial_path, output_path)
