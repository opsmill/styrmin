"""CLI tests for ``styrminctl`` auth commands (login, logout, whoami).

The tests run the Cyclopts ``app`` callable directly (matching the project's
existing CLI test style — see ``cli/tests/test_clusters.py``) and mock the
:class:`StyrminClient` at the ``client._build_client`` /
``client.get_unauthenticated_client`` seam so no transport is constructed.

All output strings asserted here are LOCKED to the contracts under
``specs/011-styrminctl-auth/contracts/`` — change those before changing the
strings here.
"""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminAuthenticationError, StyrminTransportError
from styrminctl.cli import app

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


SERVER = "http://localhost:8000"


@pytest.fixture(autouse=True)
def _isolated_token_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``TokenStore`` at a per-test directory so nothing leaks."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    # Strip any inherited credential env vars so each test starts clean.
    for var in ("STYRMIN_TOKEN", "STYRMIN_USERNAME", "STYRMIN_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STYRMIN_ADDRESS", SERVER)
    # Re-evaluate ``SETTINGS`` with the new env so ``_server_address`` reflects it.
    from styrminctl import config as cfg

    monkeypatch.setattr(cfg, "SETTINGS", cfg.Settings())
    # Same for the ``auth`` and ``client`` modules' bindings.
    from styrminctl.commands import auth as auth_mod

    monkeypatch.setattr(auth_mod, "SETTINGS", cfg.SETTINGS)
    return tmp_path


def _token_file_path(tmp_path: Path) -> Path:
    return tmp_path / "xdg" / "styrminctl" / "token"


