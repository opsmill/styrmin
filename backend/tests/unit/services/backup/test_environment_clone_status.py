"""Unit matrix for the derived environment-clone status.

``EnvironmentClone`` stores no status column (010 spec FR-009), so
:func:`derive_environment_clone_status` is the single definition of what a
clone's four heterogeneous inputs mean together — the capture's own derived
status, whether the created environment exists, the constituent restore rows,
and the recorded ``clone_errors``.

The rows that matter most are the ones where an input has been *removed*
underneath the record: data-model.md's resolution rules say a missing input is
never re-interpreted, and that history is rewritten only through an explicit
``clone_errors`` entry. That is what separates "the TTL cleaner deleted the
backup of a finished clone" (outcome stands) from "an operator deleted the
backup of a running clone" (FAILED, attributed) — two states whose stored
columns are otherwise identical.
"""

from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    EnvironmentBackup,
    EnvironmentClone,
    Restore,
    RestoreStatus,
)
from styrmin_backend.services.backup.clone import (
    CLONE_STEP_CAPTURE_FAILED,
    CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
    CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
    CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
    CLONE_STEP_TARGET_NAME_TAKEN,
    CLONE_STEPS,
    TERMINAL_ENVIRONMENT_CLONE_STATUSES,
    CloneDeploymentResult,
    CloneError,
    EnvironmentCloneDeploymentOutcome,
    EnvironmentCloneStatus,
    derive_clone_capture_status,
    derive_environment_clone_status,
    derive_environment_clone_status_from_record,
)
from styrmin_backend.services.backup.environment import EnvironmentOperationStatus

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _result(
    outcome: str,
    *,
    restore_id: UUID | None = None,
    name: str = "app",
    reason: str | None = None,
    counterpart_deployment_id: UUID | None = None,
) -> dict:
    """One stored ``deployment_results`` entry (JSON, as the service writes it)."""
    return CloneDeploymentResult(
        deployment_id=uuid4(),
        deployment_name=name,
        outcome=EnvironmentCloneDeploymentOutcome(outcome),
        reason=reason,
        counterpart_deployment_id=counterpart_deployment_id,
        restore_id=restore_id,
    ).model_dump(mode="json")


def _error(step: str, *, fatal: bool, error: str = "boom") -> dict:
    return CloneError(step=step, error=error, fatal=fatal).model_dump(mode="json")


def _restore(status: RestoreStatus) -> Restore:
    return Restore(
        name=f"restore-{uuid4().hex[:8]}",
        status=status,
        target_namespace="styrmin-counterpart",
        backup_id=uuid4(),
    )


def _restores(*restores: Restore) -> dict[UUID, Restore]:
    return {restore.id: restore for restore in restores}


COMPLETED_CAPTURE = EnvironmentOperationStatus.COMPLETED
PARTIAL_CAPTURE = EnvironmentOperationStatus.PARTIAL


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_clone_status_vocabulary_matches_the_environment_operation_one() -> None:
    """data-model.md: the clone reuses the environment-operation vocabulary."""
    assert {status.value for status in EnvironmentCloneStatus} == {
        status.value for status in EnvironmentOperationStatus
    }


def test_terminal_set_is_completed_partial_failed() -> None:
    """The guards (D8/D9) key on this set; drift silently re-locks environments."""
    assert TERMINAL_ENVIRONMENT_CLONE_STATUSES == {
        EnvironmentCloneStatus.COMPLETED,
        EnvironmentCloneStatus.PARTIAL,
        EnvironmentCloneStatus.FAILED,
    }
    assert EnvironmentCloneStatus.PENDING not in TERMINAL_ENVIRONMENT_CLONE_STATUSES
    assert EnvironmentCloneStatus.IN_PROGRESS not in TERMINAL_ENVIRONMENT_CLONE_STATUSES


def test_outcome_and_step_vocabularies_are_fixed() -> None:
    """The four write-side outcomes and the five recorded steps (data-model.md)."""
    assert {outcome.value for outcome in EnvironmentCloneDeploymentOutcome} == {
        "pending",
        "cloned",
        "skipped",
        "failed",
    }
    assert CLONE_STEPS == {
        CLONE_STEP_CAPTURE_FAILED,
        CLONE_STEP_TARGET_NAME_TAKEN,
        CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
        CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
        CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
    }


