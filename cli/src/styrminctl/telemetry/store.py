"""Persistent telemetry state.

``TelemetryStore`` mirrors ``styrminctl.auth.token_store.TokenStore``: it
persists ``{install_id, enabled}`` to a JSON file with atomic writes and strict
permissions, lazily generating a stable ``install_id``.

The store is best-effort by design (FR-013, FR-017): unlike ``TokenStore``,
which raises ``TokenStoreError`` on any I/O problem, telemetry persistence must
**never** raise. When the on-disk state cannot be read or written, the store
falls back to an ephemeral in-memory ``install_id`` and behaves as
default-enabled for that process — telemetry stays a silent side-channel.

On-disk JSON at ``${XDG_DATA_HOME:-$HOME/.local/share}/styrminctl/telemetry.json``;
file mode ``0o600``, parent dir mode ``0o700``. Saves are atomic via a temp file
in the same directory plus :func:`os.rename`.

See ``specs/015-styrminctl-telemetry/data-model.md`` for the on-disk schema and
``specs/015-styrminctl-telemetry/research.md`` (R6) for the rationale.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Final

_DIR_MODE: Final[int] = 0o700
_FILE_MODE: Final[int] = 0o600


def _default_telemetry_path() -> Path:
    """Return the platform-canonical telemetry-state path under XDG_DATA_HOME."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path("~/.local/share").expanduser()
    return base / "styrminctl" / "telemetry.json"


def _new_install_id() -> str:
    """Return a fresh anonymous install id (uuid4 hex)."""
    return uuid.uuid4().hex


class TelemetryStore:
    """Load / save ``{install_id, enabled}`` best-effort, never raising.

    The ``install_id`` is generated lazily once, on first access, and persists
    across loads and even when ``enabled`` is ``False``. If the state directory
    is unwritable, the id lives only in memory for the current process.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path if path is not None else _default_telemetry_path()
        # Cached ephemeral install_id used when persistence is impossible. Once
        # set, it is reused for the life of the process so the id is stable even
        # in the unwritable-dir fallback path.
        self._ephemeral_install_id: str | None = None

    # -- Public surface -----------------------------------------------------

    def path(self) -> Path:
        """Return the on-disk path this store reads and writes."""
        return self._path

    def install_id(self) -> str:
        """Return the stable anonymous install id, generating it once if needed.

        Reads the persisted id when present; otherwise generates one and tries
        to persist it (preserving the current ``enabled`` flag). If persistence
        fails, returns a process-stable ephemeral id and never raises.
        """
        data = self._load()
        existing = data.get("install_id")
        if isinstance(existing, str) and existing:
            return existing
        # No persisted id yet: mint one and try to persist it.
        new_id = _new_install_id()
        enabled = self._coerce_enabled(data.get("enabled"))
        if self._save({"install_id": new_id, "enabled": enabled}):
            return new_id
        # Persistence failed: fall back to a process-stable ephemeral id.
        if self._ephemeral_install_id is None:
            self._ephemeral_install_id = new_id
        return self._ephemeral_install_id

    def is_enabled(self) -> bool:
        """Return the persisted ``enabled`` flag; an absent file ⇒ enabled."""
        return self._coerce_enabled(self._load().get("enabled"))

    def set_enabled(self, enabled: bool) -> bool:
        """Persist ``enabled`` while preserving the stable ``install_id``.

        Returns ``True`` on a successful write, ``False`` if the directory is
        unwritable. Never raises.
        """
        # install_id() guarantees a stable id (persisted or ephemeral) and may
        # itself persist when the file was absent.
        return self._save({"install_id": self.install_id(), "enabled": enabled})

    # -- Internals ----------------------------------------------------------

    @staticmethod
    def _coerce_enabled(value: object) -> bool:
        """Treat a missing/invalid ``enabled`` as the default-on ``True``."""
        return value if isinstance(value, bool) else True

    def _load(self) -> dict[str, Any]:
        """Return the parsed state, or an empty dict on any read/parse problem.

        Never raises: a missing, empty, corrupt, or non-object file all degrade
        to ``{}`` so the caller treats it as "no persisted state yet".
        """
        try:
            if not self._path.exists():
                return {}
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}
        if not raw.strip():
            return {}
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _save(self, data: dict[str, Any]) -> bool:
        """Write ``data`` atomically with strict modes; return success.

        Best-effort: any I/O error (e.g. an unwritable directory) is swallowed
        and reported via the ``False`` return value rather than raised.
        """
        try:
            self._ensure_parent_dir()
            parent = self._path.parent
            # Temp file must live in the SAME directory as the target so that
            # os.rename() is atomic on POSIX. Use pid + random hex so two
            # concurrent saves do not race on the temp filename itself.
            tmp_name = f"{self._path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
            tmp_path = parent / tmp_name
            payload = json.dumps(data, indent=2, sort_keys=True)
            # O_CREAT|O_EXCL|O_WRONLY at 0600 so the temp file is never
            # world-readable, even transiently between create and chmod.
            fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                # Reassert mode in case umask altered it on some filesystems.
                Path(tmp_path).chmod(_FILE_MODE)
                Path(tmp_path).rename(self._path)
            except OSError:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
                return False
            # Reassert directory mode after a successful save (defensive).
            Path(parent).chmod(_DIR_MODE)
        except OSError:
            return False
        return True

    def _ensure_parent_dir(self) -> None:
        """Create the parent directory at mode ``0o700`` if missing.

        Raises :class:`OSError` on failure; callers in this module swallow it.
        """
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        # ``mkdir(mode=...)`` is filtered by umask on POSIX; reassert.
        Path(parent).chmod(_DIR_MODE)
