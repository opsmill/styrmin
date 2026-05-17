"""Per-user JSON token store for ``styrminctl``.

Persists session tokens to ``${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/token``
keyed by canonical server URL. The file is mode ``0600`` and its parent
directory is mode ``0700``; both invariants are reasserted on every save.

Saves are atomic via a temp file in the same directory plus :func:`os.rename`,
so two concurrent ``login`` invocations against different canonical URLs cannot
clobber each other's entries (FR-013 / SC-005).

See ``specs/011-styrminctl-auth/data-model.md`` for the on-disk schema and
``specs/011-styrminctl-auth/research.md`` (R4, R11) for the canonicalisation
and atomicity rationale.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from styrminctl.errors import TokenStoreError

SCHEMA_VERSION: Final[int] = 1
_DIR_MODE: Final[int] = 0o700
_FILE_MODE: Final[int] = 0o600


def _default_token_path() -> Path:
    """Return the platform-canonical token-store path under XDG_DATA_HOME."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path("~/.local/share").expanduser()
    return base / "styrminctl" / "token"


class TokenStore:
    """Load / save / delete per-server tokens, atomically and with strict modes."""

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path if path is not None else _default_token_path()

    # -- Public surface -----------------------------------------------------

    @staticmethod
    def canonicalise(server_address: str) -> str:
        """Return the canonical key for ``server_address``.

        Rule (per R4): lowercase scheme and host, preserve port verbatim,
        strip trailing slash from the path. Implemented via :func:`urlsplit`
        for safety against odd inputs.
        """
        parts = urlsplit(server_address)
        scheme = (parts.scheme or "http").lower()
        host = (parts.hostname or "").lower()
        port = f":{parts.port}" if parts.port is not None else ""
        path = parts.path.rstrip("/")
        return f"{scheme}://{host}{port}{path}"

    def path(self) -> Path:
        """Return the on-disk path this store reads and writes."""
        return self._path

    def get(self, canonical_url: str) -> str | None:
        """Return the token for ``canonical_url``, or ``None`` if absent.

        An empty-string value in the JSON is treated as absent so an
        accidental empty assignment cannot masquerade as authenticated.
        """
        data = self._load()
        token = data["tokens"].get(canonical_url)
        if not token:
            return None
        return token

    def set(self, canonical_url: str, token: str) -> None:
        """Persist ``token`` under ``canonical_url`` atomically.

        Empty tokens are rejected — callers should treat ``""`` as "no token"
        and never reach this method.
        """
        if not token:
            raise TokenStoreError(self._path, "refusing to store an empty token")
        data = self._load()
        data["tokens"][canonical_url] = token
        self._save(data)

    def delete(self, canonical_url: str) -> None:
        """Remove the entry for ``canonical_url``; no-op if absent.

        If no file exists yet, this is a successful no-op (FR-002 / FR-010).
        """
        if not self._path.exists():
            return
        data = self._load()
        if canonical_url in data["tokens"]:
            del data["tokens"][canonical_url]
            self._save(data)

    # -- Internals ----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Return the parsed token-store contents, or an empty skeleton.

        Raises :class:`TokenStoreError` for corrupt JSON, non-object roots,
        or unknown ``schema_version``.
        """
        if not self._path.exists():
            return {"schema_version": SCHEMA_VERSION, "tokens": {}}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TokenStoreError(self._path, f"could not read file: {exc}") from exc
        if not raw.strip():
            # Empty file behaves like "no tokens yet" rather than a parse error.
            return {"schema_version": SCHEMA_VERSION, "tokens": {}}
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TokenStoreError(self._path, f"corrupt JSON: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise TokenStoreError(self._path, "expected a JSON object at the root")
        schema_version = parsed.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise TokenStoreError(
                self._path,
                f"unknown schema_version {schema_version!r}; expected {SCHEMA_VERSION}",
            )
        tokens = parsed.get("tokens")
        if not isinstance(tokens, dict):
            raise TokenStoreError(self._path, "expected 'tokens' to be a JSON object")
        return {"schema_version": SCHEMA_VERSION, "tokens": dict(tokens)}

    def _save(self, data: dict[str, Any]) -> None:
        """Write ``data`` atomically with strict file and directory modes."""
        self._ensure_parent_dir()
        parent = self._path.parent
        # Temp file must live in the SAME directory as the target so that
        # os.rename() is atomic on POSIX. Use pid + random hex so two
        # concurrent saves do not race on the temp filename itself.
        tmp_name = f"{self._path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
        tmp_path = parent / tmp_name
        payload = json.dumps(data, indent=2, sort_keys=True)
        # Open with O_CREAT|O_EXCL|O_WRONLY at mode 0600 so the temp file
        # is never world-readable, even transiently between create and chmod.
        fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            # Reassert mode in case umask altered it on some filesystems.
            Path(tmp_path).chmod(_FILE_MODE)
            Path(tmp_path).rename(self._path)
        except OSError as exc:
            # Best-effort cleanup of the tmp file; preserve the original cause.
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise TokenStoreError(self._path, f"could not write file: {exc}") from exc
        # Reassert directory mode after a successful save (defensive — e.g.
        # the directory existed already with a more permissive mode).
        try:
            Path(parent).chmod(_DIR_MODE)
        except OSError as exc:
            raise TokenStoreError(parent, f"could not set directory mode 0700: {exc}") from exc

    def _ensure_parent_dir(self) -> None:
        """Create the parent directory at mode ``0700`` if missing."""
        parent = self._path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        except OSError as exc:
            raise TokenStoreError(parent, f"could not create directory: {exc}") from exc
        # ``mkdir(mode=...)`` is filtered by umask on POSIX; reassert.
        try:
            Path(parent).chmod(_DIR_MODE)
        except OSError as exc:
            raise TokenStoreError(parent, f"could not set directory mode 0700: {exc}") from exc
