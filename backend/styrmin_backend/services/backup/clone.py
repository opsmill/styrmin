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
from uuid import UUID

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
from styrmin_backend.repository.environment_backup import NON_TERMINAL_RESTORE_STATUSES
from styrmin_backend.services.backup.environment import (
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    EnvironmentOperationStatus,
    derive_environment_operation_status,
)
from styrmin_backend.services.exceptions import (
    InvalidContextError,
    UnknownEnvironmentConfigFieldError,
)


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
