"""ffmpeg failures in the encoder: the error carries ffmpeg's message, and the previous video stays."""

from __future__ import annotations

import shutil

import pytest

from tests.e2e.demos import encode
from tests.e2e.demos.encode import FfmpegError, encode_video, run_ffmpeg
from tests.e2e.demos.video import Segment

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is not on the PATH"
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
async def test_encode_video_keeps_the_previous_video_when_ffmpeg_fails(
    tmp_path,
) -> None:
    output_path = tmp_path / "videos" / "3-backup-restore.mp4"
    output_path.parent.mkdir()
    output_path.write_bytes(b"previous video")
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # No sped-up segment, so no label and no browser; the raw file is missing, so ffmpeg fails.
    with pytest.raises(FfmpegError, match="missing.webm"):
        await encode_video(
            None,
            tmp_path / "missing.webm",
            [Segment(0.0, 5.0, "normal")],
            output_path,
            work_dir,
        )

    assert output_path.read_bytes() == b"previous video"
    assert list(work_dir.iterdir()) == []
