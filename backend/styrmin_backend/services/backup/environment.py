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

from __future__ import annotations

from enum import Enum
from typing import Sequence
from uuid import UUID

from fast_depends import Depends, inject
from loguru import logger
from pydantic import BaseModel

from styrmin_backend.db.models import BackupStatus, EnvironmentBackup, RestoreStatus
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.services.backup.service import (
    create_backup,
    resolve_backup_target,
)
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
    EnvironmentNotFoundError,
    EnvironmentOperationInProgressError,
)

# ``UnitOfWork`` is imported at runtime, not under ``TYPE_CHECKING``: the
# ``@inject``-decorated ``create_environment_backup`` below has fast-depends
# build a Pydantic model from its signature, which resolves the annotation for
# real. A deferred import leaves it undefined and every call raises
# ``PydanticUserError`` instead of running.
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


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


def is_eligible_for_environment_backup(deployment: DeploymentEntity) -> bool:
    """Return whether a deployment contributes a constituent to a snapshot.

    Eligible means non-tombstoned, non-internal, and carrying an active
    application instance — regardless of the deployment's current state
    (spec FR-001). Tombstones are already excluded by
    ``find_all_by_environment``; the check is repeated here so the predicate
    is correct on any deployment list.
    """
    return (
        deployment.deleted_at is None
        and not deployment.internal
        and deployment.active_instance is not None
    )


async def _capture_deployment_snapshot(
    deployment: DeploymentEntity, uow: UnitOfWork
) -> DeploymentSnapshot:
    """Capture one eligible deployment's declared state (spec FR-003).

    The driver identity comes from the *deployment's* bound driver version —
    the declared state — and records the ADR-0053 provenance fingerprint
    (``content_hash`` for local sources, ``source_commit_sha`` for git) so a
    later clone can tell whether the same driver content is still loaded.
    A driver version that cannot be resolved degrades the driver fields to
    empty strings rather than failing the whole snapshot.
    """
    instance = deployment.active_instance
    assert instance is not None, (
        "caller must filter on is_eligible_for_environment_backup"
    )

    driver_version = await uow.application_driver_versions.get(
        deployment.application_driver_version_id
    )
    driver_name = ""
    driver_version_label = ""
    driver_fingerprint: str | None = None
    if driver_version is not None:
        driver_version_label = driver_version.version
        driver_fingerprint = (
            driver_version.content_hash or driver_version.source_commit_sha
        )
        driver = driver_version.application_driver
        if driver is not None:
            driver_name = driver.name

    return DeploymentSnapshot(
        deployment_id=deployment.id,
        deployment_name=deployment.name,
        instance_id=instance.id,
        driver_name=driver_name,
        driver_version=driver_version_label,
        driver_fingerprint=driver_fingerprint,
        application_version=deployment.application_version,
        config=deployment.config,
        parameters=deployment.parameters or None,
    )


async def _guard_no_environment_operation_in_progress(
    environment_id: UUID, uow: UnitOfWork
) -> None:
    """Enforce one environment-level operation per environment (research.md D6).

    Both directions are checked: an in-flight environment backup and an
    in-flight environment restore each block a new operation (spec FR-009).
    "In flight" is an EXISTS over the constituent rows, so the guard can never
    disagree with reality.
    """
    in_flight_backup = await uow.environment_backups.has_in_progress_environment_backup(
        environment_id
    )
    if in_flight_backup is not None:
        raise EnvironmentOperationInProgressError(
            operation_id=str(in_flight_backup.id),
            operation_kind="environment_backup",
        )

    in_flight_restore = (
        await uow.environment_restores.has_in_progress_environment_restore(
            environment_id
        )
    )
    if in_flight_restore is not None:
        raise EnvironmentOperationInProgressError(
            operation_id=str(in_flight_restore.id),
            operation_kind="environment_restore",
        )


