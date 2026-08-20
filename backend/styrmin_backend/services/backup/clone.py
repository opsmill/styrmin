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

from datetime import datetime, timezone
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
    EnvironmentBackupInUseByCloneError,
    EnvironmentCloneNotFoundError,
    InvalidCloneDeploymentSelectionError,
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
#: The source environment was deleted while the clone was still building the
#: environment it had already created (research D9). Only ever written on a
#: **non-terminal** clone that is being *kept* — one that never created an
#: environment is deleted outright instead — and therefore always fatal: the
#: clone can never make progress again (its capture goes with the source), and
#: the record survives as the created environment's provenance.
CLONE_STEP_SOURCE_ENVIRONMENT_DELETED = "source_environment_deleted"

#: Every step name the clone paths write. The derivation keys on the deletion
#: markers; the rest are always fatal and so are only read as history.
CLONE_STEPS = frozenset(
    {
        CLONE_STEP_CAPTURE_FAILED,
        CLONE_STEP_TARGET_NAME_TAKEN,
        CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
        CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
        CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
        CLONE_STEP_SOURCE_ENVIRONMENT_DELETED,
    }
)

#: How long the FR-008 ``IN_USE`` guard keeps protecting a clone's capture.
#:
#: The guard exists so an operator cannot delete a capture the clone flow is
#: still waiting on, and the flow waits for exactly this long
#: (``workflows.templates.clone.CAPTURE_POLL_TIMEOUT_SECONDS`` *is* this
#: constant, so the two cannot drift). Past that budget the flow has given up,
#: so nothing is left to strand — and the guard has to stop refusing, because a
#: capture can stay non-terminal *forever*: a constituent whose
#: ``EXECUTE_BACKUP`` dispatch failed, or that no worker ever picked up, sits
#: ``PENDING`` with nothing to move it. Refusing there would wedge the source
#: environment permanently with no escape hatch left, which is the exact state
#: ADR-0055 decision 6 and spec.md's recovery note exist to prevent.
CAPTURE_IN_FLIGHT_GUARD_SECONDS = 7200


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
#: The selection named the environment's platform-managed deployment. Only ever
#: attributed to an *explicitly selected* internal deployment: an unselected one
#: is left off the list entirely (it is not part of the environment's
#: application topology), but silently dropping something the operator asked for
#: by id would break SC-003's accounting.
CLONE_REASON_INTERNAL = "deployment is internal platform infrastructure"
#: The selection named a deleted deployment. Same rule as
#: :data:`CLONE_REASON_INTERNAL`: attributed only when explicitly selected.
CLONE_REASON_TOMBSTONED = "deployment has been deleted"
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


#: The synthetic ``outcome`` an entry gets when the stored value cannot be read
#: as an entry at all (not a mapping). It is deliberately not one of the four
#: write-side outcomes, so the fold below counts it as a failure: an entry
#: nobody can read is a source deployment nobody can account for, and letting
#: it vanish would let a clone derive ``COMPLETED`` with a deployment
#: unaccounted for (spec SC-003).
UNREADABLE_RESULT_OUTCOME = "<unreadable>"


