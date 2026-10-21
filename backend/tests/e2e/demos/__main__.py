"""Record the demos as MP4 videos: ``python -m tests.e2e.demos`` from ``backend/`` (contracts/record-command.md).

``uv run invoke record`` runs it and sets the environment variables it reads.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from playwright.async_api import async_playwright
from rich.console import Console
from rich.table import Table
from rich.text import Text

from tests.e2e.demos import ledger, prerequisites, semaphore_image, stack
from tests.e2e.demos.catalog import (
    DEMOS,
    SLUGS,
    VERSIONS_PATH,
    DemoContext,
    load_versions,
)
from tests.e2e.demos.encode import encode_video
from tests.e2e.demos.progress import report
from tests.e2e.demos.recorder import DemoRecorder, probe_duration
from tests.e2e.demos.video import RAW_NAME, VideoPlan, chapter_lines, plan_segments
from tests.e2e.pages.login import LoginPage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager

    from playwright.async_api import BrowserContext, Page
    from styrmin_sdk import StyrminClient

    from tests.e2e.demos.catalog import Demo, InfrahubVersions
    from tests.e2e.demos.stack import EnvironmentRecord

ENV_URL = "STYRMIN_DEMO_URL"
ENV_USERNAME = "STYRMIN_DEMO_USERNAME"
ENV_PASSWORD = "STYRMIN_DEMO_PASSWORD"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "demo-videos"
LONGEST_VIDEO_SECONDS = 180
EXIT_RECORDED = 0
EXIT_FAILED = 1
EXIT_PREREQUISITES = 2
# The shell's exit code for a command that SIGINT (Ctrl-C) stopped.
EXIT_INTERRUPTED = 130
PLAN_FILE = "plan.json"
CHAPTERS_SUFFIX = ".chapters.txt"
# The demo stack's names resolve to 127.0.0.1 (dev/guides/local-demo.md); mapping them in the browser
# keeps a public DNS timeout from failing a recording.
BROWSER_ARGS = ("--host-resolver-rules=MAP *.local.styrmin.io 127.0.0.1",)
MEMORY_NOTE = (
    "Kept environments still use the cluster's memory, which can make later demos fail. "
    "'uv run invoke record --delete-environments' deletes the environments of every demo."
)

type Phase = Literal["setup", "recording", "post-processing", "cleanup"]
type Status = Literal["recorded", "failed", "interrupted", "skipped"]

console = Console()


@dataclass(frozen=True)
class Settings:
    """The demo stack's Styrmin URL (without ``/graphql``) and its admin login."""

    styrmin_url: str
    username: str
    password: str = field(repr=False)

    @property
    def credentials(self) -> tuple[str, str]:
        return self.username, self.password


def read_settings(environ: Mapping[str, str]) -> Settings | None:
    values = [environ.get(name, "") for name in (ENV_URL, ENV_USERNAME, ENV_PASSWORD)]
    if not all(values):
        return None
    url, username, password = values
    return Settings(styrmin_url=url.rstrip("/"), username=username, password=password)


@dataclass(frozen=True)
class DemoResult:
    """One line of the summary (data-model "Demo result").

    ``kept_work_dir`` is the directory that holds the raw recording and its plan after a failed encoding.
    """

    slug: str
    status: Status
    video_path: Path | None = None
    video_seconds: float | None = None
    failed_step: str | None = None
    error: str | None = None
    kept_environments: tuple[str, ...] = ()
    kept_work_dir: Path | None = None