@inject(cast_result=False)  # type: ignore[arg-type]
async def create_environment_backup(
    environment_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> EnvironmentBackup:
    """Snapshot an environment and fan out one constituent backup per deployment.

    The parent row (captured config + per-deployment declared state) is
    created and **committed before any dispatch**, so a crash mid-fan-out
    leaves a durable, inspectable snapshot rather than losing the capture —
    the ADR-0012 ordering rule.

    The fan-out then follows ADR-0012's per-item isolation: each constituent
    is created and dispatched inside its own ``try``/``except``, and a failure
    is recorded as a :class:`ConstituentError` naming the deployment before
    the loop moves on (spec FR-005). The mutation never fails because one
    application was busy.

    An environment with no eligible deployments yields a config-only snapshot
    which derives as ``COMPLETED`` immediately (spec FR-011) — no constituents
    means nothing to wait for.

    Args:
        environment_id: The environment to snapshot.
        uow: Unit of work supplying the repositories.
        name: Optional snapshot name. Defaults to ``styrmin-envbackup-<id>``.
        prefect_manager: Injected dispatcher for the per-constituent
            ``EXECUTE_BACKUP`` flows.

    Returns:
        The persisted parent row, reloaded so its constituents are attached.

    Raises:
        EnvironmentNotFoundError: When ``environment_id`` does not exist.
        EnvironmentOperationInProgressError: When an environment-level backup
            or restore is already in flight for this environment (FR-009).
    """
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        await _guard_no_environment_operation_in_progress(environment_id, uow)

        deployments = await uow.deployments.find_all_by_environment(environment_id)
        eligible = [d for d in deployments if is_eligible_for_environment_backup(d)]
        snapshots = [
            await _capture_deployment_snapshot(deployment, uow)
            for deployment in eligible
        ]

        environment_backup = await uow.environment_backups.create(
            EnvironmentBackup(
                name=name or "placeholder",
                environment_id=environment_id,
                environment_config=environment.config,
                deployment_snapshots=[
                    snapshot.model_dump(mode="json") for snapshot in snapshots
                ]
                or None,
            )
        )
        if name is None:
            environment_backup.name = f"styrmin-envbackup-{environment_backup.id}"

        # Commit the capture before dispatching anything (ADR-0012).
        await uow.commit()
        await uow.session.refresh(environment_backup)

    environment_backup_id = environment_backup.id
    errors: list[ConstituentError] = []
    dispatched = 0
    dispatch_failed = 0

    for snapshot in snapshots:
        try:
            _, target_namespace, component_configs = await resolve_backup_target(
                snapshot.instance_id, uow
            )
            backup = await create_backup(
                instance_id=snapshot.instance_id,
                uow=uow,
                target_namespace=target_namespace,
                component_configs=component_configs,
                environment_backup_id=environment_backup_id,
            )
        except Exception as exc:  # noqa: BLE001 — per-constituent isolation (FR-005)
            logger.warning(
                "env_backup_constituent_error environment_backup_id={} "
                "deployment_id={} error={}",
                environment_backup_id,
                snapshot.deployment_id,
                exc,
            )
            errors.append(
                ConstituentError(
                    deployment_id=snapshot.deployment_id,
                    deployment_name=snapshot.deployment_name,
                    error=str(exc),
                )
            )
            continue

        try:
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_BACKUP,
                parameters={
                    "backup_id": str(backup.id),
                    "deployment_id": str(snapshot.deployment_id),
                },
            )
        except Exception as exc:  # noqa: BLE001 — a dispatch failure is not a lost row
            # The Backup row exists and stays PENDING, so this is visible as a
            # non-terminal constituent rather than a recorded creation error —
            # exactly how the per-instance ``createBackup`` mutation behaves.
            dispatch_failed += 1
            logger.warning(
                "env_backup_dispatch_error environment_backup_id={} backup_id={} "
                "backup record created but Velero execution not triggered: {}",
                environment_backup_id,
                backup.id,
                exc,
            )
            continue
        dispatched += 1

    async with uow:
        if errors:
            persisted = await uow.environment_backups.get(environment_backup_id)
            assert persisted is not None, (
                "The environment backup was committed above and cannot vanish here"
            )
            persisted.constituent_errors = [
                error.model_dump(mode="json") for error in errors
            ]
            await uow.commit()
        refreshed = await uow.environment_backups.get(environment_backup_id)
        assert refreshed is not None, (
            "The environment backup was committed above and cannot vanish here"
        )

    # One audit entry per fan-out, matching ``env_config_fanout_dispatched``
    # (research.md D1 amendment). ``evaluated`` counts every deployment
    # considered, including the internal / instance-less ones filtered out.
    logger.info(
        "env_backup_fanout_dispatched environment_id={} environment_backup_id={} "
        "evaluated={} dispatched={} conflict={} dispatch_failed={}",
        environment_id,
        environment_backup_id,
        len(deployments),
        dispatched,
        len(errors),
        dispatch_failed,
    )

    return refreshed


async def get_environment_backup(
    environment_backup_id: UUID, uow: UnitOfWork
) -> EnvironmentBackup:
    """Get an environment backup by ID.

    Raises:
        EnvironmentBackupNotFoundError: When no such snapshot exists.
    """
    async with uow:
        environment_backup = await uow.environment_backups.get(environment_backup_id)
        if environment_backup is None:
            raise EnvironmentBackupNotFoundError(
                f"Environment backup {environment_backup_id} not found"
            )
        return environment_backup


async def get_environment_backups(
    environment_id: UUID, uow: UnitOfWork
) -> Sequence[EnvironmentBackup]:
    """List an environment's snapshots, newest first."""
    async with uow:
        return await uow.environment_backups.get_by_environment_id(environment_id)
