"""The encoder with a real ffmpeg: a short generated recording becomes an MP4 of the planned length and size,
and an ffmpeg failure leaves no video behind."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.e2e.demos import encode
from tests.e2e.demos.encode import FfmpegError, encode_video, run_ffmpeg
from tests.e2e.demos.video import (
    Chapter,
    ClosingCard,
    Cut,
    VideoPlan,
    Wait,
    plan_segments,
    planned_length,
)

if TYPE_CHECKING:
    from pathlib import Path

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg or ffprobe is not on the PATH",
)
SIZE = (320, 180)
CLOSING_SECONDS = 2.0


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
    )


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            *("ffprobe", "-v", "error", "-print_format", "json"),
            *(
                "-show_entries",
                "format=duration:stream=codec_name,width,height,pix_fmt",
            ),
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture
def images(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Render the label and the closing card with ffmpeg instead of a browser."""
    rendered: list[str] = []

    async def render_label(context, text: str, path: Path) -> None:
        rendered.append(text)
        _ffmpeg(
            "-f", "lavfi", "-i", "color=c=black:s=120x24", "-frames:v", "1", str(path)
        )

    async def render_closing_card(context, card: ClosingCard, path: Path) -> None:
        rendered.append(card.title)
        width, height = SIZE
        _ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"color=c=navy:s={width}x{height}",
            "-frames:v",
            "1",
            str(path),
        )

    monkeypatch.setattr(encode, "render_label", render_label)
    monkeypatch.setattr(encode, "render_closing_card", render_closing_card)
    return rendered


def _plan(segments) -> VideoPlan:
    return VideoPlan(
        video_name="1-deploy-upgrade.mp4",
        segments=tuple(segments),
        chapters=(Chapter("Deploy Infrahub", 0.0),),
        closing=ClosingCard("Deploy and upgrade Infrahub", ("Upgraded.",)),
    )


@requires_ffmpeg
def test_run_ffmpeg_raises_with_the_end_of_stderr_on_failure() -> None:
    with pytest.raises(FfmpegError, match="Unrecognized option 'no-such-option'"):
        run_ffmpeg(["-no-such-option"])


def test_run_ffmpeg_raises_when_ffmpeg_is_not_on_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encode.shutil, "which", lambda _name: None)

    with pytest.raises(FfmpegError, match="not on the PATH"):
        run_ffmpeg(["-version"])


@requires_ffmpeg
async def test_encode_video_gives_an_h264_video_of_the_planned_length_and_size(
    tmp_path, images: list[str]
) -> None:
    # A 12 s recording: 2 s shown, an 8 s wait sped up to 4 s, a 1 s cut, then 1 s shown.
    _ffmpeg(
        *("-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=12"),
        *("-c:v", "libvpx", "-b:v", "300k", str(tmp_path / "raw.webm")),
    )
    segments = plan_segments(
        [Wait("The upgrade runs", 2.0, 10.0)], [Cut(10.0, 11.0)], 12.0
    )
    assert [segment.kind for segment in segments] == [
        "normal",
        "sped_up",
        "cut",
        "normal",
    ]
    plan = _plan(segments)

    video = await encode_video(
        None, plan, tmp_path, closing_seconds=CLOSING_SECONDS, size=SIZE
    )

    assert video == tmp_path / "1-deploy-upgrade.mp4"
    probed = _probe(video)
    [stream] = probed["streams"]
    assert (
        stream["codec_name"],
        stream["width"],
        stream["height"],
        stream["pix_fmt"],
    ) == (
        "h264",
        *SIZE,
        "yuv420p",
    )
    expected = planned_length(segments) + CLOSING_SECONDS
    assert expected == pytest.approx(9.0)
    assert float(probed["format"]["duration"]) == pytest.approx(expected, abs=0.2)
    assert images == [
        "The upgrade runs (8 s, shown 2× faster)",
        "Deploy and upgrade Infrahub",
    ]
    assert not (tmp_path / "1-deploy-upgrade.partial.mp4").exists()


@requires_ffmpeg
async def test_encode_video_leaves_no_video_when_ffmpeg_fails(
    tmp_path, images: list[str]
) -> None:
    # The raw recording is missing, so ffmpeg fails.
    plan = _plan(plan_segments([], [], 5.0))

    with pytest.raises(FfmpegError, match="raw.webm"):
        await encode_video(None, plan, tmp_path, size=SIZE)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["closing-card.png"]
