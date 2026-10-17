"""Prefect workflow template for the environment clone (010 research D4).

``EXECUTE_ENVIRONMENT_CLONE`` is the platform's first orchestration that has to
**wait**: every other dispatch is fire-and-forget, but a clone must not
materialise anything until the capture it is built from reaches a restorable
terminal status (spec FR-002). It is an INTERNAL flow (styrmin-work-pool, DB
access, no Kubernetes) and it writes the clone record directly, exactly as
``execute_restore_workflow`` writes restore/deployment status.

Sequence:

1. poll the backing capture's **derived** status until terminal;
2. gate: ``FAILED`` capture → one fatal ``capture_failed`` entry and nothing
   materialises; ``COMPLETED``/``PARTIAL`` → proceed with the usable
   constituents (FR-002). A constituent whose affinity terms name a deployment
   whose capture failed fails too (027 FR-005);
3. create the environment from the captured config with the clone's override
   merged over it and capabilities recomputed (FR-006, ADR-0027);
4. create one counterpart deployment per usable constituent, pinned to the
   captured driver version, in ``RESTORING``, with no initial reconcile
   (research D5). Each counterpart's id is chosen before step 3, so the copied
   affinity terms name the counterparts, and the counterparts are created in
   ``order_counterparts`` order (027 plan D-007);
5. dispatch one cross-target restore per counterpart (research D2) and record
   the attribution.

The clone's own status is never written — it is derived on every read
(FR-009). What this flow writes is the *inputs* to that derivation:
``created_environment_id``, ``deployment_results`` and ``clone_errors``.

The record vanishing mid-flight is a normal outcome, not an error: deleting the
source environment removes non-terminal clone records (research D9). Every step
therefore tolerates ``EnvironmentCloneNotFoundError`` and ends the flow quietly,
mirroring ``execute_restore_workflow``'s ``RestoreNotFoundError`` handling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Mapping, NamedTuple, Sequence
from uuid import UUID, uuid4

from prefect import flow
from prefect.logging import get_run_logger

from styrmin_backend import config
from styrmin_backend.db.models import BackupStatus, EnvironmentClone, RestoreStatus
from styrmin_backend.services.backup.clone import (
    CAPTURE_IN_FLIGHT_GUARD_SECONDS,
    CLONE_REASON_BACKUP_DELETED,
    CLONE_REASON_BACKUP_EXPIRED,
    CLONE_REASON_BACKUP_NOT_COMPLETED,
    CLONE_REASON_CAPTURE_FAILED,
    CLONE_REASON_CAPTURE_UNUSABLE,
    CLONE_REASON_DRIVER_VERSION_GONE,
    CLONE_REASON_REFERENCED_DEPLOYMENT_NOT_CLONED,
    CLONE_STEP_CAPTURE_FAILED,
    CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
    CLONE_STEP_REFERENCED_DEPLOYMENT_NOT_CLONED,
    CLONE_STEP_TARGET_NAME_TAKEN,
    CloneDeploymentResult,
    CloneError,
    EnvironmentCloneDeploymentOutcome,
    cascade_reference_failures,
    derive_clone_capture_status,
    merge_environment_config,
    order_counterparts,
)
from styrmin_backend.services.backup.environment import (
    RESTORABLE_ENVIRONMENT_BACKUP_STATUSES,
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    ConstituentError,
    DeploymentSnapshot,
    EnvironmentOperationStatus,
    _backup_expires_at,
)
from styrmin_backend.services.backup.service import (
    create_restore,
    update_restore_status,
)
from styrmin_backend.services.deployment import deploy_application
from styrmin_backend.services.environments import create_environment
from styrmin_backend.services.exceptions import (
    EnvironmentAlreadyExistsError,
    EnvironmentCloneNotFoundError,
    UnclonedDeploymentReferenceError,
    UnclonedReference,
)
from styrmin_backend.services.scheduling.references import (
    referenced_deployment_ids,
    remap_deployment_references,
)
from styrmin_backend.services.unit_of_work import UnitOfWork, get_unit_of_work
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.models import PrefectAction

# The restore flow's own "this restore is over" writer, reused rather than
# reimplemented so an undispatched restore lands in exactly the state a failed
# one does. Private by name, shared by intent — see
# ``_settle_undispatched_restore``.
from styrmin_backend.workflows.templates.backup import _set_deployment_status_failed

#: How long the flow waits for the capture to reach a terminal derived status.
#: Matches the per-restore budget in ``execute_restore_workflow`` — a capture is
#: a fan-out of Velero backups and can legitimately run for hours on a large
#: environment. Exceeding it fails the *flow run* on purpose and leaves the
#: clone non-terminal: research D9 makes that the operator-visible state, with
#: backup deletion as the escape hatch.
#:
#: It **is** the FR-008 guard's window (``CAPTURE_IN_FLIGHT_GUARD_SECONDS``)
#: rather than merely equal to it, because the guard's justification is "this
#: flow is still waiting": the moment that stops being true, the escape hatch
#: has to open. Two independently maintained numbers could disagree, and the
#: disagreement would either wedge the backup or unprotect a live capture.
CAPTURE_POLL_TIMEOUT_SECONDS = CAPTURE_IN_FLIGHT_GUARD_SECONDS

#: Prefix of the per-deployment namespace a counterpart's restore targets.
_NAMESPACE_PREFIX = "styrmin-"


async def _load_clone(clone_id: UUID, uow: UnitOfWork) -> EnvironmentClone:
    """Load a clone record, raising the typed not-found error when it is gone."""
    async with uow:
        clone = await uow.environment_clones.get(clone_id)
        if clone is None:
            raise EnvironmentCloneNotFoundError(
                f"Environment clone {clone_id} not found"
            )
        return clone


def _read_results(clone: EnvironmentClone) -> list[CloneDeploymentResult]:
    """Read the attribution entries this flow can work with, as typed models.

    An entry that will not parse is skipped *here* — the flow has nothing it
    could do with it — but it is never removed from the record:
    :func:`_merge_results` writes this list back **into** the stored one rather
    than over it, so an unreadable entry stays exactly where it was. That
    matters because the derivation counts it (as a failure), which is what stops
    a clone from reading ``COMPLETED`` with a source deployment nobody can
    account for (spec SC-003).
    """
    results: list[CloneDeploymentResult] = []
    for entry in clone.deployment_results or []:
        try:
            results.append(CloneDeploymentResult.model_validate(entry))
        except Exception:  # noqa: BLE001 — a malformed entry must not stop the clone
            get_run_logger().warning(
                "Keeping but not updating an unreadable deployment_results entry "
                "on clone %s: %r",
                clone.id,
                entry,
            )
    return results


def _merge_results(
    stored: Sequence[Any] | None, results: Sequence[CloneDeploymentResult]
) -> list[Any] | None:
    """Write the flow's typed entries back into the stored list, in place.

    The flow only ever *updates* entries the mutation already registered, so
    rebinding ``deployment_results`` to the flow's own list would delete
    anything the flow could not read — the exact entry the coverage identity
    must not lose (spec SC-003), and the one whose disappearance would leave the
    Prefect log as the only record it ever existed.

    Matching is by ``deployment_id``. An entry the flow does not know about is
    kept verbatim (unreadable, or written by a future writer); a result with no
    stored counterpart is appended, so the merge is never lossy in either
    direction.
    """
    dumped = {
        str(result.deployment_id): result.model_dump(mode="json") for result in results
    }
    merged: list[Any] = []
    matched: set[str] = set()
    for entry in stored or []:
        key = (
            str(entry.get("deployment_id"))
            if isinstance(entry, dict) and entry.get("deployment_id") is not None
            else None
        )
        if key is not None and key in dumped:
            merged.append(dumped[key])
            matched.add(key)
            continue
        merged.append(entry)
    merged.extend(payload for key, payload in dumped.items() if key not in matched)
    return merged or None


async def _save_progress(
    clone_id: UUID,
    *,
    results: Sequence[CloneDeploymentResult] | None = None,
    error: CloneError | None = None,
    created_environment_id: UUID | None = None,
) -> None:
    """Persist the derivation inputs this flow owns, in one transaction.

    Re-reads the record first so a concurrent writer (a deletion cascade
    appending its own ``clone_errors`` entry) is never clobbered wholesale, and
    merges the attribution entries into what is stored rather than replacing the
    list (see :func:`_merge_results`).
    """
    async with get_unit_of_work() as uow:
        clone = await uow.environment_clones.get(clone_id)
        if clone is None:
            raise EnvironmentCloneNotFoundError(
                f"Environment clone {clone_id} not found"
            )
        if results is not None:
            clone.deployment_results = _merge_results(clone.deployment_results, results)
        if error is not None:
            clone.clone_errors = [
                *(clone.clone_errors or []),
                error.model_dump(mode="json"),
            ]
        if created_environment_id is not None:
            clone.created_environment_id = created_environment_id
        await uow.environment_clones.save(clone)
        await uow.commit()


def _fail_pending(
    results: Sequence[CloneDeploymentResult], reason: str
) -> list[CloneDeploymentResult]:
    """Turn every still-``PENDING`` entry into a ``FAILED`` one.

    Called when the clone stops before those deployments could be attempted, so
    a terminal clone never carries a ``PENDING`` entry (the coverage identity in
    ``data-model.md``).
    """
    updated: list[CloneDeploymentResult] = []
    for result in results:
        if result.outcome is EnvironmentCloneDeploymentOutcome.PENDING:
            updated.append(
                result.model_copy(
                    update={
                        "outcome": EnvironmentCloneDeploymentOutcome.FAILED,
                        "reason": reason,
                    }
                )
            )
            continue
        updated.append(result)
    return updated


async def _await_capture_terminal(
    clone_id: UUID,
) -> tuple[EnvironmentOperationStatus | None, EnvironmentClone]:
    """Poll the capture's derived status until it stops moving (FR-002).

    Returns:
        ``(capture_status, clone)``. ``capture_status`` is ``None`` when the
        capture is not reachable — it was deleted, and that path already
        attributed the deletion on the record (research D9), so the flow has
        nothing left to decide.

    One unit of work serves the whole loop and is closed when the poll ends,
    rather than opening up to ``CAPTURE_POLL_TIMEOUT_SECONDS /
    poll_retry_delay_seconds`` sessions — 720 — for a single clone. The
    ``rollback`` between iterations is what makes reuse *correct* rather than
    merely cheap: the session's identity map would otherwise keep serving the
    first read of the capture, and the poll would never see it terminalise.

    Raises:
        EnvironmentCloneNotFoundError: When the record vanished mid-flight.
        RuntimeError: When the capture is still non-terminal after
            :data:`CAPTURE_POLL_TIMEOUT_SECONDS`. Failing the flow run rather
            than the clone is deliberate: the capture may still finish, and the
            clone stays non-terminal until an operator uses an escape hatch —
            which, past this same budget, includes deleting the capture itself
            (the FR-008 guard stops protecting it, see
            ``CAPTURE_IN_FLIGHT_GUARD_SECONDS``).
    """
    logger = get_run_logger()
    poll_delay = config.SETTINGS.agent.poll_retry_delay_seconds
    elapsed = 0
    async with get_unit_of_work() as uow:
        while True:
            clone = await _load_clone(clone_id, uow)
            capture_status = derive_clone_capture_status(clone.environment_backup)
            if capture_status is None:
                logger.info(
                    "Clone %s has no reachable capture; ending quietly", clone_id
                )
                return None, clone
            if capture_status in TERMINAL_ENVIRONMENT_OPERATION_STATUSES:
                return capture_status, clone
            if elapsed >= CAPTURE_POLL_TIMEOUT_SECONDS:
                raise RuntimeError(
                    f"Environment clone {clone_id}: its capture was still "
                    f"{capture_status.value} after {CAPTURE_POLL_TIMEOUT_SECONDS}s"
                )
            # End this read's transaction before sleeping so the connection returns
            # to the pool, and the next turn re-reads instead of the identity map.
            # Never after a ``return``: callers must not get an expired clone.
            await uow.rollback()
            await asyncio.sleep(poll_delay)
            elapsed += poll_delay


class _UsableConstituent:
    """A captured deployment whose backup can be restored into a counterpart."""

    __slots__ = ("snapshot", "backup_id")

    def __init__(self, snapshot: DeploymentSnapshot, backup_id: UUID) -> None:
        self.snapshot = snapshot
        self.backup_id = backup_id


def _classify_captured_constituents(
    clone: EnvironmentClone, now: datetime
) -> tuple[list[_UsableConstituent], dict[UUID, str]]:
    """Split the capture into restorable constituents and per-deployment failures.

    Deliberately **not** ``_classify_constituents``: that one reads the *live
    source* deployment (gone? busy restoring?) because an in-place restore
    targets it. A clone must never re-read the source after capture (FR-007)
    and does not care what became of it — only whether the captured data is
    usable. The expiry check is kept for the same reason it exists there:
    Velero garbage-collects expired data without touching the row, so a
    ``COMPLETED`` constituent can still have nothing behind it.

    Returns:
        ``(usable, failures)`` where ``failures`` maps a source deployment id to
        the reason its data cannot be used.
    """
    environment_backup = clone.environment_backup
    if environment_backup is None:
        return [], {}

    backups_by_instance = {
        backup.instance_id: backup for backup in environment_backup.backups
    }
    errored_deployment_ids = {
        ConstituentError.model_validate(raw).deployment_id
        for raw in environment_backup.constituent_errors or []
    }

    usable: list[_UsableConstituent] = []
    failures: dict[UUID, str] = {}
    for raw_snapshot in environment_backup.deployment_snapshots or []:
        snapshot = DeploymentSnapshot.model_validate(raw_snapshot)
        backup = backups_by_instance.get(snapshot.instance_id)
        if snapshot.deployment_id in errored_deployment_ids:
            failures[snapshot.deployment_id] = CLONE_REASON_CAPTURE_FAILED
        elif backup is None:
            failures[snapshot.deployment_id] = CLONE_REASON_BACKUP_DELETED
        elif backup.status != BackupStatus.COMPLETED:
            failures[snapshot.deployment_id] = CLONE_REASON_BACKUP_NOT_COMPLETED
        elif (
            expires_at := _backup_expires_at(backup)
        ) is not None and expires_at < now:
            failures[snapshot.deployment_id] = CLONE_REASON_BACKUP_EXPIRED
        else:
            usable.append(_UsableConstituent(snapshot=snapshot, backup_id=backup.id))
    return usable, failures


async def _resolve_pinned_driver_version(
    snapshot: DeploymentSnapshot, uow: UnitOfWork
) -> UUID | None:
    """Resolve the driver version row the snapshot recorded (research D5).

    Identity is ADR-0053's: driver name + version + provenance fingerprint
    (``content_hash`` for local sources, ``source_commit_sha`` for git). Two
    rows can share a version string and differ by fingerprint, so the
    fingerprint is matched when the snapshot recorded one; a snapshot from
    before the fingerprint existed falls back to the version string alone.

    Returns:
        The driver version id, or ``None`` when the captured driver content is
        no longer loaded — the deployment is then attributed ``failed`` and the
        rest of the clone proceeds.
    """
    async with uow:
        driver = await uow.application_drivers.get_by_name(name=snapshot.driver_name)
        if driver is None:
            return None
        candidates = [
            version
            for version in driver.versions
            if version.version == snapshot.driver_version
        ]
        if snapshot.driver_fingerprint is not None:
            candidates = [
                version
                for version in candidates
                if (version.content_hash or version.source_commit_sha)
                == snapshot.driver_fingerprint
            ]
        return candidates[0].id if candidates else None


def _reference_not_cloned_reason(
    named_id: UUID, source_names: Mapping[UUID, str]
) -> str:
    return CLONE_REASON_REFERENCED_DEPLOYMENT_NOT_CLONED.format(
        name=source_names.get(named_id, str(named_id))
    )


def _reference_not_cloned_error(
    unmapped: Mapping[UUID, list[str]], source_names: Mapping[UUID, str]
) -> CloneError:
    """The fatal error for an environment config that names a deployment the clone lost."""
    return CloneError(
        step=CLONE_STEP_REFERENCED_DEPLOYMENT_NOT_CLONED,
        error=str(_uncloned_reference_error(unmapped, source_names)),
        fatal=True,
    )


def _log_reference_not_cloned(
    clone_id: UUID, deployment_id: UUID, named_deployment_id: UUID
) -> None:
    get_run_logger().warning(
        "env_clone_reference_not_cloned environment_clone_id=%s deployment_id=%s "
        "named_deployment_id=%s",
        clone_id,
        deployment_id,
        named_deployment_id,
    )


def _uncloned_reference_error(
    unmapped: Mapping[UUID, list[str]], source_names: Mapping[UUID, str]
) -> UnclonedDeploymentReferenceError:
    return UnclonedDeploymentReferenceError(
        [
            UnclonedReference(
                deployment_id=deployment_id,
                deployment_name=source_names.get(deployment_id),
                paths=paths,
            )
            for deployment_id, paths in unmapped.items()
        ]
    )


async def _create_counterpart(
    clone: EnvironmentClone,
    created_environment_id: UUID,
    constituent: _UsableConstituent,
    *,
    counterpart_ids: Mapping[UUID, UUID],
    upcoming_deployments: Mapping[UUID, str],
    source_names: Mapping[UUID, str],
) -> UUID:
    """Create one counterpart deployment from a captured snapshot.

    Everything the counterpart needs comes from the snapshot, never from the
    live source (FR-005 ∧ FR-007): the driver version pin, the application
    version, the config and parameters, the resolved service-name overrides,
    and the Helm release name it adopts so its restore's data lands under an
    identity Helm already agrees with (research D2).

    The counterpart gets the id that ``counterpart_ids`` gives its source
    deployment, and each affinity term of the copied config names the
    counterpart of the deployment it named (027 FR-008).
    ``upcoming_deployments`` holds every counterpart that has not failed, by id
    with its name, so a term may name one that is not created yet.

    Returns:
        The counterpart's id, the one chosen in advance, as ``deploy_application``
        returns it. It is never looked up by name, because a user can rename the
        counterpart as soon as it is committed (#493, ADR-073).

    Raises:
        UnclonedDeploymentReferenceError: When an affinity term names a
            deployment that has no counterpart.
        RuntimeError: When the captured driver version no longer resolves.
    """
    snapshot = constituent.snapshot
    counterpart_id = counterpart_ids[snapshot.deployment_id]
    config, unmapped = remap_deployment_references(
        snapshot.config, counterpart_ids, path_prefix="deployment.config"
    )
    if unmapped:
        raise _uncloned_reference_error(unmapped, source_names)

    async with get_unit_of_work() as uow:
        driver_version_id = await _resolve_pinned_driver_version(snapshot, uow)
    if driver_version_id is None:
        raise RuntimeError(CLONE_REASON_DRIVER_VERSION_GONE)

    assert clone.created_by_user_id is not None, (
        "clone_environment records the invoking user; Deployment requires one"
    )

    async with get_unit_of_work() as uow:
        return await deploy_application(
            driver_name=snapshot.driver_name,
            version=snapshot.application_version,
            environment_id=created_environment_id,
            uow=uow,
            created_by_user_id=clone.created_by_user_id,
            deployment_config=config,
            deployment_parameters=snapshot.parameters,
            deployment_name=snapshot.deployment_name,
            service_name_overrides=snapshot.service_name_overrides,
            driver_version_id=driver_version_id,
            skip_initial_reconcile=True,
            release_reference=(
                snapshot.release_reference
                or f"{_NAMESPACE_PREFIX}{snapshot.deployment_id}"
            ),
            deployment_id=counterpart_id,
            upcoming_deployments=dict(upcoming_deployments),
        )


class _CounterpartError(Exception):
    """A per-deployment clone failure that names what it already created.

    Counterpart failures are isolated per deployment (research D5), so the
    attribution entry is all the operator gets — and everything the step created
    before it failed has to be *on* that entry. An orphaned counterpart or
    restore row nobody can name is an orphan nobody can clean up, and the clone
    itself reads terminal and settled while it sits there.

    ``str(...)`` is the reason recorded on the entry, exactly as for any other
    exception the loop catches.
    """

    def __init__(
        self,
        message: str,
        *,
        counterpart_deployment_id: UUID | None = None,
        restore_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.counterpart_deployment_id = counterpart_deployment_id
        self.restore_id = restore_id


async def _settle_undispatched_restore(
    restore_id: UUID, deployment_id: UUID, *, error: str
) -> None:
    """Close out a restore row whose dispatch never happened.

    ``create_restore`` **commits** a ``PENDING`` row and parks the counterpart in
    ``RESTORING`` before the flow run is dispatched, so a dispatch failure
    leaves behind a restore nothing will ever pick up. Left alone that row is
    worse than invisible: ``find_in_flight_restore`` counts ``PENDING`` as in
    flight, so it refuses **every** future restore into that counterpart —
    naming a restore that never ran — and no ``PENDING``-restore reaper exists
    anywhere to settle it.

    Settled the way ``execute_restore_workflow`` settles a restore it could not
    finish (restore ``FAILED`` with the reason, counterpart ``FAILED``), so a
    dispatch failure and a Velero failure leave the same recoverable state.
    """
    logger = get_run_logger()
    async with get_unit_of_work() as uow:
        try:
            await update_restore_status(
                restore_id=restore_id,
                status=RestoreStatus.FAILED,
                uow=uow,
                error_message=error,
            )
        except Exception:  # noqa: BLE001 — the counterpart flip below still matters
            logger.exception(
                "env_clone_restore_settle_error restore_id=%s could not be marked "
                "FAILED after its dispatch failed",
                restore_id,
            )
    async with get_unit_of_work() as uow:
        await _set_deployment_status_failed(
            deployment_id=deployment_id, uow=uow, error_message=error
        )


async def _dispatch_cross_target_restore(
    constituent: _UsableConstituent, counterpart_deployment_id: UUID
) -> UUID:
    """Create and dispatch the cross-target restore for one counterpart.

    The counterpart's namespace is the restore target; the source deployment
    travels separately so the flow can derive the Velero *source* namespace and
    the restored CR's name without the status writes following it (research
    D2.1/D2.2). ``target_instance_id`` is left unset — ``create_restore``
    derives it from the counterpart's active instance.

    The two halves are not atomic and cannot be: the row has to exist before it
    can be dispatched. So a dispatch failure is settled rather than propagated
    raw — the row is closed out (:func:`_settle_undispatched_restore`) and the
    error carries both ids so the attribution entry can name what was left
    behind.

    Returns:
        The restore id.

    Raises:
        _CounterpartError: When the restore row was created but its flow run
            could not be dispatched.
    """
    target_namespace = f"{_NAMESPACE_PREFIX}{counterpart_deployment_id}"
    async with get_unit_of_work() as uow:
        restore, status_target_deployment_id = await create_restore(
            backup_id=constituent.backup_id,
            target_namespace=target_namespace,
            uow=uow,
            target_deployment_id=counterpart_deployment_id,
        )

    manager = get_manager()
    try:
        await manager.run_action(
            action=PrefectAction.EXECUTE_RESTORE,
            parameters={
                "restore_id": str(restore.id),
                "backup_id": str(constituent.backup_id),
                "deployment_id": str(status_target_deployment_id),
                "target_namespace": target_namespace,
                "source_deployment_id": str(constituent.snapshot.deployment_id),
            },
        )
    except Exception as exc:  # noqa: BLE001 — settled and attributed, never lost
        error = f"the cross-target restore was created but never dispatched: {exc}"
        await _settle_undispatched_restore(
            restore.id, status_target_deployment_id, error=error
        )
        raise _CounterpartError(
            error,
            counterpart_deployment_id=counterpart_deployment_id,
            restore_id=restore.id,
        ) from exc
    return restore.id


class _CreatedEnvironment(NamedTuple):
    """The environment a clone created, with its merged config before the remap."""

    environment_id: UUID
    merged_config: dict[str, Any]


async def _create_cloned_environment(
    clone: EnvironmentClone,
    results: list[CloneDeploymentResult],
    counterpart_ids: Mapping[UUID, UUID],
    upcoming_deployments: Mapping[UUID, str],
) -> _CreatedEnvironment | None:
    """Create the cloned environment, or attribute why it could not be created.

    The config is the capture's, with the clone's cleared fields dropped and its
    override merged over the rest (research D7); ``create_environment``
    recomputes capabilities rather than copying them (ADR-0027). Each affinity
    term of the merged config then names the counterpart that ``counterpart_ids``
    gives the deployment it named, and ``upcoming_deployments`` (the
    counterparts, by id with their names) lets ``create_environment`` accept it.
    A term that names a deployment with no counterpart, because its capture
    failed, writes the fatal ``referenced_deployment_not_cloned`` error instead.

    Returns:
        The created environment's id and the merged config with the source ids,
        or ``None`` when a fatal ``clone_errors`` entry was written instead (the
        clone derives ``FAILED``).
    """
    logger = get_run_logger()
    source_environment = clone.source_environment
    if source_environment is None:
        # Non-terminal clones are deleted with their source (research D9), so
        # reaching here means the record outlived the source by a race. Nothing
        # can be created without a cluster to create it in.
        await _save_progress(
            clone.id,
            results=_fail_pending(results, CLONE_REASON_CAPTURE_UNUSABLE),
            error=CloneError(
                step=CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
                error="the source environment no longer exists",
                fatal=True,
            ),
        )
        return None

    environment_backup = clone.environment_backup
    captured_config = (
        environment_backup.environment_config if environment_backup else None
    )
    try:
        merged_config = merge_environment_config(
            captured_config,
            clone.config_override,
            clone.cleared_config_fields,
        )
    except Exception as exc:  # noqa: BLE001 — attributed, never a crashed flow
        await _save_progress(
            clone.id,
            results=_fail_pending(results, CLONE_REASON_CAPTURE_UNUSABLE),
            error=CloneError(
                step=CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
                error=f"the cloned environment config is invalid: {exc}",
                fatal=True,
            ),
        )
        return None

    remapped_config, unmapped = remap_deployment_references(
        merged_config, counterpart_ids, path_prefix="environment.config"
    )
    if unmapped:
        # A term names a deployment whose capture failed: no environment (027 FR-005).
        logger.error(
            "env_clone_environment_reference_not_cloned environment_clone_id=%s "
            "named_deployment_ids=%s",
            clone.id,
            ",".join(str(named_id) for named_id in unmapped),
        )
        source_names = {r.deployment_id: r.deployment_name for r in results}
        await _save_progress(
            clone.id,
            results=_fail_pending(
                results,
                _reference_not_cloned_reason(next(iter(unmapped)), source_names),
            ),
            error=_reference_not_cloned_error(unmapped, source_names),
        )
        return None

    try:
        async with get_unit_of_work() as uow:
            environment = await create_environment(
                name=clone.name,
                cluster_id=source_environment.cluster_id,
                uow=uow,
                config=remapped_config,
                upcoming_deployments=upcoming_deployments,
            )
    except EnvironmentAlreadyExistsError as exc:
        # The name was free when the mutation validated it and is taken now
        # (spec FR-011's TOCTOU case). Attributed, terminal, no side effects.
        logger.warning(
            "Clone %s lost its target name %r before the environment was created",
            clone.id,
            clone.name,
        )
        await _save_progress(
            clone.id,
            results=_fail_pending(results, CLONE_REASON_CAPTURE_UNUSABLE),
            error=CloneError(
                step=CLONE_STEP_TARGET_NAME_TAKEN,
                error=str(exc),
                fatal=True,
            ),
        )
        return None
    except Exception as exc:  # noqa: BLE001 — attributed, never a crashed flow
        await _save_progress(
            clone.id,
            results=_fail_pending(results, CLONE_REASON_CAPTURE_UNUSABLE),
            error=CloneError(
                step=CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
                error=str(exc),
                fatal=True,
            ),
        )
        return None

    # Committed before any counterpart exists: the created environment is the
    # discard handle for everything that follows (spec SC-005), so it must be
    # attributed on the record the moment it exists.
    await _save_progress(clone.id, created_environment_id=environment.id)
    return _CreatedEnvironment(environment.id, merged_config)


@flow(name="execute_environment_clone")
async def execute_environment_clone_workflow(clone_id: str) -> None:
    """Drive an environment clone from its capture to its counterparts.

    See the module docstring for the sequence. The flow writes only derivation
    inputs; the clone's status is always computed (FR-009).

    Args:
        clone_id: The ``EnvironmentClone`` id (a string for Prefect
            serialisation, like every other flow parameter here).
    """
    clone_uuid = UUID(clone_id)
    logger = get_run_logger()

    try:
        await _run_environment_clone(clone_uuid)
    except EnvironmentCloneNotFoundError:
        # Deleting the source environment deletes its non-terminal clone
        # records (research D9). There is nothing left to write and nothing
        # went wrong: end quietly, exactly as ``execute_restore_workflow``
        # does when its record vanishes mid-flight.
        logger.info(
            "Environment clone %s no longer exists; ending the clone flow quietly",
            clone_uuid,
        )


async def _run_environment_clone(clone_id: UUID) -> None:
    """The clone sequence proper, with the record assumed to exist."""
    logger = get_run_logger()

    capture_status, clone = await _await_capture_terminal(clone_id)
    if capture_status is None:
        return

    results = _read_results(clone)

    if capture_status not in RESTORABLE_ENVIRONMENT_BACKUP_STATUSES:
        # FR-002: a wholly failed capture materialises nothing at all.
        logger.error(
            "Clone %s: capture derived %s; nothing will be materialised",
            clone_id,
            capture_status.value,
        )
        await _save_progress(
            clone_id,
            results=_fail_pending(results, CLONE_REASON_CAPTURE_FAILED),
            error=CloneError(
                step=CLONE_STEP_CAPTURE_FAILED,
                error=(
                    f"the environment backup capture derived {capture_status.value}"
                ),
                fatal=True,
            ),
        )
        return

    usable, failures = _classify_captured_constituents(
        clone, datetime.now(timezone.utc)
    )
    source_names = {result.deployment_id: result.deployment_name for result in results}
    cascaded = cascade_reference_failures([c.snapshot for c in usable], failures)
    for deployment_id, named_id in cascaded.items():
        _log_reference_not_cloned(clone_id, deployment_id, named_id)
        failures[deployment_id] = _reference_not_cloned_reason(named_id, source_names)
    usable = [c for c in usable if c.snapshot.deployment_id not in cascaded]

    # A capture that ended PARTIAL contributes its failed constituents here:
    # they are attributed and the clone proceeds with the rest (FR-002).
    by_deployment = {result.deployment_id: result for result in results}
    for deployment_id, reason in failures.items():
        existing = by_deployment.get(deployment_id)
        if existing is None or existing.outcome is not (
            EnvironmentCloneDeploymentOutcome.PENDING
        ):
            continue
        by_deployment[deployment_id] = existing.model_copy(
            update={
                "outcome": EnvironmentCloneDeploymentOutcome.FAILED,
                "reason": reason,
            }
        )
    results = [by_deployment.get(r.deployment_id, r) for r in results]
    await _save_progress(clone_id, results=results)

    # Ids chosen in advance, so every copied term is written once, naming the counterparts.
    counterpart_ids = {c.snapshot.deployment_id: uuid4() for c in usable}
    upcoming = {
        counterpart_ids[c.snapshot.deployment_id]: c.snapshot.deployment_name
        for c in usable
    }
    created = await _create_cloned_environment(
        clone, results, counterpart_ids, upcoming
    )
    if created is None:
        return
    created_environment_id = created.environment_id
    environment_terms = referenced_deployment_ids(
        created.merged_config, "environment.config"
    )

    by_source_id = {c.snapshot.deployment_id: c for c in usable}
    ordered = [
        by_source_id[snapshot.deployment_id]
        for snapshot in order_counterparts(
            [c.snapshot for c in usable], created.merged_config
        )
    ]

    cloned = 0
    failed_ids: set[UUID] = set()
    stopped_by: UUID | None = None
    for constituent in ordered:
        deployment_id = constituent.snapshot.deployment_id
        entry = by_deployment.get(deployment_id)
        named_failed = next(
            (
                named_id
                for named_id in referenced_deployment_ids(
                    constituent.snapshot.config, ""
                )
                if named_id in failed_ids
            ),
            None,
        )
        if named_failed is not None:
            # Fails without being created, as the capture cascade does (critique E4).
            _log_reference_not_cloned(clone_id, deployment_id, named_failed)
            if entry is not None:
                by_deployment[deployment_id] = entry.model_copy(
                    update={
                        "outcome": EnvironmentCloneDeploymentOutcome.FAILED,
                        "reason": _reference_not_cloned_reason(
                            named_failed, source_names
                        ),
                    }
                )
        else:
            counterpart_deployment_id: UUID | None = None
            restore_id: UUID | None = None
            try:
                counterpart_deployment_id = await _create_counterpart(
                    clone,
                    created_environment_id,
                    constituent,
                    counterpart_ids=counterpart_ids,
                    upcoming_deployments=upcoming,
                    source_names=source_names,
                )
                restore_id = await _dispatch_cross_target_restore(
                    constituent, counterpart_deployment_id
                )
            except Exception as exc:  # noqa: BLE001 — per-deployment isolation (D5)
                if isinstance(exc, _CounterpartError):
                    counterpart_deployment_id = (
                        exc.counterpart_deployment_id or counterpart_deployment_id
                    )
                    restore_id = exc.restore_id or restore_id
                logger.exception(
                    "env_clone_counterpart_error environment_clone_id=%s "
                    "deployment_id=%s counterpart_deployment_id=%s restore_id=%s",
                    clone_id,
                    deployment_id,
                    counterpart_deployment_id,
                    restore_id,
                )
                if entry is not None:
                    # The ids go on the entry even though the outcome is a failure:
                    # whatever this step managed to create is real, and the
                    # attribution entry is the only place an operator can find it.
                    by_deployment[deployment_id] = entry.model_copy(
                        update={
                            "outcome": EnvironmentCloneDeploymentOutcome.FAILED,
                            "reason": str(exc),
                            "counterpart_deployment_id": counterpart_deployment_id,
                            "restore_id": restore_id,
                        }
                    )
            else:
                cloned += 1
                if entry is not None:
                    by_deployment[deployment_id] = entry.model_copy(
                        update={
                            "outcome": EnvironmentCloneDeploymentOutcome.CLONED,
                            "reason": None,
                            "counterpart_deployment_id": counterpart_deployment_id,
                            "restore_id": restore_id,
                        }
                    )
                continue

        failed_ids.add(deployment_id)
        # A failed counterpart is no longer upcoming for the ones created after it (critique E2).
        upcoming.pop(counterpart_ids[deployment_id], None)
        if deployment_id in environment_terms:
            # The environment config names it: attempt no further counterpart (027 FR-005).
            stopped_by = deployment_id
            break

    results = [by_deployment.get(result.deployment_id, result) for result in results]
    fatal_error: CloneError | None = None
    if stopped_by is not None:
        fatal_error = _reference_not_cloned_error(
            {stopped_by: environment_terms[stopped_by]}, source_names
        )
        results = _fail_pending(
            results, _reference_not_cloned_reason(stopped_by, source_names)
        )
    # Any entry still PENDING here names a deployment the capture never
    # snapshotted, so it will never be attempted; attribute it rather than
    # leaving the clone pinned non-terminal forever.
    results = _fail_pending(results, CLONE_REASON_CAPTURE_UNUSABLE)
    await _save_progress(clone_id, results=results, error=fatal_error)

    logger.info(
        "env_clone_materialised environment_clone_id=%s created_environment_id=%s "
        "capture=%s usable=%s cloned=%s failed=%s",
        clone_id,
        created_environment_id,
        capture_status.value,
        len(usable),
        cloned,
        len(failed_ids),
    )
