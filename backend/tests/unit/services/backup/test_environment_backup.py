"""Unit tests for the environment-level backup/restore service primitives.

The derived-status rule is the load-bearing piece of research.md D2: because
``EnvironmentBackup``/``EnvironmentRestore`` store no status column, this
function is the single definition of what a parent's status means, and it must
never contradict the constituents it is derived from (spec FR-004 / SC-003).
"""

import pytest

from styrmin_backend.db.models import BackupStatus, RestoreStatus
from styrmin_backend.services.backup.environment import (
    RESTORABLE_ENVIRONMENT_BACKUP_STATUSES,
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    ConstituentError,
    DeploymentSnapshot,
    EnvironmentOperationStatus,
    SkipReason,
    SkippedConstituent,
    derive_environment_operation_status,
)

from uuid import uuid4


# ---------------------------------------------------------------------------
# Derived status — backup constituents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "error_count", "expected"),
    [
        # All constituents succeeded and nothing failed at creation.
        (
            [BackupStatus.COMPLETED, BackupStatus.COMPLETED],
            0,
            EnvironmentOperationStatus.COMPLETED,
        ),
        # Mixed terminal outcomes -> PARTIAL.
        (
            [BackupStatus.COMPLETED, BackupStatus.FAILED],
            0,
            EnvironmentOperationStatus.PARTIAL,
        ),
        # A completed child alongside a constituent that never got a row.
        (
            [BackupStatus.COMPLETED],
            1,
            EnvironmentOperationStatus.PARTIAL,
        ),
        # Every constituent failed.
        (
            [BackupStatus.FAILED, BackupStatus.FAILED],
            0,
            EnvironmentOperationStatus.FAILED,
        ),
        # Errors only: no child row was ever created.
        ([], 2, EnvironmentOperationStatus.FAILED),
        # A failed child plus creation errors, nothing completed.
        ([BackupStatus.FAILED], 1, EnvironmentOperationStatus.FAILED),
        # Any non-terminal child keeps the parent in progress.
        (
            [BackupStatus.COMPLETED, BackupStatus.IN_PROGRESS],
            0,
            EnvironmentOperationStatus.IN_PROGRESS,
        ),
        (
            [BackupStatus.FAILED, BackupStatus.PENDING],
            0,
            EnvironmentOperationStatus.IN_PROGRESS,
        ),
        (
            [BackupStatus.PENDING, BackupStatus.IN_PROGRESS],
            0,
            EnvironmentOperationStatus.IN_PROGRESS,
        ),
        # Nothing has started yet.
        (
            [BackupStatus.PENDING, BackupStatus.PENDING],
            0,
            EnvironmentOperationStatus.PENDING,
        ),
        # Config-only snapshot: no eligible deployments, nothing failed (FR-011).
        ([], 0, EnvironmentOperationStatus.COMPLETED),
    ],
)
def test_derive_status_over_backup_outcome_matrix(
    statuses: list[BackupStatus],
    error_count: int,
    expected: EnvironmentOperationStatus,
) -> None:
    assert derive_environment_operation_status(statuses, error_count) == expected


def test_all_pending_with_recorded_errors_is_in_progress_not_pending() -> None:
    """A recorded creation error means work has already happened.

    ``PENDING`` is reserved for "nothing has happened yet", so a snapshot that
    already produced a conflict must not read as untouched.
    """
    assert (
        derive_environment_operation_status([BackupStatus.PENDING], error_count=1)
        == EnvironmentOperationStatus.IN_PROGRESS
    )