class _ResultView(NamedTuple):
    """A ``deployment_results`` entry read leniently for the derivation.

    The stored ``outcome`` is a free JSON string, so it is kept raw rather than
    coerced into :class:`EnvironmentCloneDeploymentOutcome`: an entry written by
    a future (or broken) writer must still be *counted*, since the coverage
    identity depends on every entry being accounted for. An entry that is not a
    mapping at all is counted too, under
    :data:`UNREADABLE_RESULT_OUTCOME` — dropping it was the one way the promise
    in this docstring could be broken.
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
    """Read ``deployment_results`` into the shape the derivation folds.

    Every stored entry produces exactly one view, including one that cannot be
    read as an entry at all: it is counted under
    :data:`UNREADABLE_RESULT_OUTCOME`, which the fold treats as a failure. The
    alternative — skipping it — silently shrinks the account of the source's
    deployments, so ``['a', 'b', 'c']`` would derive ``COMPLETED`` with nothing
    accounted for (spec SC-003).
    """
    views: list[_ResultView] = []
    for index, entry in enumerate(deployment_results or ()):
        if isinstance(entry, CloneDeploymentResult):
            views.append(
                _ResultView(outcome=entry.outcome.value, restore_id=entry.restore_id)
            )
            continue
        if not isinstance(entry, dict):
            logger.warning(
                "Counting unreadable deployment_results[{}] entry as a failure: {!r}",
                index,
                entry,
            )
            views.append(
                _ResultView(outcome=UNREADABLE_RESULT_OUTCOME, restore_id=None)
            )
            continue
        views.append(
            _ResultView(
                outcome=str(entry.get("outcome")),
                restore_id=_read_restore_id(entry.get("restore_id"), index=index),
            )
        )
    return views


def read_clone_errors(clone_errors: Sequence[Any] | None) -> list[CloneError]:
    """Read ``clone_errors``, defaulting a missing ``fatal`` flag to ``False``.

    Defaulting to non-fatal is the safe direction: a writer that forgot the flag
    leaves a stuck clone visibly non-terminal (recoverable through the FR-008
    escape hatch), whereas defaulting to fatal would rewrite a finished clone's
    outcome — the one thing resolution rule 1 exists to prevent.

    Public because the GraphQL projection reads the column through this very
    function: a read path stricter than the derivation would make one entry
    missing its ``fatal`` flag fail the *whole* clone query, so the operator
    could no longer see the record the entry is on.
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
    errors = read_clone_errors(clone_errors)
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
# Deletion cascades (research D9)
# ---------------------------------------------------------------------------
#
# Every cascade below is **app-level on purpose**. The DB-level
# ``ON DELETE SET NULL`` on ``created_environment_id`` is belt-and-braces only:
# a bare NULL is not computably distinguishable from "not yet created", so each
# deletion path also writes the ``clone_errors`` marker the derivation keys on,
# in the same transaction as the deletion (``data-model.md``).
#
# All four helpers assume the caller's transaction is open and none of them
# commits — the marker and the deletion have to land together or not at all,
# which is only true if the caller owns the commit.


def _append_clone_error(clone: EnvironmentClone, error: CloneError) -> None:
    """Append one operation-level event to a clone, keeping what is recorded.

    A new list rather than an in-place ``append``: ``clone_errors`` is a plain
    JSON column, and SQLAlchemy only notices a *rebound* attribute (mutating
    the list in place leaves the change undetected and silently unpersisted).
    Same reason the clone flow's ``_save_progress`` rebinds it.
    """
    clone.clone_errors = [*(clone.clone_errors or []), error.model_dump(mode="json")]


async def _derive_statuses(
    clones: Sequence[EnvironmentClone], uow: UnitOfWork
) -> dict[UUID, EnvironmentCloneStatus]:
    """Derive a batch of clones' statuses with one restore query for the batch."""
    if not clones:
        return {}
    restores = await uow.environment_clones.get_referenced_restores(list(clones))
    return {
        clone.id: derive_environment_clone_status_from_record(clone, restores)
        for clone in clones
    }


def _capture_could_still_be_awaited(
    environment_backup: EnvironmentBackup | None, now: datetime
) -> bool:
    """Is the clone flow still plausibly waiting for this capture?

    The FR-008 guard's whole justification is "a flow is waiting on this row",
    and the flow waits for :data:`CAPTURE_IN_FLIGHT_GUARD_SECONDS` before giving
    up. Past that the answer is no, whatever the capture's constituents say —
    which is what keeps the guard from becoming permanent for a capture that can
    never terminalise on its own (a constituent whose dispatch failed stays
    ``PENDING`` forever, and the derivation reads the capture as non-terminal
    forever with it).

    A capture whose ``created_on`` is not set yet has not been through the
    database (it is a server default), so it belongs to the transaction in
    flight: brand new, and protected.
    """
    if environment_backup is None:
        return False
    created_on = environment_backup.created_on
    if created_on is None:
        return True
    if created_on.tzinfo is None:
        created_on = created_on.replace(tzinfo=timezone.utc)
    return (now - created_on).total_seconds() < CAPTURE_IN_FLIGHT_GUARD_SECONDS


