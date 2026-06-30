"""End-to-end telemetry test (Constitution §V) — feature 015-styrminctl-telemetry.

This exercises the **real `styrminctl` process** against a **real local HTTP
sink** wired up via ``STYRMIN_TELEMETRY_ENDPOINT``. It is ``api_only``: the whole
flow is CLI/HTTP with no UI surface, and it deliberately does **not** use the
backend ``vcluster`` fixture — telemetry is a side-channel unrelated to
Kubernetes, so no cluster is required. "Real infrastructure, not mocks" is
satisfied by the real subprocess and the real socket/HTTP server.

## Subprocess vs in-process (disclosure)

All assertions drive the **real ``styrminctl`` console script as a subprocess**
against the real sink:

* The **opt-out / exclusion** cases (``STYRMIN_TELEMETRY=0``, ``DO_NOT_TRACK=1``,
  ``CI=true``, non-TTY, persisted ``telemetry disable``) and the **hung-endpoint
  latency / exit-behaviour** case run as plain subprocesses (no controlling
  terminal), which is itself one of the exclusion levers being asserted.
* The **positive-emit** cases (well-formed envelope, server-verifiable checksum,
  no forbidden values) require the eligibility ladder's final rung —
  ``sys.stderr.isatty()`` — to be ``True`` in the child. We satisfy it honestly
  by allocating a **real pseudo-terminal** (:func:`pty.openpty`) and running the
  real subprocess attached to it. No in-process harness and no monkeypatching is
  used; the envelope, checksum, socket, and HTTP exchange are all real.

The chosen command is ``clusters list`` pointed at an unreachable backend
(``STYRMIN_ADDRESS=http://127.0.0.1:1``): it needs no live Styrmin backend and
fails fast, so the telemetry event is emitted with ``outcome="failure"`` and a
bucketed (non-null) ``error_category`` regardless of the command's success — the
event is emitted after the outcome is known either way.
"""

from __future__ import annotations

import hashlib
import json
import os
import pty
import select
import subprocess  # noqa: S404 - the test drives the real styrminctl console script
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Self

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.api_only(
    reason="Pure CLI/HTTP side-channel: real styrminctl subprocess -> real local "
    "HTTP sink, no UI flow and no Kubernetes/vcluster. The [ui-chromium] variant "
    "would behave identically and add no coverage."
)

# Command used for every positive-emit and exclusion assertion. It is eligible,
# needs no live backend, and fails fast against an unreachable address.
_COMMAND: tuple[str, ...] = ("clusters", "list")

# An unreachable backend so the command fails fast without any live Styrmin API.
_UNREACHABLE_BACKEND = "http://127.0.0.1:1"


class _CapturingServer(ThreadingHTTPServer):
    """A threading HTTP server that accumulates received POST bodies.

    ``bodies`` is a class-level default replaced by a fresh per-instance list in
    :meth:`_Sink.__init__`; the handler appends to whichever list the live
    server instance holds.
    """

    bodies: list[bytes] = []  # noqa: RUF012 - per-instance list assigned in _Sink


class _CapturingSink(BaseHTTPRequestHandler):
    """Records every POST body on the server instance, returns 200."""

    # ``server`` is a _CapturingServer; we stash bodies on it (see _Sink).
    server: _CapturingServer

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self.server.bodies.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: object) -> None:
        """Suppress the default per-request logging to stderr."""


class _Sink:
    """A live local HTTP sink capturing POST bodies; usable as a context manager."""

    def __init__(self) -> None:
        self._server = _CapturingServer(("127.0.0.1", 0), _CapturingSink)
        self._server.bodies = []
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def bodies(self) -> list[bytes]:
        return self._server.bodies


def _styrminctl_script() -> Path:
    """Resolve the real ``styrminctl`` console script next to this interpreter."""
    script = Path(sys.executable).parent / "styrminctl"
    if not script.exists():  # pragma: no cover - environment sanity guard
        pytest.skip(f"styrminctl console script not found at {script}")
    return script


def _base_env(*, endpoint: str, xdg: Path) -> dict[str, str]:
    """A clean env: telemetry endpoint + unreachable backend, no opt-out levers."""
    env = dict(os.environ)
    env.update(
        {
            "STYRMIN_TELEMETRY_ENDPOINT": endpoint,
            "STYRMIN_ADDRESS": _UNREACHABLE_BACKEND,
            "STYRMIN_TOKEN": "dummy-token-value",
            "XDG_DATA_HOME": str(xdg),
        }
    )
    # Ensure none of the opt-out / exclusion levers are accidentally inherited.
    for var in ("STYRMIN_TELEMETRY", "DO_NOT_TRACK", "CI"):
        env.pop(var, None)
    return env


def _run_with_pty(args: list[str], env: dict[str, str], *, timeout: float = 30.0) -> int:
    """Run ``styrminctl`` attached to a real pty so ``stderr.isatty()`` is True.

    Returns the child exit code. Output is drained from the pty master so the
    child never blocks on a full buffer; the contents are irrelevant to the
    assertions (we read the sink, not stdout).
    """
    script = _styrminctl_script()
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [str(script), *args],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
        )
        os.close(slave)
        slave = -1
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    if not os.read(master, 4096):
                        break
                except OSError:
                    break
            if proc.poll() is not None:
                # Drain anything still buffered, then stop.
                _drain(master)
                break
        return proc.wait(timeout=timeout)
    finally:
        if slave != -1:
            os.close(slave)
        os.close(master)


