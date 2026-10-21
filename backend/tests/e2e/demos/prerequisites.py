"""Check, before any setup, that the record command has what it needs (FR-012, contract "Prerequisites check")."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright
from styrmin_sdk.exceptions import StyrminAuthenticationError, StyrminError

from tests.e2e.demos import stack
from tests.e2e.demos.catalog import load_versions

if TYPE_CHECKING:
    from styrmin_sdk import StyrminClient

# Loaded by `uv run invoke start` (tasks/dev.py BUNDLED_DRIVERS).
REQUIRED_DRIVERS = ("infrahub", "semaphore")
CONNECT_TIMEOUT = 15.0
FFMPEG_MISSING = (
    "ffmpeg or ffprobe is not on the PATH. Install ffmpeg (for example 'brew install ffmpeg' or "
    "'apt install ffmpeg') and run the command again."
)
DOCKER_MISSING = (
    "docker is not on the PATH. The command builds the demo Semaphore image with it."
)


def chromium_missing(path: str) -> str:
    return (
        f"The Chromium build of the installed Playwright is missing ({path}). "
        "Run 'uv run playwright install chromium' and run the command again."
    )


def kube_context_unreachable(kube_context: str, reason: str) -> str:
    return (
        f"The kube context {kube_context!r} does not reach the demo stack ({reason}). "
        "Run 'uv run invoke start', which writes the context with 'vcluster connect'."
    )


def stack_not_responding(api_url: str) -> str:
    return f"The demo stack does not respond at {api_url}. Run 'uv run invoke start' first."


def login_rejected(api_url: str, username: str) -> str:
    return (
        f"The demo stack at {api_url} rejected the login of {username!r}. The command logs in with "
        "styrmin.adminUsername and styrmin.adminPassword from dev/local/demo-values.yaml; a demo stack keeps "
        "the password it was created with, so run 'uv run invoke reset' after a change to that file."
    )


def stack_missing(items: list[str]) -> str:
    listed = items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
    return f"The demo stack is missing {listed}. Run 'uv run invoke start' again."


async def chromium_path() -> Path:
    """Return where the installed Playwright expects its Chromium build."""
    async with async_playwright() as playwright:
        return Path(playwright.chromium.executable_path)


async def check_tools() -> list[str]:
    """Return the message of the first missing tool that encoding needs (ffmpeg, ffprobe, Chromium), or none."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return [FFMPEG_MISSING]
    chromium = await chromium_path()
    if not chromium.exists():
        return [chromium_missing(str(chromium))]
    return []


async def check(
    api_url: str,
    credentials: tuple[str, str],
    versions_path: Path,
    *,
    needs_docker: bool,
    kube_context: str = stack.KUBE_CONTEXT,
) -> list[str]:
    """Run the contract's checks in its order and return the message of the first that fails, or no message.

    ``api_url`` is the Styrmin URL without ``/graphql``; ``credentials`` are the admin username and password.
    ``needs_docker`` is true when a selected demo deploys the demo Semaphore image, which the command builds.
    """
    problems = await check_tools()
    if problems:
        return problems
    if needs_docker and shutil.which("docker") is None:
        return [DOCKER_MISSING]
    reason = await stack.check_kube_context(kube_context)
    if reason is not None:
        return [kube_context_unreachable(kube_context, reason)]
    username, password = credentials
    try:
        client = await stack.connect(
            api_url, username, password, timeout=CONNECT_TIMEOUT
        )
    except StyrminAuthenticationError:
        return [login_rejected(api_url, username)]
    except StyrminError, ValueError:
        # ValueError covers a body that is not JSON or not a GraphQL answer.
        return [stack_not_responding(api_url)]
    try:
        missing = await missing_items(client)
    except StyrminError, ValueError:
        return [stack_not_responding(api_url)]
    finally:
        await client.close()
    if missing:
        return [stack_missing(missing)]
    try:
        load_versions(versions_path)
    except ValueError as error:
        return [str(error)]
    return []


async def missing_items(client: StyrminClient) -> list[str]:
    """Return what the demos need from the demo stack and it does not have, in the contract's order."""
    drivers = {driver.name for driver in await client.drivers.list() if driver.versions}
    clusters = {cluster.name for cluster in await client.clusters.list()}
    locations = {
        location.name for location in await client.backup_storage_locations.list()
    }
    missing = [
        f"the {name!r} driver" for name in REQUIRED_DRIVERS if name not in drivers
    ]
    if stack.CLUSTER_NAME not in clusters:
        missing.append(f"the {stack.CLUSTER_NAME!r} cluster")
    if stack.BACKUP_STORAGE_LOCATION_NAME not in locations:
        missing.append(
            f"the {stack.BACKUP_STORAGE_LOCATION_NAME!r} backup storage location"
        )
    return missing
