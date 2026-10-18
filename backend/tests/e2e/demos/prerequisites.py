"""Check, before any setup, that the record command has what it needs (FR-012, contract "Prerequisites check")."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from styrmin_sdk.exceptions import StyrminError

from tests.e2e.demos import stack
from tests.e2e.demos.catalog import load_versions

if TYPE_CHECKING:
    from pathlib import Path

    from styrmin_sdk import StyrminClient

# Loaded by `uv run invoke start` (tasks/dev.py BUNDLED_DRIVERS).
REQUIRED_DRIVERS = ("infrahub", "semaphore")
CONNECT_TIMEOUT = 15.0
FFMPEG_MISSING = (
    "ffmpeg is not on the PATH. Install it (for example 'brew install ffmpeg' or 'apt install ffmpeg') "
    "and run the command again."
)


def stack_not_responding(api_url: str) -> str:
    return f"The demo stack does not respond at {api_url}. Run 'uv run invoke start' first."


def stack_missing(items: list[str]) -> str:
    listed = items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
    return f"The demo stack is missing {listed}. Run 'uv run invoke start' again."


async def check(
    api_url: str, credentials: tuple[str, str], versions_path: Path
) -> list[str]:
    """Run the contract's checks in its order and return the message of the first that fails, or no message.

    ``api_url`` is the Styrmin URL without ``/graphql``; ``credentials`` are the admin username and password.
    """
    if shutil.which("ffmpeg") is None:
        return [FFMPEG_MISSING]
    username, password = credentials
    try:
        client = await stack.connect(
            api_url, username, password, timeout=CONNECT_TIMEOUT
        )
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