def test_result_and_error_entries_round_trip_through_json() -> None:
    """Both entry shapes are stored as plain JSON on the clone row."""
    deployment_id, counterpart_id, restore_id = uuid4(), uuid4(), uuid4()
    entry = CloneDeploymentResult(
        deployment_id=deployment_id,
        deployment_name="postgres-main",
        outcome=EnvironmentCloneDeploymentOutcome.CLONED,
        counterpart_deployment_id=counterpart_id,
        restore_id=restore_id,
    )
    payload = entry.model_dump(mode="json")
    assert payload["deployment_id"] == str(deployment_id)
    assert payload["outcome"] == "cloned"
    assert payload["reason"] is None
    assert CloneDeploymentResult.model_validate(payload) == entry

    error = CloneError(
        step=CLONE_STEP_CAPTURE_FAILED, error="capture failed", fatal=True
    )
    assert CloneError.model_validate(error.model_dump(mode="json")) == error


# ---------------------------------------------------------------------------
# Rule 1 — a fatal entry is terminal, whatever else is recorded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "capture_status",
    [
        None,
        EnvironmentOperationStatus.PENDING,
        EnvironmentOperationStatus.IN_PROGRESS,
        EnvironmentOperationStatus.COMPLETED,
        EnvironmentOperationStatus.PARTIAL,
        EnvironmentOperationStatus.FAILED,
    ],
)
def test_a_fatal_clone_error_is_failed_regardless_of_everything_else(
    capture_status: EnvironmentOperationStatus | None,
) -> None:
    """Rule 1: the fatal entry wins, so the D8/D9 guards are always released."""
    restore = _restore(RestoreStatus.IN_PROGRESS)
    assert (
        derive_environment_clone_status(
            capture_status=capture_status,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("pending"),
                _result("cloned", restore_id=restore.id),
            ],
            clone_errors=[_error(CLONE_STEP_TARGET_NAME_TAKEN, fatal=True)],
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.FAILED
    )


def test_a_per_deployment_failure_is_not_a_fatal_entry() -> None:
    """Per-deployment failures live in ``deployment_results``, never as fatal."""
    assert (
        derive_environment_clone_status(
            capture_status=PARTIAL_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[_result("failed", reason="driver version gone")],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.FAILED
    )
    assert (
        derive_environment_clone_status(
            capture_status=PARTIAL_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("failed", reason="driver version gone"),
                _result("cloned"),
            ],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.PARTIAL
    )


# ---------------------------------------------------------------------------
# Rules 2 & 3 — nothing yet / still moving
# ---------------------------------------------------------------------------


def test_queued_capture_with_untouched_entries_is_pending() -> None:
    """Rule 2: registration happened, nothing has progressed."""
    assert (
        derive_environment_clone_status(
            capture_status=EnvironmentOperationStatus.PENDING,
            created_environment_id=None,
            deployment_results=[_result("pending"), _result("pending")],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.PENDING
    )


def test_an_upfront_skip_counts_as_progress_so_the_clone_is_in_progress() -> None:
    """Resolved ambiguity: "nothing else recorded" means nothing past ``pending``.

    Mirrors ``derive_environment_operation_status``, where a recorded error
    means work has happened even while every surviving child is queued.
    """
    assert (
        derive_environment_clone_status(
            capture_status=EnvironmentOperationStatus.PENDING,
            created_environment_id=None,
            deployment_results=[
                _result("pending"),
                _result("skipped", reason="deployment has no active instance"),
            ],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


def test_non_fatal_history_on_a_queued_capture_is_in_progress() -> None:
    """A recorded (non-fatal) event is also progress, not an untouched clone."""
    assert (
        derive_environment_clone_status(
            capture_status=EnvironmentOperationStatus.PENDING,
            created_environment_id=None,
            deployment_results=[_result("pending")],
            clone_errors=[_error(CLONE_STEP_ENVIRONMENT_BACKUP_DELETED, fatal=False)],
            restores={},
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


def test_capture_in_flight_is_in_progress() -> None:
    assert (
        derive_environment_clone_status(
            capture_status=EnvironmentOperationStatus.IN_PROGRESS,
            created_environment_id=None,
            deployment_results=[_result("pending")],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


def test_terminal_capture_without_an_environment_yet_is_in_progress() -> None:
    """Materialisation pending — including the dead-flow case (research D9).

    A flow that died after a successful capture leaves exactly this state, and
    it stays ``IN_PROGRESS`` until an operator uses an escape hatch. That is
    deliberate: the alternative (guessing ``FAILED``) would release the guards
    on a clone that may still be building.
    """
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=None,
            deployment_results=[_result("pending")],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


def test_a_pending_entry_keeps_a_materialised_clone_in_progress() -> None:
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[_result("cloned"), _result("pending")],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


@pytest.mark.parametrize(
    "restore_status", [RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS]
)
def test_a_non_terminal_referenced_restore_keeps_the_clone_in_progress(
    restore_status: RestoreStatus,
) -> None:
    restore = _restore(restore_status)
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[_result("cloned", restore_id=restore.id)],
            clone_errors=None,
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


# ---------------------------------------------------------------------------
# Rules 4-6 — the landed outcome
# ---------------------------------------------------------------------------


def test_all_restores_completed_is_completed() -> None:
    first, second = _restore(RestoreStatus.COMPLETED), _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("cloned", restore_id=first.id),
                _result("cloned", restore_id=second.id),
            ],
            clone_errors=None,
            restores=_restores(first, second),
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_skips_are_not_failures() -> None:
    """FR-004: a skipped deployment neither fails nor rescues the clone."""
    restore = _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("cloned", restore_id=restore.id),
                _result("skipped", reason="deployment has no active instance"),
            ],
            clone_errors=None,
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_an_all_skipped_clone_is_completed() -> None:
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("skipped", reason="internal deployment"),
                _result("skipped", reason="deployment has no active instance"),
            ],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_a_failed_restore_turns_a_cloned_entry_into_a_failure() -> None:
    """Rule 5: the entry says ``cloned``, but its restore ended ``FAILED``."""
    failed = _restore(RestoreStatus.FAILED)
    completed = _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("cloned", restore_id=failed.id),
                _result("cloned", restore_id=completed.id),
            ],
            clone_errors=None,
            restores=_restores(failed, completed),
        )
        == EnvironmentCloneStatus.PARTIAL
    )
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[_result("cloned", restore_id=failed.id)],
            clone_errors=None,
            restores=_restores(failed),
        )
        == EnvironmentCloneStatus.FAILED
    )