@asynccontextmanager
async def launch_browser(
    styrmin_url: str | None,
) -> AsyncIterator[tuple[BrowserContext, Page]]:
    """Yield a headless Chromium context with a 1920×1080 viewport and ``styrmin_url`` as ``base_url``."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=list(BROWSER_ARGS)
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}, base_url=styrmin_url
            )
            yield context, await context.new_page()
        finally:
            await browser.close()


async def log_in_to_styrmin(page: Page, username: str, password: str) -> None:
    login = LoginPage(page)
    await login.goto()
    await login.fill_username(username)
    await login.fill_password(password)
    await login.submit()
    await login.wait_for_redirect()


def ask_to_confirm(question: str) -> bool:
    """Ask ``question`` on the terminal and return whether the answer is yes; with no terminal, it is no."""
    if not sys.stdin.isatty():
        console.print("There is no terminal to ask on, so the answer is no.")
        return False
    try:
        answer = input(question)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


@dataclass(frozen=True)
class Runtime:
    """What a demo run uses to reach the demo stack, the browser and ffmpeg; unit tests replace parts of it."""

    check: Callable[..., Awaitable[list[str]]] = prerequisites.check
    check_tools: Callable[[], Awaitable[list[str]]] = prerequisites.check_tools
    build_image: Callable[..., None] = semaphore_image.build
    connect: Callable[[str, str, str], Awaitable[StyrminClient]] = stack.connect
    find_environments: Callable[
        [StyrminClient, Sequence[str]], Awaitable[list[EnvironmentRecord]]
    ] = stack.find_environments
    delete_environments: Callable[
        [StyrminClient, Sequence[EnvironmentRecord]], Awaitable[None]
    ] = stack.delete_environments
    open_browser: Callable[
        [str | None], AbstractAsyncContextManager[tuple[BrowserContext, Page]]
    ] = launch_browser
    log_in: Callable[[Page, str, str], Awaitable[None]] = log_in_to_styrmin
    new_recorder: Callable[[], DemoRecorder] = DemoRecorder
    encode: Callable[[BrowserContext, VideoPlan, Path], Awaitable[Path]] = encode_video
    probe: Callable[[Path], float] = probe_duration
    confirm: Callable[[str], bool] = ask_to_confirm
    versions_path: Path = VERSIONS_PATH
    # The file of the environments the command created; None means ledger.default_path().
    ledger_path: Path | None = None
    # Where the per-demo work directories go; None means the system's temporary directory.
    work_root: Path | None = None

    def created_environments(self, settings: Settings) -> ledger.CreatedEnvironments:
        return ledger.CreatedEnvironments(
            self.ledger_path or ledger.default_path(), settings.styrmin_url
        )


class DemoRun:
    """One run of one demo: leftovers, setup, recording, post-processing, cleanup (plan "Recorder flow")."""

    def __init__(
        self,
        demo: Demo[Any],
        settings: Settings,
        versions: InfrahubVersions,
        runtime: Runtime,
        created: ledger.CreatedEnvironments,
    ) -> None:
        self._demo = demo
        self._settings = settings
        self._versions = versions
        self._runtime = runtime
        self._created = created
        self._recorder = runtime.new_recorder()
        self._client: StyrminClient | None = None
        self._phase: Phase = "setup"
        self._work_dir: Path | None = None
        self._keep_work_dir = False
        # The result of a run that Ctrl-C stopped; ``execute`` then raises instead of returning it.
        self.interrupted: DemoResult | None = None

    async def execute(self, output_path: Path) -> DemoResult:
        try:
            seconds = await self._run(output_path)
        except asyncio.CancelledError:
            self.interrupted = await self._ended("interrupted", None)
            raise
        except Exception as error:  # noqa: BLE001 - one failed demo never stops the others (FR-011)
            return await self._ended("failed", error)
        finally:
            await self._close()
        return DemoResult(
            self._demo.slug, "recorded", video_path=output_path, video_seconds=seconds
        )

    async def _run(self, output_path: Path) -> float:
        demo, settings, runtime = self._demo, self._settings, self._runtime
        self._work_dir = work_dir = Path(
            tempfile.mkdtemp(prefix=f"styrmin-demo-{demo.slug}-", dir=runtime.work_root)
        )
        self._client = await runtime.connect(
            settings.styrmin_url, settings.username, settings.password
        )
        # A failed earlier run keeps its environments; delete them before the setup (FR-009).
        await self._delete_environments()
        async with runtime.open_browser(settings.styrmin_url) as (
            browser_context,
            page,
        ):
            await runtime.log_in(page, settings.username, settings.password)
            context = DemoContext(
                client=self._client,
                styrmin_url=settings.styrmin_url,
                browser_context=browser_context,
                page=page,
                recorder=self._recorder,
                versions=self._versions,
            )
            report(f"Setting up {demo.slug}")
            state = await demo.setup(context)
            await self._remember_environments()
            self._phase = "recording"
            await self._recorder.start(page, work_dir / RAW_NAME)
            await demo.record(context, state)
            self._phase = "post-processing"
            recording = await self._recorder.stop()
            await self._remember_environments()
            plan = VideoPlan(
                video_name=output_path.name,
                segments=tuple(
                    plan_segments(
                        recording.waits, recording.cuts, recording.raw_duration
                    )
                ),
                chapters=recording.chapters,
                closing=demo.closing_card(self._versions),
            )
            (work_dir / PLAN_FILE).write_text(plan.to_json(), encoding="utf-8")
            # The environments are deleted while ffmpeg encodes, so that the two do not add up in memory.
            cleanup = asyncio.create_task(self._delete_environments())
            self._keep_work_dir = True
            try:
                report(f"Encoding {display_path(output_path)}")
                video = await runtime.encode(browser_context, plan, work_dir)
                seconds = await asyncio.to_thread(runtime.probe, video)
                publish(video, output_path, chapter_lines(plan))
            except asyncio.CancelledError:
                cleanup.cancel()
                raise
            except BaseException:
                await _settle(cleanup)
                raise
            self._keep_work_dir = False
        self._phase = "cleanup"
        await cleanup
        return seconds

    async def _delete_environments(self) -> None:
        """Delete the demo's environments; refuse one that the command did not create."""
        client = self._require_client()
        found = await self._runtime.find_environments(
            client, self._demo.environment_names
        )
        if not found:
            return
        foreign = [
            environment for environment in found if environment.id not in self._created
        ]
        if foreign:
            raise stack.StackError(
                "The record command did not create these environments, so it does not delete them: "
                f"{', '.join(environment.name for environment in foreign)}. "
                "Delete or rename them in the Styrmin UI, or run the command again and confirm their deletion."
            )
        report(f"Deleting the environments of {self._demo.slug}")
        await self._runtime.delete_environments(client, found)
        self._created.forget(found)

    async def _remember_environments(self) -> None:
        # Before the setup, the run deleted every environment with the demo's names,
        # so the ones that exist now are the run's own.
        self._created.remember(
            await self._runtime.find_environments(
                self._require_client(), self._demo.environment_names
            )
        )

    def _require_client(self) -> StyrminClient:
        if self._client is None:
            raise RuntimeError("The demo run has no Styrmin client")
        return self._client

    def _failed_step(self) -> str:
        if self._phase == "recording":
            return self._recorder.current_step or "recording"
        return self._phase

    async def _ended(self, status: Status, error: Exception | None) -> DemoResult:
        step = self._failed_step()
        if error is None:
            console.print(
                Text(
                    f'Demo {self._demo.slug} interrupted in step "{step}"',
                    style="bold yellow",
                )
            )
        else:
            console.print(
                Text(
                    f'Demo {self._demo.slug} failed in step "{step}":', style="bold red"
                )
            )
            traceback.print_exception(error)
        return DemoResult(
            self._demo.slug,
            status,
            failed_step=step,
            error=describe(error) if error is not None else None,
            kept_environments=await self._kept_environments(),
            kept_work_dir=self._work_dir if self._keep_work_dir else None,
        )

    async def _kept_environments(self) -> tuple[str, ...]:
        if self._client is None:
            return ()
        try:
            found = await self._runtime.find_environments(
                self._client, self._demo.environment_names
            )
            self._created.remember(found)
        except Exception:  # noqa: BLE001 - the summary then names every environment the demo may have left
            return self._demo.environment_names
        return tuple(environment.name for environment in found)

    async def _close(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._work_dir is not None and not self._keep_work_dir:
            shutil.rmtree(self._work_dir, ignore_errors=True)


async def _settle(task: asyncio.Task[None]) -> None:
    """Wait for ``task`` and print its error; the caller already has an error to report."""
    try:
        await task
    except Exception as error:  # noqa: BLE001 - the summary lists the environments that remain
        console.print(
            Text(
                f"Deleting the environments failed too: {describe(error)}", style="red"
            )
        )


def publish(video: Path, output_path: Path, chapters: Sequence[str]) -> None:
    """Copy ``video`` to ``output_path`` and write its chapter file next to it.

    Each file is written under a temporary name in the output directory, then renamed, so the
    output directory never holds a part of a file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_whole(output_path, lambda partial: shutil.copyfile(video, partial))
    _write_whole(
        chapters_path(output_path),
        lambda partial: partial.write_text(
            "\n".join(chapters) + "\n", encoding="utf-8"
        ),
    )


def _write_whole(target: Path, write: Callable[[Path], object]) -> None:
    partial = target.with_name(f".{target.name}.partial")
    try:
        write(partial)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def chapters_path(video_path: Path) -> Path:
    """Return the chapter file of ``video_path``, for example ``1-deploy-upgrade.chapters.txt``."""
    return video_path.with_suffix(CHAPTERS_SUFFIX)


def describe(error: BaseException) -> str:
    """Return the error's type with the first and last lines of its message, for the summary."""
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    if not lines:
        return type(error).__name__
    message = lines[0] if len(lines) == 1 else f"{lines[0]} … {lines[-1]}"
    return f"{type(error).__name__}: {message}"


def display_path(path: Path) -> str:
    return (
        str(path.relative_to(REPOSITORY_ROOT))
        if path.is_relative_to(REPOSITORY_ROOT)
        else str(path)
    )


def format_length(seconds: float) -> str:
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes}:{rest:02d}"


