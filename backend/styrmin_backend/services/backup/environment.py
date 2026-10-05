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
from uuid import UUID, uuid4

from fast_depends import Depends, inject
from loguru import logger
from pydantic import BaseModel

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Environment,
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
    settle_undispatched_restore,
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
    """The conventional reasons a constituent is not restored (spec FR-007).

    Every non-restored constituent is attributed with its deployment name and a
    reason — there are no silent skips. The reason is **not** limited to these
    members: an unexpected ``create_restore`` failure is recorded verbatim as
    ``f"restore could not be created: {exc}"``, so
    :class:`SkippedConstituent.reason` is an open string rather than a closed
    vocabulary (ADR-0055 — a wire-level enum would break older clients every
    time the set grows).
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

    ``service_name_overrides`` is the second clone-readiness field: a
    deployment's resolved service names are chosen at *creation* time and
    sibling deployments' FQDNs are built on them, so a counterpart that cannot
    read them back would either rename the services or break the FQDNs — and
    re-reading the live source after capture is forbidden (010 spec FR-005 ∧
    FR-007). It is additive and nullable: snapshots captured before this field
    existed read as ``None``, which means "no overrides" — the counterpart uses
    the driver-default service names.
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
    #: ``driver_service_name`` → overridden ``resolved_name``, for the services
    #: whose resolved name differs from the driver default. ``None`` when the
    #: deployment overrode nothing (or the snapshot predates this field).
    service_name_overrides: dict[str, str] | None = None
    #: The deployment's Helm release name at capture time. Additive and
    #: nullable: snapshots taken before this field existed read as ``None``,
    #: which means "the conventional ``styrmin-<deployment id>``". A clone's
    #: counterpart is created with this exact value so it **adopts** the
    #: restored Helm release instead of installing a second one over objects
    #: Helm already owns (010 research D2). Reading it back matters for a clone
    #: of a clone, whose source is itself already an adopter.
    release_reference: str | None = None


class ConstituentError(BaseModel):
    """A constituent that never got a ``Backup`` row, with the reason why."""

    deployment_id: UUID
    deployment_name: str
    error: str


class SkippedConstituent(BaseModel):
    """A constituent that was not restored, attributed by name and reason.

    ``reason`` is an open string: usually a :class:`SkipReason` value, but an
    unexpected constituent-creation failure is recorded verbatim.
    """

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
    A driver version that cannot be resolved degrades the driver fields rather
    than failing the whole snapshot: ``driver_name`` and ``driver_version`` to
    empty strings, ``driver_fingerprint`` to ``None`` (it is nullable because a
    resolvable driver version can also carry neither a ``content_hash`` nor a
    ``source_commit_sha``).

    The deployment's service-name overrides are captured too (010 spec FR-005 ∧
    FR-007): only the services whose ``resolved_name`` differs from the driver's
    own name are recorded, because that is exactly the argument
    :func:`create_services_for_deployment` takes — passing identity mappings
    would put driver-default names through the override validation path they
    never went through originally.

    The instance's ``release_reference`` is captured for the same reason: the
    Helm release inside the backed-up namespace is named after it, and a clone
    counterpart has to adopt that exact name (010 research D2).
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

    deployed_services = await uow.deployed_services.get_by_deployment_id(deployment.id)
    service_name_overrides = {
        service.driver_service_name: service.resolved_name
        for service in deployed_services
        if service.resolved_name != service.driver_service_name
    }

    # The Helm release name as it actually is in the cluster, not as it would
    # be recomputed: the source may itself be a clone counterpart that adopted
    # another deployment's release (010 research D2).
    release_reference = getattr(
        getattr(instance.context, "instance", None), "release_reference", None
    )

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
        service_name_overrides=service_name_overrides or None,
        release_reference=str(release_reference) if release_reference else None,
    )


async def _guard_no_environment_operation_in_progress(
    environment_id: UUID, uow: UnitOfWork
) -> None:
    """Enforce one environment-level operation per environment (research.md D6).

    Three directions are checked: an in-flight environment backup, an in-flight
    environment restore, and an environment clone occupying this environment
    each block a new operation (spec FR-009, 010 research D8). The first two are
    an EXISTS over the constituent rows, so they can never disagree with
    reality; clone terminality is not EXISTS-able, so
    :func:`~styrmin_backend.services.backup.clone.find_clone_occupying_environment`
    derives it in Python over a tiny candidate set.
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

    await guard_no_clone_occupying_environment(environment_id, uow)


