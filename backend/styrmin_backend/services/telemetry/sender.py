"""Envelope and sender of the daily telemetry report (spec 020, FR-007 to FR-009, research D3, D8)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Final

import httpx

ENVELOPE_KIND: Final[str] = "styrmin"
PAYLOAD_FORMAT: Final[str] = "1.0"
SEND_TIMEOUT_SECONDS = 10

TelemetryLogger = logging.Logger | logging.LoggerAdapter[logging.Logger]


def checksum(data: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of ``json.dumps(data)``, as ``styrminctl`` computes it."""
    return hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()


def build_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap the report data in the ``styrminctl`` envelope with ``kind: "styrmin"``."""
    return {
        "data": data,
        "checksum": checksum(data),
        "kind": ENVELOPE_KIND,
        "payload_format": PAYLOAD_FORMAT,
    }


async def send_report(
    data: dict[str, Any], endpoint: str, logger: TelemetryLogger
) -> bool:
    """Post the report once. Return True on a 2xx answer; log any failure at debug level and never raise."""
    envelope = build_envelope(data)
    try:
        # The asyncio deadline bounds DNS, connect, write and read together.
        async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
                response = await client.post(endpoint, json=envelope)
    except Exception as error:  # noqa: BLE001
        # Not only httpx.HTTPError, TimeoutError and OSError: httpx.InvalidURL and the
        # ExceptionGroup of an out-of-range port are send failures too (FR-008).
        logger.debug("Telemetry report not sent: %s", type(error).__name__)
        return False
    if not response.is_success:
        logger.debug("Telemetry report not sent: HTTP %s", response.status_code)
        return False
    return True