def is_too_long(seconds: float) -> bool:
    return round(seconds) > LONGEST_VIDEO_SECONDS


def next_steps(result: DemoResult) -> list[str]:
    """Return what to do after a failed or interrupted demo, one line per action."""
    record_again = f"uv run invoke record --demo {result.slug}"
    steps: list[str] = []
    if result.kept_work_dir is not None:
        steps.append(
            f"next: encode the kept recording with 'uv run invoke record --encode-again {result.kept_work_dir}'"
        )
    if result.kept_environments:
        steps.append(
            "next: inspect the kept environments in the Styrmin UI, then delete them with "
            f"'uv run invoke record --delete-environments --demo {result.slug}'"
        )
    if result.kept_work_dir is None:
        steps.append(
            f"next: read the error above, then record the demo again with '{record_again}'"
            if result.status == "failed"
            else f"next: record the demo again with '{record_again}'"
        )
    return steps


def summary_row(result: DemoResult) -> tuple[str, str, str, str]:
    """Return the Demo, Result, Video and Length cells of the contract's summary."""
    if (
        result.status == "recorded"
        and result.video_path is not None
        and result.video_seconds is not None
    ):
        video = display_path(result.video_path)
        if is_too_long(result.video_seconds):
            video += f"\nwarning: longer than {format_length(LONGEST_VIDEO_SECONDS)}"
        return result.slug, result.status, video, format_length(result.video_seconds)
    if result.status in {"failed", "interrupted"}:
        lines = (
            [f'step "{result.failed_step}": {result.error}']
            if result.status == "failed"
            else [f'interrupted in step "{result.failed_step}"']
        )
        if result.kept_environments:
            lines.append(f"kept environments: {', '.join(result.kept_environments)}")
        if result.kept_work_dir is not None:
            lines.append(f"kept recording: {result.kept_work_dir}")
        lines += next_steps(result)
        return result.slug, result.status, "\n".join(lines), "-"
    return result.slug, result.status, "-", "-"


