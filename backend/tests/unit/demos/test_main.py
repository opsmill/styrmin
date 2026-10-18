"""The record command's arguments, run loop, summary and exit codes, with fake demos and no browser or cluster."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from tests.e2e.demos import __main__ as cli
from tests.e2e.demos import recorder as recorder_module
from tests.e2e.demos.__main__ import (
    DemoResult,
    Runtime,
    Settings,
    format_length,
    main,
    read_settings,
    record_demos,
    select_demos,
    summary_row,
)
from tests.e2e.demos.catalog import Demo
from tests.e2e.demos.encode import FfmpegError
from tests.e2e.demos.recorder import DemoRecorder

SETTINGS = Settings(
    styrmin_url="http://styrmin.test:8080", username="admin", password="secret-value"
)
ENVIRON = {
    "STYRMIN_DEMO_URL": "http://styrmin.test:8080/",
    "STYRMIN_DEMO_USERNAME": "admin",
    "STYRMIN_DEMO_PASSWORD": "secret-value",
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeScreencast:
    def __init__(self) -> None:
        self.started = False

    async def start(self, *, path: Path, size: dict) -> None:
        path.write_bytes(b"raw video")
        self.started = True

    async def show_actions(self, **kwargs) -> None:
        return None

    async def show_chapter(self, title: str, **kwargs) -> None:
        return None

    async def stop(self) -> None:
        return None


class FakePage:
    def __init__(self) -> None:
        self.screencast = FakeScreencast()


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class Stack:
    """A fake demo stack that records what the run loop asks of it."""

    def __init__(self, work_root: Path, clock: FakeClock) -> None:
        self.work_root = work_root
        self.clock = clock
        self.calls: list[tuple] = []
        self.clients: list[FakeClient] = []
        self.problems: list[str] = []
        self.failing_encodes: set[str] = set()
        self.failing_deletions: set[tuple[str, ...]] = set()
        self.deletions: dict[tuple[str, ...], int] = {}
        self.raw_paths: list[Path] = []

    def runtime(self, versions_path: Path) -> Runtime:
        return Runtime(
            check=self.check,
            connect=self.connect,
            delete_environments=self.delete_environments,
            existing_environments=self.existing_environments,
            open_browser=self.open_browser,
            log_in=self.log_in,
            new_recorder=lambda: DemoRecorder(clock=self.clock),
            encode=self.encode,
            probe=lambda path: 95.0,
            versions_path=versions_path,
            work_root=self.work_root,
        )

    async def check(self, api_url, credentials, versions_path) -> list[str]:
        self.calls.append(("check", api_url, credentials[0]))
        return self.problems

    async def connect(self, api_url, username, password) -> FakeClient:
        client = FakeClient()
        self.clients.append(client)
        return client

    async def delete_environments(self, client, names) -> None:
        names = tuple(names)
        self.calls.append(("delete", names))
        self.deletions[names] = self.deletions.get(names, 0) + 1
        if names in self.failing_deletions and self.deletions[names] > 1:
            raise RuntimeError("namespace still exists")

    async def existing_environments(self, client, names) -> list[str]:
        return list(names)

    @asynccontextmanager
    async def open_browser(self, styrmin_url):
        self.calls.append(("browser", styrmin_url))
        try:
            yield object(), FakePage()
        finally:
            self.calls.append(("browser closed",))

    async def log_in(self, page, username, password) -> None:
        self.calls.append(("log in", username))

    async def encode(self, context, raw_path, segments, output_path, work_dir) -> None:
        self.raw_paths.append(raw_path)
        assert raw_path.read_bytes() == b"raw video"
        (work_dir / "label-0.png").write_bytes(b"label")
        if output_path.name in self.failing_encodes:
            raise FfmpegError("ffmpeg exited with code 1:\nInvalid filter")
        output_path.write_bytes(b"mp4 " + raw_path.parent.name.encode())


def _demo(slug: str, number: int, *, setup=None, record=None) -> Demo:
    async def default_setup(context) -> str:
        return f"state of {slug}"

    async def default_record(context, state) -> None:
        assert state == f"state of {slug}"
        async with context.recorder.step(f"{slug}: first step"):
            async with context.recorder.wait("The cluster works"):
                context.recorder._clock.now += 30
        async with context.recorder.step(f"{slug}: second step"):
            context.recorder._clock.now += 2

    return Demo(
        slug=slug,
        number=number,
        environment_names=(f"network-lab-{slug}",),
        setup=setup or default_setup,
        record=record or default_record,
    )


async def _failing_setup(context) -> None:
    raise RuntimeError(
        "Deployment 'infrahub' failed: step \"render\" failed: bad chart"
    )


async def _failing_second_step(context, state) -> None:
    async with context.recorder.step("Restore the backup"):
        context.recorder._clock.now += 5
    async with context.recorder.step("The device and the template are back"):
        raise AssertionError("sw2 is not listed")


@pytest.fixture
def stack(tmp_path, monkeypatch) -> Stack:
    monkeypatch.setattr(recorder_module, "probe_duration", lambda path: 40.0)
    work_root = tmp_path / "work"
    work_root.mkdir()
    return Stack(work_root, FakeClock())


@pytest.fixture
def versions_path(tmp_path) -> Path:
    path = tmp_path / "infrahub_versions.yml"
    path.write_text('previous: "1.10.11"\nlatest: "1.11.7"\n')
    return path


async def test_each_failure_names_its_step_keeps_the_environments_and_the_others_still_run(
    stack, versions_path, tmp_path
) -> None:
    output_dir = tmp_path / "videos"
    output_dir.mkdir()
    (output_dir / "3-backup-restore.mp4").write_bytes(b"previous video")
    stack.failing_encodes.add("4-clone.mp4")
    demos = [
        _demo("deploy-upgrade", 1),
        _demo("component-overrides", 2, setup=_failing_setup),
        _demo("backup-restore", 3, record=_failing_second_step),
        _demo("clone", 4),
    ]

    code = await record_demos(demos, SETTINGS, output_dir, stack.runtime(versions_path))

    assert code == 1
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "1-deploy-upgrade.mp4",
        "3-backup-restore.mp4",
    ]
    assert (output_dir / "3-backup-restore.mp4").read_bytes() == b"previous video"
    # The raw recordings, labels and partial videos are gone with their temporary directories.
    assert list(stack.work_root.iterdir()) == []
    assert all(not path.exists() for path in stack.raw_paths)
    # Leftovers are deleted before each setup; only the recorded demo's environments are deleted after.
    assert stack.deletions == {
        ("network-lab-deploy-upgrade",): 2,
        ("network-lab-component-overrides",): 1,
        ("network-lab-backup-restore",): 1,
        ("network-lab-clone",): 1,
    }
    assert all(client.closed for client in stack.clients)
    assert len(stack.clients) == 4


async def test_the_summary_rows_of_a_mixed_run(
    stack, versions_path, tmp_path, monkeypatch
) -> None:
    results: list[list[DemoResult]] = []
    monkeypatch.setattr(cli, "print_summary", results.append)
    stack.failing_encodes.add("4-clone.mp4")
    output_dir = tmp_path / "videos"
    demos = [
        _demo("deploy-upgrade", 1),
        _demo("component-overrides", 2, setup=_failing_setup),
        _demo("backup-restore", 3, record=_failing_second_step),
        _demo("clone", 4),
    ]

    await record_demos(demos, SETTINGS, output_dir, stack.runtime(versions_path))

    [summary] = results
    assert [(row.slug, row.status, row.failed_step) for row in summary] == [
        ("deploy-upgrade", "recorded", None),
        ("component-overrides", "failed", "setup"),
        ("backup-restore", "failed", "The device and the template are back"),
        ("clone", "failed", "post-processing"),
    ]
    assert summary[0].video_path == output_dir / "1-deploy-upgrade.mp4"
    assert summary[0].video_seconds == 95.0
    assert (
        summary[1].error
        == "RuntimeError: Deployment 'infrahub' failed: step \"render\" failed: bad chart"
    )
    assert summary[2].error == "AssertionError: sw2 is not listed"
    assert (
        summary[3].error == "FfmpegError: ffmpeg exited with code 1: … Invalid filter"
    )
    assert [row.kept_environments for row in summary[1:]] == [
        ("network-lab-component-overrides",),
        ("network-lab-backup-restore",),
        ("network-lab-clone",),
    ]
    assert summary_row(summary[2]) == (
        "backup-restore",
        "failed",
        'step "The device and the template are back": AssertionError: sw2 is not listed\n'
        "kept environments: network-lab-backup-restore",
        "-",
    )


async def test_every_demo_recorded_exits_0_and_the_run_order_is_the_contracts(
    stack, versions_path, tmp_path
) -> None:
    code = await record_demos(
        [_demo("deploy-upgrade", 1)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 0
    assert stack.calls == [
        ("check", "http://styrmin.test:8080", "admin"),
        ("delete", ("network-lab-deploy-upgrade",)),
        ("browser", "http://styrmin.test:8080"),
        ("log in", "admin"),
        ("browser closed",),
        ("delete", ("network-lab-deploy-upgrade",)),
    ]


async def test_a_failure_before_the_first_step_is_a_recording_failure(
    stack, versions_path, tmp_path, monkeypatch
) -> None:
    results: list[list[DemoResult]] = []
    monkeypatch.setattr(cli, "print_summary", results.append)

    async def record(context, state) -> None:
        raise RuntimeError("page closed")

    await record_demos(
        [_demo("clone", 4, record=record)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert results[0][0].failed_step == "recording"


async def test_a_cleanup_failure_keeps_the_video_and_fails_the_demo(
    stack, versions_path, tmp_path, monkeypatch
) -> None:
    results: list[list[DemoResult]] = []
    monkeypatch.setattr(cli, "print_summary", results.append)
    stack.failing_deletions.add(("network-lab-clone",))
    output_dir = tmp_path / "videos"

    code = await record_demos(
        [_demo("clone", 4)], SETTINGS, output_dir, stack.runtime(versions_path)
    )

    assert code == 1
    assert (output_dir / "4-clone.mp4").exists()
    assert results[0][0].failed_step == "cleanup"
    assert results[0][0].kept_environments == ("network-lab-clone",)


async def test_a_failed_prerequisite_exits_2_before_any_setup(
    stack, versions_path, tmp_path, monkeypatch, capsys
) -> None:
    results: list[list[DemoResult]] = []
    monkeypatch.setattr(cli, "print_summary", results.append)
    stack.problems = ["ffmpeg is not on the PATH. Install it."]

    code = await record_demos(
        [_demo("deploy-upgrade", 1), _demo("clone", 4)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 2
    assert "ffmpeg is not on the PATH. Install it." in capsys.readouterr().out
    assert [call[0] for call in stack.calls] == ["check"]
    assert [(row.slug, row.status) for row in results[0]] == [
        ("deploy-upgrade", "skipped"),
        ("clone", "skipped"),
    ]


async def test_an_empty_catalog_checks_the_prerequisites_and_exits_0(
    stack, versions_path, tmp_path, capsys
) -> None:
    code = await record_demos(
        [], SETTINGS, tmp_path / "videos", stack.runtime(versions_path)
    )

    output = capsys.readouterr().out
    assert code == 0
    assert stack.calls == [("check", "http://styrmin.test:8080", "admin")]
    assert "nothing to record" in output
    assert "Demo" in output
    assert "Result" in output


def test_an_unknown_slug_lists_the_four_slugs_and_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            ["--demo", "nope"], environ=ENVIRON, demos=[_demo("component-overrides", 2)]
        )

    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert (
        "'nope' is not a demo. The demos are: deploy-upgrade (not available yet), "
        "component-overrides, backup-restore (not available yet), clone (not available yet)"
    ) in error


def test_a_slug_without_a_scenario_is_not_available_yet() -> None:
    with pytest.raises(
        ValueError, match="^'clone' is not available yet. The demos are: deploy-upgrade"
    ):
        select_demos("clone", [_demo("deploy-upgrade", 1)])


def test_select_demos_returns_one_demo_or_all_of_them() -> None:
    demos = [_demo("deploy-upgrade", 1), _demo("backup-restore", 3)]

    assert select_demos("", demos) == tuple(demos)
    assert select_demos("backup-restore", demos) == (demos[1],)


def test_main_reads_the_settings_and_passes_the_arguments(
    tmp_path, monkeypatch
) -> None:
    received: list[tuple] = []

    async def fake_record_demos(demos, settings, output_dir, runtime) -> int:
        received.append((demos, settings, output_dir))
        return 1

    monkeypatch.setattr(cli, "record_demos", fake_record_demos)
    demo = _demo("backup-restore", 3)

    code = main(
        ["--demo", "backup-restore", "--output-dir", str(tmp_path / "out")],
        environ=ENVIRON,
        demos=[demo],
    )

    assert code == 1
    assert received == [((demo,), SETTINGS, tmp_path / "out")]


def test_main_exits_2_without_the_environment_variables(capsys) -> None:
    assert (
        main([], environ={"STYRMIN_DEMO_URL": "http://styrmin.test:8080"}, demos=[])
        == 2
    )
    assert "uv run invoke record" in capsys.readouterr().out


def test_the_settings_never_show_the_password() -> None:
    settings = read_settings(ENVIRON)

    assert settings == SETTINGS
    assert "secret-value" not in repr(settings)


def test_a_recorded_video_over_three_minutes_gets_a_warning_but_stays_recorded() -> (
    None
):
    result = DemoResult(
        "clone",
        "recorded",
        video_path=cli.REPOSITORY_ROOT / "demo-videos" / "4-clone.mp4",
        video_seconds=181.0,
    )

    assert summary_row(result) == (
        "clone",
        "recorded",
        "demo-videos/4-clone.mp4\nwarning: longer than 3:00",
        "3:01",
    )
    assert summary_row(replace(result, video_seconds=161.2))[2:] == (
        "demo-videos/4-clone.mp4",
        "2:41",
    )
    assert cli.exit_code([result]) == 0


def test_format_length_rounds_to_the_second() -> None:
    assert format_length(59.6) == "1:00"
    assert format_length(180.4) == "3:00"
    assert format_length(7) == "0:07"


def test_the_memory_note_follows_a_summary_with_kept_environments(capsys) -> None:
    cli.print_summary(
        [
            DemoResult(
                "clone",
                "failed",
                failed_step="setup",
                error="E",
                kept_environments=("network-lab",),
            )
        ]
    )

    output = " ".join(capsys.readouterr().out.split())
    assert "kept environments: network-lab" in output
    assert "until the next run of their demo deletes them" in output