def test_skipped_alongside_failed_with_nothing_cloned_is_failed() -> None:
    """Resolved ambiguity: "every *included* entry failed" — skips aren't included."""
    assert (
        derive_environment_clone_status(
            capture_status=PARTIAL_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("skipped", reason="deployment has no active instance"),
                _result("failed", reason="constituent backup failed at capture"),
            ],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.FAILED
    )


def test_a_partial_capture_attributes_its_failures_and_ends_partial() -> None:
    """FR-002: constituents that failed at capture are ``failed`` entries.

    The capture itself being ``PARTIAL`` is not a clone-level failure — it is
    restorable, so the clone proceeds and the lost constituents show up as
    per-deployment failures alongside the ones that made it.
    """
    restore = _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=PARTIAL_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                _result("cloned", name="ok", restore_id=restore.id),
                _result(
                    "failed",
                    name="lost-at-capture",
                    reason="constituent backup failed at capture",
                ),
            ],
            clone_errors=None,
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.PARTIAL
    )


def test_an_empty_selection_is_completed() -> None:
    """Nothing selected, nothing failed — matching ``derive([], 0) == COMPLETED``.

    The environment still materialises (config-only), so this is a success, not
    a clone that did nothing.
    """
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=None,
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.COMPLETED
    )
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[],
            clone_errors=[],
            restores={},
        )
        == EnvironmentCloneStatus.COMPLETED
    )


# ---------------------------------------------------------------------------
# Resolution rule 1 — a missing input is never re-interpreted
# ---------------------------------------------------------------------------


