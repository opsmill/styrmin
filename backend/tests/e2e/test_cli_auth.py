"""End-to-end ``styrminctl`` authentication scenario (spec 011-styrminctl-auth).

Single API-only scenario that drives the production ``styrminctl`` console
script as a subprocess against the e2e backend, covering the full
login -> authenticated command -> whoami -> logout lifecycle.

The test is ``api_only`` because every step shells out to the same
``styrminctl`` binary; the ``[ui-chromium]`` variant would re-execute the
identical subprocess against the identical SDK ``auth.login`` path with no
incremental UI coverage. See the dual-entrypoint scope guidance in
``AGENTS.md``.

The test isolates the token store via a per-test ``XDG_DATA_HOME`` under
``tmp_path`` so it never touches the developer's real
``~/.local/share/styrminctl/token``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.graphql._generated.enums import Role

# Project root, derived from this file's location so the subprocess runs
# the same ``styrminctl`` console script the repo ships (installed via
# ``uv sync`` against the workspace).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


pytestmark = [
    pytest.mark.ci,
    pytest.mark.api_only(
        reason=(
            "Drives the styrminctl subprocess; no UI flow. The "
            "[ui-chromium] variant would re-execute the same subprocess "
            "and the same SDK login path with no incremental coverage."
        ),
    ),
]


@dataclass(frozen=True)
class _Completed:
    """Outcome of a ``styrminctl`` subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str


async def _run_styrminctl(
    args: list[str],
    *,
    server_address: str,
    xdg_data_home: Path,
    stdin: str | None = None,
) -> _Completed:
    """Run the ``styrminctl`` console script asynchronously.

    Uses ``uv run styrminctl`` so the entry point resolves through the
    workspace install. Only the env vars the CLI actually needs are
    forwarded; ``STYRMIN_TOKEN`` / ``STYRMIN_USERNAME`` / ``STYRMIN_PASSWORD``
    are explicitly omitted so the credential resolver sees an empty
    environment for those rungs unless the test sets them explicitly.

    Uses ``asyncio.create_subprocess_exec`` rather than ``subprocess.run``
    so the event loop keeps running while the subprocess executes —
    critical because the ``styrmin_deployment`` port-forward is a
    userspace TCP proxy implemented in this same asyncio loop. A
    blocking ``subprocess.run`` would freeze the proxy and the
    subprocess would see ``StyrminTransportError`` against the
    port-forwarded backend.
    """
    env = {
        # Preserve PATH so ``uv`` is discoverable.
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", str(xdg_data_home.parent)),
        "STYRMIN_ADDRESS": server_address,
        "XDG_DATA_HOME": str(xdg_data_home),
    }
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "styrminctl",
        *args,
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdin_bytes = stdin.encode() if stdin is not None else None
    stdout_bytes, stderr_bytes = await proc.communicate(input=stdin_bytes)
    assert proc.returncode is not None
    return _Completed(
        returncode=proc.returncode,
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
    )


