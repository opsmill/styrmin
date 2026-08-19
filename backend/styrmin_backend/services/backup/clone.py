"""Environment clone primitives: the config merge and the derived status.

An :class:`~styrmin_backend.db.models.EnvironmentClone` deliberately stores
**no status column** (010 spec FR-009, ADR-0055 decision 2). Unlike its
environment backup/restore siblings — whose status folds one homogeneous list
of constituent rows — a clone's status folds four heterogeneous inputs:

* the backing capture's *own* derived status (or its absence),
* whether the created environment exists,
* the constituent cross-target ``Restore`` rows, reachable only through the
  JSON ``deployment_results[].restore_id`` values, and
* the recorded ``clone_errors``.

:func:`derive_environment_clone_status` is the single definition of what those
four mean together. Two resolution rules make it safe to run against a record
whose inputs have been cleaned up underneath it (``data-model.md``):

1. **A missing derivation input is never re-interpreted.** A capture that is no
   longer reachable, or a ``deployment_results`` entry whose ``restore_id`` no
   longer resolves to a row, keeps the recorded outcome as final. Routine TTL
   cleanup of a backup must not rewrite the history of a finished clone.
2. **History is rewritten only through** ``clone_errors``. Every deletion path
   writes an entry in the same transaction as the deletion, with ``fatal: true``
   when it hit a non-terminal clone (the clone becomes ``FAILED``, attributed)
   and ``fatal: false`` when the clone was already terminal (the event is kept,
   the outcome stands). This is why the derivation keys on the step names
   below and not on a bare NULL foreign key: a null
   ``created_environment_id`` alone cannot distinguish "deleted" from "not yet
   created".
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, NamedTuple, Sequence
from uuid import UUID, uuid4

from fast_depends import Depends, inject
from loguru import logger
from pydantic import BaseModel

from styrmin_backend.context.exceptions import InvalidEnvironmentContextError
from styrmin_backend.context.models.config import EnvironmentConfig
from styrmin_backend.context.validators import validate_environment_config
from styrmin_backend.db.models import (
    EnvironmentBackup,
    EnvironmentClone,
    Restore,
    RestoreStatus,
)
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.repository.environment_backup import NON_TERMINAL_RESTORE_STATUSES
from styrmin_backend.services.backup.environment import (
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    EnvironmentOperationStatus,
    _guard_no_environment_operation_in_progress,
    derive_environment_operation_status,
    dispatch_constituent_backups,
    is_eligible_for_environment_backup,
    register_environment_backup,
)
from styrmin_backend.services.environments import resolve_environment
from styrmin_backend.services.exceptions import (
    EnvironmentAlreadyExistsError,
    EnvironmentCloneNotFoundError,
    InvalidContextError,
    UnknownEnvironmentConfigFieldError,
)

# ``UnitOfWork`` is imported at runtime, not under ``TYPE_CHECKING``: the
# ``@inject``-decorated ``clone_environment`` below has fast-depends build a
# Pydantic model from its signature, which resolves the annotation for real.
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction


class EnvironmentCloneStatus(str, Enum):
    """Derived status of an environment clone.

    Same vocabulary as
    :class:`~styrmin_backend.services.backup.environment.EnvironmentOperationStatus`
    (a clone *is* an environment-level operation), but its own enum: the
    derivation folds different inputs, and the GraphQL layer binds one name per
    Python enum class.

    Never stored — computed by :func:`derive_environment_clone_status`.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


#: Statuses at which a clone stops changing on its own. Mirrors
#: :data:`~styrmin_backend.services.backup.environment.TERMINAL_ENVIRONMENT_OPERATION_STATUSES`.
#: Terminality releases the D8/D9 guards, and is **not** expressible as a SQL
#: ``EXISTS`` — guards load the candidate clones (the clones of one
#: environment: a tiny set) and derive in Python.
TERMINAL_ENVIRONMENT_CLONE_STATUSES = frozenset(
    {
        EnvironmentCloneStatus.COMPLETED,
        EnvironmentCloneStatus.PARTIAL,
        EnvironmentCloneStatus.FAILED,
    }
)


class EnvironmentCloneDeploymentOutcome(str, Enum):
    """What became of one source deployment in a clone (spec SC-003).

    Every source deployment considered gets exactly one entry, so the record
    accounts for 100% of them. ``PENDING`` is the transient value between
    registration and the step landing; a terminal clone contains no ``PENDING``
    entry (that is part of the derivation).
    """

    PENDING = "pending"
    CLONED = "cloned"
    SKIPPED = "skipped"
    FAILED = "failed"


