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

from tests.e2e.demos import prerequisites, stack
from tests.e2e.demos.catalog import (
    DEMOS,
    SLUGS,
    VERSIONS_PATH,
    DemoContext,
    load_versions,
)
from tests.e2e.demos.encode import encode_video
from tests.e2e.demos.recorder import DemoRecorder, probe_duration
from tests.e2e.demos.video import plan_segments
from tests.e2e.pages.login import LoginPage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager

    from playwright.async_api import BrowserContext, Page
    from styrmin_sdk import StyrminClient

    from tests.e2e.demos.catalog import Demo, InfrahubVersions
    from tests.e2e.demos.video import Segment

ENV_URL = "STYRMIN_DEMO_URL"
ENV_USERNAME = "STYRMIN_DEMO_USERNAME"
ENV_PASSWORD = "STYRMIN_DEMO_PASSWORD"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "demo-videos"
LONGEST_VIDEO_SECONDS = 180
EXIT_RECORDED = 0
EXIT_FAILED = 1
EXIT_PREREQUISITES = 2
# The demo stack's names resolve to 127.0.0.1 (dev/guides/local-demo.md); mapping them in the browser
# keeps a public DNS timeout from failing a recording.
BROWSER_ARGS = ("--host-resolver-rules=MAP *.local.styrmin.io 127.0.0.1",)
MEMORY_NOTE = (
    "Kept environments still use the cluster's memory until the next run of their demo deletes them, "
    "which can make later demos of the same run fail."
)

type Phase = Literal["setup", "recording", "post-processing", "cleanup"]
type Status = Literal["recorded", "failed", "skipped"]

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
    """One line of the summary (data-model "Demo result")."""

    slug: str
    status: Status
    video_path: Path | None = None
    video_seconds: float | None = None
    failed_step: str | None = None
    error: str | None = None
    kept_environments: tuple[str, ...] = ()


@asynccontextmanager
async def launch_browser(
    styrmin_url: str,
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


@dataclass(frozen=True)
class Runtime:
    """What a demo run uses to reach the demo stack, the browser and ffmpeg; unit tests replace parts of it."""

    check: Callable[[str, tuple[str, str], Path], Awaitable[list[str]]] = (
        prerequisites.check
    )
    connect: Callable[[str, str, str], Awaitable[StyrminClient]] = stack.connect
    delete_environments: Callable[[StyrminClient, Sequence[str]], Awaitable[None]] = (
        stack.delete_environments
    )
    existing_environments: Callable[
        [StyrminClient, Sequence[str]], Awaitable[list[str]]
    ] = stack.existing_environments
    open_browser: Callable[
        [str], AbstractAsyncContextManager[tuple[BrowserContext, Page]]
    ] = launch_browser
    log_in: Callable[[Page, str, str], Awaitable[None]] = log_in_to_styrmin
    new_recorder: Callable[[], DemoRecorder] = DemoRecorder
    encode: Callable[
        [BrowserContext, Path, Sequence[Segment], Path, Path], Awaitable[None]
    ] = encode_video
    probe: Callable[[Path], float] = probe_duration
    versions_path: Path = VERSIONS_PATH
    # Where the per-demo temporary directories go; None means the system's temporary directory.
    work_root: Path | None = None


class DemoRun:
    """One run of one demo: leftovers, setup, recording, post-processing, cleanup (plan "Recorder flow")."""

    def __init__(
        self,
        demo: Demo[Any],
        settings: Settings,
        versions: InfrahubVersions,
        runtime: Runtime,
    ) -> None:
        self._demo = demo
        self._settings = settings
        self._versions = versions
        self._runtime = runtime
        self._recorder = runtime.new_recorder()
        self._client: StyrminClient | None = None
        self._phase: Phase = "setup"

    async def execute(self, output_path: Path) -> DemoResult:
        try:
            seconds = await self._record(output_path)
            self._phase = "cleanup"
            console.print(
                f"Deleting the environments of {self._demo.slug}", style="dim"
            )
            await self._runtime.delete_environments(
                self._require_client(), self._demo.environment_names
            )
        except Exception as error:  # noqa: BLE001 - one failed demo never stops the others (FR-011)
            return await self._failed(error)
        finally:
            if self._client is not None:
                await self._client.close()
        return DemoResult(
            self._demo.slug, "recorded", video_path=output_path, video_seconds=seconds
        )

    async def _record(self, output_path: Path) -> float:
        demo, settings, runtime = self._demo, self._settings, self._runtime
        with tempfile.TemporaryDirectory(
            prefix=f"styrmin-demo-{demo.slug}-", dir=runtime.work_root
        ) as work:
            work_dir = Path(work)
            self._client = await runtime.connect(
                settings.styrmin_url, settings.username, settings.password
            )
            # A failed earlier run keeps its environments; delete them before the setup (FR-009).
            await runtime.delete_environments(self._client, demo.environment_names)
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
                console.print(f"Setting up {demo.slug}", style="dim")
                state = await demo.setup(context)
                self._phase = "recording"
                raw_path = work_dir / "raw.webm"
                await self._recorder.start(page, raw_path)
                await demo.record(context, state)
                self._phase = "post-processing"
                waits, cuts, raw_duration = await self._recorder.stop()
                staged = work_dir / output_path.name
                console.print(f"Encoding {display_path(output_path)}", style="dim")
                await runtime.encode(
                    browser_context,
                    raw_path,
                    plan_segments(waits, cuts, raw_duration),
                    staged,
                    work_dir,
                )
            seconds = await asyncio.to_thread(runtime.probe, staged)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(staged, output_path)
        return seconds

    def _require_client(self) -> StyrminClient:
        if self._client is None:
            raise RuntimeError("The demo run has no Styrmin client")
        return self._client

    def _failed_step(self) -> str:
        if self._phase == "recording":
            return self._recorder.current_step or "recording"
        return self._phase

    async def _failed(self, error: Exception) -> DemoResult:
        step = self._failed_step()
        console.print(
            Text(f'Demo {self._demo.slug} failed in step "{step}":', style="bold red")
        )
        traceback.print_exception(error)
        return DemoResult(
            self._demo.slug,
            "failed",
            failed_step=step,
            error=describe(error),
            kept_environments=await self._kept_environments(),
        )

    async def _kept_environments(self) -> tuple[str, ...]:
        if self._client is None:
            return ()
        try:
            return tuple(
                await self._runtime.existing_environments(
                    self._client, self._demo.environment_names
                )
            )
        except Exception:  # noqa: BLE001 - the summary then names every environment the demo may have left
            return self._demo.environment_names


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
    if result.status == "failed":
        video = f'step "{result.failed_step}": {result.error}'
        if result.kept_environments:
            video += f"\nkept environments: {', '.join(result.kept_environments)}"
        return result.slug, result.status, video, "-"
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
        if any(result.status == "failed" for result in results)
        else EXIT_RECORDED
    )


