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

from datetime import datetime, timezone
from enum import Enum
from typing import NamedTuple, Sequence
from uuid import UUID

from fast_depends import Depends, inject
from loguru import logger
from pydantic import BaseModel

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    EnvironmentBackup,
    EnvironmentRestore,
    RestoreStatus,
)
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentState
from styrmin_backend.services.backup.metadata import read_backup_metadata
from styrmin_backend.services.backup.service import (
    create_backup,
    create_restore,
    delete_backup,
    resolve_backup_target,
)
from styrmin_backend.services.capabilities import compute_environment_capabilities
from styrmin_backend.services.deployment import redeploy_for_environment_update
from styrmin_backend.services.exceptions import (
    BackupNotFoundError,
    EnvironmentBackupNotFoundError,
    EnvironmentBackupNotRestorableError,
    EnvironmentNotFoundError,
    EnvironmentOperationInProgressError,
    EnvironmentRestoreNotFoundError,
    RestoreAlreadyInProgressError,
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

#: Prefix of the per-deployment namespace every constituent restore targets.
#: Mirrors :func:`resolve_backup_target`'s ``styrmin-<deployment id>``.
_NAMESPACE_PREFIX = "styrmin-"


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


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


class RestorableConstituent(NamedTuple):
    """A constituent that survived classification and will be restored."""

    snapshot: DeploymentSnapshot
    backup_id: UUID


def _backup_expires_at(backup: Backup) -> datetime | None:
    """Read a constituent's recorded expiry, or ``None`` when unknown.

    Same derivation as the ``Backup.expiresAt`` GraphQL resolver: the value
    comes from the typed ``metadata_`` key contract, and anything unparseable
    degrades to "unknown" rather than raising. A naive timestamp is read as
    UTC so the comparison below never mixes aware and naive datetimes.
    """
    metadata = read_backup_metadata(backup.metadata_)
    raw = metadata.get("expires_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        logger.warning(
            "Backup {backup_id} has an unparseable expires_at metadata value "
            "{raw!r}; treating it as never expiring",
            backup_id=backup.id,
            raw=raw,
        )
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


async def _classify_constituents(
    environment_backup: EnvironmentBackup, uow: UnitOfWork, now: datetime
) -> tuple[list[RestorableConstituent], list[SkippedConstituent]]:
    """Split a snapshot's constituents into restorable and skipped (FR-007).

    Every captured deployment lands in exactly one of the two lists, and each
    skip carries the deployment name plus one of the uniform
    :class:`SkipReason` values — there are no silent skips.

    The expiry check is the subtle one (critique E4): Velero garbage-collects
    an expired backup's data cluster-side but never touches the database row,
    so an expired constituent still reads ``COMPLETED``. Restoring it would
    dispatch a Velero restore against data that no longer exists, so expiry is
    computed from the recorded TTL metadata instead of trusting the status.
    """
    backups_by_instance = {
        backup.instance_id: backup for backup in environment_backup.backups
    }
    errored_deployment_ids = {
        ConstituentError.model_validate(raw).deployment_id
        for raw in environment_backup.constituent_errors or []
    }

    usable: list[RestorableConstituent] = []
    skipped: list[SkippedConstituent] = []

    for raw_snapshot in environment_backup.deployment_snapshots or []:
        snapshot = DeploymentSnapshot.model_validate(raw_snapshot)
        backup = backups_by_instance.get(snapshot.instance_id)

        reason: SkipReason | None = None
        if snapshot.deployment_id in errored_deployment_ids:
            reason = SkipReason.BACKUP_FAILED_AT_CREATION
        elif backup is None:
            # The snapshot captured the deployment but no constituent row
            # survives: it was deleted individually after the backup (US3).
            reason = SkipReason.BACKUP_DELETED
        elif backup.status != BackupStatus.COMPLETED:
            reason = SkipReason.BACKUP_NOT_COMPLETED
        elif (
            expires_at := _backup_expires_at(backup)
        ) is not None and expires_at < now:
            reason = SkipReason.BACKUP_EXPIRED
        else:
            deployment = await uow.deployments.find(snapshot.deployment_id)
            if deployment is None or deployment.deleted_at is not None:
                reason = SkipReason.DEPLOYMENT_GONE
            elif deployment.status == DeploymentState.RESTORING:
                reason = SkipReason.DEPLOYMENT_BUSY

        if reason is not None:
            skipped.append(
                SkippedConstituent(
                    deployment_id=snapshot.deployment_id,
                    deployment_name=snapshot.deployment_name,
                    reason=reason.value,
                )
            )
            continue

        assert backup is not None, "a usable constituent always has a backup row"
        usable.append(RestorableConstituent(snapshot=snapshot, backup_id=backup.id))

    return usable, skipped


@inject(cast_result=False)  # type: ignore[arg-type]
async def restore_environment_backup(
    environment_backup_id: UUID,
    uow: UnitOfWork,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> EnvironmentRestore:
    """Revert an environment to a snapshot and restore its constituents in place.

    The ordering is research.md D4:

    1. guard restorability (derived status must be ``COMPLETED``/``PARTIAL``)
       and environment-level concurrency (D6);
    2. classify every captured constituent as restorable or skipped, and
       record the skips on the new ``EnvironmentRestore`` row (FR-007);
    3. revert ``Environment.config`` to the captured value, recompute
       capabilities, and **commit before any dispatch** (ADR-0012);
    4. fan the reverted config out to the eligible deployments that are
       *not* receiving a constituent restore — restored deployments come
       back with their backup-time state, so redeploying them concurrently
       would race the Velero restore on the same namespace;
    5. create and dispatch one constituent restore per usable constituent.

    The config revert assigns ``Environment.config`` directly rather than
    delegating to ``update_environment``: that service treats ``config=None``
    as an idempotent no-op, which would silently make a captured ``None``
    config unrestorable (critique E3).

    No deployment is ever created or deleted (spec FR-008) — topology drift is
    reported as skips, never repaired.

    Args:
        environment_backup_id: The snapshot to restore.
        uow: Unit of work supplying the repositories.
        prefect_manager: Injected dispatcher for the per-constituent
            ``EXECUTE_RESTORE`` flows.

    Returns:
        The persisted ``EnvironmentRestore``, reloaded so its constituents
        are attached.

    Raises:
        EnvironmentBackupNotFoundError: When the snapshot does not exist.
        EnvironmentBackupNotRestorableError: When its derived status is not
            ``COMPLETED`` or ``PARTIAL``.
        EnvironmentNotFoundError: When the snapshot's environment is gone.
        EnvironmentOperationInProgressError: When an environment-level backup
            or restore is already in flight for this environment (FR-009).
    """
    now = datetime.now(timezone.utc)

    async with uow:
        environment_backup = await uow.environment_backups.get(environment_backup_id)
        if environment_backup is None:
            raise EnvironmentBackupNotFoundError(
                f"Environment backup {environment_backup_id} not found"
            )

        backup_status = derive_environment_operation_status(
            [backup.status for backup in environment_backup.backups],
            error_count=len(environment_backup.constituent_errors or []),
        )
        if backup_status not in RESTORABLE_ENVIRONMENT_BACKUP_STATUSES:
            raise EnvironmentBackupNotRestorableError(
                f"Environment backup {environment_backup_id} is not restorable: "
                f"its derived status is {backup_status.value}"
            )

        environment_id = environment_backup.environment_id
        await _guard_no_environment_operation_in_progress(environment_id, uow)

        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        usable, skipped = await _classify_constituents(environment_backup, uow, now)

        environment_restore = await uow.environment_restores.create(
            EnvironmentRestore(
                environment_backup_id=environment_backup_id,
                skipped_constituents=[
                    entry.model_dump(mode="json") for entry in skipped
                ]
                or None,
            )
        )

        # Direct assignment, deliberately (critique E3): a captured ``None``
        # config must revert to ``None``, which ``update_environment`` would
        # treat as "no change requested".
        environment.config = environment_backup.environment_config
        environment.capabilities = compute_environment_capabilities(environment)

        deployments = await uow.deployments.find_all_by_environment(environment_id)

        # The revert and the restore record are durable before anything is
        # dispatched (ADR-0012): a crash mid-fan-out leaves a re-submittable
        # operation rather than a half-applied config.
        await uow.commit()
        await uow.session.refresh(environment_restore)

    environment_restore_id = environment_restore.id
    restoring_deployment_ids = {
        constituent.snapshot.deployment_id for constituent in usable
    }

    # Step 4 — exclusion-aware config fan-out. Deployments receiving a
    # constituent restore are excluded: their in-cluster state is about to be
    # replaced wholesale by Velero, and a concurrent redeploy would race it.
    fanout_dispatched = 0
    fanout_failed = 0
    async with uow:
        for deployment in deployments:
            if not is_eligible_for_environment_backup(deployment):
                continue
            if deployment.id in restoring_deployment_ids:
                continue
            try:
                await redeploy_for_environment_update(deployment, uow)
            except Exception:  # noqa: BLE001 — per-deployment isolation (ADR-0012)
                fanout_failed += 1
                logger.exception(
                    "env_restore_fanout_dispatch_error environment_id={} "
                    "deployment_id={}",
                    environment_id,
                    deployment.id,
                )
                continue
            fanout_dispatched += 1
        await uow.commit()

    # Step 5 — one constituent restore per usable constituent.
    late_skips: list[SkippedConstituent] = []
    restored = 0
    dispatch_failed = 0
    for constituent in usable:
        snapshot = constituent.snapshot
        try:
            _, target_namespace, _ = await resolve_backup_target(
                snapshot.instance_id, uow
            )
            # ``resolve_backup_target`` degrades to an empty namespace when the
            # instance row cannot be walked; the deployment (alive as of
            # classification) still names its own namespace.
            target_namespace = (
                target_namespace or f"{_NAMESPACE_PREFIX}{snapshot.deployment_id}"
            )
            restore, deployment_id = await create_restore(
                backup_id=constituent.backup_id,
                target_namespace=target_namespace,
                uow=uow,
                environment_restore_id=environment_restore_id,
            )
        except RestoreAlreadyInProgressError:
            # research.md D4 / critique P2: a deployment that began an
            # individual restore between classification and dispatch is a
            # skip, never an abort.
            late_skips.append(
                _skip(snapshot, SkipReason.DEPLOYMENT_BUSY.value),
            )
            continue
        except BackupNotFoundError:
            # The constituent (or its instance) vanished in the same window.
            late_skips.append(_skip(snapshot, SkipReason.BACKUP_DELETED.value))
            continue
        except Exception as exc:  # noqa: BLE001 — per-constituent isolation
            # Belt and braces: an unexpected failure is still an attributed
            # skip rather than a silent one (FR-007).
            logger.warning(
                "env_restore_constituent_error environment_restore_id={} "
                "deployment_id={} error={}",
                environment_restore_id,
                snapshot.deployment_id,
                exc,
            )
            late_skips.append(_skip(snapshot, f"restore could not be created: {exc}"))
            continue

        try:
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_RESTORE,
                parameters={
                    "restore_id": str(restore.id),
                    "backup_id": str(constituent.backup_id),
                    "deployment_id": str(deployment_id),
                    "target_namespace": target_namespace,
                },
            )
        except Exception as exc:  # noqa: BLE001 — a dispatch failure is not a lost row
            # The Restore row exists and stays PENDING, so this shows up as a
            # non-terminal constituent rather than a skip — same contract as
            # the per-deployment ``createRestore`` mutation.
            dispatch_failed += 1
            logger.warning(
                "env_restore_dispatch_error environment_restore_id={} restore_id={} "
                "restore record created but Velero execution not triggered: {}",
                environment_restore_id,
                restore.id,
                exc,
            )
            continue
        restored += 1

    async with uow:
        if late_skips:
            persisted = await uow.environment_restores.get(environment_restore_id)
            assert persisted is not None, (
                "The environment restore was committed above and cannot vanish here"
            )
            persisted.skipped_constituents = [
                *(persisted.skipped_constituents or []),
                *(entry.model_dump(mode="json") for entry in late_skips),
            ]
            await uow.commit()
        refreshed = await uow.environment_restores.get(environment_restore_id)
        assert refreshed is not None, (
            "The environment restore was committed above and cannot vanish here"
        )

    # One audit entry per fan-out, matching ``env_backup_fanout_dispatched``
    # (research.md D1 amendment).
    logger.info(
        "env_restore_fanout_dispatched environment_id={} environment_backup_id={} "
        "environment_restore_id={} evaluated={} restored={} skipped={} "
        "config_redeployed={} dispatch_failed={}",
        environment_id,
        environment_backup_id,
        environment_restore_id,
        len(environment_backup.deployment_snapshots or []),
        restored,
        len(skipped) + len(late_skips),
        fanout_dispatched,
        dispatch_failed + fanout_failed,
    )

    return refreshed


def _skip(snapshot: DeploymentSnapshot, reason: str) -> SkippedConstituent:
    """Attribute a skip to its deployment by id *and* name (FR-007)."""
    return SkippedConstituent(
        deployment_id=snapshot.deployment_id,
        deployment_name=snapshot.deployment_name,
        reason=reason,
    )


async def get_environment_restore(
    environment_restore_id: UUID, uow: UnitOfWork
) -> EnvironmentRestore:
    """Get an environment restore by ID.

    Raises:
        EnvironmentRestoreNotFoundError: When no such restore exists.
    """
    async with uow:
        environment_restore = await uow.environment_restores.get(environment_restore_id)
        if environment_restore is None:
            raise EnvironmentRestoreNotFoundError(
                f"Environment restore {environment_restore_id} not found"
            )
        return environment_restore


async def get_environment_restores(
    environment_backup_id: UUID, uow: UnitOfWork
) -> Sequence[EnvironmentRestore]:
    """List a snapshot's restores, newest first."""
    async with uow:
        return await uow.environment_restores.get_by_environment_backup_id(
            environment_backup_id
        )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_environment_backup(
    environment_backup_id: UUID, uow: UnitOfWork
) -> None:
    """Delete a snapshot together with everything that hangs off it (FR-010).

    The cascade is research.md D5, in FK-dependency order:

    1. every constituent backup, via the existing :func:`delete_backup` — which
       already deletes each backup's ``Restore`` rows, so the constituent
       restores of this snapshot's environment restores go with them;
    2. the snapshot's ``EnvironmentRestore`` rows, now childless;
    3. the parent row itself.

    Reusing :func:`delete_backup` per constituent is what keeps FR-014's
    "constituents behave as ordinary backups" true for deletion too: the DB row
    goes, and the Velero object's lifecycle stays governed by its TTL exactly
    as for a standalone backup.

    **There is deliberately no status guard.** Deleting an environment backup
    whose constituents are still ``PENDING``/``IN_PROGRESS`` is legal and is
    the documented escape hatch (spec FR-010, critique E1): a constituent whose
    work was never picked up pins the snapshot non-terminal forever, and since
    the D6 concurrency guard reads that same non-terminal state, deletion is
    the only way to release the environment for new operations.

    Constituent backups remain individually deletable; doing so leaves the
    parent alive with a visible gap in ``deployment_snapshots`` (spec US3),
    which is also why an already-vanished constituent here is a no-op rather
    than an error.

    Args:
        environment_backup_id: The snapshot to delete.
        uow: Unit of work supplying the repositories.

    Raises:
        EnvironmentBackupNotFoundError: When the snapshot does not exist.
    """
    async with uow:
        environment_backup = await uow.environment_backups.get(environment_backup_id)
        if environment_backup is None:
            raise EnvironmentBackupNotFoundError(
                f"Environment backup {environment_backup_id} not found"
            )
        environment_id = environment_backup.environment_id
        constituent_ids = [backup.id for backup in environment_backup.backups]

    deleted_constituents = 0
    for backup_id in constituent_ids:
        try:
            await delete_backup(backup_id, uow)
        except BackupNotFoundError:
            # The constituent was deleted individually in the meantime, which
            # is already the state this cascade is trying to reach.
            logger.debug(
                "env_backup_delete_constituent_absent environment_backup_id={} "
                "backup_id={}",
                environment_backup_id,
                backup_id,
            )
            continue
        deleted_constituents += 1

    async with uow:
        environment_backup = await uow.environment_backups.get(environment_backup_id)
        if environment_backup is None:
            # A concurrent deletion of the same snapshot won the race; the
            # requested end state holds either way.
            return
        environment_restores = list(environment_backup.restores)
        for environment_restore in environment_restores:
            await uow.environment_restores.delete(environment_restore)
        await uow.environment_backups.delete(environment_backup)
        await uow.commit()

    logger.info(
        "env_backup_deleted environment_id={} environment_backup_id={} "
        "constituents_deleted={} environment_restores_deleted={}",
        environment_id,
        environment_backup_id,
        deleted_constituents,
        len(environment_restores),
    )


async def delete_environment_backups_for_environment(
    environment_id: UUID, uow: UnitOfWork
) -> int:
    """Cascade-delete every snapshot of an environment (spec FR-015).

    Called by :func:`~styrmin_backend.services.environments.delete_environment`
    before the environment row goes: ``environmentbackup.environment_id`` is a
    non-nullable FK, so without this the delete fails on a constraint violation
    surfacing as an opaque ``INTERNAL_ERROR`` (critique E2).

    Returns:
        The number of snapshots deleted.
    """
    async with uow:
        environment_backups = await uow.environment_backups.get_by_environment_id(
            environment_id
        )
        environment_backup_ids = [parent.id for parent in environment_backups]

    for environment_backup_id in environment_backup_ids:
        await delete_environment_backup(environment_backup_id, uow)

    return len(environment_backup_ids)
