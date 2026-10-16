"""Check that ``scripts/e2e-pdb.sh`` stops a run without leaving a vcluster behind.

AGENTS.md ("Debugging E2E Tests") documents ``kill <pid>`` as the way to stop a
run that is paused in pdb. A stand-in ``uv`` on PATH runs real pytest and pdb on
a probe test whose session fixture records its teardown, which is where the E2E
fixtures delete the vcluster. The tests check the exit status, that teardown runs
after ``kill <pid>`` and after a SIGKILL to the wrapper, that no FIFO directory or
process from the run is left behind, that each run writes its own log, that
an unwritable log or a missing test path stops the wrapper before pytest starts,
and that at a terminal pdb takes typed commands and Ctrl-C does not end the run.
"""

from __future__ import annotations

import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "e2e-pdb.sh"
TIMEOUT = 30.0

pytestmark = pytest.mark.skipif(
    not (
        shutil.which("bash")
        and shutil.which("mkfifo")
        and Path("/proc/self/stat").exists()
    ),
    reason="needs bash, mkfifo and /proc",
)

# The session fixture stands in for the E2E vcluster fixture and records its teardown.
PROBE_TEST = """
import os, pytest

@pytest.fixture(scope="session")
def cluster():
    yield
    with open(os.environ["PROBE_MARK"], "a") as mark:
        mark.write("teardown\\n")

def test_probe(cluster):
    assert os.environ["PROBE_MODE"] == "pass"
"""

# Replaces `uv run pytest ...` with real pytest from this interpreter.
STAND_IN_UV = """#!/usr/bin/env bash
shift 2
exec {python} -m pytest "$@"
"""

# Makes the pty the controlling terminal of a new session, as a terminal emulator does.
LOGIN_TTY = (
    "import os, sys; os.login_tty(int(sys.argv[1])); "
    "os.execv(sys.argv[2], sys.argv[2:])"
)

Start = Callable[..., subprocess.Popen[bytes]]


def _session_members(sid: int) -> list[int]:
    """Return the PIDs of the live processes in session ``sid``."""
    pids = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        with suppress(OSError):
            state, _ppid, _pgrp, session = (
                stat.read_text().rsplit(")", 1)[1].split()[:4]
            )
            if state != "Z" and int(session) == sid:
                pids.append(int(stat.parent.name))
    return pids