async def test_cli_login_persists_token_and_subsequent_command_succeeds(
    authenticated_styrmin_client: StyrminClient,
    styrmin_deployment: str,
    tmp_path: Path,
) -> None:
    """Full ``styrminctl`` auth lifecycle, end-to-end against the live backend.

    Steps (per ``specs/011-styrminctl-auth/quickstart.md``):

    1. Seed a ``READ_WRITE`` user via the admin SDK fixture.
    2. ``styrminctl login --username <u>`` with password on stdin →
       exit 0; stdout contains ``Logged in to <addr> as <u>``.
    3. Inspect the on-disk token store: file at mode ``0600``, parent at
       ``0700``, JSON with ``schema_version: 1`` and a non-empty token
       under the canonical-URL key.
    4. Fresh subprocess: ``styrminctl clusters list`` → exit 0.
    5. Fresh subprocess: ``styrminctl whoami`` → exit 0; stdout shows
       the seeded username and the ``Authenticated via: token file (...)``
       source line.
    6. ``styrminctl logout`` → exit 0; stdout contains
       ``Logged out of <addr>``.
    7. Re-read the token store: ``tokens`` no longer contains the
       canonical-URL key.
    8. ``styrminctl whoami`` again → non-zero exit; stderr matches
       ``Not logged in``.
    """
    # ------------------------------------------------------------------
    # Step 1: seed a READ_WRITE user via the admin SDK fixture.
    # ------------------------------------------------------------------
    suffix = uuid.uuid4().hex[:8]
    username = f"cli-auth-{suffix}"
    password = f"cli-auth-pw-{suffix}"
    display_name = f"CLI Auth Test {suffix}"

    created = await authenticated_styrmin_client.users.create(
        username=username,
        password=password,
        display_name=display_name,
        role=Role.READ_WRITE,
    )
    created_user_id = str(created.id)

    # Per-test isolated token store — the CLI uses
    # ``${XDG_DATA_HOME}/styrminctl/token`` (see TokenStore._default_token_path).
    xdg_data_home = tmp_path / "xdg"
    xdg_data_home.mkdir()
    token_file = xdg_data_home / "styrminctl" / "token"

    try:
        # --------------------------------------------------------------
        # Step 2: styrminctl login --username <u>, password on stdin.
        # --------------------------------------------------------------
        login_result = await _run_styrminctl(
            ["login", "--username", username],
            server_address=styrmin_deployment,
            xdg_data_home=xdg_data_home,
            stdin=f"{password}\n",
        )
        assert login_result.returncode == 0, (
            f"login exited {login_result.returncode}; "
            f"stdout={login_result.stdout!r} stderr={login_result.stderr!r}"
        )
        assert (
            f"Logged in to {styrmin_deployment} as {username}" in login_result.stdout
        ), f"unexpected login stdout: {login_result.stdout!r}"

        # --------------------------------------------------------------
        # Step 3: verify on-disk token store shape + permissions.
        # --------------------------------------------------------------
        assert token_file.exists(), (
            f"token file {token_file} should exist after login; "
            f"xdg dir contents: {list(xdg_data_home.rglob('*'))}"
        )
        file_mode = oct(token_file.stat().st_mode & 0o777)
        assert file_mode == "0o600", f"token file mode must be 0o600, got {file_mode}"
        dir_mode = oct(token_file.parent.stat().st_mode & 0o777)
        assert dir_mode == "0o700", (
            f"token directory mode must be 0o700, got {dir_mode}"
        )

        store_payload = json.loads(token_file.read_text(encoding="utf-8"))
        assert store_payload.get("schema_version") == 1, (
            f"unexpected schema_version: {store_payload!r}"
        )
        tokens = store_payload.get("tokens", {})
        # Compute the canonical key the same way TokenStore.canonicalise does:
        # lowercase scheme/host, preserve port, strip trailing slash. The e2e
        # backend address comes from the port-forward and is already lowercase
        # http://localhost:<port>, so an equality check against the raw URL
        # suffices — but we still pick out by prefix to stay robust.
        canonical_keys = [k for k in tokens if k.startswith("http://localhost:")]
        assert len(canonical_keys) == 1, (
            f"expected exactly one canonical-URL entry, got {list(tokens)!r}"
        )
        canonical_key = canonical_keys[0]
        assert tokens[canonical_key], f"token under {canonical_key!r} must be non-empty"

        # --------------------------------------------------------------
        # Step 4: fresh subprocess runs an authenticated command.
        # --------------------------------------------------------------
        clusters_result = await _run_styrminctl(
            ["clusters", "list"],
            server_address=styrmin_deployment,
            xdg_data_home=xdg_data_home,
        )
        assert clusters_result.returncode == 0, (
            f"`clusters list` exited {clusters_result.returncode}; "
            f"stdout={clusters_result.stdout!r} stderr={clusters_result.stderr!r}"
        )

        # --------------------------------------------------------------
        # Step 5: whoami shows the seeded user + token-file source line.
        # --------------------------------------------------------------
        whoami_result = await _run_styrminctl(
            ["whoami"],
            server_address=styrmin_deployment,
            xdg_data_home=xdg_data_home,
        )
        assert whoami_result.returncode == 0, (
            f"whoami exited {whoami_result.returncode}; "
            f"stdout={whoami_result.stdout!r} stderr={whoami_result.stderr!r}"
        )
        assert f"Username: {username}" in whoami_result.stdout, (
            f"whoami stdout missing username: {whoami_result.stdout!r}"
        )
        assert "Authenticated via: token file (" in whoami_result.stdout, (
            f"whoami stdout missing token-file source line: {whoami_result.stdout!r}"
        )
        assert str(token_file) in whoami_result.stdout, (
            f"whoami source line should reference the isolated token file "
            f"{token_file}; got: {whoami_result.stdout!r}"
        )

        # --------------------------------------------------------------
        # Step 6: logout — exits 0, prints the expected line.
        # --------------------------------------------------------------
        logout_result = await _run_styrminctl(
            ["logout"],
            server_address=styrmin_deployment,
            xdg_data_home=xdg_data_home,
        )
        assert logout_result.returncode == 0, (
            f"logout exited {logout_result.returncode}; "
            f"stdout={logout_result.stdout!r} stderr={logout_result.stderr!r}"
        )
        assert f"Logged out of {styrmin_deployment}" in logout_result.stdout, (
            f"unexpected logout stdout: {logout_result.stdout!r}"
        )

        # --------------------------------------------------------------
        # Step 7: token-store entry is gone (the file itself is kept;
        # `tokens` no longer contains the canonical-URL key — see
        # contracts/logout.md "Why not delete the file entirely").
        # --------------------------------------------------------------
        post_logout = json.loads(token_file.read_text(encoding="utf-8"))
        assert canonical_key not in post_logout.get("tokens", {}), (
            f"token entry for {canonical_key!r} should be removed after "
            f"logout; got {post_logout!r}"
        )

        # --------------------------------------------------------------
        # Step 8: whoami after logout fails with the friendly line.
        # --------------------------------------------------------------
        whoami_again = await _run_styrminctl(
            ["whoami"],
            server_address=styrmin_deployment,
            xdg_data_home=xdg_data_home,
        )
        assert whoami_again.returncode != 0, (
            f"whoami after logout should exit non-zero; "
            f"stdout={whoami_again.stdout!r} stderr={whoami_again.stderr!r}"
        )
        assert "Not logged in" in whoami_again.stderr, (
            f"whoami stderr should contain `Not logged in`; "
            f"got: {whoami_again.stderr!r}"
        )

    finally:
        # Best-effort cleanup of the seeded user.
        try:
            await authenticated_styrmin_client.users.delete(created_user_id)
        except StyrminError:
            pass
