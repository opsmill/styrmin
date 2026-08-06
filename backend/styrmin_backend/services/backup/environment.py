"""Environment-level backup and restore service primitives.

An :class:`~styrmin_backend.db.models.EnvironmentBackup` /
:class:`~styrmin_backend.db.models.EnvironmentRestore` deliberately stores **no
status column**. The parent status is derived at read time by
:func:`derive_environment_operation_status` from the constituent rows plus the
recorded errors/skips, which makes a parent status that contradicts its
constituents structurally impossible (spec FR-004 / SC-003, research.md D2).

The models below define the shape of the JSON captured on the parent rows:

* :class:`DeploymentSnapshot` → ``EnvironmentBackup.deployment_snapshots``
* :class:`ConstituentError` → ``EnvironmentBackup.constituent_errors``
* :class:`SkippedConstituent` → ``EnvironmentRestore.skipped_constituents``
"""

from enum import Enum
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel

from styrmin_backend.db.models import BackupStatus, RestoreStatus


class EnvironmentOperationStatus(str, Enum):
    """Derived status of an environment backup or environment restore.

    Never stored — computed by :func:`derive_environment_operation_status`.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


#: Statuses at which an environment-level operation stops changing on its own.
TERMINAL_ENVIRONMENT_OPERATION_STATUSES = frozenset(
    {
        EnvironmentOperationStatus.COMPLETED,
        EnvironmentOperationStatus.PARTIAL,
        EnvironmentOperationStatus.FAILED,
    }
)

#: A restore is only offered for snapshots that captured something usable.
RESTORABLE_ENVIRONMENT_BACKUP_STATUSES = frozenset(
    {
        EnvironmentOperationStatus.COMPLETED,
        EnvironmentOperationStatus.PARTIAL,
    }
)

_PENDING = "pending"
_IN_PROGRESS = "in_progress"
_COMPLETED = "completed"


class SkipReason(str, Enum):
    """The uniform reasons a constituent is not restored (spec FR-007).

    Every non-restored constituent carries exactly one of these — there are no
    silent skips.
    """

    BACKUP_FAILED_AT_CREATION = "backup failed at creation"
    BACKUP_NOT_COMPLETED = "backup not completed"
    BACKUP_DELETED = "backup deleted"
    BACKUP_EXPIRED = "backup expired"
    DEPLOYMENT_GONE = "deployment no longer exists"
    DEPLOYMENT_BUSY = "deployment busy with another restore"


class DeploymentSnapshot(BaseModel):
    """The declared state of one eligible deployment at backup time.

    Self-contained on purpose: it records the driver *fingerprint* (ADR-0053),
    not just the version string, so a later clone can tell whether the same
    driver content is still loaded.
    """

    deployment_id: UUID
    deployment_name: str
    instance_id: UUID
    driver_name: str
    driver_version: str
    driver_fingerprint: str | None = None
    application_version: str
    config: dict | None = None
    parameters: dict | None = None


class ConstituentError(BaseModel):
    """A constituent that never got a ``Backup`` row, with the reason why."""

    deployment_id: UUID
    deployment_name: str
    error: str


class SkippedConstituent(BaseModel):
    """A constituent that was not restored, attributed by name and reason."""

    deployment_id: UUID
    deployment_name: str
    reason: str


def derive_environment_operation_status(
    children_statuses: Sequence[BackupStatus | RestoreStatus],
    error_count: int,
) -> EnvironmentOperationStatus:
    """Derive the status of an environment backup or restore from its children.

    The rule (data-model.md "Derived status"):

    * any child still ``PENDING``/``IN_PROGRESS`` → ``IN_PROGRESS``, narrowing
      to ``PENDING`` when nothing has happened at all (every child ``PENDING``
      and no recorded errors);
    * otherwise, over the terminal children plus ``error_count``:
      no failures → ``COMPLETED``; some completed and some failed →
      ``PARTIAL``; nothing completed → ``FAILED``.

    Zero children and zero errors is ``COMPLETED``: a config-only snapshot of
    an environment with no eligible deployments succeeded (spec FR-011).

    Args:
        children_statuses: Statuses of the linked constituent rows. Deleted
            constituents are simply absent — the gap shows up in the parent's
            ``deployment_snapshots``, not here.
        error_count: Constituents that failed before a child row existed
            (``EnvironmentBackup.constituent_errors``) or that were skipped
            at classification time (``EnvironmentRestore.skipped_constituents``).

    Returns:
        The derived status. Never persisted.
    """
    values = [status.value for status in children_statuses]

    if any(value in (_PENDING, _IN_PROGRESS) for value in values):
        # An error already recorded means work has happened, so the operation
        # is under way even when every surviving child is still queued.
        if error_count == 0 and all(value == _PENDING for value in values):
            return EnvironmentOperationStatus.PENDING
        return EnvironmentOperationStatus.IN_PROGRESS

    completed = sum(1 for value in values if value == _COMPLETED)
    failed = len(values) - completed + error_count

    if failed == 0:
        return EnvironmentOperationStatus.COMPLETED
    if completed == 0:
        return EnvironmentOperationStatus.FAILED
    return EnvironmentOperationStatus.PARTIAL
