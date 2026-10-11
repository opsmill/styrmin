"""The typed key contract for ``Backup.metadata_``.

``Backup.metadata_`` is a plain ``JSON`` column, so the database side of it is
an untyped blob by construction. What this module types is the *update
contract*: which keys the backup pipeline is allowed to write, and which keys
its readers are allowed to look up.

Without that contract the keys are bare string literals spread across three
layers — :mod:`styrmin_backend.services.backup.service` (the writer),
:mod:`styrmin_backend.workflows.templates.backup` (the caller that supplies
them), and :mod:`styrmin_backend.api.definitions.backup.backup` (the GraphQL
reader) — with nothing tying writer to reader. The concrete failure that
permits: the Velero result payload the backup flow reads spells the expiry
``"expiration"`` (Velero's own CRD field name), while the persisted key is
``expires_at``. A writer carrying the upstream spelling through as
``metadata_updates={"expiration": ...}`` used to type-check, and the GraphQL
``expiresAt`` resolver would then report null forever. Only an E2E would catch
it.

:class:`BackupMetadata` closes that: it is the single declaration of the key
names, so a misspelled key is a type error at the call site instead of a silent
null. ``total=False`` because every key is written independently at a different
point in the backup lifecycle — a metadata blob carrying only ``timeout`` is
valid, and so is one carrying all four keys.
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

from styrmin_backend.services.backup.ttl import BackupTtlSource

# Seconds a backup may run; the neo4j-community watchdog resumes Neo4j after the same time.
DEFAULT_BACKUP_TIMEOUT: int = 3600


class BackupMetadata(TypedDict, total=False):
    """Keys the backup pipeline may write to, and read from, ``metadata_``.

    Attributes:
        timeout: Seconds the Velero backup flow may run for, recorded at
            creation time by
            :func:`styrmin_backend.services.backup.service.create_backup` and
            read back by ``execute_backup_workflow`` when it dispatches the
            USER flow.
        ttl: The retention TTL applied to this backup, as a Go duration
            (016-backup-retention-ttl / FR-001). Exposed as ``Backup.ttl``.
        ttl_source: Which scope supplied ``ttl`` — the audit half of the
            retention record (FR-002).
        expires_at: Velero's own ``status.expiration`` for this backup, an ISO
            8601 timestamp string (FR-006). Exposed as ``Backup.expiresAt``.
            Note the deliberate rename: Velero calls this ``expiration``, and
            that spelling is *not* a valid key here.
    """

    timeout: int
    ttl: str
    ttl_source: BackupTtlSource
    expires_at: str


def read_backup_metadata(metadata: dict[str, Any] | None) -> BackupMetadata:
    """Narrow a persisted ``Backup.metadata_`` blob to the typed key contract.

    The column is a plain ``JSON``, so what comes back from the database is an
    untyped dict (``None`` on rows written before the column existed). Passing
    it through here is what makes a reader's key lookups checkable — a
    ``.get("expiration")`` on the result is a type error, where the same lookup
    on the raw column is not.

    This is a narrowing, not a validation: the values are whatever is stored,
    which is why each reader still guards the type of what it got. See
    ``Backup.expires_at`` in the GraphQL layer for the degrade-to-null contract
    that a hand-edited or restored row needs.

    Args:
        metadata: The raw ``Backup.metadata_`` value.

    Returns:
        The same mapping, typed — or an empty one when the column is unset.
    """
    return cast("BackupMetadata", metadata or {})
