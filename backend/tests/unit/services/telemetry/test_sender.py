"""The telemetry envelope and sender (spec 020, FR-007, research D3, D8)."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from styrminctl.telemetry import envelope as styrminctl_envelope

from styrmin_backend.services.telemetry import sender
from styrmin_backend.services.telemetry.sender import (
    build_envelope,
    checksum,
    send_report,
)
from tests.helpers.http_sink import Sink, refused_url, serve_sink

# Fixed values in FR-006 order; the digest is computed, not copied (wire-format contract).
FIXED_DATA = {
    "install_id": "0b6f4f0e-6d0e-4a55-9a51-2f8c3f7c9f0d",
    "styrmin_version": "0.1.48",
    "python_version": "3.14.0",
    "os_family": "Linux",
    "arch": "x86_64",
    "cluster_count": 1,
    "environment_count": 3,
    "deployment_count": 5,
    "drivers": [
        {
            "name": "infrahub",
            "version": "1.2.0",
            "source_type": "git",
            "deployment_count": 2,
        },
        {
            "name": "semaphore",
            "version": "0.4.1",
            "source_type": "local",
            "deployment_count": 0,
        },
        {
            "name": "styrmin-ingress-controller",
            "version": "0.3.0",
            "source_type": "local",
            "deployment_count": 3,
        },
    ],
}


# FR-009 allows 10 seconds; the failure tests require a much faster answer.
FAILURE_TIME_LIMIT_SECONDS = 2
UNRESOLVABLE_HOST = "telemetry.invalid"


@pytest.fixture
def sink() -> Iterator[Sink]:
    with serve_sink() as running:
        yield running


def test_checksum_matches_styrminctl() -> None:
    assert checksum(FIXED_DATA) == styrminctl_envelope.checksum(FIXED_DATA)


def test_envelope_keys_and_constants() -> None:
    envelope = build_envelope(FIXED_DATA)

    assert list(envelope) == ["data", "checksum", "kind", "payload_format"]
    assert envelope["data"] is FIXED_DATA
    assert envelope["checksum"] == checksum(FIXED_DATA)
    assert envelope["kind"] == "styrmin"
    assert envelope["payload_format"] == "1.0"


async def test_send_report_posts_the_envelope_and_returns_true_on_200(
    sink: Sink,
) -> None:
    logger = MagicMock()

    assert await send_report(FIXED_DATA, sink.url, logger) is True

    (request,) = sink.requests
    assert request.method == "POST"
    assert request.path == "/report"
    assert request.content_type == "application/json"
    body = json.loads(request.body)
    assert list(body) == ["data", "checksum", "kind", "payload_format"]
    assert body["kind"] == "styrmin"
    assert body["payload_format"] == "1.0"
    assert body["data"] == FIXED_DATA
    assert body["checksum"] == styrminctl_envelope.checksum(body["data"])
    logger.debug.assert_not_called()


async def _timed_send(endpoint: str, logger: MagicMock) -> tuple[bool, float]:
    started = time.monotonic()
    sent = await send_report(FIXED_DATA, endpoint, logger)
    return sent, time.monotonic() - started


def _log_methods(logger: MagicMock) -> list[str]:
    """Return the logger methods called, in order (``debug``, ``warning`` and so on)."""
    return [name for name, _args, _kwargs in logger.method_calls]


async def test_send_report_returns_false_when_the_connection_is_refused() -> None:
    logger = MagicMock()

    with refused_url() as url:
        sent, elapsed = await _timed_send(url, logger)

    assert sent is False
    assert elapsed < FAILURE_TIME_LIMIT_SECONDS
    assert _log_methods(logger) == ["debug"]


async def test_send_report_returns_false_when_the_host_name_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail the lookup locally, as the resolver does for .invalid (RFC 6761), with no DNS query.
    real_getaddrinfo = socket.getaddrinfo
    looked_up: list[str] = []

    def getaddrinfo(host: str | bytes | None, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else host
        if name == UNRESOLVABLE_HOST:
            looked_up.append(name)
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    logger = MagicMock()

    sent, elapsed = await _timed_send(f"http://{UNRESOLVABLE_HOST}/report", logger)

    assert sent is False
    assert elapsed < FAILURE_TIME_LIMIT_SECONDS
    assert looked_up == [UNRESOLVABLE_HOST]
    assert _log_methods(logger) == ["debug"]


@pytest.mark.parametrize("status", [404, 503])
async def test_send_report_returns_false_on_an_error_status(status: int) -> None:
    logger = MagicMock()

    with serve_sink(status) as error_sink:
        sent, elapsed = await _timed_send(error_sink.url, logger)

    assert sent is False
    assert elapsed < FAILURE_TIME_LIMIT_SECONDS
    assert len(error_sink.requests) == 1
    assert _log_methods(logger) == ["debug"]
    assert status in logger.debug.call_args.args


async def test_send_report_stops_when_the_endpoint_never_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sender, "SEND_TIMEOUT_SECONDS", 1)
    logger = MagicMock()

    with serve_sink(answer=False) as silent_sink:
        sent, elapsed = await _timed_send(silent_sink.url, logger)

    assert sent is False
    assert 0.9 <= elapsed < FAILURE_TIME_LIMIT_SECONDS
    assert len(silent_sink.requests) == 1
    assert _log_methods(logger) == ["debug"]


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param("http://[::1/report", id="invalid-url"),
        pytest.param("http://127.0.0.1:70000/report", id="port-out-of-range"),
    ],
)
async def test_send_report_returns_false_for_a_malformed_endpoint(
    endpoint: str,
) -> None:
    logger = MagicMock()

    sent, elapsed = await _timed_send(endpoint, logger)

    assert sent is False
    assert elapsed < FAILURE_TIME_LIMIT_SECONDS
    assert _log_methods(logger) == ["debug"]