async def guard_no_clone_capturing_environment_backup(
    environment_backup_id: UUID, uow: UnitOfWork
) -> dict[UUID, bool]:
    """Refuse to delete a capture a clone is still taking (spec FR-008, D9).

    The guard is scoped to the **capture window**, the only window in which
    deleting the backup would strand work that can no longer be attributed to
    anything: the clone flow is still polling for a capture that no longer
    exists, and nothing has been created it could report against. Once the
    capture is terminal the backup becomes deletable **on purpose** — that is
    the documented escape hatch for a clone whose flow died (ADR-0055
    decision 6), and :func:`detach_clones_from_environment_backup` attributes
    the deletion on the record.

    A clone that is *itself* already terminal never blocks the deletion either,
    even in the (fatal-error-only) state where its capture still reads
    non-terminal: it has nothing in flight left to strand, and refusing here
    would recreate exactly the wedge D9 exists to prevent — most visibly on the
    source-deletion cascade, which must never be blocked by a record it has
    already resolved.

    **The window is bounded in time as well as in state** (see
    :data:`CAPTURE_IN_FLIGHT_GUARD_SECONDS`), because "the capture is
    non-terminal" is not a self-healing condition. A constituent whose
    ``EXECUTE_BACKUP`` dispatch failed — or that no worker ever picked up —
    stays ``PENDING`` with nothing to move it, so the capture derives
    non-terminal forever and the clone with it. Refusing on state alone
    therefore produced the permanent wedge FR-008's own escape hatch exists to
    prevent: the source environment stayed occupied for every environment-level
    operation *and* ``update_environment``, the backing capture could not be
    deleted, and there was no created environment to discard. Once the flow's
    own budget is spent the flow has given up, so deletion can no longer pull
    anything out from under it and the escape hatch opens.

    This is also the **snapshot point** for how each referencing clone stood
    when the operator asked for the deletion, and the return value is not a
    convenience: the deletion cascade destroys two of the derivation's own
    inputs (the capture's constituent ``Backup`` rows, and the constituent
    ``Restore`` rows that go with them), so a clone re-derived *after* the
    cascade would read as though its restores had finished. Deriving here and
    carrying the answer to
    :func:`detach_clones_from_environment_backup` is what makes FR-008's
    "drives a non-terminal clone to a failed terminal state" true for a clone
    that was mid-restore.

    Returns:
        ``{clone_id: was_terminal}`` for every clone built from this capture.

    Raises:
        EnvironmentBackupInUseByCloneError: ``IN_USE``, naming the clone.
    """
    clones = await uow.environment_clones.get_by_environment_backup_id(
        environment_backup_id
    )
    if not clones:
        return {}
    statuses = await _derive_statuses(clones, uow)
    terminality = {
        clone_id: status in TERMINAL_ENVIRONMENT_CLONE_STATUSES
        for clone_id, status in statuses.items()
    }
    now = datetime.now(timezone.utc)
    for clone in clones:
        if terminality[clone.id]:
            continue
        capture_status = derive_clone_capture_status(clone.environment_backup)
        if (
            capture_status is None
            or capture_status in TERMINAL_ENVIRONMENT_OPERATION_STATUSES
        ):
            continue
        if not _capture_could_still_be_awaited(clone.environment_backup, now):
            # The escape hatch, opened: nothing is waiting on this capture any
            # more, so releasing it is the only way the clone (and its source)
            # can ever come unstuck.
            logger.warning(
                "clone_capture_guard_expired environment_clone_id={} "
                "environment_backup_id={} capture_status={} allowing the "
                "deletion so the clone can be released",
                clone.id,
                environment_backup_id,
                capture_status.value,
            )
            continue
        raise EnvironmentBackupInUseByCloneError(
            clone_id=str(clone.id), clone_name=clone.name
        )
    return terminality