async def record_demos(
    demos: Sequence[Demo[Any]], settings: Settings, output_dir: Path, runtime: Runtime
) -> int:
    """Check the prerequisites, run each demo in turn, print the summary and return the exit code."""
    problems = await runtime.check(
        settings.styrmin_url, settings.credentials, runtime.versions_path
    )
    if problems:
        for problem in problems:
            console.print(Text(problem, style="bold red"))
        print_summary([DemoResult(demo.slug, "skipped") for demo in demos])
        return EXIT_PREREQUISITES
    versions = load_versions(runtime.versions_path)
    results: list[DemoResult] = []
    for demo in demos:
        console.rule(f"Demo {demo.number}: {demo.slug}")
        run = DemoRun(demo, settings, versions, runtime)
        results.append(await run.execute(output_dir / f"{demo.number}-{demo.slug}.mp4"))
    print_summary(results)
    return exit_code(results)


def select_demos(slug: str, demos: Sequence[Demo[Any]]) -> tuple[Demo[Any], ...]:
    """Return the demo named ``slug``, or every demo when ``slug`` is empty; raise ``ValueError`` otherwise."""
    if not slug:
        return tuple(demos)
    by_slug = {demo.slug: demo for demo in demos}
    if slug in by_slug:
        return (by_slug[slug],)
    raise ValueError(f"{slug!r} is not a demo. The demos are: {', '.join(SLUGS)}")


def parse_arguments(
    argv: Sequence[str] | None, demos: Sequence[Demo[Any]]
) -> tuple[tuple[Demo[Any], ...], Path]:
    """Return the selected demos and the output directory; exit with code 2 on an unknown demo."""
    parser = argparse.ArgumentParser(
        prog="uv run invoke record",
        description="Record the Styrmin feature demos as MP4 videos.",
    )
    parser.add_argument(
        "--demo",
        default="",
        help=f"The one demo to record: {', '.join(SLUGS)}. Default: all four demos.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the videos.",
    )
    arguments = parser.parse_args(argv)
    try:
        selected = select_demos(arguments.demo, demos)
    except ValueError as error:
        parser.error(str(error))
    return selected, arguments.output_dir


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runtime: Runtime | None = None,
    demos: Sequence[Demo[Any]] = DEMOS,
) -> int:
    selected, output_dir = parse_arguments(argv, demos)
    settings = read_settings(os.environ if environ is None else environ)
    if settings is None:
        console.print(
            f"Set {ENV_URL}, {ENV_USERNAME} and {ENV_PASSWORD}, or run 'uv run invoke record', which sets them.",
            style="bold red",
        )
        return EXIT_PREREQUISITES
    return asyncio.run(
        record_demos(selected, settings, output_dir.resolve(), runtime or Runtime())
    )


if __name__ == "__main__":
    sys.exit(main())
