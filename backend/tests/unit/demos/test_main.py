"""The record command's arguments, run loop, summary and exit codes, with fake demos and no browser or cluster."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from tests.e2e.demos import __main__ as cli
from tests.e2e.demos import recorder as recorder_module
from tests.e2e.demos.__main__ import (
    PLAN_FILE,
    DemoResult,
    Runtime,
    Settings,
    encode_again,
    format_length,
    main,
    read_settings,
    record_demos,
    select_demos,
    summary_row,
)
from tests.e2e.demos.catalog import Demo
from tests.e2e.demos.encode import FfmpegError
from tests.e2e.demos.ledger import CreatedEnvironments
from tests.e2e.demos.recorder import DemoRecorder
from tests.e2e.demos.semaphore_image import ImageBuildError
from tests.e2e.demos.stack import EnvironmentRecord, StackError
from tests.e2e.demos.video import VideoPlan

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
    async def start(self, *, path: Path, size: dict) -> None:
        path.write_bytes(b"raw video")

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
    """A fake demo stack that records what the run loop asks of it.

    ``environments`` maps the name of each environment on the stack to its id; a demo's setup creates its
    environments.
    """

    def __init__(self, work_root: Path, ledger_path: Path, clock: FakeClock) -> None:
        self.work_root = work_root
        self.ledger_path = ledger_path
        self.clock = clock
        self.calls: list[tuple] = []
        self.clients: list[FakeClient] = []
        self.problems: list[str] = []
        self.build_error: ImageBuildError | None = None
        self.answer = False
        self.questions: list[str] = []
        self.environments: dict[str, str] = {}
        self.created = 0
        self.failing_encodes: set[str] = set()
        self.failing_deletions: set[str] = set()
        self.deleted: list[tuple[str, ...]] = []
        self.deleting = asyncio.Event()

    def runtime(self, versions_path: Path) -> Runtime:
        return Runtime(
            check=self.check,
            check_tools=self.check_tools,
            build_image=self.build_image,
            connect=self.connect,
            find_environments=self.find_environments,
            delete_environments=self.delete_environments,
            open_browser=self.open_browser,
            log_in=self.log_in,
            new_recorder=lambda: DemoRecorder(clock=self.clock),
            encode=self.encode,
            probe=lambda path: 95.0,
            confirm=self.confirm,
            versions_path=versions_path,
            ledger_path=self.ledger_path,
            work_root=self.work_root,
        )

    def create(self, name: str) -> None:
        self.created += 1
        self.environments[name] = f"env-{self.created}"

    def ledger(self) -> CreatedEnvironments:
        return CreatedEnvironments(self.ledger_path, SETTINGS.styrmin_url)

    async def check(
        self, api_url, credentials, versions_path, *, needs_docker, empty_stack=False
    ):
        self.calls.append(("check", api_url, credentials[0], needs_docker, empty_stack))
        return self.problems

    async def check_tools(self) -> list[str]:
        self.calls.append(("check tools",))
        return self.problems

    def build_image(self, *, no_cache: bool) -> None:
        self.calls.append(("build", no_cache))
        if self.build_error is not None:
            raise self.build_error

    async def connect(self, api_url, username, password) -> FakeClient:
        client = FakeClient()
        self.clients.append(client)
        return client

    async def find_environments(self, client, names) -> list[EnvironmentRecord]:
        return [
            EnvironmentRecord(name, self.environments[name])
            for name in names
            if name in self.environments
        ]

    async def delete_environments(self, client, environments) -> None:
        names = tuple(environment.name for environment in environments)
        self.calls.append(("delete", names))
        self.deleting.set()
        if set(names) & self.failing_deletions and self.created:
            raise StackError("These namespaces still exist after 600 s: styrmin-1")
        for name in names:
            del self.environments[name]
        self.deleted.append(names)

    @asynccontextmanager
    async def open_browser(self, styrmin_url):
        self.calls.append(("browser", styrmin_url))
        try:
            yield object(), FakePage()
        finally:
            self.calls.append(("browser closed",))

    async def log_in(self, page, username, password) -> None:
        self.calls.append(("log in", username))

    async def encode(self, context, plan: VideoPlan, work_dir: Path) -> Path:
        self.calls.append(("encode", plan.video_name))
        assert (work_dir / plan.raw_name).read_bytes() == b"raw video"
        assert VideoPlan.from_json((work_dir / PLAN_FILE).read_text()) == plan
        (work_dir / "label-0.png").write_bytes(b"label")
        if plan.video_name in self.failing_encodes:
            raise FfmpegError("ffmpeg exited with code 1:\nInvalid filter")
        video = work_dir / plan.video_name
        video.write_bytes(b"mp4 " + plan.video_name.encode())
        return video

    def confirm(self, question: str) -> bool:
        self.questions.append(question)
        return self.answer


def _demo(slug: str, number: int, *, setup=None, record=None, image=False) -> Demo:
    environment = f"network-lab-{slug}"

    async def default_setup(context) -> str:
        STACK.create(environment)
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
        title=f"Title of {slug}",
        environment_names=(environment,),
        setup=setup or default_setup,
        record=record or default_record,
        summary=("Infrahub {previous} to {latest}.",),
        uses_semaphore_image=image,
    )


def _setup_demo(*, record=None) -> Demo:
    """A setup demo that creates the environment of the fake deploy-upgrade demo during its recording."""

    async def setup(context) -> None:
        return None

    async def default_record(context, state) -> None:
        async with context.recorder.step("Add the Kubernetes cluster"):
            STACK.create("network-lab-deploy-upgrade")
            context.recorder._clock.now += 2

    return Demo(
        slug="setup",
        number=0,
        title="Set up Styrmin",
        environment_names=(),
        setup=setup,
        record=record or default_record,
        summary=("Set up.",),
        hands_over=("network-lab-deploy-upgrade",),
        sets_up_stack=True,
    )


def _upgrade_demo(seen: list[dict[str, str]]) -> Demo:
    """A deploy-upgrade demo whose setup keeps the environment it finds, as the real one does."""

    async def setup(context) -> str:
        seen.append(dict(STACK.environments))
        if "network-lab-deploy-upgrade" not in STACK.environments:
            STACK.create("network-lab-deploy-upgrade")
        return "state of deploy-upgrade"

    return _demo("deploy-upgrade", 1, setup=setup)


async def _failing_setup(context) -> None:
    STACK.create("network-lab-component-overrides")
    raise RuntimeError(
        "Deployment 'infrahub' failed: step \"render\" failed: bad chart"
    )


async def _failing_second_step(context, state) -> None:
    async with context.recorder.step("Restore the backup"):
        context.recorder._clock.now += 5
    async with context.recorder.step("The device and the template are back"):
        raise AssertionError("sw2 is not listed")


STACK: Stack


@pytest.fixture
def stack(tmp_path, monkeypatch) -> Stack:
    global STACK  # noqa: PLW0603 - the fake demos reach the fake stack of the running test
    monkeypatch.setattr(recorder_module, "probe_duration", lambda path: 40.0)
    work_root = tmp_path / "work"
    work_root.mkdir()
    STACK = Stack(work_root, tmp_path / "state" / "demo-environments.json", FakeClock())
    return STACK


@pytest.fixture
def versions_path(tmp_path) -> Path:
    path = tmp_path / "infrahub_versions.yml"
    path.write_text('previous: "1.10.11"\nlatest: "1.11.7"\n')
    return path


@pytest.fixture
def summaries(monkeypatch) -> list[list[DemoResult]]:
    results: list[list[DemoResult]] = []
    monkeypatch.setattr(cli, "print_summary", results.append)
    return results


async def test_each_failure_names_its_step_keeps_the_environments_and_the_others_still_run(
    stack, versions_path, tmp_path, summaries
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
        "1-deploy-upgrade.chapters.txt",
        "1-deploy-upgrade.mp4",
        "3-backup-restore.mp4",
    ]
    assert (output_dir / "3-backup-restore.mp4").read_bytes() == b"previous video"
    # Only the demo whose encoding failed keeps its work directory, with the raw recording and the plan.
    [kept] = list(stack.work_root.iterdir())
    assert kept.name.startswith("styrmin-demo-clone-")
    assert {path.name for path in kept.iterdir()} >= {"raw.webm", PLAN_FILE}
    assert [row.kept_work_dir for row in summaries[0]] == [None, None, None, kept]
    # The deletion after a failed encoding still runs; failed setups and recordings keep theirs.
    assert stack.deleted == [("network-lab-deploy-upgrade",), ("network-lab-clone",)]
    assert set(stack.environments) == {
        "network-lab-component-overrides",
        "network-lab-backup-restore",
    }
    assert all(client.closed for client in stack.clients)


async def test_the_summary_rows_of_a_mixed_run(
    stack, versions_path, tmp_path, summaries
) -> None:
    stack.failing_encodes.add("4-clone.mp4")
    output_dir = tmp_path / "videos"
    demos = [
        _demo("deploy-upgrade", 1),
        _demo("component-overrides", 2, setup=_failing_setup),
        _demo("backup-restore", 3, record=_failing_second_step),
        _demo("clone", 4),
    ]

    await record_demos(demos, SETTINGS, output_dir, stack.runtime(versions_path))

    [summary] = summaries
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
        (),
    ]
    assert summary_row(summary[2]) == (
        "backup-restore",
        "failed",
        'step "The device and the template are back": AssertionError: sw2 is not listed\n'
        "kept environments: network-lab-backup-restore\n"
        "next: inspect the kept environments in the Styrmin UI, then delete them with "
        "'uv run invoke record --delete-environments --demo backup-restore'\n"
        "next: read the error above, then record the demo again with "
        "'uv run invoke record --demo backup-restore'",
        "-",
    )
    kept = summary[3].kept_work_dir
    assert summary_row(summary[3])[2] == (
        'step "post-processing": FfmpegError: ffmpeg exited with code 1: … Invalid filter\n'
        f"kept recording: {kept}\n"
        f"next: encode the kept recording with 'uv run invoke record --encode-again {kept}'"
    )


async def test_every_demo_recorded_exits_0_and_the_run_order_is_the_contracts(
    stack, versions_path, tmp_path
) -> None:
    output_dir = tmp_path / "videos"

    code = await record_demos(
        [_demo("deploy-upgrade", 1)],
        SETTINGS,
        output_dir,
        stack.runtime(versions_path),
    )

    assert code == 0
    assert stack.calls == [
        ("check", "http://styrmin.test:8080", "admin", False, False),
        ("browser", "http://styrmin.test:8080"),
        ("log in", "admin"),
        ("encode", "1-deploy-upgrade.mp4"),
        ("delete", ("network-lab-deploy-upgrade",)),
        ("browser closed",),
    ]
    # The 30 s wait plays 8 times faster (3.75 s), then 10 s of the 40 s recording remain.
    assert (output_dir / "1-deploy-upgrade.chapters.txt").read_text() == (
        "0:00 deploy-upgrade: first step\n"
        "0:03 deploy-upgrade: second step\n"
        "0:13 Summary\n"
    )
    # No temporary name is left in the output directory.
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "1-deploy-upgrade.chapters.txt",
        "1-deploy-upgrade.mp4",
    ]
    assert list(stack.work_root.iterdir()) == []
    # The command forgets the environments it deleted.
    assert "env-1" not in stack.ledger()


async def test_the_environments_are_deleted_while_the_video_is_encoded(
    stack, versions_path, tmp_path
) -> None:
    runtime = stack.runtime(versions_path)

    async def encode(context, plan, work_dir) -> Path:
        # The deletion runs while ffmpeg would encode, so this wait ends.
        await asyncio.wait_for(stack.deleting.wait(), timeout=5)
        return await stack.encode(context, plan, work_dir)

    code = await record_demos(
        [_demo("clone", 4)],
        SETTINGS,
        tmp_path / "videos",
        replace(runtime, encode=encode),
    )

    assert code == 0


async def test_a_failure_before_the_first_step_is_a_recording_failure(
    stack, versions_path, tmp_path, summaries
) -> None:
    async def record(context, state) -> None:
        raise RuntimeError("page closed")

    await record_demos(
        [_demo("clone", 4, record=record)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert summaries[0][0].failed_step == "recording"


async def test_a_cleanup_failure_keeps_the_video_and_fails_the_demo(
    stack, versions_path, tmp_path, summaries
) -> None:
    stack.failing_deletions.add("network-lab-clone")
    output_dir = tmp_path / "videos"

    code = await record_demos(
        [_demo("clone", 4)], SETTINGS, output_dir, stack.runtime(versions_path)
    )

    assert code == 1
    assert (output_dir / "4-clone.mp4").exists()
    [result] = summaries[0]
    assert result.failed_step == "cleanup"
    assert result.kept_environments == ("network-lab-clone",)
    assert result.kept_work_dir is None
    assert list(stack.work_root.iterdir()) == []


async def test_ctrl_c_prints_the_summary_so_far_and_closes_the_client_and_the_browser(
    stack, versions_path, tmp_path, summaries, capsys
) -> None:
    recording = asyncio.Event()

    async def record(context, state) -> None:
        async with context.recorder.step("Clone the environment"):
            recording.set()
            await asyncio.Event().wait()

    run = asyncio.create_task(
        record_demos(
            [
                _demo("deploy-upgrade", 1),
                _demo("backup-restore", 3, record=record),
                _demo("clone", 4),
            ],
            SETTINGS,
            tmp_path / "videos",
            stack.runtime(versions_path),
        )
    )
    await asyncio.wait_for(recording.wait(), timeout=5)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    [summary] = summaries
    assert [(row.slug, row.status) for row in summary] == [
        ("deploy-upgrade", "recorded"),
        ("backup-restore", "interrupted"),
        ("clone", "skipped"),
    ]
    assert summary[1].failed_step == "Clone the environment"
    assert summary[1].kept_environments == ("network-lab-backup-restore",)
    assert summary_row(summary[1])[2] == (
        'interrupted in step "Clone the environment"\n'
        "kept environments: network-lab-backup-restore\n"
        "next: inspect the kept environments in the Styrmin UI, then delete them with "
        "'uv run invoke record --delete-environments --demo backup-restore'\n"
        "next: record the demo again with 'uv run invoke record --demo backup-restore'"
    )
    assert "Interrupted (Ctrl-C)." in capsys.readouterr().out
    assert all(client.closed for client in stack.clients)
    assert stack.calls.count(("browser closed",)) == 2
    assert list(stack.work_root.iterdir()) == []
    # The next run deletes the kept environment without asking.
    assert stack.environments["network-lab-backup-restore"] in stack.ledger()


def test_main_exits_130_on_ctrl_c(monkeypatch) -> None:
    async def interrupted(*args, **kwargs) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "record_demos", interrupted)

    assert main([], environ=ENVIRON, demos=[_demo("clone", 4)]) == 130


async def test_an_environment_the_command_did_not_create_stops_the_run_unless_confirmed(
    stack, versions_path, tmp_path, summaries
) -> None:
    stack.environments["network-lab-clone"] = "env-by-hand"

    code = await record_demos(
        [_demo("deploy-upgrade", 1), _demo("clone", 4)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 2
    [question] = stack.questions
    assert question == "Delete them? [y/N] "
    assert stack.environments == {"network-lab-clone": "env-by-hand"}
    assert not any(call[0] in {"browser", "delete"} for call in stack.calls)
    assert [(row.slug, row.status) for row in summaries[0]] == [
        ("deploy-upgrade", "skipped"),
        ("clone", "skipped"),
    ]


async def test_a_confirmed_environment_is_deleted_before_the_setup(
    stack, versions_path, tmp_path
) -> None:
    stack.environments["network-lab-clone"] = "env-by-hand"
    stack.answer = True

    code = await record_demos(
        [_demo("clone", 4)], SETTINGS, tmp_path / "videos", stack.runtime(versions_path)
    )

    assert code == 0
    assert stack.deleted == [("network-lab-clone",), ("network-lab-clone",)]


async def test_a_kept_environment_of_an_earlier_run_is_deleted_without_a_question(
    stack, versions_path, tmp_path
) -> None:
    stack.environments["network-lab-clone"] = "env-kept"
    stack.ledger().remember([EnvironmentRecord("network-lab-clone", "env-kept")])

    code = await record_demos(
        [_demo("clone", 4)], SETTINGS, tmp_path / "videos", stack.runtime(versions_path)
    )

    assert code == 0
    assert stack.questions == []
    assert stack.deleted[0] == ("network-lab-clone",)


async def test_a_demo_refuses_to_delete_an_environment_that_appeared_after_the_question(
    stack, versions_path, tmp_path, summaries
) -> None:
    async def setup(context) -> str:
        return "state of clone"

    runtime = stack.runtime(versions_path)

    async def connect(*args) -> FakeClient:
        # Someone creates the environment by hand after the command asked.
        if len(stack.clients) == 1:
            stack.environments["network-lab-clone"] = "env-by-hand"
        return await stack.connect(*args)

    await record_demos(
        [_demo("clone", 4, setup=setup)],
        SETTINGS,
        tmp_path / "videos",
        replace(runtime, connect=connect),
    )

    [result] = summaries[0]
    assert result.failed_step == "setup"
    assert "did not create these environments, so it does not delete them" in (
        result.error or ""
    )
    assert stack.environments == {"network-lab-clone": "env-by-hand"}


async def test_the_semaphore_image_is_built_before_any_demo_that_deploys_it(
    stack, versions_path, tmp_path
) -> None:
    await record_demos(
        [_demo("clone", 4, image=True)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
        rebuild_image=True,
    )

    assert stack.calls[:2] == [
        ("check", "http://styrmin.test:8080", "admin", True, False),
        ("build", True),
    ]


async def test_a_failed_image_build_exits_2_before_any_setup(
    stack, versions_path, tmp_path, summaries, capsys
) -> None:
    stack.build_error = ImageBuildError("docker build of x exited with code 1:\nboom")

    code = await record_demos(
        [_demo("clone", 4, image=True)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 2
    assert "boom" in capsys.readouterr().out
    assert [call[0] for call in stack.calls] == ["check", "build"]
    assert summaries[0][0].status == "skipped"


async def test_a_failed_prerequisite_exits_2_before_any_setup(
    stack, versions_path, tmp_path, summaries, capsys
) -> None:
    stack.problems = ["ffmpeg is not on the PATH. Install it."]

    code = await record_demos(
        [_demo("deploy-upgrade", 1), _demo("clone", 4, image=True)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 2
    assert "ffmpeg is not on the PATH. Install it." in capsys.readouterr().out
    assert [call[0] for call in stack.calls] == ["check"]
    assert [(row.slug, row.status) for row in summaries[0]] == [
        ("deploy-upgrade", "skipped"),
        ("clone", "skipped"),
    ]


async def test_encode_again_publishes_the_video_and_deletes_the_kept_recording(
    stack, versions_path, tmp_path, summaries
) -> None:
    stack.failing_encodes.add("4-clone.mp4")
    output_dir = tmp_path / "videos"
    await record_demos(
        [_demo("clone", 4)], SETTINGS, output_dir, stack.runtime(versions_path)
    )
    kept = summaries[0][0].kept_work_dir
    assert kept is not None
    stack.failing_encodes.clear()

    code = await encode_again(kept, output_dir, stack.runtime(versions_path))

    assert code == 0
    assert (output_dir / "4-clone.mp4").read_bytes() == b"mp4 4-clone.mp4"
    assert (output_dir / "4-clone.chapters.txt").exists()
    assert not kept.exists()
    [result] = summaries[1]
    assert (result.slug, result.status) == ("clone", "recorded")
    assert ("browser", None) in stack.calls


async def test_encode_again_refuses_a_directory_without_a_plan(
    stack, versions_path, tmp_path, capsys
) -> None:
    code = await encode_again(
        tmp_path, tmp_path / "videos", stack.runtime(versions_path)
    )

    assert code == 2
    assert "holds no recording to encode" in " ".join(capsys.readouterr().out.split())


async def test_delete_environments_deletes_only_the_selected_demos_environments(
    stack, versions_path
) -> None:
    for name in ("network-lab-clone", "network-lab-deploy-upgrade"):
        stack.environments[name] = f"env-{name}"
        stack.ledger().remember([EnvironmentRecord(name, f"env-{name}")])

    code = await cli.delete_demo_environments(
        [_demo("clone", 4)], SETTINGS, stack.runtime(versions_path)
    )

    assert code == 0
    assert stack.deleted == [("network-lab-clone",)]
    assert set(stack.environments) == {"network-lab-deploy-upgrade"}
    assert "env-network-lab-clone" not in stack.ledger()


def test_an_unknown_slug_lists_the_slugs_and_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            ["--demo", "nope"], environ=ENVIRON, demos=[_demo("component-overrides", 2)]
        )

    assert raised.value.code == 2
    error = capsys.readouterr().err
    assert (
        "'nope' is not a demo. The demos are: setup, deploy-upgrade, "
        "component-overrides, backup-restore, clone"
    ) in error


def test_select_demos_takes_several_slugs_in_the_catalogs_order() -> None:
    demos = [_demo("deploy-upgrade", 1), _demo("backup-restore", 3), _demo("clone", 4)]

    assert select_demos([], demos) == tuple(demos)
    assert select_demos(["backup-restore"], demos) == (demos[1],)
    assert select_demos(["clone", "deploy-upgrade"], demos) == (demos[0], demos[2])
    assert select_demos(["clone,backup-restore", "clone"], demos) == (
        demos[1],
        demos[2],
    )


def test_main_reads_the_settings_and_passes_the_arguments(
    tmp_path, monkeypatch
) -> None:
    received: list[tuple] = []

    async def fake_record_demos(demos, settings, output_dir, runtime, *, rebuild_image):
        received.append((demos, settings, output_dir, rebuild_image))
        return 1

    monkeypatch.setattr(cli, "record_demos", fake_record_demos)
    demos = [_demo("backup-restore", 3), _demo("clone", 4)]

    code = main(
        [
            *("--demo", "clone", "--demo", "backup-restore"),
            *("--output-dir", str(tmp_path / "out"), "--rebuild-image"),
        ],
        environ=ENVIRON,
        demos=demos,
    )

    assert code == 1
    assert received == [(tuple(demos), SETTINGS, tmp_path / "out", True)]


def test_main_runs_only_the_deletion_with_delete_environments(monkeypatch) -> None:
    received: list[tuple] = []

    async def fake_delete(demos, settings, runtime) -> int:
        received.append((demos, settings))
        return 0

    monkeypatch.setattr(cli, "delete_demo_environments", fake_delete)
    demo = _demo("clone", 4)

    assert main(["--delete-environments"], environ=ENVIRON, demos=[demo]) == 0
    assert received == [((demo,), SETTINGS)]


def test_main_encodes_again_without_the_stack_settings(tmp_path, monkeypatch) -> None:
    received: list[tuple] = []

    async def fake_encode_again(work_dir, output_dir, runtime) -> int:
        received.append((work_dir, output_dir))
        return 0

    monkeypatch.setattr(cli, "encode_again", fake_encode_again)

    code = main(
        ["--encode-again", str(tmp_path / "kept"), "--output-dir", str(tmp_path)],
        environ={},
        demos=[],
    )

    assert code == 0
    assert received == [(tmp_path / "kept", tmp_path)]


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
    assert "'uv run invoke record --delete-environments' deletes" in output


async def test_the_setup_demo_hands_its_environment_to_demo_1(
    stack, versions_path, tmp_path
) -> None:
    seen: list[dict[str, str]] = []

    code = await record_demos(
        [_setup_demo(), _upgrade_demo(seen)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 0
    # The check asks for a stack without the cluster and the backup storage location.
    assert stack.calls[0] == ("check", "http://styrmin.test:8080", "admin", False, True)
    # Demo 1 finds the environment of the setup demo: no deletion before its setup.
    assert seen == [{"network-lab-deploy-upgrade": "env-1"}]
    assert stack.deleted == [("network-lab-deploy-upgrade",)]
    assert (tmp_path / "videos" / "0-setup.mp4").exists()
    assert "env-1" not in stack.ledger()


async def test_without_the_setup_demo_a_kept_environment_of_demo_1_is_deleted_first(
    stack, versions_path, tmp_path
) -> None:
    stack.environments["network-lab-deploy-upgrade"] = "env-kept"
    stack.ledger().remember(
        [EnvironmentRecord("network-lab-deploy-upgrade", "env-kept")]
    )
    seen: list[dict[str, str]] = []

    code = await record_demos(
        [_upgrade_demo(seen)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 0
    assert seen == [{}]
    assert stack.deleted[0] == ("network-lab-deploy-upgrade",)


async def test_a_failed_setup_demo_skips_the_later_demos(
    stack, versions_path, tmp_path, summaries, capsys
) -> None:
    async def record(context, state) -> None:
        async with context.recorder.step("Add a backup storage location"):
            STACK.create("network-lab-deploy-upgrade")
            raise AssertionError("the dialog stayed open")

    code = await record_demos(
        [_setup_demo(record=record), _upgrade_demo([]), _demo("clone", 4)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 1
    assert cli.SETUP_FAILED_NOTE in " ".join(capsys.readouterr().out.split())
    [summary] = summaries
    assert [(row.slug, row.status) for row in summary] == [
        ("setup", "failed"),
        ("deploy-upgrade", "skipped"),
        ("clone", "skipped"),
    ]
    assert summary[0].reset_stack
    assert summary[0].kept_environments == ("network-lab-deploy-upgrade",)
    assert summary_row(summary[0])[2] == (
        'step "Add a backup storage location": AssertionError: the dialog stayed open\n'
        "kept environments: network-lab-deploy-upgrade\n"
        "next: read the error above, then create an empty demo stack with "
        "'uv run invoke reset --no-bootstrap', then record again with 'uv run invoke record'"
    )
    # The later demos never opened a browser.
    assert stack.calls.count(("browser", "http://styrmin.test:8080")) == 1


async def test_a_setup_demo_whose_encoding_failed_still_lets_the_later_demos_run(
    stack, versions_path, tmp_path, summaries
) -> None:
    stack.failing_encodes.add("0-setup.mp4")
    seen: list[dict[str, str]] = []

    code = await record_demos(
        [_setup_demo(), _upgrade_demo(seen)],
        SETTINGS,
        tmp_path / "videos",
        stack.runtime(versions_path),
    )

    assert code == 1
    [summary] = summaries
    assert [(row.slug, row.status, row.failed_step) for row in summary] == [
        ("setup", "failed", "post-processing"),
        ("deploy-upgrade", "recorded", None),
    ]
    assert not summary[0].reset_stack
    assert seen == [{"network-lab-deploy-upgrade": "env-1"}]
