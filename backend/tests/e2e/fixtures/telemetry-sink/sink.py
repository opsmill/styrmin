"""In-cluster sink for the daily telemetry report in E2E tests (spec 020, research D12).

POST /report stores the JSON body in memory, GET /reports lists the stored bodies,
GET /healthz answers 200. Standard library only.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_REPORTS: list[Any] = []
_LOCK = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def _answer(self, status: int, body: object | None = None) -> None:
        payload = json.dumps(body if body is not None else {}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path != "/report":
            self._answer(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            report = json.loads(self.rfile.read(length))
        except ValueError:
            self._answer(400, {"error": "body is not JSON"})
            return
        with _LOCK:
            _REPORTS.append(report)
            count = len(_REPORTS)
        print(f"stored report {count}", flush=True)
        self._answer(200)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._answer(200)
        elif self.path == "/reports":
            with _LOCK:
                reports = list(_REPORTS)
            self._answer(200, reports)
        else:
            self._answer(404)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the pod log to one line per stored report."""


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), _Handler).serve_forever()  # noqa: S104
