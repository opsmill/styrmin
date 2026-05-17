"""Unit tests for :func:`styrminctl.auth.resolver.resolve`.

Covers all 9 rows of the decision table in
``specs/011-styrminctl-auth/contracts/credential-precedence.md`` plus the
"empty STYRMIN_TOKEN is treated as unset" edge case and the no-persist
invariant for the auto-login rung.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from styrminctl.auth import resolver as resolver_mod
from styrminctl.auth.resolver import resolve
from styrminctl.auth.token_store import TokenStore
from styrminctl.errors import AsymmetricEnvCredentialsError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


# -- Fixtures ---------------------------------------------------------------


@dataclass
class _StubSettings:
    server_address: str = "http://prod:8000"
    timeout: float = 30.0


@pytest.fixture
def settings() -> _StubSettings:
    return _StubSettings()


@pytest.fixture
def token_store_stub() -> MagicMock:
    """A stubbed :class:`TokenStore` with the canonicalise rule delegated."""
    stub = MagicMock(spec=TokenStore)
    # ``canonicalise`` is a staticmethod; reuse the real one so the resolver
    # exercises the actual rule rather than a fake passthrough.
    stub.canonicalise.side_effect = TokenStore.canonicalise
    stub.get.return_value = None
    return stub


@pytest.fixture
def mock_login(mocker: MockerFixture) -> AsyncMock:
    """Patch the SDK ``StyrminClient`` used by the auto-login rung."""
    fake_client = MagicMock()
    fake_client.auth = MagicMock()
    fake_client.auth.login = AsyncMock(return_value=MagicMock(token="tok-auto"))
    fake_client.close = AsyncMock()
    mocker.patch.object(resolver_mod, "StyrminClient", return_value=fake_client)
    return fake_client.auth.login


# -- Row 1: STYRMIN_TOKEN wins ---------------------------------------------


async def test_row_1_env_token_wins(settings: _StubSettings, token_store_stub: MagicMock) -> None:
    token, source = await resolve(settings, {"STYRMIN_TOKEN": "tok-env"}, token_store_stub)
    assert source == "env"
    assert token == "tok-env"
    token_store_stub.get.assert_not_called()


# -- Row 2: empty STYRMIN_TOKEN treated as unset; disk wins ----------------


async def test_row_2_empty_env_token_falls_through_to_disk(
    settings: _StubSettings, token_store_stub: MagicMock
) -> None:
    token_store_stub.get.return_value = "tok-disk"
    token, source = await resolve(settings, {"STYRMIN_TOKEN": ""}, token_store_stub)
    assert source == "file"
    assert token == "tok-disk"


# -- Row 3: unset env, disk has token --------------------------------------


async def test_row_3_disk_wins_when_env_token_absent(settings: _StubSettings, token_store_stub: MagicMock) -> None:
    token_store_stub.get.return_value = "tok-disk"
    token, source = await resolve(settings, {}, token_store_stub)
    assert source == "file"
    assert token == "tok-disk"


# -- Row 4: auto-login when both creds present, no disk token --------------


async def test_row_4_auto_login_when_both_env_creds_present(
    settings: _StubSettings,
    token_store_stub: MagicMock,
    mock_login: AsyncMock,
) -> None:
    token, source = await resolve(
        settings,
        {"STYRMIN_USERNAME": "alice", "STYRMIN_PASSWORD": "secret"},
        token_store_stub,
    )
    assert source == "auto-login"
    assert token == "tok-auto"
    mock_login.assert_awaited_once_with("alice", "secret")


# -- Row 5: env-var auto-login wins over disk token ------------------------


async def test_row_5_auto_login_wins_over_disk(
    settings: _StubSettings,
    token_store_stub: MagicMock,
    mock_login: AsyncMock,
) -> None:
    token_store_stub.get.return_value = "tok-disk"
    token, source = await resolve(
        settings,
        {"STYRMIN_USERNAME": "alice", "STYRMIN_PASSWORD": "secret"},
        token_store_stub,
    )
    assert source == "auto-login"
    assert token == "tok-auto"
    mock_login.assert_awaited_once_with("alice", "secret")
    # Disk token must NOT be consulted once the auto-login rung activates.
    token_store_stub.set.assert_not_called()


# -- Row 6: STYRMIN_TOKEN beats every other rung ---------------------------


async def test_row_6_env_token_beats_auto_login_and_disk(
    settings: _StubSettings,
    token_store_stub: MagicMock,
    mock_login: AsyncMock,
) -> None:
    token_store_stub.get.return_value = "tok-disk"
    token, source = await resolve(
        settings,
        {
            "STYRMIN_TOKEN": "tok-env",
            "STYRMIN_USERNAME": "alice",
            "STYRMIN_PASSWORD": "secret",
        },
        token_store_stub,
    )
    assert source == "env"
    assert token == "tok-env"
    mock_login.assert_not_called()


# -- Rows 7 / 8: asymmetric env vars are a hard error ---------------------


async def test_row_7_missing_password_raises(settings: _StubSettings, token_store_stub: MagicMock) -> None:
    with pytest.raises(AsymmetricEnvCredentialsError) as exc:
        await resolve(settings, {"STYRMIN_USERNAME": "alice"}, token_store_stub)
    assert exc.value.missing_variable == "STYRMIN_PASSWORD"


async def test_row_8_missing_username_raises(settings: _StubSettings, token_store_stub: MagicMock) -> None:
    with pytest.raises(AsymmetricEnvCredentialsError) as exc:
        await resolve(settings, {"STYRMIN_PASSWORD": "secret"}, token_store_stub)
    assert exc.value.missing_variable == "STYRMIN_USERNAME"


async def test_empty_string_password_treated_as_unset(settings: _StubSettings, token_store_stub: MagicMock) -> None:
    with pytest.raises(AsymmetricEnvCredentialsError) as exc:
        await resolve(
            settings,
            {"STYRMIN_USERNAME": "alice", "STYRMIN_PASSWORD": ""},
            token_store_stub,
        )
    assert exc.value.missing_variable == "STYRMIN_PASSWORD"


# -- Row 9: nothing → none -------------------------------------------------


async def test_row_9_returns_none_source_when_nothing_set(settings: _StubSettings, token_store_stub: MagicMock) -> None:
    token, source = await resolve(settings, {}, token_store_stub)
    assert source == "none"
    assert token is None


# -- Persistence invariant -------------------------------------------------


async def test_auto_login_does_not_persist_to_disk(
    settings: _StubSettings,
    token_store_stub: MagicMock,
    mock_login: AsyncMock,
) -> None:
    """Rung 3 must never call ``TokenStore.set``."""
    await resolve(
        settings,
        {"STYRMIN_USERNAME": "alice", "STYRMIN_PASSWORD": "secret"},
        token_store_stub,
    )
    token_store_stub.set.assert_not_called()


async def test_auto_login_closes_short_lived_client(
    settings: _StubSettings,
    token_store_stub: MagicMock,
    mocker: MockerFixture,
) -> None:
    """The in-process client used for rung 3 must be closed after login."""
    fake_client = MagicMock()
    fake_client.auth = MagicMock()
    fake_client.auth.login = AsyncMock(return_value=MagicMock(token="tok-auto"))
    fake_client.close = AsyncMock()
    mocker.patch.object(resolver_mod, "StyrminClient", return_value=fake_client)
    await resolve(
        settings,
        {"STYRMIN_USERNAME": "alice", "STYRMIN_PASSWORD": "secret"},
        token_store_stub,
    )
    fake_client.close.assert_awaited_once()