# ---------------------------------------------------------------------------
# Derived status — restore constituents (same rule, different enum)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "error_count", "expected"),
    [
        (
            [RestoreStatus.COMPLETED, RestoreStatus.COMPLETED],
            0,
            EnvironmentOperationStatus.COMPLETED,
        ),
        # A completed restore plus a skipped constituent -> PARTIAL.
        ([RestoreStatus.COMPLETED], 1, EnvironmentOperationStatus.PARTIAL),
        (
            [RestoreStatus.COMPLETED, RestoreStatus.FAILED],
            0,
            EnvironmentOperationStatus.PARTIAL,
        ),
        ([RestoreStatus.FAILED], 0, EnvironmentOperationStatus.FAILED),
        # Everything was skipped: nothing to restore, nothing succeeded.
        ([], 3, EnvironmentOperationStatus.FAILED),
        (
            [RestoreStatus.IN_PROGRESS, RestoreStatus.COMPLETED],
            0,
            EnvironmentOperationStatus.IN_PROGRESS,
        ),
        ([RestoreStatus.PENDING], 0, EnvironmentOperationStatus.PENDING),
        ([], 0, EnvironmentOperationStatus.COMPLETED),
    ],
)
def test_derive_status_over_restore_outcome_matrix(
    statuses: list[RestoreStatus],
    error_count: int,
    expected: EnvironmentOperationStatus,
) -> None:
    assert derive_environment_operation_status(statuses, error_count) == expected


def test_derived_status_never_contradicts_a_non_terminal_child() -> None:
    """SC-003: a terminal parent status with a non-terminal child is impossible."""
    for non_terminal in (BackupStatus.PENDING, BackupStatus.IN_PROGRESS):
        for companion in BackupStatus:
            status = derive_environment_operation_status(
                [companion, non_terminal], error_count=0
            )
            assert status not in TERMINAL_ENVIRONMENT_OPERATION_STATUSES


def test_restorable_statuses_are_completed_and_partial() -> None:
    """A restore is offered only for snapshots that captured something usable."""
    assert RESTORABLE_ENVIRONMENT_BACKUP_STATUSES == {
        EnvironmentOperationStatus.COMPLETED,
        EnvironmentOperationStatus.PARTIAL,
    }
    assert (
        EnvironmentOperationStatus.FAILED not in RESTORABLE_ENVIRONMENT_BACKUP_STATUSES
    )


# ---------------------------------------------------------------------------
# Snapshot models
# ---------------------------------------------------------------------------


def test_deployment_snapshot_round_trips_through_json() -> None:
    """The snapshot is stored as plain JSON on the parent row."""
    deployment_id = uuid4()
    instance_id = uuid4()
    snapshot = DeploymentSnapshot(
        deployment_id=deployment_id,
        deployment_name="infrahub",
        instance_id=instance_id,
        driver_name="infrahub-driver",
        driver_version="1.2.0",
        driver_fingerprint="abc1234",
        application_version="1.6.0",
        config={"replicas": 2},
        parameters={"license": "ent"},
    )

    payload = snapshot.model_dump(mode="json")

    assert payload["deployment_id"] == str(deployment_id)
    assert payload["instance_id"] == str(instance_id)
    assert DeploymentSnapshot.model_validate(payload) == snapshot


def test_deployment_snapshot_fingerprint_and_config_are_optional() -> None:
    """A local driver with no config still produces a valid snapshot."""
    snapshot = DeploymentSnapshot(
        deployment_id=uuid4(),
        deployment_name="minimal",
        instance_id=uuid4(),
        driver_name="simple-app",
        driver_version="0.1.0",
        application_version="0.1.0",
    )

    assert snapshot.driver_fingerprint is None
    assert snapshot.config is None
    assert snapshot.parameters is None


def test_constituent_error_and_skipped_constituent_attribute_by_name() -> None:
    """FR-005/FR-007: every failure names the deployment it belongs to."""
    deployment_id = uuid4()

    error = ConstituentError(
        deployment_id=deployment_id,
        deployment_name="busy-app",
        error="backup already in progress (existing: 123)",
    )
    skipped = SkippedConstituent(
        deployment_id=deployment_id,
        deployment_name="busy-app",
        reason=SkipReason.BACKUP_EXPIRED,
    )

    assert error.model_dump(mode="json")["deployment_name"] == "busy-app"
    assert skipped.model_dump(mode="json")["reason"] == "backup expired"


def test_skip_reasons_match_the_uniform_vocabulary() -> None:
    """data-model.md fixes the skip vocabulary; drift here breaks the UI copy."""
    assert {reason.value for reason in SkipReason} == {
        "backup failed at creation",
        "backup not completed",
        "backup deleted",
        "backup expired",
        "deployment no longer exists",
        "deployment busy with another restore",
    }
