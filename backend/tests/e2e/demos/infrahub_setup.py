"""Load the device schema and the devices into a demo's Infrahub, and wait for it to answer (research R-008)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import yaml
from infrahub_sdk import Config, InfrahubClient

if TYPE_CHECKING:
    from collections.abc import Sequence

SCHEMA_PATH = Path(__file__).parent / "infrahub" / "schema.yml"
DEVICE_KIND = "InfraDevice"
# Both Infrahub charts the drivers use (4.33.2 and 4.19.2) preset this admin token
# as INFRAHUB_INITIAL_ADMIN_TOKEN. Never print it.
INFRAHUB_TOKEN = "06438eb2-8019-4776-878c-0941b1f1d1ec"  # noqa: S105
POLL_INTERVAL = 3.0


class InfrahubSetupError(RuntimeError):
    """Infrahub refused the schema or did not answer in time."""


def client(url: str) -> InfrahubClient:
    """Return an Infrahub SDK client for ``url`` that authenticates with the preset admin token."""
    return InfrahubClient(config=Config(address=url, api_token=INFRAHUB_TOKEN))


async def load_devices(url: str, names: Sequence[str]) -> None:
    """Load the device schema into the Infrahub at ``url``, then create one device per name."""
    infrahub = client(url)
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    response = await infrahub.schema.load(schemas=[schema], wait_until_converged=True)
    if response.errors:
        raise InfrahubSetupError(
            f"Infrahub at {url} refused the schema {SCHEMA_PATH.name}: {response.errors}"
        )
    for name in names:
        device = await infrahub.create(kind=DEVICE_KIND, name=name)
        await device.save()


async def wait_until_ready(url: str, timeout: float) -> None:
    """Wait until the Infrahub at ``url`` answers ``GET /api/schema/summary`` with 200."""
    deadline = time.monotonic() + timeout
    last = "no answer"
    async with httpx.AsyncClient(timeout=10.0) as http:
        while time.monotonic() < deadline:
            try:
                response = await http.get(f"{url}/api/schema/summary")
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                if response.status_code == httpx.codes.OK:
                    return
                last = f"HTTP {response.status_code}"
            await asyncio.sleep(POLL_INTERVAL)
    raise InfrahubSetupError(
        f"Infrahub at {url} did not answer within {timeout:.0f} s (last answer: {last})"
    )