def test_a_missing_restore_row_leaves_the_recorded_outcome_final() -> None:
    """The restore cascaded away with its backup; ``cloned`` still means cloned."""
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[_result("cloned", restore_id=uuid4())],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_an_unparseable_restore_id_is_treated_as_a_missing_row() -> None:
    """A historical row with a junk id must not break every read of the clone."""
    entry = _result("cloned")
    entry["restore_id"] = "not-a-uuid"
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[entry],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_a_backup_deleted_after_terminality_leaves_the_outcome_standing() -> None:
    """FR-008 / research D9: routine TTL cleanup must not rewrite history.

    The capture is gone (``capture_status is None``) and the deletion recorded
    itself non-fatally because the clone had already finished.
    """
    restore = _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=None,
            created_environment_id=uuid4(),
            deployment_results=[_result("cloned", restore_id=restore.id)],
            clone_errors=[
                _error(
                    CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
                    fatal=False,
                    error="backup deleted after the clone completed",
                )
            ],
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_a_backup_deleted_mid_clone_is_failed_and_attributed() -> None:
    """The escape hatch for a stuck clone: FAILED, with the deletion recorded.

    Same stored columns as the row above apart from the ``fatal`` flag — which
    is precisely why the flag exists.
    """
    status = derive_environment_clone_status(
        capture_status=None,
        created_environment_id=None,
        deployment_results=[_result("pending")],
        clone_errors=[
            _error(
                CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
                fatal=True,
                error="backing environment backup deleted while the clone was running",
            )
        ],
        restores={},
    )
    assert status == EnvironmentCloneStatus.FAILED
    assert status in TERMINAL_ENVIRONMENT_CLONE_STATUSES


def test_a_deleted_created_environment_is_told_apart_from_a_missing_one() -> None:
    """A bare null FK cannot say which of the two happened — the marker can.

    Non-terminal at deletion time → ``FAILED``; already terminal → the recorded
    outcome stands. Without the marker the same null reads as "not yet created"
    (``IN_PROGRESS``).
    """
    restore = _restore(RestoreStatus.COMPLETED)
    results = [_result("cloned", restore_id=restore.id)]
    rows = _restores(restore)

    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=None,
            deployment_results=results,
            clone_errors=[_error(CLONE_STEP_CREATED_ENVIRONMENT_DELETED, fatal=False)],
            restores=rows,
        )
        == EnvironmentCloneStatus.COMPLETED
    )
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=None,
            deployment_results=[_result("pending")],
            clone_errors=[_error(CLONE_STEP_CREATED_ENVIRONMENT_DELETED, fatal=True)],
            restores={},
        )
        == EnvironmentCloneStatus.FAILED
    )
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=None,
            deployment_results=results,
            clone_errors=None,
            restores=rows,
        )
        == EnvironmentCloneStatus.IN_PROGRESS
    )


# ---------------------------------------------------------------------------
# Malformed / unknown inputs
# ---------------------------------------------------------------------------


def test_malformed_entries_are_ignored_rather_than_raising() -> None:
    """One unreadable JSON entry must not break every read of the clone."""
    restore = _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=["nonsense", _result("cloned", restore_id=restore.id)],
            clone_errors=["nonsense"],
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_a_clone_error_without_a_fatal_flag_reads_as_non_fatal() -> None:
    """Safe direction: never rewrite a standing outcome because of a bad write."""
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[_result("cloned")],
            clone_errors=[{"step": "mystery", "error": "no flag"}],
            restores={},
        )
        == EnvironmentCloneStatus.COMPLETED
    )


def test_an_unrecognised_outcome_is_counted_as_a_failure() -> None:
    """The coverage identity needs every entry accounted for, readable or not."""
    entry = _result("cloned")
    entry["outcome"] = "teleported"
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[entry],
            clone_errors=None,
            restores={},
        )
        == EnvironmentCloneStatus.FAILED
    )


def test_pydantic_entries_are_accepted_as_well_as_stored_dicts() -> None:
    """The flow holds typed entries; the resolvers hold the JSON it wrote."""
    restore = _restore(RestoreStatus.COMPLETED)
    assert (
        derive_environment_clone_status(
            capture_status=COMPLETED_CAPTURE,
            created_environment_id=uuid4(),
            deployment_results=[
                CloneDeploymentResult(
                    deployment_id=uuid4(),
                    deployment_name="app",
                    outcome=EnvironmentCloneDeploymentOutcome.CLONED,
                    restore_id=restore.id,
                )
            ],
            clone_errors=[
                CloneError(
                    step=CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
                    error="gone",
                    fatal=False,
                )
            ],
            restores=_restores(restore),
        )
        == EnvironmentCloneStatus.COMPLETED
    )


