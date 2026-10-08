"""The telemetry envelope and sender (spec 020, FR-007, research D3, D8)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest
from styrminctl.telemetry import envelope as styrminctl_envelope

from styrmin_backend.services.telemetry.sender import (
    build_envelope,
    checksum,
    send_report,
)

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


@dataclass
class ReceivedRequest:
    method: str
    path: str
    content_type: str | None
    body: bytes


@dataclass
class Sink:
    url: str
    requests: list[ReceivedRequest] = field(default_factory=list)


class _SinkServer(ThreadingHTTPServer):
    sink: Sink


class _Handler(BaseHTTPRequestHandler):
    server: _SinkServer

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.server.sink.requests.append(
            ReceivedRequest(
                method="POST",
                path=self.path,
                content_type=self.headers.get("Content-Type"),
                body=self.rfile.read(length),
            )
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output quiet."""


@pytest.fixture
def sink() -> Iterator[Sink]:
    server = _SinkServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address[:2]
    server.sink = Sink(url=f"http://{host}:{port}/report")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.sink
    server.shutdown()
    server.server_close()


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
