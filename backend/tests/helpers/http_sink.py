"""A local HTTP server that records the POST requests it receives (spec 020 telemetry tests)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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


@contextmanager
def serve_sink() -> Iterator[Sink]:
    """Serve on a free 127.0.0.1 port; the sink URL ends in ``/report``."""
    server = _SinkServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address[:2]
    server.sink = Sink(url=f"http://{host}:{port}/report")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.sink
    finally:
        server.shutdown()
        server.server_close()