async def detach_clones_from_environment_backup(
    environment_backup_id: UUID,
    uow: UnitOfWork,
    terminal_at_request: Mapping[UUID, bool] | None = None,
) -> int:
    """Attribute a capture's deletion on every clone built from it (D9).

    Runs *before* the parent row goes, in the caller's transaction: the FK is
    nullable but not ``ON DELETE SET NULL``, so the clone has to release it
    first, and the marker has to be written where the release is.

    The ``fatal`` flag is what makes one event mean two things (``data-model.md``
    resolution rule 2):

    * a **non-terminal** clone gets ``fatal: true`` and derives ``FAILED`` with
      the deletion attributed — the escape hatch, honest about why it ended;
    * an **already-terminal** clone gets ``fatal: false``: the event is kept as
      history and the recorded outcome stands. Environment backups are
      TTL-governed, and routine cleanup must never rewrite a finished clone.

    Args:
        environment_backup_id: The capture being deleted.
        uow: The caller's open unit of work. Not committed here.
        terminal_at_request: ``{clone_id: was_terminal}`` from
            :func:`guard_no_clone_capturing_environment_backup`, taken before
            the cascade removed the constituent backups and restores this
            derivation reads. Omitting it derives now instead, which is only
            right when nothing has been cascaded yet.

    Returns:
        The number of clone records updated.
    """
    clones = await uow.environment_clones.get_by_environment_backup_id(
        environment_backup_id
    )
    if not clones:
        return 0
    terminality = dict(terminal_at_request or {})
    unknown = [clone for clone in clones if clone.id not in terminality]
    if unknown:
        terminality.update(
            {
                clone_id: status in TERMINAL_ENVIRONMENT_CLONE_STATUSES
                for clone_id, status in (await _derive_statuses(unknown, uow)).items()
            }
        )
    for clone in clones:
        terminal = terminality[clone.id]
        _append_clone_error(
            clone,
            CloneError(
                step=CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
                error=(
                    f"the backing environment backup {environment_backup_id} "
                    "was deleted"
                ),
                fatal=not terminal,
            ),
        )
        clone.environment_backup_id = None
        clone.environment_backup = None
        await uow.environment_clones.save(clone)
        logger.info(
            "clone_environment_backup_detached environment_clone_id={} "
            "environment_backup_id={} was_terminal={}",
            clone.id,
            environment_backup_id,
            terminal,
        )
    return len(clones)


async def detach_clones_from_created_environment(
    environment_id: UUID, uow: UnitOfWork
) -> int:
    """Attribute the discard of a cloned environment on its clone (SC-005).

    Deleting the created environment is always allowed — it *is* the discard
    path, and it is what drives a stuck clone terminal (D9). The clone record
    itself survives as history, with the same ``fatal``-iff-non-terminal rule as
    :func:`detach_clones_from_environment_backup`: discarding a half-built clone
    ends it ``FAILED``, while discarding the environment of a clone that already
    finished keeps the finished outcome and merely records that the environment
    is gone.

    Returns:
        The number of clone records updated.
    """
    clones = await uow.environment_clones.get_by_created_environment_id(environment_id)
    if not clones:
        return 0
    statuses = await _derive_statuses(clones, uow)
    for clone in clones:
        terminal = statuses[clone.id] in TERMINAL_ENVIRONMENT_CLONE_STATUSES
        _append_clone_error(
            clone,
            CloneError(
                step=CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
                error=f"the created environment {environment_id} was deleted",
                fatal=not terminal,
            ),
        )
        clone.created_environment_id = None
        clone.created_environment = None
        await uow.environment_clones.save(clone)
        logger.info(
            "clone_created_environment_deleted environment_clone_id={} "
            "environment_id={} was_terminal={}",
            clone.id,
            environment_id,
            terminal,
        )
    return len(clones)


