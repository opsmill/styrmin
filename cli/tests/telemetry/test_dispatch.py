"""Unit tests for best-effort, bounded telemetry dispatch (T010 / FR-001-FR-004).

Covers the four critical guarantees of :func:`styrminctl.telemetry.dispatch.dispatch`:

* **Latency cap (FR-003, critique E3)** -- against a hung endpoint the call returns
  within the injected budget. Asserted via the *mechanism* (a tiny injected
  ``budget_ms`` returns promptly even though the worker never finishes) plus a
  generous wall-clock guard, never a tight ``< 200 ms`` assertion that flakes on CI.
* **Failure isolation (FR-004)** -- a refused connection / 4xx / 5xx / arbitrary
  client error is swallowed and never raises out of ``dispatch``.
* **No stderr noise (critique E2, SC-003)** -- tearing the process down with an
  in-flight (hung) dispatch yields **zero stderr bytes** (no
  ``Exception ignored in thread ...`` from the daemon worker at teardown).
* **At most one POST** -- a single eligible dispatch performs exactly one POST.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - used only to spawn a trusted, fixed-argv child interpreter
import sys
import threading
import time
from typing import Self

from styrminctl.telemetry.dispatch import dispatch

_ENVELOPE: dict[str, object] = {
    "data": {"event_id": "abc-go", "command": "go"},
    "checksum": "deadbeef",
    "kind": "styrminctl",
    "payload_format": "1.0",
}
_ENDPOINT = "http://localhost:1/styrminctl"


class _RecordingClient:
    """Minimal stand-in for ``httpx.Client`` recording POSTs."""

    def __init__(
        self,
        posts: list[tuple[str, dict[str, object]]],
        *,
        raise_on_post: BaseException | None = None,
    ) -> None:
        self._posts = posts
        self._raise = raise_on_post

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def post(self, url: str, **kwargs: object) -> object:
        self._posts.append((url, kwargs))
        if self._raise is not None:
            raise self._raise
        return object()


def test_single_post_on_success() -> None:
    posts: list[tuple[str, dict[str, object]]] = []
    dispatch(
        _ENVELOPE,
        _ENDPOINT,
        budget_ms=1000,
        client_factory=lambda: _RecordingClient(posts),
    )
    assert len(posts) == 1
    url, kwargs = posts[0]
    assert url == _ENDPOINT
    # The envelope must be sent as the JSON body, by value.
    assert kwargs.get("json") == _ENVELOPE


def test_refused_connection_is_swallowed() -> None:
    posts: list[tuple[str, dict[str, object]]] = []
    # Must not raise.
    dispatch(
        _ENVELOPE,
        _ENDPOINT,
        budget_ms=1000,
        client_factory=lambda: _RecordingClient(posts, raise_on_post=ConnectionRefusedError("refused")),
    )
    assert len(posts) == 1  # one attempt, no retry


def test_http_error_status_is_swallowed() -> None:
    # A 4xx/5xx surfaces (if the impl calls raise_for_status) as an exception from
    # the client; dispatch must swallow whatever the client raises.
    posts: list[tuple[str, dict[str, object]]] = []
    dispatch(
        _ENVELOPE,
        _ENDPOINT,
        budget_ms=1000,
        client_factory=lambda: _RecordingClient(posts, raise_on_post=RuntimeError("500 Server Error")),
    )
    assert len(posts) == 1


def test_hung_endpoint_returns_within_budget() -> None:
    """A worker that never completes must not block the caller past the budget.

    Mechanism assertion: with a tiny injected budget the call returns promptly
    even though the POST blocks forever. The wall-clock guard is generous (2 s)
    so CI scheduling jitter cannot flake it.
    """
    release = threading.Event()

    class _HungClient:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def post(self, _url: str, **_kwargs: object) -> object:
            release.wait()  # block until the test tears down
            return object()

    start = time.monotonic()
    dispatch(_ENVELOPE, _ENDPOINT, budget_ms=20, client_factory=_HungClient)
    elapsed = time.monotonic() - start
    # Generous guard: we only assert the bound was *enforced*, not its exact value.
    assert elapsed < 2.0
    release.set()  # let the abandoned daemon worker unwind cleanly


def test_no_stderr_noise_when_process_exits_with_inflight_dispatch() -> None:
    """Tearing down the interpreter with a hung dispatch emits zero stderr bytes.

    The daemon worker's top-level catch-all must absorb any teardown error so
    Python never prints ``Exception ignored in thread ...`` (protects SC-003).
    """
    program = (
        "import sys\n"
        "from styrminctl.telemetry.dispatch import dispatch\n"
        "class C:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *a):\n"
        "        return False\n"
        "    def post(self, url, **kw):\n"
        "        import time\n"
        "        time.sleep(60)\n"
        "        return object()\n"
        "dispatch({'data': {}}, 'http://localhost:1/x', budget_ms=20, client_factory=C)\n"
        "print('done', flush=True)\n"
        "sys.exit(0)\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no untrusted input
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.stdout.strip() == "done"
    # The whole point: a hung daemon thread at interpreter teardown prints nothing.
    assert result.stderr == ""  # noqa: PLC1901 - assert byte-exact emptiness, not falsiness
    assert result.returncode == 0