# ---------------------------------------------------------------------------
# Coverage identity (SC-003)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "companions",
    [
        [],
        [_result("cloned")],
        [_result("skipped", reason="no active instance")],
        [_result("failed", reason="driver version gone")],
        [_result("cloned"), _result("failed", reason="driver version gone")],
    ],
)
@pytest.mark.parametrize(
    "capture_status",
    [
        None,
        EnvironmentOperationStatus.PENDING,
        EnvironmentOperationStatus.IN_PROGRESS,
        EnvironmentOperationStatus.COMPLETED,
        EnvironmentOperationStatus.PARTIAL,
        EnvironmentOperationStatus.FAILED,
    ],
)
@pytest.mark.parametrize("created", [True, False])
def test_a_pending_entry_can_never_appear_on_a_terminal_clone(
    companions: list[dict],
    capture_status: EnvironmentOperationStatus | None,
    created: bool,
) -> None:
    """Coverage identity, half one: a terminal clone contains no ``pending``.

    Asserted as the mechanical property rather than a single row, because it is
    what makes ``deployment_results`` trustworthy as an account of every source
    deployment: a clone cannot come to rest while an entry is unresolved.
    """
    status = derive_environment_clone_status(
        capture_status=capture_status,
        created_environment_id=uuid4() if created else None,
        deployment_results=[*companions, _result("pending")],
        clone_errors=None,
        restores={},
    )
    assert status not in TERMINAL_ENVIRONMENT_CLONE_STATUSES


def test_a_terminal_clone_accounts_for_every_source_deployment() -> None:
    """Coverage identity, half two: one entry per deployment considered."""
    considered = ["postgres-main", "web", "never-deployed"]
    results = [
        _result("cloned", name="postgres-main"),
        _result(
            "failed", name="web", reason="captured driver version no longer exists"
        ),
        _result(
            "skipped", name="never-deployed", reason="deployment has no active instance"
        ),
    ]

    status = derive_environment_clone_status(
        capture_status=PARTIAL_CAPTURE,
        created_environment_id=uuid4(),
        deployment_results=results,
        clone_errors=None,
        restores={},
    )

    assert status in TERMINAL_ENVIRONMENT_CLONE_STATUSES
    assert status == EnvironmentCloneStatus.PARTIAL
    assert len(results) == len(considered)
    assert [entry["deployment_name"] for entry in results] == considered
    assert all(entry["outcome"] != "pending" for entry in results)
    assert all(
        entry["reason"] is not None
        for entry in results
        if entry["outcome"] in ("skipped", "failed")
    )


# ---------------------------------------------------------------------------
# Reading a persisted record
# ---------------------------------------------------------------------------


def _environment_backup(
    *backup_statuses: BackupStatus, errors: int = 0
) -> EnvironmentBackup:
    environment_backup = EnvironmentBackup(
        name=f"styrmin-envbackup-{uuid4()}",
        environment_id=uuid4(),
        constituent_errors=[
            {"deployment_id": str(uuid4()), "deployment_name": "x", "error": "boom"}
            for _ in range(errors)
        ]
        or None,
    )
    for status in backup_statuses:
        environment_backup.backups.append(
            Backup(name=f"backup-{uuid4().hex[:8]}", status=status, instance_id=uuid4())
        )
    return environment_backup


def test_derive_clone_capture_status_folds_the_captures_own_constituents() -> None:
    assert derive_clone_capture_status(None) is None
    assert (
        derive_clone_capture_status(_environment_backup(BackupStatus.PENDING))
        is EnvironmentOperationStatus.PENDING
    )
    assert (
        derive_clone_capture_status(
            _environment_backup(BackupStatus.COMPLETED, errors=1)
        )
        is EnvironmentOperationStatus.PARTIAL
    )


def test_deriving_from_a_record_reads_the_same_inputs() -> None:
    """The adapter every resolver, guard and cascade goes through."""
    restore = _restore(RestoreStatus.COMPLETED)
    clone = EnvironmentClone(
        name="staging-copy",
        source_environment_name="staging",
        deployment_results=[_result("cloned", restore_id=restore.id)],
        created_environment_id=uuid4(),
    )
    clone.environment_backup = _environment_backup(BackupStatus.COMPLETED)

    assert (
        derive_environment_clone_status_from_record(clone, _restores(restore))
        == EnvironmentCloneStatus.COMPLETED
    )

    clone.environment_backup = None
    clone.created_environment_id = None
    clone.clone_errors = [_error(CLONE_STEP_ENVIRONMENT_BACKUP_DELETED, fatal=True)]
    assert (
        derive_environment_clone_status_from_record(clone)
        == EnvironmentCloneStatus.FAILED
    )
