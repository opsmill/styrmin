"""Credential resolver — the four-rung precedence ladder.

Implements the contract in
``specs/011-styrminctl-auth/contracts/credential-precedence.md``:

1. ``STYRMIN_TOKEN`` env-var (non-empty)             -> ``"env"``
2. Token-store entry for the canonical server URL    -> ``"file"``
3. ``STYRMIN_USERNAME`` + ``STYRMIN_PASSWORD``       -> ``"auto-login"`` (in-process)
4. Asymmetric env vars                                -> ``AsymmetricEnvCredentialsError``
5. None of the above                                  -> ``"none"``

The resolver never persists. Rung 3 performs exactly one in-process
``auth.login`` call against ``settings.server_address`` and returns the
freshly minted token; the caller MUST NOT save it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from styrmin_sdk import StyrminClient

from styrminctl.errors import AsymmetricEnvCredentialsError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from styrminctl.auth.token_store import TokenStore
    from styrminctl.auth.types import TokenSource


class _SettingsLike(Protocol):
    """Structural slice of :class:`styrminctl.config.Settings` we depend on."""

    server_address: str
    timeout: float


def _nonempty(env: Mapping[str, str], name: str) -> str | None:
    """Return the trimmed env value if set and non-empty, else ``None``."""
    value = env.get(name)
    if not value:
        return None
    return value


async def resolve(
    settings: _SettingsLike,
    env: Mapping[str, str],
    token_store: TokenStore,
) -> tuple[str | None, TokenSource]:
    """Resolve credentials per the four-rung ladder.

    See ``specs/011-styrminctl-auth/contracts/credential-precedence.md`` for
    the full decision table. Returns ``(token, source)`` where ``token`` is
    ``None`` only when ``source == "none"``.
    """
    # Rung 1: explicit STYRMIN_TOKEN wins.
    token_env = _nonempty(env, "STYRMIN_TOKEN")
    if token_env is not None:
        return token_env, "env"

    username = _nonempty(env, "STYRMIN_USERNAME")
    password = _nonempty(env, "STYRMIN_PASSWORD")

    # Rung 4: asymmetric env vars are a hard error, not a fall-through.
    if username is not None and password is None:
        raise AsymmetricEnvCredentialsError("STYRMIN_PASSWORD")
    if password is not None and username is None:
        raise AsymmetricEnvCredentialsError("STYRMIN_USERNAME")

    # Rung 3: env-var auto-login wins over the disk token (row 5 of the table).
    if username is not None and password is not None:
        token = await _auto_login(settings, username, password)
        return token, "auto-login"

    # Rung 2: token-store entry for the canonical URL.
    canonical = token_store.canonicalise(settings.server_address)
    disk_token = token_store.get(canonical)
    if disk_token is not None:
        return disk_token, "file"

    # Rung 5: nothing — only ``login`` and ``--help`` can succeed.
    return None, "none"


async def _auto_login(settings: _SettingsLike, username: str, password: str) -> str:
    """Perform the rung-3 in-process login and return the freshly minted token."""
    # Short-lived client; closed before we return so the per-invocation lifetime
    # is bounded and no transport stays open after the resolver returns.
    client = StyrminClient(server_address=settings.server_address, timeout=settings.timeout)
    try:
        login_result = await client.auth.login(username, password)
    finally:
        await client.close()
    return login_result.token
