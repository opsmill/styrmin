"""The demo recorder's waits, cuts and steps, with a fake page and a fake clock instead of a browser."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.e2e.demos import recorder as recorder_module
from tests.e2e.demos.encode import FfmpegError
from tests.e2e.demos.recorder import DemoRecorder, probe_duration
from tests.e2e.demos.video import Cut, Wait

RAW_DURATION = 42.5


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeScreencast:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    async def start(self, **kwargs) -> None:
        self.calls.append(("start", kwargs))

    async def show_actions(self, **kwargs) -> None:
        self.calls.append(("show_actions", kwargs))

    async def show_chapter(self, title, **kwargs) -> None:
        self.calls.append(("show_chapter", title, kwargs))

    async def stop(self) -> None:
        self.calls.append(("stop",))


class FakeContext:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.pages: list[FakePage] = []

    async def new_page(self) -> FakePage:
        page = FakePage(self.calls, self)
        self.pages.append(page)
        self.calls.append(("new_page",))
        return page


class FakePage:
    def __init__(self, calls: list[tuple], context: FakeContext | None = None) -> None:
        self.calls = calls
        self.context = context or FakeContext(calls)
        self.screencast = FakeScreencast(calls)
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self.calls.append(("close",))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    monkeypatch.setattr(recorder_module, "probe_duration", lambda _path: RAW_DURATION)
    return FakeClock()


@pytest.fixture
def calls() -> list[tuple]:
    return []


@pytest.fixture
async def started(clock: FakeClock, calls: list[tuple]) -> DemoRecorder:
    recorder = DemoRecorder(clock=clock)
    await recorder.start(FakePage(calls), Path("raw.webm"))
    return recorder


async def test_start_records_at_1920x1080_with_the_pointer_and_actions_at_the_top(
    started: DemoRecorder, calls: list[tuple]
) -> None:
    assert calls == [
        ("start", {"path": Path("raw.webm"), "size": {"width": 1920, "height": 1080}}),
        ("show_actions", {"cursor": "pointer", "position": "top"}),
    ]


async def test_waits_are_recorded_in_seconds_since_start_and_printed(
    started: DemoRecorder, clock: FakeClock, capsys: pytest.CaptureFixture[str]
) -> None:
    clock.advance(3.0)
    async with started.wait("Backup in progress"):
        clock.advance(252.0)
    clock.advance(2.0)
    async with started.wait("Restore in progress"):
        clock.advance(38.0)

    waits, cuts, duration = await started.stop()

    assert waits == [
        Wait("Backup in progress", 3.0, 255.0),
        Wait("Restore in progress", 257.0, 295.0),
    ]
    assert cuts == []
    assert duration == RAW_DURATION
    output = capsys.readouterr().out
    assert "Wait: Backup in progress took 4 min 12 s" in output
    assert "Wait: Restore in progress took 38 s" in output


async def test_a_wait_whose_block_raises_is_not_recorded(
    started: DemoRecorder, clock: FakeClock
) -> None:
    with pytest.raises(RuntimeError, match="restore failed"):
        async with started.wait("Restore in progress"):
            clock.advance(5.0)
            raise RuntimeError("restore failed")

    waits, _cuts, _duration = await started.stop()
    assert waits == []


async def test_unrecorded_yields_a_new_page_of_the_same_context_and_records_a_cut(
    started: DemoRecorder, clock: FakeClock, calls: list[tuple]
) -> None:
    clock.advance(10.0)
    async with started.unrecorded() as page:
        assert page is not started._page
        assert page.context is started._page.context
        clock.advance(7.5)

    assert page.closed
    _waits, cuts, _duration = await started.stop()
    assert cuts == [Cut(10.0, 17.5)]


async def test_unrecorded_records_the_cut_and_closes_the_page_when_its_block_raises(
    started: DemoRecorder, clock: FakeClock
) -> None:
    clock.advance(4.0)
    with pytest.raises(ValueError, match="login failed"):
        async with started.unrecorded() as page:
            clock.advance(2.0)
            raise ValueError("login failed")

    assert page.closed
    _waits, cuts, _duration = await started.stop()
    assert cuts == [Cut(4.0, 6.0)]


async def test_step_shows_a_chapter_and_stays_current_when_its_block_raises(
    started: DemoRecorder, calls: list[tuple], capsys: pytest.CaptureFixture[str]
) -> None:
    assert started.current_step is None
    async with started.step("Back up the whole environment"):
        assert started.current_step == "Back up the whole environment"
    with pytest.raises(RuntimeError):
        async with started.step("Restore the backup"):
            raise RuntimeError("restore failed")

    assert started.current_step == "Restore the backup"
    chapters = [call for call in calls if call[0] == "show_chapter"]
    assert chapters == [
        ("show_chapter", "Back up the whole environment", {"duration": 2500}),
        ("show_chapter", "Restore the backup", {"duration": 2500}),
    ]
    output = capsys.readouterr().out
    assert "Step: Back up the whole environment" in output
    assert "Step: Restore the backup" in output


async def test_stop_stops_the_screencast_and_returns_copies(
    started: DemoRecorder, calls: list[tuple]
) -> None:
    waits, cuts, _duration = await started.stop()
    waits.append(Wait("x", 1.0, 2.0))
    cuts.append(Cut(1.0, 2.0))

    assert calls[-1] == ("stop",)
    again_waits, again_cuts, _ = await started.stop()
    assert again_waits == []
    assert again_cuts == []


async def test_a_wait_and_a_cut_cannot_nest(started: DemoRecorder) -> None:
    with pytest.raises(RuntimeError, match="A cut cannot start inside a wait"):
        async with started.wait("Clone in progress"), started.unrecorded():
            pass


async def test_the_recorder_refuses_steps_before_start(clock: FakeClock) -> None:
    with pytest.raises(RuntimeError, match="has not started"):
        async with DemoRecorder(clock=clock).step("Too early"):
            pass


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on the PATH")
def test_probe_duration_reads_the_container_duration(tmp_path: Path) -> None:
    video = tmp_path / "two-seconds.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:r=25:d=2",
            "-c:v",
            "libvpx-vp9",
            str(video),
        ],
        check=True,
    )

    assert probe_duration(video) == pytest.approx(2.0, abs=0.1)


@pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe is not on the PATH"
)
def test_probe_duration_raises_for_a_file_that_is_not_a_video(tmp_path: Path) -> None:
    text = tmp_path / "raw.webm"
    text.write_text("not a video")

    with pytest.raises(FfmpegError, match="no duration"):
        probe_duration(text)