def print_summary(results: Sequence[DemoResult]) -> None:
    table = Table(box=None, pad_edge=False, header_style="bold")
    for column in ("Demo", "Result", "Video", "Length"):
        table.add_column(column, overflow="fold")
    for result in results:
        table.add_row(*(Text(cell) for cell in summary_row(result)))
    console.print()
    console.print(table)
    if any(result.kept_environments for result in results):
        console.print(MEMORY_NOTE, style="yellow")


def exit_code(results: Sequence[DemoResult]) -> int:
    return (
        EXIT_FAILED
        if any(result.status in {"failed", "interrupted"} for result in results)
        else EXIT_RECORDED
    )


def skipped(demos: Sequence[Demo[Any]]) -> list[DemoResult]:
    return [DemoResult(demo.slug, "skipped") for demo in demos]


def print_problems(problems: Sequence[str]) -> None:
    for problem in problems:
        console.print(Text(problem, style="bold red"))


async def confirm_environments(
    client: StyrminClient,
    demos: Sequence[Demo[Any]],
    runtime: Runtime,
    created: ledger.CreatedEnvironments,
) -> bool:
    """Return whether the command may delete every existing environment of ``demos``.

    An environment that the command did not create is deleted only after a yes on the terminal.
    """
    names = [name for demo in demos for name in demo.environment_names]
    foreign = [
        environment
        for environment in await runtime.find_environments(client, names)
        if environment.id not in created
    ]
    if not foreign:
        return True
    listed = ", ".join(
        f"{environment.name} (id {environment.id})" for environment in foreign
    )
    console.print(
        f"These environments exist on cluster {stack.CLUSTER_NAME!r}, and this command did not create "
        f"them: {listed}. The command deletes the environments that have a demo's names before it records "
        "the demo.",
        style="bold yellow",
    )
    if runtime.confirm("Delete them? [y/N] "):
        created.remember(foreign)
        return True
    console.print(
        "Stopped before any change. Delete or rename these environments in the Styrmin UI, "
        "or run the command again and answer y.",
        style="bold red",
    )
    return False