def _wait_for(check: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + TIMEOUT
    while not check():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out after {TIMEOUT:.0f}s waiting for {what}")
        time.sleep(0.1)


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


@pytest.fixture
def start(tmp_path: Path) -> Iterator[Start]:
    """Start the wrapper in its own session; kill whatever is left of it on teardown."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(STAND_IN_UV.format(python=shlex.quote(sys.executable)))
    uv.chmod(0o755)
    (tmp_path / "tmp").mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_probe.py").write_text(PROBE_TEST)
    started: list[subprocess.Popen[bytes]] = []

    def _start(
        *args: str,
        mode: str = "fail",
        log: Path | None = tmp_path / "pdb.log",
        tty: int | None = None,
    ) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "TMPDIR": str(tmp_path / "tmp"),
            "E2E_PDB_LOG": str(log),
            "PROBE_MARK": str(tmp_path / "mark"),
            "PROBE_MODE": mode,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
        env.pop("PYTEST_ADDOPTS", None)
        if log is None:
            env.pop("E2E_PDB_LOG")
        argv = [str(SCRIPT), *args]
        if tty is not None:
            argv = [sys.executable, "-c", LOGIN_TTY, str(tty), *argv]
        with (tmp_path / "stderr").open("wb") as stderr:
            proc = subprocess.Popen(  # noqa: S603
                argv,
                cwd=tmp_path,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                start_new_session=True,
                pass_fds=() if tty is None else (tty,),
            )
        started.append(proc)
        return proc

    yield _start
    for proc in started:
        for pid in _session_members(proc.pid):
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _assert_run_cleaned_up(proc: subprocess.Popen[bytes], tmp_path: Path) -> None:
    assert _read(tmp_path / "mark") == "teardown\n"
    _wait_for(
        lambda: not _session_members(proc.pid), "every process of the run to exit"
    )
    assert not list((tmp_path / "tmp").glob("e2e-pdb.*"))


def _wait_for_pdb(tmp_path: Path) -> None:
    _wait_for(lambda: "(Pdb)" in _read(tmp_path / "pdb.log"), "pytest to pause in pdb")


def test_passing_test_exits_with_pytest_status(start: Start, tmp_path: Path) -> None:
    proc = start("test_probe.py", mode="pass")
    assert proc.wait(timeout=TIMEOUT) == 0
    assert "1 passed" in _read(tmp_path / "pdb.log")
    _assert_run_cleaned_up(proc, tmp_path)


def test_sigterm_ends_paused_run_with_teardown(start: Start, tmp_path: Path) -> None:
    proc = start("test_probe.py")
    _wait_for_pdb(tmp_path)
    first_line = _read(tmp_path / "stderr").splitlines()[0]
    assert first_line.startswith(f"e2e-pdb: pid={proc.pid} ")
    assert f"(stop with: kill {proc.pid})" in first_line
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=TIMEOUT) == 143
    last_line = _read(tmp_path / "stderr").splitlines()[-1]
    assert last_line == f"e2e-pdb: exit=143 log={tmp_path / 'pdb.log'}"
    # At the prompt only end of input is sent; a SIGINT there can go off during teardown.
    assert "KeyboardInterrupt" not in _read(tmp_path / "pdb.log")
    _assert_run_cleaned_up(proc, tmp_path)


def test_sigkill_to_wrapper_still_runs_teardown(start: Start, tmp_path: Path) -> None:
    proc = start("test_probe.py")
    _wait_for_pdb(tmp_path)
    proc.kill()
    assert proc.wait(timeout=TIMEOUT) == -signal.SIGKILL
    _wait_for(lambda: "teardown" in _read(tmp_path / "mark"), "the session teardown")
    _assert_run_cleaned_up(proc, tmp_path)


@pytest.mark.parametrize(
    "args", [(), ("--tb=long", "-k", "test_probe")], ids=["none", "options-only"]
)
def test_no_test_path_prints_usage(
    start: Start, tmp_path: Path, args: tuple[str, ...]
) -> None:
    proc = start(*args, mode="pass")
    assert proc.wait(timeout=TIMEOUT) == 2
    assert "usage: e2e-pdb.sh <test path or node id>" in _read(tmp_path / "stderr")
    assert not (tmp_path / "pdb.log").exists()
    assert not (tmp_path / "mark").exists()
    assert not list((tmp_path / "tmp").glob("e2e-pdb.*"))


def test_options_before_the_test_path(start: Start, tmp_path: Path) -> None:
    proc = start(
        "-k", "probe or other", "--tb=long", "test_probe.py::test_probe", mode="pass"
    )
    assert proc.wait(timeout=TIMEOUT) == 0
    assert "1 passed" in _read(tmp_path / "pdb.log")


def test_unwritable_log_stops_before_pytest(start: Start, tmp_path: Path) -> None:
    log = tmp_path / "missing" / "pdb.log"
    proc = start("test_probe.py", mode="pass", log=log)
    assert proc.wait(timeout=TIMEOUT) == 2
    assert f"cannot write the log file {log}" in _read(tmp_path / "stderr")
    assert not (tmp_path / "mark").exists()
    assert not list((tmp_path / "tmp").glob("e2e-pdb.*"))


def test_each_run_writes_its_own_log(start: Start, tmp_path: Path) -> None:
    logs = []
    for _ in range(2):
        proc = start("test_probe.py", mode="pass", log=None)
        assert proc.wait(timeout=TIMEOUT) == 0
        first_line, *_, last_line = _read(tmp_path / "stderr").splitlines()
        match = re.fullmatch(
            r"e2e-pdb: pid=\d+ log=(.+) \(stop with: kill \d+\)", first_line
        )
        assert match
        log = Path(match.group(1))
        assert log.parent == tmp_path / "tmp"
        assert log.read_text().startswith(f"{first_line}\n")
        assert "1 passed" in log.read_text()
        assert last_line == f"e2e-pdb: exit=0 log={log}"
        logs.append(log)
    assert logs[0] != logs[1]


def test_terminal_takes_pdb_commands_and_ctrl_c(start: Start, tmp_path: Path) -> None:
    master, slave = os.openpty()
    proc = start("test_probe.py", tty=slave)
    os.close(slave)
    out = b""

    def read_until(text: bytes) -> None:
        nonlocal out
        deadline = time.monotonic() + TIMEOUT
        while text not in out and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    out += os.read(master, 4096)
                except OSError:  # EIO once no process has the terminal open
                    break
        assert text in out

    read_until(b"(Pdb) ")
    os.write(master, b"\x03")
    read_until(b"--KeyboardInterrupt--")
    os.write(master, b"c\n")
    read_until(b"e2e-pdb: exit=1 ")
    assert proc.wait(timeout=TIMEOUT) == 1
    os.close(master)
    assert b"(stop with: Ctrl-C, then q at the pdb prompt)" in out
    assert "1 failed" in _read(tmp_path / "pdb.log").split("--KeyboardInterrupt--")[1]
    _assert_run_cleaned_up(proc, tmp_path)