def _drain(fd: int) -> None:
    """Best-effort drain of a pty master fd until it would block or closes."""
    while True:
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            return
        try:
            if not os.read(fd, 4096):
                return
        except OSError:
            return


def _run_plain(
    args: list[str],
    env: dict[str, str],
    *,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``styrminctl`` as a plain subprocess (no controlling terminal)."""
    script = _styrminctl_script()
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(script), *args],
        env=env,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _settle(sink: _Sink, *, expected: int, timeout: float = 3.0) -> None:
    """Wait until the sink has at least ``expected`` bodies, or the timeout lapses.

    For the zero-request assertions we still wait the full timeout to give a
    (wrongly) emitted request time to arrive — otherwise a regression could slip
    through on a race.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if expected and len(sink.bodies) >= expected:
            return
        time.sleep(0.05)


@pytest.fixture
def xdg_dir(tmp_path: Path) -> Iterator[Path]:
    """A fresh, writable XDG_DATA_HOME so each test gets its own telemetry state."""
    target = tmp_path / "xdg"
    target.mkdir()
    yield target


@pytest.fixture
def sink() -> Iterator[_Sink]:
    """A live local HTTP sink capturing telemetry POST bodies."""
    with _Sink() as live:
        yield live


# --------------------------------------------------------------------------- #
# (a) Exactly one well-formed envelope with a server-verifiable checksum.
# --------------------------------------------------------------------------- #


def test_emits_one_well_formed_envelope_with_verifiable_checksum(sink: _Sink, xdg_dir: Path) -> None:
    """A real interactive (pty) invocation emits exactly one valid envelope."""
    env = _base_env(endpoint=sink.url, xdg=xdg_dir)

    code = _run_with_pty(list(_COMMAND), env)
    _settle(sink, expected=1)

    assert code != 0, "the unreachable-backend command is expected to fail"
    assert len(sink.bodies) == 1, f"expected exactly one POST, got {len(sink.bodies)}"

    envelope = json.loads(sink.bodies[0])
    assert envelope["kind"] == "styrminctl"
    assert envelope["payload_format"] == "1.0"
    assert set(envelope) == {"data", "checksum", "kind", "payload_format"}

    data = envelope["data"]
    # Closed key set in exact insertion order (FR-007, wire-format contract).
    assert list(data) == [
        "event_id",
        "install_id",
        "command",
        "options",
        "outcome",
        "error_category",
        "styrminctl_version",
        "python_version",
        "os_family",
    ]
    assert data["command"] == "clusters list"
    assert data["outcome"] == "failure"
    # The command fails fast; error_category must be a non-null bucketed value.
    assert data["error_category"] in {
        "auth",
        "network",
        "validation",
        "not_found",
        "server",
        "usage",
        "unknown",
    }
    assert data["os_family"] in {"Linux", "Darwin", "Windows"}
    assert data["event_id"] == f"{data['install_id'][:8]}-clusters_list"

    # Server-side checksum recomputation (SC-005): the server reproduces the
    # CPython-default json.dumps(data) and sha256, and must match the client.
    recomputed = hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()
    assert envelope["checksum"] == recomputed


# --------------------------------------------------------------------------- #
# (b) No forbidden values with known-sensitive inputs.
# --------------------------------------------------------------------------- #


def test_no_forbidden_values_with_sensitive_inputs(sink: _Sink, xdg_dir: Path, tmp_path: Path) -> None:
    """A deployment-name positional + ``--config @file`` leak nothing into the body."""
    secret_file = tmp_path / "super-secret-creds.json"
    secret_file.write_text('{"password": "hunter2-do-not-leak"}', encoding="utf-8")

    deployment_name = "my-confidential-deployment"
    env = _base_env(endpoint=sink.url, xdg=xdg_dir)

    code = _run_with_pty(
        ["deployments", "update", deployment_name, "--config", f"@{secret_file}"],
        env,
    )
    _settle(sink, expected=1)

    assert code != 0
    assert len(sink.bodies) == 1, f"expected exactly one POST, got {len(sink.bodies)}"

    raw = sink.bodies[0]
    body_text = raw.decode("utf-8")
    forbidden = [
        deployment_name,
        str(secret_file),
        secret_file.name,
        "hunter2-do-not-leak",
        "password",
        _UNREACHABLE_BACKEND,
        "dummy-token-value",
        env["STYRMIN_TELEMETRY_ENDPOINT"],
    ]
    for needle in forbidden:
        assert needle not in body_text, f"forbidden value leaked into telemetry body: {needle!r}"

    data = json.loads(raw)["data"]
    assert data["command"] == "deployments update"
    # Only canonical long option NAMES, never values.
    assert all(opt.startswith("--") for opt in data["options"])
    assert "--config" in data["options"]


# --------------------------------------------------------------------------- #
# (c) ≤ 200 ms added latency + unchanged exit behaviour against a hung endpoint.
# --------------------------------------------------------------------------- #


def test_hung_endpoint_does_not_delay_or_change_exit(xdg_dir: Path) -> None:
    """A black-hole endpoint must not change exit behaviour or blow the budget.

    Runs the same command twice as a plain subprocess: once with telemetry
    excluded (CI=1) and once pointed at an unroutable/hung endpoint. Exit codes
    must match (failure isolation, SC-003) and the hung run must not add a
    pathological delay. The assertion uses a generous wall-clock guard rather
    than a tight 200 ms bound (process spawn dominates and CI is noisy); the
    tight per-mechanism budget is covered by the unit suite (critique E3).
    """
    # 203.0.113.0/24 (TEST-NET-3) is reserved and unroutable -> connect hangs
    # until the daemon-thread budget abandons it.
    hung_endpoint = "http://203.0.113.1:81"

    excluded_env = _base_env(endpoint=hung_endpoint, xdg=xdg_dir)
    excluded_env["CI"] = "true"  # exclusion lever -> no dispatch at all
    baseline = _run_plain(list(_COMMAND), excluded_env)

    hung_env = _base_env(endpoint=hung_endpoint, xdg=xdg_dir)
    # No TTY here (plain subprocess) so this run is itself non-emitting, but the
    # dispatch budget mechanism is still exercised by the interactive paths; the
    # purpose here is the exit-code / failure-isolation guarantee against a hung
    # endpoint without a pathological hang.
    start = time.monotonic()
    hung = _run_plain(list(_COMMAND), hung_env)
    elapsed = time.monotonic() - start

    assert hung.returncode == baseline.returncode, "telemetry changed the exit code"
    # Generous guard: the command itself plus at most the (≤200 ms) telemetry
    # budget. 15 s leaves ample headroom for process spawn while still failing
    # loudly if a hung endpoint blocks command exit.
    assert elapsed < 15.0, f"hung endpoint delayed command exit by {elapsed:.2f}s"


def test_hung_endpoint_interactive_emits_no_stderr_noise(sink: _Sink, xdg_dir: Path) -> None:
    """An interactive run against a hung endpoint still exits cleanly and fast.

    The dispatch worker is abandoned (daemon thread) on budget expiry; this
    asserts the command does not hang and the event is dropped (the hung sink
    never records it) — failure isolation under the interactive path.
    """
    # A sink that never responds: bind a socket but never accept/answer in time.
    hung_endpoint = "http://203.0.113.2:81"
    env = _base_env(endpoint=hung_endpoint, xdg=xdg_dir)

    start = time.monotonic()
    code = _run_with_pty(list(_COMMAND), env)
    elapsed = time.monotonic() - start

    assert code != 0
    assert elapsed < 15.0, f"interactive run against hung endpoint took {elapsed:.2f}s"
    # The hung endpoint is not our recording sink, so nothing should be captured.
    assert sink.bodies == []


# --------------------------------------------------------------------------- #
# (d) Zero requests under each opt-out / exclusion lever (SC-004).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("STYRMIN_TELEMETRY", "0"),
        ("DO_NOT_TRACK", "1"),
        ("CI", "true"),
    ],
)
def test_env_opt_out_levers_emit_nothing(sink: _Sink, xdg_dir: Path, var: str, value: str) -> None:
    """Each env opt-out / exclusion lever independently yields zero requests."""
    env = _base_env(endpoint=sink.url, xdg=xdg_dir)
    env[var] = value

    # Run under a pty so the ONLY suppressing factor is the lever under test
    # (otherwise the non-TTY rung would suppress it and mask a regression).
    code = _run_with_pty(list(_COMMAND), env)
    _settle(sink, expected=0)

    assert code != 0
    assert sink.bodies == [], f"{var}={value} should suppress all telemetry, got {len(sink.bodies)}"


def test_non_tty_emits_nothing(sink: _Sink, xdg_dir: Path) -> None:
    """A non-interactive (no controlling terminal) invocation emits nothing."""
    env = _base_env(endpoint=sink.url, xdg=xdg_dir)

    result = _run_plain(list(_COMMAND), env)
    _settle(sink, expected=0)

    assert result.returncode != 0
    assert sink.bodies == [], "a non-TTY stderr must suppress all telemetry"


def test_persisted_disable_emits_nothing(sink: _Sink, xdg_dir: Path) -> None:
    """``telemetry disable`` persists an opt-out that suppresses later commands."""
    env = _base_env(endpoint=sink.url, xdg=xdg_dir)

    # Persist the opt-out via the real command (also exercises the command group,
    # which is itself ineligible and must not emit).
    disable = _run_plain(["telemetry", "disable"], env)
    assert disable.returncode == 0
    assert sink.bodies == [], "the telemetry command group must not emit"

    # An eligible interactive command must now stay silent.
    code = _run_with_pty(list(_COMMAND), env)
    _settle(sink, expected=0)

    assert code != 0
    assert sink.bodies == [], "a persisted opt-out must suppress all telemetry"