async def record_demos(
    demos: Sequence[Demo[Any]],
    settings: Settings,
    output_dir: Path,
    runtime: Runtime,
    *,
    rebuild_image: bool = False,
) -> int:
    """Check the prerequisites, run each demo in turn, print the summary and return the exit code.

    Ctrl-C prints the summary of the demos so far, then raises ``CancelledError``.
    """
    results: list[DemoResult] = []
    run: DemoRun | None = None
    try:
        status = await _prepare(demos, settings, runtime, rebuild_image=rebuild_image)
        if status is not None:
            print_summary(skipped(demos))
            return status
        versions = load_versions(runtime.versions_path)
        created = runtime.created_environments(settings)
        for demo in demos:
            console.rule(f"Demo {demo.number}: {demo.slug}")
            report(
                f"Demo {demo.number} usually takes about {demo.expected_minutes} min, setup and cleanup included"
            )
            run = DemoRun(demo, settings, versions, runtime, created)
            results.append(
                await run.execute(output_dir / f"{demo.number}-{demo.slug}.mp4")
            )
    except asyncio.CancelledError:
        if run is not None and run.interrupted is not None:
            results.append(run.interrupted)
        done = {result.slug for result in results}
        results += skipped([demo for demo in demos if demo.slug not in done])
        console.print("\nInterrupted (Ctrl-C).", style="bold yellow")
        print_summary(results)
        raise
    print_summary(results)
    return exit_code(results)


