"""Shared client construction for styrminctl commands.

This module exposes two entry points:

* :func:`get_client` -- sync, returns a configured :class:`StyrminClient`.
  Signature is intentionally preserved (per critique E1 / plan section
  "Backwards-compatible ``get_client()``") so the existing command modules
  (``clusters``, ``environments``, ``drivers``, ``deployments``, ``backups``,
  ``backup_storage_locations``, ``tasks``) continue to compile and run with
  zero changes.

* :func:`get_auth_context` -- async, returns an :class:`AuthContext` carrying
  both the client and the credential rung that produced its token. Only the
  ``whoami`` command consumes the ``source`` field; everything else uses the
  sync ``get_client``.

Both helpers delegate to the same :class:`CredentialResolver` so the
precedence ladder lives in exactly one place.
"""

from __future__ import annotations

import asyncio
import os
import threading

from styrmin_sdk import StyrminClient

from styrminctl import config as _config
from styrminctl.auth import resolver as credential_resolver
from styrminctl.auth.token_store import TokenStore
from styrminctl.auth.types import AuthContext, TokenSource


def _build_client(token: str | None, *, timeout: float | None = None) -> StyrminClient:
    """Construct a :class:`StyrminClient` from settings + an optional token.

    ``_config.SETTINGS`` is read at call time (not module-load time) so tests
    that monkeypatch the attribute on the ``config`` module still see the
    override.

    ``timeout`` overrides the per-request HTTP timeout for this client only;
    ``None`` falls back to ``SETTINGS.timeout`` (the global default). Used by
    commands that want to fail fast on an unreachable server rather than
    waiting out the default budget.
    """
    return StyrminClient(
        server_address=_config.SETTINGS.server_address,
        timeout=timeout if timeout is not None else _config.SETTINGS.timeout,
        headers=_config.SETTINGS.additional_headers,
        token=token,
    )


async def _resolve_token() -> tuple[str | None, TokenSource]:
    """Run the credential resolver and return the resulting ``(token, source)``."""
    token_store = TokenStore()
    return await credential_resolver.resolve(_config.SETTINGS, os.environ, token_store)


def _resolve_token_sync() -> tuple[str | None, TokenSource]:
    """Run :func:`_resolve_token` from a synchronous context.

    ``get_client`` is sync (to preserve its existing signature) but is almost
    always called from inside a running asyncio loop (Cyclopts spins one up
    for each ``async def`` command). ``asyncio.run`` is forbidden there, so
    we delegate to a worker thread that owns its own short-lived event loop.
    """
    result: list[tuple[str | None, TokenSource]] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(_resolve_token()))
        except BaseException as exc:  # noqa: BLE001 -- re-raised on the caller thread
            error.append(exc)

    thread = threading.Thread(target=_runner, name="styrminctl-resolve", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def get_client(*, timeout: float | None = None) -> StyrminClient:
    """Create a configured :class:`StyrminClient` instance.

    Runs the credential resolver and returns the resulting authenticated
    client. Signature is sync so existing command modules can keep their
    ``async with client.get_client() as sdk:`` idiom without restructuring.

    ``timeout`` overrides the per-request HTTP timeout for the returned
    client only (``None`` uses ``SETTINGS.timeout``). Pass a small value to
    fail fast against an unreachable server.
    """
    token, _source = _resolve_token_sync()
    return _build_client(token, timeout=timeout)


async def get_auth_context() -> AuthContext:
    """Resolve credentials and return both the client and the rung.

    Used by ``whoami`` to render the ``Authenticated via: ...`` line. All
    other commands should keep using :func:`get_client` since they do not
    need to surface the source.
    """
    token, source = await _resolve_token()
    return AuthContext(client=_build_client(token), source=source)


def get_unauthenticated_client() -> StyrminClient:
    """Return a client with no ``Authorization`` header.

    Used by ``login`` itself, which intentionally bypasses the precedence
    ladder because its job is to *produce* a token rather than consume one.
    """
    return _build_client(None)