def _make_mock_client() -> MagicMock:
    """Return a ``StyrminClient`` test double that supports ``async with``."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.auth = MagicMock()
    return client


# ---------------------------------------------------------------------------
# T014 — login + logout
# ---------------------------------------------------------------------------


def test_login_prints_resolved_address(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    client = _make_mock_client()
    client.auth.login = AsyncMock(return_value=MagicMock(token="tok-1"))
    mocker.patch("styrminctl.client.get_unauthenticated_client", return_value=client)
    mocker.patch("getpass.getpass", return_value="pw")

    with pytest.raises(SystemExit) as exc:
        app(["login", "--username", "alice"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert f"Authenticating against {SERVER}" in out
    assert f"Logged in to {SERVER} as alice" in out


def test_login_persists_token_with_correct_permissions(mocker: MockerFixture, tmp_path: Path) -> None:
    client = _make_mock_client()
    client.auth.login = AsyncMock(return_value=MagicMock(token="tok-secret"))
    mocker.patch("styrminctl.client.get_unauthenticated_client", return_value=client)
    mocker.patch("getpass.getpass", return_value="pw")

    with pytest.raises(SystemExit) as exc:
        app(["login", "--username", "alice"])
    assert exc.value.code == 0

    token_path = _token_file_path(tmp_path)
    assert token_path.exists(), "token file should be created on the disk"
    file_mode = stat.S_IMODE(token_path.stat().st_mode)
    assert file_mode == 0o600, f"file mode should be 0o600, got {oct(file_mode)}"
    dir_mode = stat.S_IMODE(token_path.parent.stat().st_mode)
    assert dir_mode == 0o700, f"parent dir mode should be 0o700, got {oct(dir_mode)}"

    data = json.loads(token_path.read_text())
    assert data["schema_version"] == 1
    # Canonical key is the lowercased scheme+host (no trailing slash).
    assert data["tokens"][SERVER] == "tok-secret"


def test_login_handles_non_tty_stdin_with_friendly_error(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """Critique E5: an EOF from ``getpass`` becomes a single human line, not a traceback."""
    mocker.patch("getpass.getpass", side_effect=EOFError())

    with pytest.raises(SystemExit) as exc:
        app(["login", "--username", "alice"])
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "Cannot prompt for password" in err
    assert "STYRMIN_USERNAME + STYRMIN_PASSWORD" in err
    # Never a traceback.
    assert "Traceback" not in err


def test_logout_is_noop_without_prior_token(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # No mock needed for ``_build_client`` since no token => no backend call.
    build_spy = mocker.patch("styrminctl.client._build_client")

    with pytest.raises(SystemExit) as exc:
        app(["logout"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert f"Logged out of {SERVER}" in out
    # No token => no client constructed for the logout round-trip.
    build_spy.assert_not_called()
    # File never created (delete on a missing store is a no-op per the contract).
    assert not _token_file_path(tmp_path).exists()


def test_logout_swallows_backend_errors(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Seed a token entry by running login first.
    seed_client = _make_mock_client()
    seed_client.auth.login = AsyncMock(return_value=MagicMock(token="tok-1"))
    mocker.patch("styrminctl.client.get_unauthenticated_client", return_value=seed_client)
    mocker.patch("getpass.getpass", return_value="pw")
    with pytest.raises(SystemExit):
        app(["login", "--username", "alice"])

    # Now: backend logout raises but the local entry is still cleaned up.
    logout_client = _make_mock_client()
    logout_client.auth.logout = AsyncMock(side_effect=StyrminTransportError("network down"))
    mocker.patch("styrminctl.client._build_client", return_value=logout_client)

    with pytest.raises(SystemExit) as exc:
        app(["logout"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert f"Logged out of {SERVER}" in out

    data = json.loads(_token_file_path(tmp_path).read_text())
    assert SERVER not in data["tokens"], "local entry must be removed even when backend errors"


def test_password_never_logged_or_echoed(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = "super-secret-pw-7B3F"
    client = _make_mock_client()
    client.auth.login = AsyncMock(return_value=MagicMock(token="tok-1"))
    mocker.patch("styrminctl.client.get_unauthenticated_client", return_value=client)
    mocker.patch("getpass.getpass", return_value=sentinel)

    with caplog.at_level(logging.DEBUG), pytest.raises(SystemExit):
        app(["login", "--username", "alice"])

    captured = capsys.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err
    for record in caplog.records:
        assert sentinel not in record.getMessage(), f"password leaked into log record: {record}"


# ---------------------------------------------------------------------------
# T015 — whoami
# ---------------------------------------------------------------------------


def _patch_get_auth_context(
    mocker: MockerFixture,
    *,
    source: str,
    user: MagicMock | BaseException | None,
) -> MagicMock:
    """Install a mocked ``get_auth_context`` returning the given rung + user."""
    sdk = _make_mock_client()
    if isinstance(user, BaseException):
        sdk.auth.current_user = AsyncMock(side_effect=user)
    else:
        sdk.auth.current_user = AsyncMock(return_value=user)
    ctx = MagicMock()
    ctx.client = sdk
    ctx.source = source
    mocker.patch(
        "styrminctl.client.get_auth_context",
        new=AsyncMock(return_value=ctx),
    )
    return sdk


def _user(username: str = "alice", display_name: str = "Alice Example") -> MagicMock:
    user = MagicMock(spec=["username", "display_name"])
    user.username = username
    user.display_name = display_name
    return user


def test_whoami_source_line_env(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_get_auth_context(mocker, source="env", user=_user())

    with pytest.raises(SystemExit) as exc:
        app(["whoami"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "Username: alice" in out
    assert "Display name: Alice Example" in out
    assert "Authenticated via: env (STYRMIN_TOKEN)" in out


def test_whoami_source_line_file(mocker: MockerFixture, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    _patch_get_auth_context(mocker, source="file", user=_user())

    with pytest.raises(SystemExit) as exc:
        app(["whoami"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    expected_path = _token_file_path(tmp_path)
    assert f"Authenticated via: token file ({expected_path})" in out


def test_whoami_source_line_auto_login(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_get_auth_context(mocker, source="auto-login", user=_user())

    with pytest.raises(SystemExit) as exc:
        app(["whoami"])
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "Authenticated via: auto-login (STYRMIN_USERNAME)" in out


def test_whoami_friendly_error_when_unauthenticated(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_get_auth_context(mocker, source="none", user=None)

    with pytest.raises(SystemExit) as exc:
        app(["whoami"])
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert "Not logged in" in captured.err
    assert "Run `styrminctl login`" in captured.err
    assert "Traceback" not in captured.err


def test_whoami_friendly_error_on_stale_token(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Seed a real token entry so we can assert the disk file is NOT auto-deleted.
    seed_client = _make_mock_client()
    seed_client.auth.login = AsyncMock(return_value=MagicMock(token="tok-stale"))
    mocker.patch("styrminctl.client.get_unauthenticated_client", return_value=seed_client)
    mocker.patch("getpass.getpass", return_value="pw")
    with pytest.raises(SystemExit):
        app(["login", "--username", "alice"])
    token_path = _token_file_path(tmp_path)
    before = json.loads(token_path.read_text())
    assert before["tokens"][SERVER] == "tok-stale"

    # whoami sees a stale token -> backend raises ``StyrminAuthenticationError``.
    _patch_get_auth_context(
        mocker,
        source="file",
        user=StyrminAuthenticationError("token expired", "AuthenticationError"),
    )

    with pytest.raises(SystemExit) as exc:
        app(["whoami"])
    assert exc.value.code == 1

    err = capsys.readouterr().err
    assert "Not logged in" in err
    assert "Run `styrminctl login` to refresh." in err
    assert "Traceback" not in err

    # CRITICAL: the stale token must NOT be auto-deleted from disk
    # (contract: only ``logout`` removes entries).
    after = json.loads(token_path.read_text())
    assert after["tokens"][SERVER] == "tok-stale", "stale token must be preserved for debugging"