async def _prepare(
    demos: Sequence[Demo[Any]],
    settings: Settings,
    runtime: Runtime,
    *,
    rebuild_image: bool,
) -> int | None:
    """Check the prerequisites, build the demo Semaphore image and confirm the deletions; return an exit code
    when the run must stop."""
    needs_image = any(demo.uses_semaphore_image for demo in demos)
    problems = await runtime.check(
        settings.styrmin_url,
        settings.credentials,
        runtime.versions_path,
        needs_docker=needs_image,
    )
    if problems:
        print_problems(problems)
        return EXIT_PREREQUISITES
    if needs_image:
        report(
            f"Building {semaphore_image.IMAGE}; Docker reuses its cached layers when nothing changed"
        )
        try:
            await asyncio.to_thread(runtime.build_image, no_cache=rebuild_image)
        except semaphore_image.ImageBuildError as error:
            print_problems([str(error)])
            return EXIT_PREREQUISITES
    client = await runtime.connect(
        settings.styrmin_url, settings.username, settings.password
    )
    try:
        confirmed = await confirm_environments(
            client, demos, runtime, runtime.created_environments(settings)
        )
    except ValueError as error:
        print_problems([str(error)])
        return EXIT_PREREQUISITES
    finally:
        await client.close()
    return None if confirmed else EXIT_PREREQUISITES


async def delete_demo_environments(
    demos: Sequence[Demo[Any]], settings: Settings, runtime: Runtime
) -> int:
    """Delete the environments of ``demos`` and nothing else; return the exit code."""
    problems = await runtime.check(
        settings.styrmin_url,
        settings.credentials,
        runtime.versions_path,
        needs_docker=False,
    )
    if problems:
        print_problems(problems)
        return EXIT_PREREQUISITES
    created = runtime.created_environments(settings)
    client = await runtime.connect(
        settings.styrmin_url, settings.username, settings.password
    )
    try:
        if not await confirm_environments(client, demos, runtime, created):
            return EXIT_PREREQUISITES
        names = [name for demo in demos for name in demo.environment_names]
        found = await runtime.find_environments(client, names)
        if not found:
            console.print(f"No environment of these demos exists: {', '.join(names)}")
            return EXIT_RECORDED
        await runtime.delete_environments(client, found)
        created.forget(found)
    except Exception as error:  # noqa: BLE001 - the command reports the error and exits
        console.print(
            Text(
                f"Deleting the environments failed: {describe(error)}", style="bold red"
            )
        )
        return EXIT_FAILED
    finally:
        await client.close()
    console.print(f"Deleted: {', '.join(environment.name for environment in found)}")
    return EXIT_RECORDED


