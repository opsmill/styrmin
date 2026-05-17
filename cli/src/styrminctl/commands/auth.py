"""Authentication commands: ``login``, ``logout``, ``whoami``.

Wire-level contracts:

* ``specs/011-styrminctl-auth/contracts/login.md``
* ``specs/011-styrminctl-auth/contracts/logout.md``
* ``specs/011-styrminctl-auth/contracts/whoami.md``

The output wording, exit codes, and error lines below are LOCKED to those
contracts. Read those files before editing strings in this module.
"""

from __future__ import annotations

import getpass
import sys
from typing import Annotated

from cyclopts import App, Parameter
from styrmin_sdk.exceptions import StyrminAuthenticationError, StyrminError

from styrminctl import client as client_module
from styrminctl.auth.token_store import TokenStore
from styrminctl.config import SETTINGS
from styrminctl.errors import TokenStoreError

auth_app = App(name="auth", help="Authentication commands (login, logout, whoami).")


def _server_address() -> str:
    """Return the current ``STYRMIN_ADDRESS`` so all output lines stay in sync."""
    return SETTINGS.server_address


def _prompt_password() -> str:
    """Read a password from stdin without echoing.

    Renders the contract's friendly non-TTY message instead of a traceback
    when ``getpass`` raises ``EOFError`` (critique E5 / quickstart).
    """
    try:
        return getpass.getpass("Password: ")
    except EOFError as exc:
        # Single-line friendly error, no traceback. Exit non-zero.
        print(
            "Cannot prompt for password: stdin is not a terminal. "
            "Use STYRMIN_USERNAME + STYRMIN_PASSWORD for non-interactive auth.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _prompt_username() -> str:
    """Read a username from stdin (visible)."""
    try:
        return input("Username: ").strip()
    except EOFError as exc:
        print(
            "Cannot prompt for username: stdin is not a terminal. "
            "Use STYRMIN_USERNAME + STYRMIN_PASSWORD for non-interactive auth.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


@auth_app.command
async def login(
    *,
    username: Annotated[str | None, Parameter(name=["--username", "-u"], help="Username to log in as.")] = None,
) -> None:
    """Authenticate against the Styrmin backend and persist the resulting token.

    Bypasses the precedence ladder used by ``get_client`` -- its job is to
    *produce* a token, not consume one.
    """
    server = _server_address()
    resolved_username = username or _prompt_username()
    password = _prompt_password()

    # Echo the address BEFORE the round-trip so a wrong target can be aborted.
    print(f"Authenticating against {server} …")

    unauthenticated = client_module.get_unauthenticated_client()
    try:
        async with unauthenticated as sdk:
            try:
                result = await sdk.auth.login(resolved_username, password)
            except StyrminAuthenticationError:
                print("Login failed: invalid username or password.", file=sys.stderr)
                raise SystemExit(1) from None
            except StyrminError as exc:
                print(
                    f"Login failed: could not reach {server} ({type(exc).__name__}).",
                    file=sys.stderr,
                )
                raise SystemExit(1) from exc
    except StyrminError as exc:
        # Catches transport-layer errors raised on ``__aexit__`` close.
        print(
            f"Login failed: could not reach {server} ({type(exc).__name__}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    token_store = TokenStore()
    canonical = token_store.canonicalise(server)
    try:
        token_store.set(canonical, result.token)
    except TokenStoreError as exc:
        # Server-side login succeeded but we could not persist locally.
        print(
            f"Logged in to {server} as {resolved_username}, but could not save token: {exc.reason}.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print(f"Logged in to {server} as {resolved_username}")


@auth_app.command
async def logout() -> None:
    """Best-effort end of the server-side session and removal of the local entry."""
    server = _server_address()
    token_store = TokenStore()
    try:
        canonical = token_store.canonicalise(server)
        token = token_store.get(canonical)
    except TokenStoreError as exc:
        print(f"Could not update token store: {exc.reason}.", file=sys.stderr)
        raise SystemExit(1) from exc

    if token is not None:
        # Best-effort backend logout. Any error here is intentionally swallowed
        # so the local delete still proceeds (contract: "Backend errors ... are
        # NEVER surfaced to the user").
        try:
            sdk = client_module._build_client(token)
            async with sdk:
                try:
                    await sdk.auth.logout()
                except StyrminError:
                    pass
        except StyrminError:
            pass

    try:
        token_store.delete(canonical)
    except TokenStoreError as exc:
        print(f"Could not update token store: {exc.reason}.", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Logged out of {server}")


_NOT_LOGGED_IN_LINE = "Not logged in. Run `styrminctl login` or set STYRMIN_TOKEN."


@auth_app.command
async def whoami() -> None:
    """Print identity + the credential rung that produced the active token."""
    ctx = await client_module.get_auth_context()

    if ctx.source == "none":
        print(_NOT_LOGGED_IN_LINE, file=sys.stderr)
        raise SystemExit(1)

    server = _server_address()
    try:
        async with ctx.client as sdk:
            user = await sdk.auth.current_user()
    except StyrminAuthenticationError:
        print(_NOT_LOGGED_IN_LINE, file=sys.stderr)
        print("Run `styrminctl login` to refresh.", file=sys.stderr)
        raise SystemExit(1) from None
    except StyrminError as exc:
        print(f"Could not reach {server}: {type(exc).__name__}.", file=sys.stderr)
        raise SystemExit(1) from exc

    if user is None:
        print(_NOT_LOGGED_IN_LINE, file=sys.stderr)
        raise SystemExit(1)

    print(f"Username: {user.username}")
    print(f"Display name: {user.display_name}")
    print(f"Role: {user.effective_role.value}")
    print(f"Authenticated via: {_format_source(ctx.source)}")


def _format_source(source: str) -> str:
    """Render the source line per the ``whoami`` contract."""
    if source == "env":
        return "env (STYRMIN_TOKEN)"
    if source == "file":
        return f"token file ({TokenStore().path()})"
    if source == "auto-login":
        return "auto-login (STYRMIN_USERNAME)"
    # Defensive: ``whoami`` exits early on ``none`` so this branch is unreachable.
    return source