class CloneDeploymentResult(BaseModel):
    """One attribution entry on ``EnvironmentClone.deployment_results``.

    ``reason`` is an open string, required for ``SKIPPED``/``FAILED`` and null
    otherwise — same convention as
    :class:`~styrmin_backend.services.backup.environment.SkippedConstituent`
    (ADR-0055 decision 4: an enum on the wire would break older clients every
    time the vocabulary grows).
    """

    deployment_id: UUID
    deployment_name: str
    outcome: EnvironmentCloneDeploymentOutcome
    reason: str | None = None
    #: The deployment created in the cloned environment; null unless ``CLONED``.
    counterpart_deployment_id: UUID | None = None
    #: The cross-target restore that carries this deployment's data; null until
    #: one is dispatched.
    restore_id: UUID | None = None


class CloneError(BaseModel):
    """One operation-level event on ``EnvironmentClone.clone_errors``.

    Operation-level means "outside any single deployment": the capture failed
    wholly, the target name was lost in the TOCTOU window, the environment could
    not be created, or an input was deleted underneath the clone. Per-deployment
    failures are **not** recorded here — they live in ``deployment_results``.

    ``fatal`` is what lets one event mean two things depending on when it
    happened: ``true`` drives the derivation to ``FAILED``; ``false`` keeps the
    event as history without rewriting an outcome that already stands.
    """

    step: str
    error: str
    fatal: bool


#: The capture never reached a restorable terminal status, so nothing
#: materialised (spec FR-002). Always fatal.
CLONE_STEP_CAPTURE_FAILED = "capture_failed"
#: The target environment name was free at validation time and taken by the
#: time the environment was created (spec FR-011). Always fatal.
CLONE_STEP_TARGET_NAME_TAKEN = "target_name_taken"
#: Creating the cloned environment failed for any other reason. Always fatal.
CLONE_STEP_ENVIRONMENT_CREATION_FAILED = "environment_creation_failed"
#: The backing environment backup was deleted (spec FR-008 escape hatch).
#: Fatal iff the clone was still non-terminal.
CLONE_STEP_ENVIRONMENT_BACKUP_DELETED = "environment_backup_deleted"
#: The created environment was deleted — the discard path (spec SC-005).
#: Fatal iff the clone was still non-terminal.
CLONE_STEP_CREATED_ENVIRONMENT_DELETED = "created_environment_deleted"

#: Every step name the clone paths write. The derivation keys on the two
#: deletion markers; the rest are always fatal and so are only read as history.
CLONE_STEPS = frozenset(
    {
        CLONE_STEP_CAPTURE_FAILED,
        CLONE_STEP_TARGET_NAME_TAKEN,
        CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
        CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
        CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
    }
)


# ---------------------------------------------------------------------------
# Per-deployment attribution reasons (spec FR-004 / SC-003)
# ---------------------------------------------------------------------------
#
# Open strings on the wire (ADR-0055 decision 4) but written from one place, so
# the UI copy and the tests have something stable to key on.

#: An explicit selection was given and did not name this deployment.
CLONE_REASON_NOT_SELECTED = "not included in the requested deployment selection"
#: The deployment cannot contribute a constituent backup at all.
CLONE_REASON_NOT_ELIGIBLE = "deployment has no active instance"
#: The capture never produced a constituent ``Backup`` row for it.
CLONE_REASON_CAPTURE_FAILED = "constituent backup failed at capture"
#: The constituent exists but did not reach ``COMPLETED``.
CLONE_REASON_BACKUP_NOT_COMPLETED = "constituent backup did not complete"
#: The constituent row is gone (deleted individually after the capture).
CLONE_REASON_BACKUP_DELETED = "constituent backup deleted"
#: Velero garbage-collected the constituent's data before the clone ran.
CLONE_REASON_BACKUP_EXPIRED = "constituent backup expired"
#: The capture's driver identity no longer resolves to a loaded driver version.
CLONE_REASON_DRIVER_VERSION_GONE = "captured driver version no longer exists"
#: The whole capture failed, so no counterpart was ever attempted (FR-002).
CLONE_REASON_CAPTURE_UNUSABLE = "environment backup capture did not succeed"


# ---------------------------------------------------------------------------
# Config merge (research D7)
# ---------------------------------------------------------------------------