async def guard_no_clone_occupying_environment(
    environment_id: UUID, uow: UnitOfWork
) -> None:
    """Refuse the operation when a clone occupies ``environment_id`` (010 D8).

    Deliberately importable on its own so ``update_environment`` can apply the
    clone half of the guard without also inheriting the backup/restore halves —
    a config update has never been blocked by an in-flight environment backup
    and must not start being.

    The import is deferred because ``services.backup.clone`` imports this
    module for the shared status vocabulary; hoisting it would make the two
    modules a cycle.
    """
    from styrmin_backend.services.backup.clone import (
        find_clone_occupying_environment,
    )

    occupying = await find_clone_occupying_environment(environment_id, uow)
    if occupying is not None:
        raise EnvironmentOperationInProgressError(
            operation_id=str(occupying.id),
            operation_kind="environment_clone",
        )


class _SharedTransaction(UnitOfWork):
    """A unit-of-work view that lets a nested service join the caller's transaction.

    ``create_backup`` / ``create_restore`` each own their transaction: they end
    with ``uow.commit()``, and ``UnitOfWork.__aexit__`` calls ``uow.rollback()``
    whenever an exception leaves their ``async with uow`` block. Both are right
    for the per-instance mutations that call them directly and fatal for the
    environment fan-out, which needs the parent record, every constituent row
    and every recorded error to commit **once**:

    * their ``commit()`` would publish a half-built capture, and
    * their ``rollback()`` would discard the parent snapshot INSERT because one
      constituent's instance happened to be busy — turning FR-005's
      "one conflicted constituent, peers proceed" into "no snapshot at all".

    Forwarding every repository to the real unit of work while turning
    ``commit`` and ``rollback`` into no-ops leaves the enclosing service the
    single owner of the transaction boundary, with no change to the reused
    services. Construct it **inside** the caller's ``async with uow`` block:
    the real unit of work binds its repositories in ``__aenter__``.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def __getattr__(self, name: str) -> object:
        # Only reached for attributes this view does not define itself — i.e.
        # ``session`` and every repository.
        return getattr(self._uow, name)

    async def commit(self) -> None:
        """No-op: the enclosing service commits the shared transaction."""

    async def rollback(self) -> None:
        """No-op: the enclosing service owns rollback too."""


class _PendingBackupDispatch(NamedTuple):
    """A committed constituent backup awaiting its ``EXECUTE_BACKUP`` dispatch.

    Collected while the capture transaction is still open and consumed after it
    commits, which is what keeps "nothing is dispatched before the whole capture
    is durable" true (ADR-0012).
    """

    backup_id: UUID
    deployment_id: UUID


class CaptureRegistration(NamedTuple):
    """Everything one capture wrote inside the caller's open transaction.

    Returned by :func:`register_environment_backup` so the caller can commit
    once and only then dispatch — the ADR-0012 ordering rule. ``evaluated``
    counts every deployment considered (including the internal /
    instance-less ones and the ones an explicit selection excluded) so the
    audit line can distinguish "nothing to capture" from "everything filtered
    out".
    """

    environment_backup: EnvironmentBackup
    pending_dispatch: list[_PendingBackupDispatch]
    errors: list[ConstituentError]
    evaluated: int


async def register_environment_backup(
    environment: Environment,
    uow: UnitOfWork,
    name: str | None = None,
    deployment_ids: list[UUID] | None = None,
) -> CaptureRegistration:
    """Write a whole capture into the caller's transaction, dispatching nothing.

    Extracted from :func:`create_environment_backup` so the environment clone
    can register its capture in the **same** transaction as the clone record
    (010 research D4) without duplicating the snapshot/constituent logic. The
    caller owns the concurrency guard, the commit, and the fan-out dispatch.

    Must be called inside an ``async with uow`` block: the constituents join
    that transaction through :class:`_SharedTransaction` rather than opening
    (and committing) one each.

    Args:
        environment: The already-loaded environment row being snapshotted.
        uow: Unit of work supplying the repositories, transaction already open.
        name: Optional snapshot name. Defaults to ``styrmin-envbackup-<id>``.
        deployment_ids: Optional selection — see
            :func:`create_environment_backup` for the full contract.

    Returns:
        The capture registration; nothing has been dispatched or committed.
    """
    environment_id = environment.id
    deployments = await uow.deployments.find_all_by_environment(environment_id)
    eligible = [d for d in deployments if is_eligible_for_environment_backup(d)]
    if deployment_ids is not None:
        selected = set(deployment_ids)
        eligible = [d for d in eligible if d.id in selected]
    snapshots = [
        await _capture_deployment_snapshot(deployment, uow) for deployment in eligible
    ]

    # The id is generated up front so the auto-generated name is final
    # *before* the INSERT. ``EnvironmentBackup.name`` is unique, so writing
    # a shared sentinel and renaming afterwards makes two concurrently
    # auto-named snapshots — even in different environments — collide on
    # that index.
    environment_backup_id = uuid4()
    environment_backup = await uow.environment_backups.create(
        EnvironmentBackup(
            id=environment_backup_id,
            name=name or f"styrmin-envbackup-{environment_backup_id}",
            environment_id=environment_id,
            environment_config=environment.config,
            deployment_snapshots=[
                snapshot.model_dump(mode="json") for snapshot in snapshots
            ]
            or None,
        )
    )

    errors: list[ConstituentError] = []
    pending_dispatch: list[_PendingBackupDispatch] = []
    # The constituents join this transaction instead of opening one each.
    constituent_uow = _SharedTransaction(uow)

    for snapshot in snapshots:
        try:
            _, target_namespace, component_configs = await resolve_backup_target(
                snapshot.instance_id, constituent_uow
            )
            backup = await create_backup(
                instance_id=snapshot.instance_id,
                uow=constituent_uow,
                target_namespace=target_namespace,
                component_configs=component_configs,
                environment_backup_id=environment_backup_id,
            )
        except Exception as exc:  # noqa: BLE001 — per-constituent isolation (FR-005)
            logger.exception(
                "env_backup_constituent_error environment_backup_id={} "
                "deployment_id={}",
                environment_backup_id,
                snapshot.deployment_id,
            )
            errors.append(
                ConstituentError(
                    deployment_id=snapshot.deployment_id,
                    deployment_name=snapshot.deployment_name,
                    error=str(exc),
                )
            )
            continue

        pending_dispatch.append(
            _PendingBackupDispatch(
                backup_id=backup.id, deployment_id=snapshot.deployment_id
            )
        )

    if errors:
        environment_backup.constituent_errors = [
            error.model_dump(mode="json") for error in errors
        ]

    return CaptureRegistration(
        environment_backup=environment_backup,
        pending_dispatch=pending_dispatch,
        errors=errors,
        evaluated=len(deployments),
    )


async def dispatch_constituent_backups(
    pending_dispatch: Sequence[_PendingBackupDispatch],
    prefect_manager: PrefectManager,
    environment_backup_id: UUID,
) -> tuple[int, int]:
    """Dispatch one ``EXECUTE_BACKUP`` per committed constituent.

    Shared by :func:`create_environment_backup` and the clone registration, so
    both report dispatch failures the same way.

    Returns:
        ``(dispatched, dispatch_failed)``.
    """
    dispatched = 0
    dispatch_failed = 0
    for pending in pending_dispatch:
        try:
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_BACKUP,
                parameters={
                    "backup_id": str(pending.backup_id),
                    "deployment_id": str(pending.deployment_id),
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
                pending.backup_id,
                exc,
            )
            continue
        dispatched += 1
    return dispatched, dispatch_failed


@inject(cast_result=False)  # type: ignore[arg-type]
async def create_environment_backup(
    environment_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    deployment_ids: list[UUID] | None = None,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> EnvironmentBackup:
    """Snapshot an environment and fan out one constituent backup per deployment.

    The whole capture — the parent row (captured config + per-deployment
    declared state), every constituent ``Backup`` row and every recorded
    :class:`ConstituentError` — is written in **one transaction, committed
    before any dispatch**. That is the ADR-0012 ordering rule made atomic: a
    crash or client disconnect mid-capture leaves either no snapshot at all or
    a complete, inspectable one, never a committed parent that lost the
    constituents and errors belonging to it. Two defects follow from the
    non-atomic ordering and are closed by this shape:

    * ``CancelledError`` (client disconnect, request timeout) escapes the
      per-constituent ``except Exception``, so deferring the error write until
      after the fan-out could publish a snapshot with fewer children than
      snapshots and *zero* recorded errors — which derives ``COMPLETED``
      (spec FR-007);
    * the D6 guard is an EXISTS over non-terminal *children*, so a committed
      parent with no children yet does not block a second environment backup
      (spec FR-009).

    The fan-out still follows ADR-0012's per-item isolation: each constituent
    is created inside its own ``try``/``except``, and a failure is recorded as
    a :class:`ConstituentError` naming the deployment before the loop moves on
    (spec FR-005) — now in the same transaction as its peers. The mutation
    never fails because one application was busy.

    An environment with no eligible deployments yields a config-only snapshot
    which derives as ``COMPLETED`` immediately (spec FR-011) — no constituents
    means nothing to wait for.

    Args:
        environment_id: The environment to snapshot.
        uow: Unit of work supplying the repositories.
        name: Optional snapshot name. Defaults to ``styrmin-envbackup-<id>``.
        deployment_ids: Optional selection, applied to the eligible set before
            anything is captured (010 spec FR-003, research D6): ``None`` means
            "every eligible deployment", an explicit list narrows the capture to
            the ids it names, and ``[]`` selects nothing (a config-only
            snapshot). Ids that are unknown, tombstoned, internal, or
            instance-less are simply not captured — this filter never raises.
            Rejecting or attributing them is the caller's job, because only the
            caller knows whether an id it cannot use is a client mistake
            (``cloneEnvironment`` → ``NOT_FOUND``) or an attributable skip
            (FR-004). The ``createEnvironmentBackup`` mutation does not expose
            this argument; the clone path is its only caller.
        prefect_manager: Injected dispatcher for the per-constituent
            ``EXECUTE_BACKUP`` flows.

    Returns:
        The persisted parent row, reloaded so its constituents are attached.

    Raises:
        EnvironmentNotFoundError: When ``environment_id`` does not exist.
        EnvironmentOperationInProgressError: When an environment-level backup
            or restore is already in flight for this environment (FR-009).
        EnvironmentBackupNotFoundError: When the snapshot was deleted while the
            fan-out was still dispatching — legal, because
            :func:`delete_environment_backup` has no status guard (FR-010).
    """
    async with uow:
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment with id {environment_id} not found."
            )

        await _guard_no_environment_operation_in_progress(environment_id, uow)

        registration = await register_environment_backup(
            environment=environment,
            uow=uow,
            name=name,
            deployment_ids=deployment_ids,
        )
        environment_backup = registration.environment_backup
        environment_backup_id = environment_backup.id

        # The single commit: from here on the capture is complete and durable,
        # and nothing has been dispatched yet (ADR-0012).
        await uow.commit()
        await uow.session.refresh(environment_backup)

    dispatched, dispatch_failed = await dispatch_constituent_backups(
        registration.pending_dispatch, prefect_manager, environment_backup_id
    )

    async with uow:
        refreshed = await uow.environment_backups.get(environment_backup_id)
    if refreshed is None:
        # ``delete_environment_backup`` deliberately has no status guard (spec
        # FR-010): an operator clearing an in-flight snapshot while this
        # fan-out was still dispatching really can delete the row underneath
        # us. That is a NOT_FOUND, not an internal error.
        logger.warning(
            "env_backup_deleted_during_fanout environment_id={} "
            "environment_backup_id={}",
            environment_id,
            environment_backup_id,
        )
        raise EnvironmentBackupNotFoundError(
            f"Environment backup {environment_backup_id} was deleted while its "
            "fan-out was still running"
        )

    # One audit entry per fan-out, matching ``env_config_fanout_dispatched``
    # (research.md D1 amendment). ``evaluated`` counts every deployment
    # considered, including the internal / instance-less ones filtered out and
    # the ones an explicit ``deployment_ids`` selection excluded.
    logger.info(
        "env_backup_fanout_dispatched environment_id={} environment_backup_id={} "
        "evaluated={} dispatched={} conflict={} dispatch_failed={}",
        environment_id,
        environment_backup_id,
        registration.evaluated,
        dispatched,
        len(registration.errors),
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


class _PendingRestoreDispatch(NamedTuple):
    """A committed constituent restore awaiting its ``EXECUTE_RESTORE`` dispatch.

    The restore counterpart of :class:`_PendingBackupDispatch`: collected inside
    the capture transaction, consumed after it commits.
    """

    restore_id: UUID
    backup_id: UUID
    deployment_id: UUID
    target_namespace: str


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
       capabilities, create one constituent ``Restore`` row per usable
       constituent (recording any late skip discovered while doing so), and
       **commit all of it once, before any dispatch** (ADR-0012);
    4. fan the reverted config out to the eligible deployments that are
       *not* receiving a constituent restore — restored deployments come
       back with their backup-time state, so redeploying them concurrently
       would race the Velero restore on the same namespace;
    5. dispatch one ``EXECUTE_RESTORE`` per created constituent restore.

    Steps 2, 3 and the row creation of step 5 share **one** transaction for the
    same reason ``create_environment_backup`` does: a ``CancelledError`` (client
    disconnect, request timeout) escapes the per-constituent ``except
    Exception``, so persisting the late skips after the loop could publish a
    restore that silently dropped them (spec FR-007), and a committed parent
    with no constituent rows yet does not block a second environment-level
    operation (spec FR-009).

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
        EnvironmentRestoreNotFoundError: When the restore record was deleted
            (via its snapshot's cascade) while the fan-out was still
            dispatching — legal, because that cascade has no status guard
            (FR-010).
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

        environment_restore_id = uuid4()
        environment_restore = await uow.environment_restores.create(
            EnvironmentRestore(
                id=environment_restore_id,
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

        # Step 5, creation half — one constituent restore per usable
        # constituent, in the same transaction as the revert and the parent row.
        late_skips: list[SkippedConstituent] = []
        pending_dispatch: list[_PendingRestoreDispatch] = []
        # The constituents join this transaction instead of opening one each.
        constituent_uow = _SharedTransaction(uow)
        for constituent in usable:
            snapshot = constituent.snapshot
            try:
                _, target_namespace, _ = await resolve_backup_target(
                    snapshot.instance_id, constituent_uow
                )
                # ``resolve_backup_target`` degrades to an empty namespace when
                # the instance row cannot be walked; the deployment (alive as of
                # classification) still names its own namespace.
                target_namespace = (
                    target_namespace or f"{_NAMESPACE_PREFIX}{snapshot.deployment_id}"
                )
                restore, deployment_id = await create_restore(
                    backup_id=constituent.backup_id,
                    target_namespace=target_namespace,
                    uow=constituent_uow,
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
                logger.exception(
                    "env_restore_constituent_error environment_restore_id={} "
                    "deployment_id={}",
                    environment_restore_id,
                    snapshot.deployment_id,
                )
                late_skips.append(
                    _skip(snapshot, f"restore could not be created: {exc}")
                )
                continue

            pending_dispatch.append(
                _PendingRestoreDispatch(
                    restore_id=restore.id,
                    backup_id=constituent.backup_id,
                    deployment_id=deployment_id,
                    target_namespace=target_namespace,
                )
            )

        if late_skips:
            environment_restore.skipped_constituents = [
                *(environment_restore.skipped_constituents or []),
                *(entry.model_dump(mode="json") for entry in late_skips),
            ]

        # The single commit: the revert, the restore record, every constituent
        # restore row and every recorded skip become durable together, and
        # nothing has been dispatched yet (ADR-0012). A crash mid-fan-out
        # leaves a re-submittable operation rather than a half-applied config.
        await uow.commit()
        await uow.session.refresh(environment_restore)

    # Every classified-usable constituent, not just the ones that got a row: a
    # late skip means the deployment began its own restore, so redeploying it
    # would race that restore for the same reason.
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

    # Step 5, dispatch half — the rows already exist and are committed.
    restored = 0
    dispatch_failed = 0
    for pending in pending_dispatch:
        try:
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_RESTORE,
                parameters={
                    "restore_id": str(pending.restore_id),
                    "backup_id": str(pending.backup_id),
                    "deployment_id": str(pending.deployment_id),
                    "target_namespace": pending.target_namespace,
                },
            )
        except Exception as exc:  # noqa: BLE001 — a dispatch failure is not a lost row
            # The Restore row exists, so this shows up as a failed constituent
            # rather than a skip — same contract as the ``createRestore`` mutation.
            dispatch_failed += 1
            logger.warning(
                "env_restore_dispatch_error environment_restore_id={} restore_id={} "
                "restore record created but Velero execution not triggered, "
                "marking the restore and its deployment failed: {}",
                environment_restore_id,
                pending.restore_id,
                exc,
            )
            await settle_undispatched_restore(
                restore_id=pending.restore_id,
                deployment_id=pending.deployment_id,
                uow=uow,
                error=(
                    "the restore was created but its workflow was never "
                    f"dispatched: {exc}"
                ),
            )
            continue
        restored += 1

    async with uow:
        refreshed = await uow.environment_restores.get(environment_restore_id)
    if refreshed is None:
        # The cascade behind ``delete_environment_backup`` has no status guard
        # (spec FR-010), so an operator clearing the snapshot while this
        # fan-out was still dispatching really can delete this row underneath
        # us. Mirrors ``create_environment_backup``: NOT_FOUND, not an
        # internal error.
        logger.warning(
            "env_restore_deleted_during_fanout environment_id={} "
            "environment_restore_id={}",
            environment_id,
            environment_restore_id,
        )
        raise EnvironmentRestoreNotFoundError(
            f"Environment restore {environment_restore_id} was deleted while its "
            "fan-out was still running"
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

    **One guard does exist, and only one** (010 spec FR-008, research D9): a
    snapshot a clone is still *capturing into* cannot be deleted, because that
    is the single window in which deletion strands work nothing can be
    attributed to. Once the capture is terminal deletion is allowed again and
    becomes the escape hatch for a stuck clone —
    :func:`~styrmin_backend.services.backup.clone.detach_clones_from_environment_backup`
    releases the foreign key and attributes the deletion on every referencing
    clone, fatally iff that clone was still non-terminal.

    Args:
        environment_backup_id: The snapshot to delete.
        uow: Unit of work supplying the repositories.

    Raises:
        EnvironmentBackupNotFoundError: When the snapshot does not exist.
        EnvironmentBackupInUseByCloneError: When a clone's capture of this
            snapshot is still in flight (010 spec FR-008).
    """
    # Deferred: ``services.backup.clone`` imports this module for the shared
    # status vocabulary, so hoisting these would make the two a cycle — same
    # reason ``guard_no_clone_occupying_environment`` defers its import.
    from styrmin_backend.services.backup.clone import (
        detach_clones_from_environment_backup,
        guard_no_clone_capturing_environment_backup,
    )

    async with uow:
        environment_backup = await uow.environment_backups.get(environment_backup_id)
        if environment_backup is None:
            raise EnvironmentBackupNotFoundError(
                f"Environment backup {environment_backup_id} not found"
            )
        # Also the snapshot point for clone terminality: the cascade below
        # destroys the constituent backups and their restores, both of which the
        # clone derivation reads, so "was this clone terminal when the operator
        # asked?" can only be answered here.
        clone_terminality = await guard_no_clone_capturing_environment_backup(
            environment_backup_id, uow
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
        # Before the parent row: ``environmentclone.environment_backup_id`` is
        # nullable but carries no ``ON DELETE SET NULL``, so a referencing clone
        # has to release it first — and the marker the derivation reads has to
        # be written in the same transaction as the release.
        detached_clones = await detach_clones_from_environment_backup(
            environment_backup_id, uow, clone_terminality
        )
        await uow.environment_backups.delete(environment_backup)
        await uow.commit()

    logger.info(
        "env_backup_deleted environment_id={} environment_backup_id={} "
        "constituents_deleted={} environment_restores_deleted={} "
        "clones_detached={}",
        environment_id,
        environment_backup_id,
        deleted_constituents,
        len(environment_restores),
        detached_clones,
    )


async def delete_environment_backups_for_environment(
    environment_id: UUID, uow: UnitOfWork
) -> int:
    """Cascade-delete every snapshot of an environment (spec FR-015).

    Called by :func:`~styrmin_backend.services.environments.delete_environment`
    before the environment row goes: ``environmentbackup.environment_id`` is a
    non-nullable FK, so without this the delete fails on a constraint violation
    surfacing as an opaque ``INTERNAL_ERROR`` (critique E2).

    Inherits :func:`delete_environment_backup`'s FR-008 guard, which is why
    ``delete_environment`` settles the environment's clone records *first*: a
    clone whose capture is still in flight would otherwise refuse the very
    snapshot this cascade has to remove (010 research D9).

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
