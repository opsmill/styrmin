"""A local HTTP server that records the POST requests it receives (spec 020 telemetry tests)."""

from __future__ import annotations

import socket
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
    status: int
    answer: bool
    release: threading.Event


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
        if not self.server.answer:
            # Hold the connection open without a response until the server stops.
            self.server.release.wait()
            self.close_connection = True
            return
        self.send_response(self.server.status)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output quiet."""


@contextmanager
def serve_sink(status: int = 200, *, answer: bool = True) -> Iterator[Sink]:
    """Serve on a free 127.0.0.1 port; the sink URL ends in ``/report``.

    The server answers each POST with ``status``, or never answers when ``answer`` is False.
    """
    server = _SinkServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address[:2]
    server.sink = Sink(url=f"http://{host}:{port}/report")
    server.status = status
    server.answer = answer
    server.release = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.sink
    finally:
        server.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def refused_url() -> Iterator[str]:
    """Yield a ``/report`` URL on a 127.0.0.1 port that refuses connections.

    The port is bound but not listening, so no other process can take it during the test.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(("127.0.0.1", 0))
        host, port = reserved.getsockname()[:2]
        yield f"http://{host}:{port}/report"
