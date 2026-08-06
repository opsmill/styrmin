"""Unit tests for the environment-level backup/restore service primitives.

The derived-status rule is the load-bearing piece of research.md D2: because
``EnvironmentBackup``/``EnvironmentRestore`` store no status column, this
function is the single definition of what a parent's status means, and it must
never contradict the constituents it is derived from (spec FR-004 / SC-003).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    ApplicationInstance,
    Backup,
    BackupStatus,
    Environment,
    EnvironmentBackup,
    EnvironmentRestore,
    InstanceStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity
from styrmin_backend.services.backup.environment import (
    RESTORABLE_ENVIRONMENT_BACKUP_STATUSES,
    TERMINAL_ENVIRONMENT_OPERATION_STATUSES,
    ConstituentError,
    DeploymentSnapshot,
    EnvironmentOperationStatus,
    SkipReason,
    SkippedConstituent,
    create_environment_backup,
    derive_environment_operation_status,
)
from styrmin_backend.services.exceptions import (
    EnvironmentNotFoundError,
    EnvironmentOperationInProgressError,
)
from styrmin_backend.workflows.models import PrefectAction
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
    FakeDeploymentRepository,
    FakeEnvironmentBackupRepository,
    FakeEnvironmentRepository,
    FakeEnvironmentRestoreRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeRestoreRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


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


# ---------------------------------------------------------------------------
# create_environment_backup — fan-out
# ---------------------------------------------------------------------------


def _global_context() -> GlobalContext:
    """The minimum viable instance context; none of its values are asserted on."""
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=uuid4(),
            namespace="test-ns",
            release_reference="test-ref",
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="test-chart", version="0.1.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )


def _driver_version(
    *,
    driver_name: str = "infrahub-driver",
    version: str = "1.2.0",
    content_hash: str | None = None,
    source_commit_sha: str | None = None,
) -> ApplicationDriverVersion:
    driver = ApplicationDriver(name=driver_name)
    adv = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type="local" if content_hash else "git",
        source_repository="https://github.com/test/repo",
        content_hash=content_hash,
        source_commit_sha=source_commit_sha,
        helm_chart_id=uuid4(),
    )
    adv.application_driver = driver
    return adv


def _deployment(
    *,
    environment_id: UUID,
    adv: ApplicationDriverVersion,
    name: str,
    with_instance: bool = True,
    internal: bool = False,
    deleted_at: datetime | None = None,
    config: dict | None = None,
    parameters: dict | None = None,
    application_version: str = "1.6.0",
) -> DeploymentEntity:
    deployment = DeploymentEntity(
        id=uuid4(),
        name=name,
        application_version=application_version,
        config=config,
        parameters=parameters or {},
        internal=internal,
        application_driver_version_id=adv.id,
        environment_id=environment_id,
        deleted_at=deleted_at,
        created_by_user_id=uuid4(),
    )
    if with_instance:
        deployment.set_active_instance(
            InstanceEntity(
                id=uuid4(),
                name=f"{name}-instance",
                application_version=application_version,
                status=InstanceStatusEntity.RUNNING,
                deployment_id=deployment.id,
                application_driver_version_id=adv.id,
                context=_global_context(),
            )
        )
    return deployment


def _make_uow(
    *,
    environment: Environment,
    deployments: list[DeploymentEntity],
    driver_versions: list[ApplicationDriverVersion],
    backups: list[Backup] | None = None,
    restores: list[Restore] | None = None,
    environment_backups: list[EnvironmentBackup] | None = None,
    environment_restores: list[EnvironmentRestore] | None = None,
) -> FakeUnitOfWork:
    """Build a UoW whose repositories are consistent with each other.

    Every eligible deployment gets a matching ``ApplicationInstance`` row so
    ``resolve_backup_target`` can walk instance → deployment the same way it
    does in production.
    """
    instances = FakeApplicationInstanceRepository(
        [
            ApplicationInstance(
                id=deployment.active_instance.id,
                name=deployment.active_instance.name,
                application_version=deployment.active_instance.application_version,
                status=InstanceStatus.RUNNING,
                deployment_id=deployment.id,
                application_driver_version_id=deployment.application_driver_version_id,
            )
            for deployment in deployments
            if deployment.active_instance is not None
        ]
    )
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository([environment]),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(driver_versions),
        instances=instances,
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployments=FakeDeploymentRepository(deployments),
        backups=FakeBackupRepository(backups or []),
        restores=FakeRestoreRepository(restores or []),
        environment_backups=FakeEnvironmentBackupRepository(environment_backups or []),
        environment_restores=FakeEnvironmentRestoreRepository(
            environment_restores or []
        ),
    )


@pytest.fixture
def environment() -> Environment:
    return Environment(
        name="staging",
        cluster_id=uuid4(),
        config={"dns_zone": "staging.example.com"},
    )


@pytest.mark.asyncio
async def test_fan_out_creates_one_constituent_per_eligible_deployment(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-001/SC-001: one action, one constituent per eligible deployment."""
    adv = _driver_version()
    deployments = [
        _deployment(environment_id=environment.id, adv=adv, name="infrahub"),
        _deployment(environment_id=environment.id, adv=adv, name="netbox"),
    ]
    uow = _make_uow(
        environment=environment, deployments=deployments, driver_versions=[adv]
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert len(uow.backups.models) == 2
    assert {backup.environment_backup_id for backup in uow.backups.models} == {
        environment_backup.id
    }
    assert environment_backup.constituent_errors is None
    assert environment_backup.name == f"styrmin-envbackup-{environment_backup.id}"

    dispatched = [
        call.kwargs for call in prefect_manager_mock.run_action.call_args_list
    ]
    assert len(dispatched) == 2
    assert {call["action"] for call in dispatched} == {PrefectAction.EXECUTE_BACKUP}
    assert {call["parameters"]["deployment_id"] for call in dispatched} == {
        str(deployment.id) for deployment in deployments
    }


@pytest.mark.asyncio
async def test_snapshot_captures_config_and_declared_state(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-002/FR-003: captured config plus per-deployment declared state."""
    adv = _driver_version(
        driver_name="infrahub-driver", version="1.2.0", source_commit_sha="abc1234def"
    )
    deployment = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="infrahub",
        config={"replicas": 2},
        parameters={"license": "ent"},
        application_version="1.6.0",
    )
    uow = _make_uow(
        environment=environment, deployments=[deployment], driver_versions=[adv]
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.environment_config == {"dns_zone": "staging.example.com"}
    assert environment_backup.deployment_snapshots is not None
    snapshot = DeploymentSnapshot.model_validate(
        environment_backup.deployment_snapshots[0]
    )
    assert snapshot.deployment_id == deployment.id
    assert snapshot.deployment_name == "infrahub"
    assert deployment.active_instance is not None
    assert snapshot.instance_id == deployment.active_instance.id
    assert snapshot.driver_name == "infrahub-driver"
    assert snapshot.driver_version == "1.2.0"
    assert snapshot.application_version == "1.6.0"
    assert snapshot.config == {"replicas": 2}
    assert snapshot.parameters == {"license": "ent"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_hash", "source_commit_sha", "expected"),
    [
        ("f" * 64, None, "f" * 64),
        (None, "abc1234def", "abc1234def"),
        (None, None, None),
    ],
)
async def test_snapshot_records_the_driver_provenance_fingerprint(
    environment: Environment,
    prefect_manager_mock,
    content_hash: str | None,
    source_commit_sha: str | None,
    expected: str | None,
) -> None:
    """FR-003 / ADR-0053: content hash for local sources, commit SHA for git."""
    adv = _driver_version(
        content_hash=content_hash, source_commit_sha=source_commit_sha
    )
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    uow = _make_uow(
        environment=environment, deployments=[deployment], driver_versions=[adv]
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.deployment_snapshots is not None
    snapshot = DeploymentSnapshot.model_validate(
        environment_backup.deployment_snapshots[0]
    )
    assert snapshot.driver_fingerprint == expected


@pytest.mark.asyncio
async def test_internal_tombstoned_and_instanceless_deployments_are_excluded(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-001: eligibility is non-tombstoned, non-internal, with an instance."""
    adv = _driver_version()
    eligible = _deployment(environment_id=environment.id, adv=adv, name="eligible")
    uow = _make_uow(
        environment=environment,
        deployments=[
            eligible,
            _deployment(
                environment_id=environment.id,
                adv=adv,
                name="ingress",
                internal=True,
            ),
            _deployment(
                environment_id=environment.id,
                adv=adv,
                name="retired",
                deleted_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
            _deployment(
                environment_id=environment.id,
                adv=adv,
                name="never-deployed",
                with_instance=False,
            ),
        ],
        driver_versions=[adv],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.deployment_snapshots is not None
    assert [
        DeploymentSnapshot.model_validate(raw).deployment_name
        for raw in environment_backup.deployment_snapshots
    ] == ["eligible"]
    assert len(uow.backups.models) == 1
    assert uow.backups.models[0].instance_id == eligible.active_instance.id  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_conflicting_constituent_is_recorded_and_peers_proceed(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-005: a busy instance becomes an attributable error, never an abort."""
    adv = _driver_version()
    busy = _deployment(environment_id=environment.id, adv=adv, name="busy-app")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy-app")
    assert busy.active_instance is not None
    in_flight = Backup(
        name="pre-existing",
        status=BackupStatus.IN_PROGRESS,
        instance_id=busy.active_instance.id,
    )
    uow = _make_uow(
        environment=environment,
        deployments=[busy, healthy],
        driver_versions=[adv],
        backups=[in_flight],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.constituent_errors is not None
    errors = [
        ConstituentError.model_validate(raw)
        for raw in environment_backup.constituent_errors
    ]
    assert [error.deployment_name for error in errors] == ["busy-app"]
    assert str(in_flight.id) in errors[0].error

    # The healthy peer still got its constituent and its dispatch.
    constituents = [
        backup
        for backup in uow.backups.models
        if backup.environment_backup_id == environment_backup.id
    ]
    assert len(constituents) == 1
    assert constituents[0].instance_id == healthy.active_instance.id  # type: ignore[union-attr]
    prefect_manager_mock.run_action.assert_called_once()

    # One completed peer alongside one recorded error derives as PARTIAL.
    constituents[0].status = BackupStatus.COMPLETED
    assert (
        derive_environment_operation_status(
            [backup.status for backup in constituents], error_count=len(errors)
        )
        == EnvironmentOperationStatus.PARTIAL
    )


@pytest.mark.asyncio
async def test_empty_environment_yields_a_config_only_completed_snapshot(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-011: no eligible deployments -> config-only snapshot, COMPLETED now."""
    uow = _make_uow(environment=environment, deployments=[], driver_versions=[])

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.deployment_snapshots is None
    assert environment_backup.constituent_errors is None
    assert uow.backups.models == []
    prefect_manager_mock.run_action.assert_not_called()
    assert (
        derive_environment_operation_status([], error_count=0)
        == EnvironmentOperationStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_explicit_name_is_preserved(
    environment: Environment, prefect_manager_mock
) -> None:
    uow = _make_uow(environment=environment, deployments=[], driver_versions=[])

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow, name="pre-upgrade"
    )

    assert environment_backup.name == "pre-upgrade"


@pytest.mark.asyncio
async def test_unknown_environment_raises_not_found(prefect_manager_mock) -> None:
    environment = Environment(name="staging", cluster_id=uuid4())
    uow = _make_uow(environment=environment, deployments=[], driver_versions=[])

    with pytest.raises(EnvironmentNotFoundError):
        await create_environment_backup(environment_id=uuid4(), uow=uow)


# ---------------------------------------------------------------------------
# create_environment_backup — D6 concurrency guards (FR-009)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
async def test_in_flight_environment_backup_blocks_a_second_operation(
    environment: Environment, prefect_manager_mock, status: BackupStatus
) -> None:
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    in_flight_parent = EnvironmentBackup(
        name="in-flight", environment_id=environment.id
    )
    assert deployment.active_instance is not None
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[
            Backup(
                name="in-flight-constituent",
                status=status,
                instance_id=deployment.active_instance.id,
                environment_backup_id=in_flight_parent.id,
            )
        ],
        environment_backups=[in_flight_parent],
    )

    with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
        await create_environment_backup(environment_id=environment.id, uow=uow)

    assert excinfo.value.error_code == "ALREADY_IN_PROGRESS"
    assert excinfo.value.error_metadata == {
        "operation_id": str(in_flight_parent.id),
        "operation_kind": "environment_backup",
    }
    # The in-flight operation is untouched: no new parent, no new constituent.
    assert len(uow.environment_backups.models) == 1
    assert len(uow.backups.models) == 1


@pytest.mark.asyncio
async def test_in_flight_environment_restore_blocks_a_new_backup(
    environment: Environment, prefect_manager_mock
) -> None:
    """The guard is bidirectional — a restore holds the environment too."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    assert deployment.active_instance is not None
    parent = EnvironmentBackup(name="source-snapshot", environment_id=environment.id)
    source_backup = Backup(
        name="source-constituent",
        status=BackupStatus.COMPLETED,
        instance_id=deployment.active_instance.id,
        environment_backup_id=parent.id,
    )
    environment_restore = EnvironmentRestore(environment_backup_id=parent.id)
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[source_backup],
        restores=[
            Restore(
                name="in-flight-restore",
                status=RestoreStatus.IN_PROGRESS,
                target_namespace=f"styrmin-{deployment.id}",
                backup_id=source_backup.id,
                environment_restore_id=environment_restore.id,
            )
        ],
        environment_backups=[parent],
        environment_restores=[environment_restore],
    )

    with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
        await create_environment_backup(environment_id=environment.id, uow=uow)

    assert excinfo.value.error_metadata == {
        "operation_id": str(environment_restore.id),
        "operation_kind": "environment_restore",
    }


@pytest.mark.asyncio
async def test_terminal_constituents_do_not_block_a_new_backup(
    environment: Environment, prefect_manager_mock
) -> None:
    """A finished snapshot must release the environment (no stored status)."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    assert deployment.active_instance is not None
    finished = EnvironmentBackup(name="finished", environment_id=environment.id)
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[
            Backup(
                name="finished-constituent",
                status=BackupStatus.COMPLETED,
                instance_id=deployment.active_instance.id,
                environment_backup_id=finished.id,
            )
        ],
        environment_backups=[finished],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.id != finished.id
    assert len(uow.environment_backups.models) == 2


# ---------------------------------------------------------------------------
# create_environment_backup — ADR-0012 ordering and isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_is_committed_before_any_dispatch(
    environment: Environment, prefect_manager_mock
) -> None:
    """ADR-0012: the snapshot must survive a crash mid-fan-out."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    uow = _make_uow(
        environment=environment, deployments=[deployment], driver_versions=[adv]
    )
    commits_at_dispatch: list[int] = []
    prefect_manager_mock.run_action.side_effect = lambda **_: (
        commits_at_dispatch.append(uow.commit_count)
    )

    await create_environment_backup(environment_id=environment.id, uow=uow)

    # At least the parent commit and the constituent's own commit precede the
    # first dispatch.
    assert commits_at_dispatch and commits_at_dispatch[0] >= 2


@pytest.mark.asyncio
async def test_dispatch_failure_leaves_the_constituent_row_and_records_no_error(
    environment: Environment, prefect_manager_mock
) -> None:
    """A Prefect submission failure is a pending constituent, not a lost one."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    uow = _make_uow(
        environment=environment, deployments=[deployment], driver_versions=[adv]
    )
    prefect_manager_mock.run_action.side_effect = RuntimeError("prefect is down")

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.constituent_errors is None
    assert len(uow.backups.models) == 1
    assert uow.backups.models[0].status == BackupStatus.PENDING
