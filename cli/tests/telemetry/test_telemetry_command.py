"""CLI tests for the ``telemetry enable | disable | status`` command group (T020, US2).

Runs the Cyclopts ``app`` callable directly (matching ``cli/tests/commands/
test_auth_commands.py``). Output strings are LOCKED to
``specs/015-styrminctl-telemetry/contracts/cli-telemetry-command.md``.

All commands persist via :class:`TelemetryStore`, isolated per test through a
tmp ``XDG_DATA_HOME``. The unwritable-dir tests assert best-effort behaviour:
``enable`` / ``disable`` / ``status`` still exit ``0`` (FR-016, FR-017).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from styrminctl.cli import app
from styrminctl.telemetry.store import TelemetryStore


@pytest.fixture(autouse=True)
def _isolated_telemetry_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``TelemetryStore`` at a per-test XDG dir and strip env opt-outs."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    for var in ("STYRMIN_TELEMETRY", "DO_NOT_TRACK"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _telemetry_path(tmp_path: Path) -> Path:
    return tmp_path / "xdg" / "styrminctl" / "telemetry.json"


def _run(*tokens: str) -> int:
    """Invoke the app and return the exit code (Cyclopts always raises SystemExit)."""
    with pytest.raises(SystemExit) as exc:
        app(list(tokens))
    code = exc.value.code
    return 0 if code is None else int(code)


# -- disable -> status shows disabled-with-reason ---------------------------


def test_disable_then_status_shows_disabled_with_reason(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert _run("telemetry", "disable") == 0
    assert "Telemetry disabled." in capsys.readouterr().out

    assert _run("telemetry", "status") == 0
    out = capsys.readouterr().out
    assert "Telemetry: disabled (persisted opt-out via 'telemetry disable')." in out

    # The flag really landed on disk as enabled=false.
    assert TelemetryStore(path=_telemetry_path(tmp_path)).is_enabled() is False


# -- enable persists --------------------------------------------------------


def test_enable_persists_enabled_true(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    # Start disabled, then enable.
    assert _run("telemetry", "disable") == 0
    capsys.readouterr()
    assert _run("telemetry", "enable") == 0
    assert "Telemetry enabled." in capsys.readouterr().out

    assert TelemetryStore(path=_telemetry_path(tmp_path)).is_enabled() is True

    assert _run("telemetry", "status") == 0
    out = capsys.readouterr().out
    assert "Telemetry: enabled (default; interactive terminal)." in out


# -- set/read round-trip via the store -------------------------------------


def test_set_read_round_trip(tmp_path: Path) -> None:
    assert _run("telemetry", "disable") == 0
    assert TelemetryStore(path=_telemetry_path(tmp_path)).is_enabled() is False
    assert _run("telemetry", "enable") == 0
    assert TelemetryStore(path=_telemetry_path(tmp_path)).is_enabled() is True
    # install_id is stable across the enable/disable round-trip.
    store = TelemetryStore(path=_telemetry_path(tmp_path))
    first_id = store.install_id()
    assert _run("telemetry", "disable") == 0
    assert TelemetryStore(path=_telemetry_path(tmp_path)).install_id() == first_id


# -- status reason precedence: env beats persisted --------------------------


def test_status_reason_env_beats_persisted(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    # Persist enabled=true, then assert each env lever overrides it in status.
    assert _run("telemetry", "enable") == 0
    capsys.readouterr()

    monkeypatch.setenv("STYRMIN_TELEMETRY", "0")
    assert _run("telemetry", "status") == 0
    assert "Telemetry: disabled (STYRMIN_TELEMETRY=0)." in capsys.readouterr().out
    monkeypatch.delenv("STYRMIN_TELEMETRY")

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert _run("telemetry", "status") == 0
    assert "Telemetry: disabled (DO_NOT_TRACK=1)." in capsys.readouterr().out


# -- best-effort under an unwritable telemetry directory --------------------


def test_commands_succeed_under_unwritable_dir(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enable/disable/status must all exit 0 even when persistence is impossible."""
    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o500)  # read+execute only -> child dir cannot be created
    monkeypatch.setenv("XDG_DATA_HOME", str(blocked))
    try:
        assert _run("telemetry", "disable") == 0
        assert "Telemetry disabled." in capsys.readouterr().out

        assert _run("telemetry", "enable") == 0
        assert "Telemetry enabled." in capsys.readouterr().out

        assert _run("telemetry", "status") == 0
        out = capsys.readouterr().out
        # Persistence failed, so the disable never stuck -> default-on state.
        assert out.startswith("Telemetry: enabled (")
        # Never a traceback.
        assert "Traceback" not in out
        # The file was never created under the unwritable dir.
        assert not (blocked / "styrminctl" / "telemetry.json").exists()
    finally:
        blocked.chmod(0o700)