class SourceCloneResolution(NamedTuple):
    """What became of a deleted source environment's clone records."""

    #: Clones kept as provenance, with ``source_environment_id`` nulled. Every
    #: terminal clone, plus every non-terminal clone that had already created an
    #: environment (those also get the fatal marker counted in :attr:`failed`).
    kept: int
    #: Non-terminal clones deleted outright — the ones that never materialised
    #: anything, so there is no provenance to keep.
    deleted: int
    #: How many of :attr:`kept` were non-terminal and were therefore failed by
    #: the deletion (a subset of ``kept``, not a third bucket).
    failed: int = 0


async def resolve_clones_of_deleted_source_environment(
    environment_id: UUID, uow: UnitOfWork
) -> SourceCloneResolution:
    """Settle a source environment's clone records before it goes (D9).

    Two outcomes, and the split is on **what the clone created**, not on its
    status alone:

    * a clone that has a created environment — terminal or not — survives with
      ``source_environment_id`` nulled. That environment is an ordinary
      environment which outlives the source, and its provenance must not die
      with it (``source_environment_name`` keeps the record readable, which is
      why the FK is nullable at all). A clone still *building* that environment
      also gets the fatal :data:`CLONE_STEP_SOURCE_ENVIRONMENT_DELETED` marker:
      its capture is about to be cascaded away with the source, so it can never
      progress again, and without the marker the record would sit
      ``IN_PROGRESS`` forever — non-terminal, still occupying its created
      environment, still refusing the FR-008 guard below.
    * a **non-terminal** clone that never created an environment is deleted
      outright. There is nothing to be the provenance *of*, no outcome worth
      keeping, and the clone flow tolerates its row vanishing mid-flight (the
      same contract ``execute_restore_workflow`` has with
      ``RestoreNotFoundError``).

    Deleting a clone that had already created an environment was the bug this
    split fixes: it destroyed the provenance of a live environment, and the
    backup cascade behind it then deleted the constituent backups *and the
    in-flight cross-target restores* of counterparts nothing was left to
    attribute.

    **Must run before the environment's backups cascade.** Deleting those
    backups goes through :func:`guard_no_clone_capturing_environment_backup`,
    and a non-terminal clone whose capture is still in flight would refuse it —
    wedging the deletion of the very environment that owns both rows. Settling
    the clones first means the guard has nothing left to refuse: the deleted
    ones are gone, and the kept ones are all terminal by the time it runs.

    Returns:
        How many records were kept, how many were deleted, and how many of the
        kept ones the deletion failed.
    """
    clones = await uow.environment_clones.get_by_source_environment_id(environment_id)
    if not clones:
        return SourceCloneResolution(kept=0, deleted=0, failed=0)
    statuses = await _derive_statuses(clones, uow)
    kept = 0
    deleted = 0
    failed = 0
    for clone in clones:
        terminal = statuses[clone.id] in TERMINAL_ENVIRONMENT_CLONE_STATUSES
        if not terminal and clone.created_environment_id is None:
            await uow.environment_clones.delete(clone)
            deleted += 1
            continue
        if not terminal:
            _append_clone_error(
                clone,
                CloneError(
                    step=CLONE_STEP_SOURCE_ENVIRONMENT_DELETED,
                    error=(
                        f"the source environment {environment_id} was deleted "
                        "while the clone was still building"
                    ),
                    fatal=True,
                ),
            )
            failed += 1
        clone.source_environment_id = None
        clone.source_environment = None
        await uow.environment_clones.save(clone)
        kept += 1
    logger.info(
        "clone_source_environment_deleted environment_id={} clones_kept={} "
        "clones_deleted={} clones_failed={}",
        environment_id,
        kept,
        deleted,
        failed,
    )
    return SourceCloneResolution(kept=kept, deleted=deleted, failed=failed)


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


