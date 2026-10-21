"""Encode a demo's raw screencast into the final MP4: images from the browser, then ffmpeg (research R-003)."""

from __future__ import annotations

import asyncio
import html
import shutil
import subprocess
from typing import TYPE_CHECKING

from tests.e2e.demos.video import CLOSING_SECONDS, VIDEO_SIZE, ffmpeg_arguments

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from playwright.async_api import BrowserContext

    from tests.e2e.demos.video import ClosingCard, VideoPlan

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
_CARD_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; width: 100%; height: 100%; background: #111827; color: #f9fafb; }}
  body {{ display: flex; flex-direction: column; justify-content: center; padding: 0 160px;
          box-sizing: border-box; font-family: system-ui, sans-serif; }}
  h1 {{ margin: 0 0 48px; font-size: 72px; font-weight: 700; }}
  li {{ margin: 0 0 24px; font-size: 40px; line-height: 1.35; color: #e5e7eb; }}
  ul {{ margin: 0; padding-left: 48px; }}
</style></head><body><h1>{title}</h1><ul>{items}</ul></body></html>
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


async def render_closing_card(
    context: BrowserContext, card: ClosingCard, path: Path
) -> None:
    """Render ``card`` into a PNG of the size of the context's viewport, in a new page."""
    page = await context.new_page()
    try:
        items = "".join(f"<li>{html.escape(line)}</li>" for line in card.lines)
        await page.set_content(
            _CARD_HTML.format(title=html.escape(card.title), items=items)
        )
        await page.screenshot(path=path, scale="css")
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
    plan: VideoPlan,
    work_dir: Path,
    *,
    closing_seconds: float = CLOSING_SECONDS,
    size: tuple[int, int] = VIDEO_SIZE,
) -> Path:
    """Encode the raw video in ``work_dir`` as ``plan`` describes; return the MP4, which is in ``work_dir``.

    The MP4 exists only when ffmpeg succeeds. The raw video and the plan stay in ``work_dir``.
    """
    label_paths: list[Path] = []
    for segment in plan.segments:
        if segment.kind != "sped_up":
            continue
        if segment.label is None:
            raise ValueError(f"A sped-up segment needs a label: {segment}")
        label_path = work_dir / f"label-{len(label_paths)}.png"
        await render_label(context, segment.label, label_path)
        label_paths.append(label_path)
    card_path = work_dir / "closing-card.png"
    await render_closing_card(context, plan.closing, card_path)

    video_path = work_dir / plan.video_name
    partial_path = work_dir / f"{video_path.stem}.partial.mp4"
    arguments = ffmpeg_arguments(
        work_dir / plan.raw_name,
        plan.segments,
        label_paths,
        partial_path,
        closing_card=card_path,
        closing_seconds=closing_seconds,
        size=size,
    )
    try:
        await asyncio.to_thread(run_ffmpeg, arguments)
    except BaseException:
        partial_path.unlink(missing_ok=True)
        raise
    partial_path.replace(video_path)
    return video_path