async def encode_again(work_dir: Path, output_dir: Path, runtime: Runtime) -> int:
    """Encode the raw recording that a failed post-processing kept in ``work_dir``; delete ``work_dir`` after."""
    try:
        plan = VideoPlan.from_json((work_dir / PLAN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print_problems([f"{work_dir} holds no recording to encode: {error}"])
        return EXIT_PREREQUISITES
    if not (work_dir / plan.raw_name).is_file():
        print_problems([f"{work_dir} has no {plan.raw_name}"])
        return EXIT_PREREQUISITES
    problems = await runtime.check_tools()
    if problems:
        print_problems(problems)
        return EXIT_PREREQUISITES
    slug = Path(plan.video_name).stem.partition("-")[2]
    output_path = output_dir / plan.video_name
    try:
        async with runtime.open_browser(None) as (browser_context, _page):
            report(f"Encoding {display_path(output_path)}")
            video = await runtime.encode(browser_context, plan, work_dir)
        seconds = await asyncio.to_thread(runtime.probe, video)
        publish(video, output_path, chapter_lines(plan))
    except Exception as error:  # noqa: BLE001 - the summary reports the error
        traceback.print_exception(error)
        result = DemoResult(
            slug,
            "failed",
            failed_step="post-processing",
            error=describe(error),
            kept_work_dir=work_dir,
        )
        print_summary([result])
        return EXIT_FAILED
    shutil.rmtree(work_dir, ignore_errors=True)
    print_summary(
        [DemoResult(slug, "recorded", video_path=output_path, video_seconds=seconds)]
    )
    return EXIT_RECORDED


def select_demos(
    slugs: Sequence[str], demos: Sequence[Demo[Any]]
) -> tuple[Demo[Any], ...]:
    """Return the demos named in ``slugs`` (each may hold several, separated by commas), in the catalog's
    order, or every demo when ``slugs`` names none; raise ``ValueError`` on an unknown slug."""
    wanted = [
        slug.strip() for value in slugs for slug in value.split(",") if slug.strip()
    ]
    if not wanted:
        return tuple(demos)
    unknown = [slug for slug in wanted if slug not in SLUGS]
    if unknown:
        raise ValueError(
            f"{', '.join(map(repr, unknown))} is not a demo. The demos are: {', '.join(SLUGS)}"
        )
    return tuple(demo for demo in demos if demo.slug in wanted)


@dataclass(frozen=True)
class Arguments:
    demos: tuple[Demo[Any], ...]
    output_dir: Path
    rebuild_image: bool
    delete_environments: bool
    encode_again: Path | None


def parse_arguments(
    argv: Sequence[str] | None, demos: Sequence[Demo[Any]]
) -> Arguments:
    """Return the parsed arguments; exit with code 2 on an unknown demo."""
    parser = argparse.ArgumentParser(
        prog="uv run invoke record",
        description="Record the Styrmin feature demos as MP4 videos.",
    )
    parser.add_argument(
        "--demo",
        action="append",
        default=[],
        metavar="SLUG",
        help=f"A demo to record: {', '.join(SLUGS)}. Repeat the option, or separate the slugs "
        "with commas, to record several. Default: all four demos.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the videos.",
    )
    parser.add_argument(
        "--rebuild-image",
        action="store_true",
        help=f"Build {semaphore_image.IMAGE} without Docker's build cache.",
    )
    only = parser.add_mutually_exclusive_group()
    only.add_argument(
        "--delete-environments",
        action="store_true",
        help="Only delete the environments of the selected demos, then exit.",
    )
    only.add_argument(
        "--encode-again",
        type=Path,
        metavar="DIR",
        help="Only encode the raw recording that a failed encoding kept in DIR, then exit.",
    )
    arguments = parser.parse_args(argv)
    try:
        selected = select_demos(arguments.demo, demos)
    except ValueError as error:
        parser.error(str(error))
    return Arguments(
        demos=selected,
        output_dir=arguments.output_dir,
        rebuild_image=arguments.rebuild_image,
        delete_environments=arguments.delete_environments,
        encode_again=arguments.encode_again,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runtime: Runtime | None = None,
    demos: Sequence[Demo[Any]] = DEMOS,
) -> int:
    arguments = parse_arguments(argv, demos)
    runtime = runtime or Runtime()
    output_dir = arguments.output_dir.resolve()
    try:
        if arguments.encode_again is not None:
            return asyncio.run(
                encode_again(arguments.encode_again.resolve(), output_dir, runtime)
            )
        settings = read_settings(os.environ if environ is None else environ)
        if settings is None:
            console.print(
                f"Set {ENV_URL}, {ENV_USERNAME} and {ENV_PASSWORD}, or run 'uv run invoke record', which sets them.",
                style="bold red",
            )
            return EXIT_PREREQUISITES
        if arguments.delete_environments:
            return asyncio.run(
                delete_demo_environments(arguments.demos, settings, runtime)
            )
        return asyncio.run(
            record_demos(
                arguments.demos,
                settings,
                output_dir,
                runtime,
                rebuild_image=arguments.rebuild_image,
            )
        )
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