def _validate_deployment_selection(
    deployment_ids: Sequence[UUID] | None,
    deployments: Sequence[DeploymentEntity],
) -> None:
    """Reject a selection naming deployments the source does not have (FR-011).

    The selection carries exactly one hard failure, and it is a *request* error
    rather than a state one: an id that names nothing, or names a deployment in
    a **different** environment. Both are indistinguishable from the source's
    point of view — the id is simply not one of its deployments — and both are
    rejected the same way, upfront, with zero side effects (``NOT_FOUND``).
    Cloning the wrong environment's deployment is never what the caller meant,
    and attributing it as a skip would bury a typo in a report.

    Everything else about the selection is *not* an error (FR-004): a selected
    deployment that exists here but cannot be cloned — no active instance,
    internal, deleted — is attributed as ``SKIPPED`` with a reason by
    :func:`_plan_deployment_results`.

    ``deployments`` must therefore be the environment's **full** roster,
    including tombstoned and internal rows, or a legal-but-ineligible id would
    be misreported as unknown.

    Raises:
        InvalidCloneDeploymentSelectionError: When any selected id is not a
            deployment of the source environment.
    """
    if deployment_ids is None:
        return
    known = {deployment.id for deployment in deployments}
    # ``dict.fromkeys`` de-duplicates a repeated id while keeping the order the
    # caller sent, so the error names each offender once and reads predictably.
    unknown = [
        str(deployment_id)
        for deployment_id in dict.fromkeys(deployment_ids)
        if deployment_id not in known
    ]
    if unknown:
        raise InvalidCloneDeploymentSelectionError(deployment_ids=unknown)


def _plan_deployment_results(
    deployments: Sequence[DeploymentEntity], deployment_ids: Sequence[UUID] | None
) -> list[CloneDeploymentResult]:
    """Account for every source deployment before the capture is registered.

    SC-003 wants 100% attribution, and every outcome that is already known at
    registration time is recorded here so it survives even a clone whose flow
    never runs:

    * a deployment an explicit selection left out → ``SKIPPED``;
    * a deployment that cannot contribute a constituent backup → ``SKIPPED``
      with the reason, never an error (FR-004). Ineligibility comes in three
      flavours and each gets its own reason: no active instance (never
      deployed), internal, deleted.

    Everything else starts ``PENDING`` and the flow resolves it.

    Deployments that are not part of the environment's application topology —
    internal ones (platform-managed infrastructure; the cloned environment gets
    its own through ``_ensure_ingress_controller``) and tombstoned ones — are
    listed **only when the selection names them explicitly**. Left out of an
    unfiltered clone they would be noise on every clone record of every
    environment; named by the caller they are an answer the caller is owed.

    ``deployments`` is the full roster (``include_deleted=True``) so that the
    explicit case above is expressible at all.
    """
    selected = set(deployment_ids) if deployment_ids is not None else None
    results: list[CloneDeploymentResult] = []
    for deployment in deployments:
        explicitly_selected = selected is not None and deployment.id in selected
        if deployment.deleted_at is not None or deployment.internal:
            if not explicitly_selected:
                continue
            reason: str | None = (
                CLONE_REASON_TOMBSTONED
                if deployment.deleted_at is not None
                else CLONE_REASON_INTERNAL
            )
        elif selected is not None and not explicitly_selected:
            reason = CLONE_REASON_NOT_SELECTED
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
       is free in the source's cluster, check every selected deployment id is
       one of the source's, and apply the environment-level concurrency guard
       to the source (research D8).
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
        deployment_ids: Optional selection of the source's deployments.
            ``None`` means every eligible deployment (spec FR-003); ``[]`` is a
            legal empty selection and clones nothing. An id the source does not
            have is rejected upfront; a selected id that exists but is
            ineligible is attributed as a skip (spec FR-004).
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
        InvalidCloneDeploymentSelectionError: When ``deployment_ids`` names a
            deployment that is unknown or belongs to another environment.
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

        # The full roster, tombstones included: the selection is validated
        # against what the source *has* (a deleted deployment is ineligible,
        # not unknown — FR-004 vs FR-011), and the planner needs the same list
        # to attribute an explicitly selected internal or deleted deployment.
        deployments = await uow.deployments.find_all_by_environment(
            source.id, include_deleted=True
        )
        # Request validation before the state-dependent guard: a selection
        # naming a deployment the source does not have is wrong no matter what
        # else is running (FR-011).
        _validate_deployment_selection(deployment_ids, deployments)

        await _guard_no_environment_operation_in_progress(source.id, uow)

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