def _canonicalise_environment_config(
    config: Mapping[str, Any] | None, *, what: str
) -> dict[str, Any]:
    """Validate a config dict and return its canonical form.

    Canonical means "through the ``EnvironmentConfig`` round-trip", which
    flattens ``None``-vs-missing drift so a config that omits a field compares
    and merges identically to one that sets it to ``None``. Same normalisation
    ``_deployment_already_at_config`` uses for its equality check.

    Raises:
        InvalidContextError: When the dict is not a valid environment config.
            Wrapping keeps the typed ``VALIDATION_ERROR`` code the GraphQL
            boundary needs, exactly as ``create_environment`` does.
    """
    payload = dict(config or {})
    try:
        validate_environment_config(payload)
    except InvalidEnvironmentContextError as exc:
        raise InvalidContextError(f"{what} is invalid: {exc}") from exc
    return EnvironmentConfig.model_validate(payload).model_dump(
        exclude_none=True, mode="json"
    )


def merge_environment_config(
    captured: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None = None,
    cleared_fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a cloned environment's config from the capture (research D7).

    Three steps, in this order:

    1. both sides are canonicalised through ``EnvironmentConfig``;
    2. every name in ``cleared_fields`` is popped from the captured config —
       this is the only way to *remove* a scalar, because the override input
       omits ``None``-valued fields and so cannot express "unset this"
       (spec FR-006, US3's motive: dropping production-only settings);
    3. the override is applied as a **top-level-field replacement merge** —
       each field present in the override replaces the captured field
       wholesale, absent fields keep their captured value.

    Because the merge runs after the pop, a field that is both cleared and
    overridden ends up with the override value.

    Replacement, not deep merge, is deliberate: ADR-0012 rejected deep/PATCH
    merge for ``updateEnvironment``, so per-field replacement is the platform's
    established granularity and the clone override adopts it one level up
    (override a field → you own that whole field).

    Args:
        captured: ``EnvironmentBackup.environment_config`` — the source's config
            at capture time. ``None`` is treated as an empty config.
        override: The override as supplied, already converted from
            ``UpdateEnvironmentInput`` by ``update_environment_input_to_dict``.
        cleared_fields: Top-level ``EnvironmentConfig`` field names to drop from
            the captured config before the merge.

    Returns:
        The merged, validated, canonical config dict, ready for
        ``create_environment``.

    Raises:
        UnknownEnvironmentConfigFieldError: When ``cleared_fields`` names
            something that is not a top-level ``EnvironmentConfig`` field.
        InvalidContextError: When either side — or the merged result — fails
            ``EnvironmentConfig`` validation. The captured side can fail too: a
            snapshot taken before a config field was removed no longer
            validates, and failing loudly beats silently creating an
            environment whose config differs from what was captured.
    """
    known_fields = set(EnvironmentConfig.model_fields)
    unknown = [name for name in cleared_fields or () if name not in known_fields]
    if unknown:
        raise UnknownEnvironmentConfigFieldError(
            fields=unknown, known_fields=sorted(known_fields)
        )

    merged = _canonicalise_environment_config(
        captured, what="the captured environment config"
    )
    for name in cleared_fields or ():
        merged.pop(name, None)
    merged.update(
        _canonicalise_environment_config(
            override, what="the environment config override"
        )
    )

    # Re-validated as a whole: both halves are individually valid, but only the
    # merged document can be checked against rules that span fields.
    try:
        validate_environment_config(merged)
    except InvalidEnvironmentContextError as exc:
        raise InvalidContextError(
            f"the merged environment config is invalid: {exc}"
        ) from exc
    return merged


# ---------------------------------------------------------------------------
# Derived status
# ---------------------------------------------------------------------------


class _ResultView(NamedTuple):
    """A ``deployment_results`` entry read leniently for the derivation.

    The stored ``outcome`` is a free JSON string, so it is kept raw rather than
    coerced into :class:`EnvironmentCloneDeploymentOutcome`: an entry written by
    a future (or broken) writer must still be *counted*, since the coverage
    identity depends on every entry being accounted for.
    """

    outcome: str
    restore_id: UUID | None


def _read_restore_id(raw: Any, *, index: int) -> UUID | None:
    """Read one entry's ``restore_id``, tolerating a value that will not parse.

    Pairs with ``repository.environment_clone.referenced_restore_ids``, which
    does the same for a whole batch: an unparseable id is skipped with a warning
    and then treated exactly like a restore row that cascaded away — the
    entry's recorded outcome stands.
    """
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return raw
    try:
        return UUID(str(raw))
    except ValueError:
        logger.warning(
            "Ignoring unparseable restore_id {!r} on deployment_results[{}]",
            raw,
            index,
        )
        return None


def _read_deployment_results(
    deployment_results: Sequence[Any] | None,
) -> list[_ResultView]:
    """Read ``deployment_results`` into the shape the derivation folds."""
    views: list[_ResultView] = []
    for index, entry in enumerate(deployment_results or ()):
        if isinstance(entry, CloneDeploymentResult):
            views.append(
                _ResultView(outcome=entry.outcome.value, restore_id=entry.restore_id)
            )
            continue
        if not isinstance(entry, dict):
            logger.warning(
                "Ignoring malformed deployment_results[{}] entry: {!r}", index, entry
            )
            continue
        views.append(
            _ResultView(
                outcome=str(entry.get("outcome")),
                restore_id=_read_restore_id(entry.get("restore_id"), index=index),
            )
        )
    return views


def _read_clone_errors(clone_errors: Sequence[Any] | None) -> list[CloneError]:
    """Read ``clone_errors``, defaulting a missing ``fatal`` flag to ``False``.

    Defaulting to non-fatal is the safe direction: a writer that forgot the flag
    leaves a stuck clone visibly non-terminal (recoverable through the FR-008
    escape hatch), whereas defaulting to fatal would rewrite a finished clone's
    outcome — the one thing resolution rule 1 exists to prevent.
    """
    entries: list[CloneError] = []
    for index, entry in enumerate(clone_errors or ()):
        if isinstance(entry, CloneError):
            entries.append(entry)
            continue
        if not isinstance(entry, dict):
            logger.warning(
                "Ignoring malformed clone_errors[{}] entry: {!r}", index, entry
            )
            continue
        if "fatal" not in entry:
            logger.warning(
                "clone_errors[{}] (step={!r}) carries no 'fatal' flag; "
                "reading it as non-fatal",
                index,
                entry.get("step"),
            )
        entries.append(
            CloneError(
                step=str(entry.get("step", "")),
                error=str(entry.get("error", "")),
                fatal=bool(entry.get("fatal")),
            )
        )
    return entries


def derive_clone_capture_status(
    environment_backup: EnvironmentBackup | None,
) -> EnvironmentOperationStatus | None:
    """Derive the status of the capture a clone is built from.

    ``None`` means the capture is not reachable — either it was never
    registered, or it has since been deleted. The derivation never
    re-interprets that absence; the deletion path records what happened in
    ``clone_errors`` instead.
    """
    if environment_backup is None:
        return None
    return derive_environment_operation_status(
        [backup.status for backup in environment_backup.backups],
        error_count=len(environment_backup.constituent_errors or []),
    )


def derive_environment_clone_status(
    *,
    capture_status: EnvironmentOperationStatus | None,
    created_environment_id: UUID | None,
    deployment_results: Sequence[Any] | None,
    clone_errors: Sequence[Any] | None,
    restores: Mapping[UUID, Restore] | None = None,
) -> EnvironmentCloneStatus:
    """Derive a clone's status from its four inputs (``data-model.md``).

    First match wins:

    1. any **fatal** ``clone_errors`` entry → ``FAILED`` (terminal; releases the
       D8/D9 guards). Per-deployment failures are never fatal entries.
    2. the capture is queued and nothing has progressed past registration →
       ``PENDING``.
    3. anything is still moving → ``IN_PROGRESS``: the capture is non-terminal,
       or the environment has not materialised yet, or an entry is still
       ``pending``, or a resolvable restore row is non-terminal. The
       dead-flow case lands here and stays here until an operator uses an
       escape hatch (research D9).
    4. no included entry failed → ``COMPLETED``. Skips are not failures
       (spec FR-004), so an all-skipped clone — and a clone of an empty
       selection — is ``COMPLETED``, matching
       ``derive_environment_operation_status([], 0)``.
    5. some included entry failed alongside a success → ``PARTIAL``.
    6. every included entry failed → ``FAILED``.

    Three points ``data-model.md`` leaves open, resolved here and pinned by the
    unit matrix:

    * **"nothing else recorded"** (rule 2) means no ``clone_errors``, no created
      environment, and no ``deployment_results`` entry past ``pending``. An
      upfront skip is progress, so a clone that already recorded one reads as
      ``IN_PROGRESS`` — the same reasoning that makes
      ``derive_environment_operation_status`` treat a recorded error as work
      having happened.
    * **"included"** (rules 5 and 6) means *not skipped*. A skipped deployment
      was deliberately left out of the clone, so it neither fails the clone nor
      rescues it: ``skipped`` + ``failed`` with nothing cloned is ``FAILED``,
      while all-skipped is ``COMPLETED``.
    * **a restore "ended PARTIAL"** cannot happen —
      :class:`~styrmin_backend.db.models.RestoreStatus` has no ``PARTIAL``
      member — so only ``FAILED`` turns a ``cloned`` entry into a failure.

    Args:
        capture_status: The backing capture's own derived status, or ``None``
            when it is not reachable (see :func:`derive_clone_capture_status`).
        created_environment_id: The cloned environment, or ``None`` when it has
            not been created yet **or** was deleted. The two are told apart by
            the ``created_environment_deleted`` marker in ``clone_errors``.
        deployment_results: The attribution entries, as stored (JSON dicts) or
            as :class:`CloneDeploymentResult` instances.
        clone_errors: The operation-level events, as stored (JSON dicts) or as
            :class:`CloneError` instances.
        restores: The referenced ``Restore`` rows keyed by id, from
            ``EnvironmentCloneRepository.get_referenced_restores``. Extra
            entries are harmless — only ids named by ``deployment_results`` are
            looked up — and a referenced id that is *absent* is a restore that
            cascaded away, whose entry keeps its recorded outcome.

    Returns:
        The derived status. Never persisted.
    """
    errors = _read_clone_errors(clone_errors)
    if any(error.fatal for error in errors):
        return EnvironmentCloneStatus.FAILED

    results = _read_deployment_results(deployment_results)
    rows = restores or {}
    pending = EnvironmentCloneDeploymentOutcome.PENDING.value
    environment_was_deleted = any(
        error.step == CLONE_STEP_CREATED_ENVIRONMENT_DELETED for error in errors
    )

    if (
        capture_status is EnvironmentOperationStatus.PENDING
        and not errors
        and created_environment_id is None
        and all(result.outcome == pending for result in results)
    ):
        return EnvironmentCloneStatus.PENDING

    if (
        capture_status is not None
        and capture_status not in TERMINAL_ENVIRONMENT_OPERATION_STATUSES
    ):
        return EnvironmentCloneStatus.IN_PROGRESS
    if created_environment_id is None and not environment_was_deleted:
        return EnvironmentCloneStatus.IN_PROGRESS
    if any(result.outcome == pending for result in results):
        return EnvironmentCloneStatus.IN_PROGRESS
    for result in results:
        if result.restore_id is None:
            continue
        restore = rows.get(result.restore_id)
        if restore is not None and restore.status in NON_TERMINAL_RESTORE_STATUSES:
            return EnvironmentCloneStatus.IN_PROGRESS

    succeeded = 0
    failed = 0
    for result in results:
        if result.outcome == EnvironmentCloneDeploymentOutcome.SKIPPED.value:
            continue
        if result.outcome == EnvironmentCloneDeploymentOutcome.CLONED.value:
            restore = rows.get(result.restore_id) if result.restore_id else None
            if restore is not None and restore.status is RestoreStatus.FAILED:
                failed += 1
            else:
                # No restore row means the recorded outcome stands (resolution
                # rule 1): a cascade-deleted restore does not retract a clone.
                succeeded += 1
            continue
        if result.outcome != EnvironmentCloneDeploymentOutcome.FAILED.value:
            logger.warning(
                "Unrecognised deployment_results outcome {!r}; counting it as a "
                "failure so the entry is still accounted for",
                result.outcome,
            )
        failed += 1

    if failed == 0:
        return EnvironmentCloneStatus.COMPLETED
    if succeeded:
        return EnvironmentCloneStatus.PARTIAL
    return EnvironmentCloneStatus.FAILED


def derive_environment_clone_status_from_record(
    clone: EnvironmentClone, restores: Mapping[UUID, Restore] | None = None
) -> EnvironmentCloneStatus:
    """Derive a persisted clone's status.

    A thin adapter over :func:`derive_environment_clone_status` so the
    resolvers, the guards and the deletion cascades all read the record the
    same way. ``clone.environment_backup`` (and its constituents) must be
    loaded — the repository eager-loads them for exactly this call.
    """
    return derive_environment_clone_status(
        capture_status=derive_clone_capture_status(clone.environment_backup),
        created_environment_id=clone.created_environment_id,
        deployment_results=clone.deployment_results,
        clone_errors=clone.clone_errors,
        restores=restores,
    )


# ---------------------------------------------------------------------------
# Occupancy guard (research D8)
# ---------------------------------------------------------------------------


async def find_clone_occupying_environment(
    environment_id: UUID, uow: UnitOfWork
) -> EnvironmentClone | None:
    """Return the clone that currently occupies ``environment_id``, if any.

    A clone occupies **two** environments, for different windows (research D8):

    * its **source**, only while the capture is non-terminal. That is the one
      window where a second environment-level operation would fight it: the
      per-instance backup guards would degrade both captures to ``PARTIAL``
      anyway. Once the capture is terminal the source is released, so further
      backups/restores/clones may start while this clone is still building its
      new environment.
    * its **created environment**, for the clone's whole lifetime. That
      environment is still being assembled — its counterparts are mid-restore —
      so an environment-level operation (or a config update, whose fan-out
      would race the restore's namespace delete-and-wait) has to wait.

    A clone whose ``environment_backup_id`` is still ``None`` occupies nothing:
    registration has not completed, and treating it as an occupant would make
    the registering transaction collide with itself.

    Returns:
        The occupying clone, or ``None``. Callers turn it into
        ``EnvironmentOperationInProgressError``; the candidate sets are the
        clones of one environment, so deriving in Python is cheap (clone
        terminality is not expressible as a SQL ``EXISTS``).
    """
    for clone in await uow.environment_clones.get_by_source_environment_id(
        environment_id
    ):
        if clone.environment_backup_id is None:
            continue
        capture_status = derive_clone_capture_status(clone.environment_backup)
        if capture_status is None:
            # The capture is unreachable: it was deleted, which the deletion
            # path attributed on the record. Nothing is in flight.
            continue
        if capture_status not in TERMINAL_ENVIRONMENT_OPERATION_STATUSES:
            return clone

    created_by = await uow.environment_clones.get_by_created_environment_id(
        environment_id
    )
    if created_by:
        restores = await uow.environment_clones.get_referenced_restores(created_by)
        for clone in created_by:
            status = derive_environment_clone_status_from_record(clone, restores)
            if status not in TERMINAL_ENVIRONMENT_CLONE_STATUSES:
                return clone
    return None


# ---------------------------------------------------------------------------
# clone_environment (research D4)
# ---------------------------------------------------------------------------


def _validate_cleared_config_fields(cleared_fields: Sequence[str] | None) -> None:
    """Reject unknown ``clearConfigFields`` names before anything is written.

    :func:`merge_environment_config` performs the same check, but it only runs
    inside the clone flow — long after the mutation returned. FR-011 requires
    an invalid request to fail upfront with zero side effects, so the names are
    validated here too.
    """
    known_fields = set(EnvironmentConfig.model_fields)
    unknown = [name for name in cleared_fields or () if name not in known_fields]
    if unknown:
        raise UnknownEnvironmentConfigFieldError(
            fields=unknown, known_fields=sorted(known_fields)
        )


def _plan_deployment_results(
    deployments: Sequence[DeploymentEntity], deployment_ids: Sequence[UUID] | None
) -> list[CloneDeploymentResult]:
    """Account for every source deployment before the capture is registered.

    SC-003 wants 100% attribution, and the two outcomes that are already known
    at registration time are recorded here so they survive even a clone whose
    flow never runs:

    * a deployment an explicit selection left out → ``SKIPPED``;
    * a deployment that cannot contribute a constituent backup (no active
      instance) → ``SKIPPED`` with the reason, never an error (FR-004).

    Everything else starts ``PENDING`` and the flow resolves it.

    Internal deployments are deliberately **not** listed: they are
    platform-managed infrastructure (the per-environment ingress controller),
    never part of an environment's application topology, and the cloned
    environment gets its own through ``_ensure_ingress_controller``. Tombstoned
    deployments are already excluded by ``find_all_by_environment``.
    """
    selected = set(deployment_ids) if deployment_ids is not None else None
    results: list[CloneDeploymentResult] = []
    for deployment in deployments:
        if deployment.internal:
            continue
        if selected is not None and deployment.id not in selected:
            reason: str | None = CLONE_REASON_NOT_SELECTED
        elif not is_eligible_for_environment_backup(deployment):
            reason = CLONE_REASON_NOT_ELIGIBLE
        else:
            reason = None
        results.append(
            CloneDeploymentResult(
                deployment_id=deployment.id,
                deployment_name=deployment.name,
                outcome=(
                    EnvironmentCloneDeploymentOutcome.PENDING
                    if reason is None
                    else EnvironmentCloneDeploymentOutcome.SKIPPED
                ),
                reason=reason,
            )
        )
    return results


@inject(cast_result=False)  # type: ignore[arg-type]
async def clone_environment(
    uow: UnitOfWork,
    name: str,
    created_by_user_id: UUID,
    environment_id: UUID | None = None,
    environment_name: str | None = None,
    cluster_id: UUID | None = None,
    cluster_name: str | None = None,
    deployment_ids: list[UUID] | None = None,
    config_override: dict | None = None,
    clear_config_fields: list[str] | None = None,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> EnvironmentClone:
    """Register a clone of an environment and start it (research D4).

    The mutation half of the operation, and deliberately only that half.
    Everything that can be decided synchronously happens here — validation,
    the clone record, the capture, the fan-out — and everything that has to
    *wait* happens in the ``EXECUTE_ENVIRONMENT_CLONE`` flow, which polls the
    capture to terminality before anything materialises (spec FR-002).

    Ordering, in three phases:

    1. **Upfront validation with zero side effects** (spec FR-011): resolve the
       source (ADR-031 dual identifier), canonicalise/validate the config
       override and the cleared-field names, check the target environment name
       is free in the source's cluster, and apply the environment-level
       concurrency guard to the source (research D8).
    2. **One registration transaction**: the clone record, its per-deployment
       attribution (including the skips already knowable — FR-004), and the
       whole capture (parent snapshot + constituent ``Backup`` rows + recorded
       constituent errors) are written and committed **together**. Same
       atomicity argument as ``create_environment_backup``: a client
       disconnect mid-registration must leave either nothing or a complete,
       inspectable clone — never a clone record whose capture is missing, or a
       capture nobody can attribute.
    3. **Dispatch, after the commit** (ADR-0012): one ``EXECUTE_BACKUP`` per
       constituent, then the single ``EXECUTE_ENVIRONMENT_CLONE`` flow run.

    The target name is checked but **not** reserved: reserving it would need a
    placeholder environment row, which FR-002 forbids (nothing materialises
    before the capture succeeds). The race is therefore accepted and handled
    where it lands — the flow attributes a lost name as a fatal
    ``target_name_taken`` and the clone derives ``FAILED`` (spec FR-011).

    Args:
        uow: Unit of work supplying the repositories.
        name: The target environment's name.
        created_by_user_id: The invoking user; also the attributed creator of
            every counterpart deployment (``Deployment.created_by_user_id`` is
            not nullable).
        environment_id: The source environment's id (exclusive with
            ``environment_name``).
        environment_name: The source environment's name; needs cluster context.
        cluster_id: Cluster context for ``environment_name``.
        cluster_name: Cluster context for ``environment_name``.
        deployment_ids: Optional selection; ``None`` means every eligible
            deployment (spec FR-003).
        config_override: Optional environment-config override, merged over the
            captured config by the flow (spec FR-006, research D7).
        clear_config_fields: Optional captured-config field names to drop
            before the merge (spec FR-006).
        prefect_manager: Injected dispatcher.

    Returns:
        The persisted clone record, reloaded so its capture is attached.

    Raises:
        EnvironmentNotFoundError: When the source does not exist.
        AmbiguousIdentifierError: When the source identifiers conflict.
        EnvironmentAlreadyExistsError: When ``name`` is already taken in the
            source's cluster.
        InvalidContextError: When ``config_override`` is not a valid
            environment config.
        UnknownEnvironmentConfigFieldError: When ``clear_config_fields`` names
            something that is not a top-level ``EnvironmentConfig`` field.
        EnvironmentOperationInProgressError: When an environment-level
            operation already occupies the source (research D8).
        EnvironmentCloneNotFoundError: When the record was deleted while the
            fan-out was still dispatching — legal, because deleting the source
            environment removes non-terminal clone records (research D9).
    """
    source = await resolve_environment(
        uow,
        environment_id=environment_id,
        environment_name=environment_name,
        cluster_id=cluster_id,
        cluster_name=cluster_name,
    )

    # Pure, before any write: an invalid override or cleared-field name must
    # cost the caller a typed error and nothing else (FR-011).
    canonical_override = (
        _canonicalise_environment_config(
            config_override, what="the environment config override"
        )
        if config_override
        else None
    )
    _validate_cleared_config_fields(clear_config_fields)

    async with uow:
        existing = await uow.environments.get_by_name_in_cluster(
            name, source.cluster_id
        )
        if existing is not None:
            raise EnvironmentAlreadyExistsError(
                f"An environment named {name!r} already exists in this cluster."
            )

        await _guard_no_environment_operation_in_progress(source.id, uow)

        deployments = await uow.deployments.find_all_by_environment(source.id)
        results = _plan_deployment_results(deployments, deployment_ids)

        clone_id = uuid4()
        clone = await uow.environment_clones.create(
            EnvironmentClone(
                id=clone_id,
                name=name,
                source_environment_id=source.id,
                source_environment_name=source.name,
                requested_deployment_ids=(
                    [str(value) for value in deployment_ids]
                    if deployment_ids is not None
                    else None
                ),
                config_override=canonical_override,
                cleared_config_fields=(
                    list(clear_config_fields) if clear_config_fields else None
                ),
                deployment_results=[
                    result.model_dump(mode="json") for result in results
                ]
                or None,
                created_by_user_id=created_by_user_id,
            )
        )

        registration = await register_environment_backup(
            environment=source,
            uow=uow,
            deployment_ids=deployment_ids,
        )
        environment_backup_id = registration.environment_backup.id
        # Linked last: ``find_clone_occupying_environment`` reads a clone with
        # no capture as occupying nothing, which is what keeps the guard above
        # from colliding with the row this transaction is writing.
        clone.environment_backup_id = environment_backup_id
        await uow.environment_clones.save(clone)

        # The single commit: clone record, attribution, capture and every
        # constituent become durable together, and nothing has been dispatched
        # yet (ADR-0012).
        await uow.commit()

    dispatched, dispatch_failed = await dispatch_constituent_backups(
        registration.pending_dispatch, prefect_manager, environment_backup_id
    )

    clone_dispatched = True
    try:
        await prefect_manager.run_action(
            action=PrefectAction.EXECUTE_ENVIRONMENT_CLONE,
            parameters={"clone_id": str(clone_id)},
        )
    except Exception as exc:  # noqa: BLE001 — a dispatch failure is not a lost row
        # The clone record exists and derives non-terminal, so this shows up as
        # a clone that never progresses rather than a lost operation. The
        # documented recovery is the FR-008 escape hatch: delete the backing
        # capture once it is terminal and the clone ends FAILED, attributed.
        clone_dispatched = False
        logger.warning(
            "env_clone_dispatch_error environment_clone_id={} clone record created "
            "but the clone flow was not triggered: {}",
            clone_id,
            exc,
        )

    skipped = sum(
        1
        for result in results
        if result.outcome is EnvironmentCloneDeploymentOutcome.SKIPPED
    )

    async with uow:
        refreshed = await uow.environment_clones.get(clone_id)
    if refreshed is None:
        # Deleting the source environment removes its non-terminal clone
        # records (research D9), so an operator really can delete this row
        # underneath the fan-out. NOT_FOUND, not an internal error — same
        # contract as ``create_environment_backup``.
        logger.warning(
            "env_clone_deleted_during_fanout source_environment_id={} "
            "environment_clone_id={}",
            source.id,
            clone_id,
        )
        raise EnvironmentCloneNotFoundError(
            f"Environment clone {clone_id} was deleted while its registration "
            "was still dispatching"
        )

    # One audit entry per clone registration, matching
    # ``env_backup_fanout_dispatched`` (ADR-0012/0055 convention).
    logger.info(
        "env_clone_dispatched source_environment_id={} environment_clone_id={} "
        "environment_backup_id={} target_name={} evaluated={} pending={} "
        "skipped={} capture_dispatched={} capture_conflict={} "
        "capture_dispatch_failed={} flow_dispatched={}",
        source.id,
        clone_id,
        environment_backup_id,
        name,
        registration.evaluated,
        len(results) - skipped,
        skipped,
        dispatched,
        len(registration.errors),
        dispatch_failed,
        clone_dispatched,
    )

    return refreshed


# ---------------------------------------------------------------------------
# Read side (research D10)
# ---------------------------------------------------------------------------


class EnvironmentCloneReadout(NamedTuple):
    """Clone records plus the ``Restore`` rows their statuses are derived from.

    The rows travel *with* the records because they cannot be eager-loaded:
    they are named by ids inside the JSON ``deployment_results`` entries, not by
    a relationship. Fetching them per clone (let alone per entry) would be an
    N+1 on every read of the clone surface, so both getters resolve the whole
    batch with one ``IN`` query and hand the mapping to the caller, which passes
    it straight into ``EnvironmentClone.from_instance``.
    """

    clones: Sequence[EnvironmentClone]
    restores: dict[UUID, Restore]


async def get_environment_clone(
    environment_clone_id: UUID, uow: UnitOfWork
) -> EnvironmentCloneReadout:
    """Get one clone record and the restore rows its status needs.

    Raises:
        EnvironmentCloneNotFoundError: When no such clone exists.
    """
    async with uow:
        clone = await uow.environment_clones.get(environment_clone_id)
        if clone is None:
            raise EnvironmentCloneNotFoundError(
                f"Environment clone {environment_clone_id} not found"
            )
        restores = await uow.environment_clones.get_referenced_restores([clone])
    return EnvironmentCloneReadout(clones=[clone], restores=restores)


async def get_environment_clones(
    environment_id: UUID, uow: UnitOfWork
) -> EnvironmentCloneReadout:
    """List the clones made *from* an environment, newest first.

    Scoped by **source** environment (contracts/graphql.md): the created
    environment's own provenance is reached through
    ``Environment.clonedFrom``, not through this list.
    """
    async with uow:
        clones = await uow.environment_clones.get_by_source_environment_id(
            environment_id
        )
        restores = await uow.environment_clones.get_referenced_restores(clones)
    return EnvironmentCloneReadout(clones=clones, restores=restores)
