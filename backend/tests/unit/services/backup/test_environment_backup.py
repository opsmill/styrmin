"""Unit tests for the environment-level backup/restore service primitives.

The derived-status rule is the load-bearing piece of research.md D2: because
``EnvironmentBackup``/``EnvironmentRestore`` store no status column, this
function is the single definition of what a parent's status means, and it must
never contradict the constituents it is derived from (spec FR-004 / SC-003).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
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
    DeployedService,
    Environment,
    EnvironmentBackup,
    EnvironmentRestore,
    InstanceStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.api.definitions.backup.environment_restore import (
    EnvironmentRestoreStatus,
)
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentState
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
    delete_environment_backup,
    derive_environment_operation_status,
    restore_environment_backup,
)
from styrmin_backend.services.backup.service import create_restore
from styrmin_backend.services.environments import delete_environment
from styrmin_backend.services.exceptions import (
    EnvironmentBackupNotFoundError,
    EnvironmentBackupNotRestorableError,
    EnvironmentNotFoundError,
    EnvironmentOperationInProgressError,
    EnvironmentRestoreNotFoundError,
    RestoreAlreadyInProgressError,
    UnresolvableAffinityReferenceError,
)
from styrmin_backend.workflows.models import PrefectAction
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
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
    status: DeploymentState = DeploymentState.RUNNING,
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
        status=status,
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
    deployed_services: list[DeployedService] | None = None,
    uow_type: type[FakeUnitOfWork] = FakeUnitOfWork,
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
    return uow_type(
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
        deployed_services=FakeDeployedServiceRepository(deployed_services or []),
    )


def _deployed_service(
    *,
    deployment: DeploymentEntity,
    environment_id: UUID,
    driver_service_name: str,
    resolved_name: str | None = None,
) -> DeployedService:
    """One resolved service row, overridden when ``resolved_name`` differs."""
    return DeployedService(
        driver_service_name=driver_service_name,
        resolved_name=resolved_name or driver_service_name,
        kind="http",
        scope="external",
        port=8080,
        component="server",
        deployment_id=deployment.id,
        environment_id=environment_id,
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
async def test_snapshot_captures_only_genuine_service_name_overrides(
    environment: Environment, prefect_manager_mock
) -> None:
    """010 FR-005 ∧ FR-007: a counterpart must reproduce overridden service names.

    Only the services whose resolved name differs from the driver's own name are
    recorded, because that is what ``create_services_for_deployment`` takes as
    its override argument — capturing identity mappings would push
    driver-default names through validation they never went through.
    """
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        deployed_services=[
            _deployed_service(
                deployment=deployment,
                environment_id=environment.id,
                driver_service_name="api",
                resolved_name="infrahub-api",
            ),
            _deployed_service(
                deployment=deployment,
                environment_id=environment.id,
                driver_service_name="ui",
            ),
        ],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.deployment_snapshots is not None
    snapshot = DeploymentSnapshot.model_validate(
        environment_backup.deployment_snapshots[0]
    )
    assert snapshot.service_name_overrides == {"api": "infrahub-api"}


@pytest.mark.asyncio
async def test_snapshot_records_no_overrides_when_every_name_is_the_driver_default(
    environment: Environment, prefect_manager_mock
) -> None:
    """``None`` means "use the driver defaults" — the same as an older snapshot."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        deployed_services=[
            _deployed_service(
                deployment=deployment,
                environment_id=environment.id,
                driver_service_name="api",
            )
        ],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert environment_backup.deployment_snapshots is not None
    snapshot = DeploymentSnapshot.model_validate(
        environment_backup.deployment_snapshots[0]
    )
    assert snapshot.service_name_overrides is None


def test_a_snapshot_taken_before_service_overrides_existed_still_reads() -> None:
    """The field is additive: pre-existing JSON has no key and reads as ``None``."""
    legacy = {
        "deployment_id": str(uuid4()),
        "deployment_name": "infrahub",
        "instance_id": str(uuid4()),
        "driver_name": "infrahub-driver",
        "driver_version": "1.2.0",
        "driver_fingerprint": None,
        "application_version": "1.6.0",
        "config": None,
        "parameters": None,
    }

    assert DeploymentSnapshot.model_validate(legacy).service_name_overrides is None


# ---------------------------------------------------------------------------
# create_environment_backup — the deployment selection filter (010 research D6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_explicit_selection_narrows_the_capture(
    environment: Environment, prefect_manager_mock
) -> None:
    """010 FR-003: the capture covers the selection, not the whole environment.

    Filtering at capture time is the point of the selection — an excluded
    heavyweight deployment must not be backed up at all.
    """
    adv = _driver_version()
    included = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    excluded = _deployment(environment_id=environment.id, adv=adv, name="netbox")
    uow = _make_uow(
        environment=environment,
        deployments=[included, excluded],
        driver_versions=[adv],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow, deployment_ids=[included.id]
    )

    assert environment_backup.deployment_snapshots is not None
    assert [
        DeploymentSnapshot.model_validate(raw).deployment_name
        for raw in environment_backup.deployment_snapshots
    ] == ["infrahub"]
    assert len(uow.backups.models) == 1
    assert uow.backups.models[0].instance_id == included.active_instance.id  # type: ignore[union-attr]
    prefect_manager_mock.run_action.assert_called_once()


@pytest.mark.asyncio
async def test_an_omitted_selection_captures_every_eligible_deployment(
    environment: Environment, prefect_manager_mock
) -> None:
    """``None`` means "all eligible" — the standalone mutation's behaviour."""
    adv = _driver_version()
    deployments = [
        _deployment(environment_id=environment.id, adv=adv, name="infrahub"),
        _deployment(environment_id=environment.id, adv=adv, name="netbox"),
    ]
    uow = _make_uow(
        environment=environment, deployments=deployments, driver_versions=[adv]
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow, deployment_ids=None
    )

    assert environment_backup.deployment_snapshots is not None
    assert len(environment_backup.deployment_snapshots) == 2
    assert len(uow.backups.models) == 2


@pytest.mark.asyncio
async def test_an_empty_selection_captures_nothing(
    environment: Environment, prefect_manager_mock
) -> None:
    """``[]`` is an explicit "select nothing", distinct from an omitted filter.

    It yields the same config-only snapshot as an environment with no eligible
    deployments, which derives ``COMPLETED`` immediately.
    """
    adv = _driver_version()
    uow = _make_uow(
        environment=environment,
        deployments=[
            _deployment(environment_id=environment.id, adv=adv, name="netbox")
        ],
        driver_versions=[adv],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow, deployment_ids=[]
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
async def test_the_selection_filter_never_raises_on_unusable_ids(
    environment: Environment, prefect_manager_mock
) -> None:
    """Unknown and ineligible ids are simply not captured.

    Deciding whether an unusable id is a client mistake (``NOT_FOUND``) or an
    attributable skip (FR-004) belongs to the caller — the filter itself stays
    silent so ``create_environment_backup`` keeps one behaviour.
    """
    adv = _driver_version()
    eligible = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    never_deployed = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="never-deployed",
        with_instance=False,
    )
    uow = _make_uow(
        environment=environment,
        deployments=[eligible, never_deployed],
        driver_versions=[adv],
    )

    environment_backup = await create_environment_backup(
        environment_id=environment.id,
        uow=uow,
        deployment_ids=[eligible.id, never_deployed.id, uuid4()],
    )

    assert environment_backup.deployment_snapshots is not None
    assert [
        DeploymentSnapshot.model_validate(raw).deployment_name
        for raw in environment_backup.deployment_snapshots
    ] == ["infrahub"]
    assert environment_backup.constituent_errors is None


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
async def test_the_whole_capture_is_committed_once_before_any_dispatch(
    environment: Environment, prefect_manager_mock
) -> None:
    """ADR-0012 made atomic: parent + constituents + errors, one commit, then dispatch.

    The parent used to be committed on its own and the constituent rows and
    recorded errors afterwards, which left two observable windows: a committed
    parent with no children at all (which derives ``COMPLETED`` and does not
    trip the D6 EXISTS guard, FR-009) and errors that were still only in memory
    (FR-007). Asserting the *count* of commits is what pins the fix: a single
    commit cannot expose a partial capture.
    """
    adv = _driver_version()
    busy = _deployment(environment_id=environment.id, adv=adv, name="busy-app")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy-app")
    other = _deployment(environment_id=environment.id, adv=adv, name="other-app")
    assert busy.active_instance is not None
    uow = _make_uow(
        environment=environment,
        deployments=[busy, healthy, other],
        driver_versions=[adv],
        backups=[
            Backup(
                name="pre-existing",
                status=BackupStatus.IN_PROGRESS,
                instance_id=busy.active_instance.id,
            )
        ],
    )
    observed: list[tuple[int, int, int]] = []

    def _observe(**_):
        parents = uow.environment_backups.models
        constituents = [
            backup
            for backup in uow.backups.models
            if backup.environment_backup_id in {parent.id for parent in parents}
        ]
        errors = [
            error for parent in parents for error in (parent.constituent_errors or [])
        ]
        observed.append((uow.commit_count, len(constituents), len(errors)))

    prefect_manager_mock.run_action.side_effect = _observe

    await create_environment_backup(environment_id=environment.id, uow=uow)

    # Exactly one commit precedes the first dispatch, and by then *both*
    # constituent rows and the recorded error for the busy peer are durable.
    assert observed[0] == (1, 2, 1)
    assert uow.commit_count == 1


@pytest.mark.asyncio
async def test_constituent_errors_survive_a_cancellation_mid_dispatch(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-007: a client disconnect must not publish a snapshot with zero errors.

    ``CancelledError`` is a ``BaseException``, so it escapes the
    per-constituent ``except Exception``. When the errors were persisted only
    *after* the dispatch loop, a cancellation left a committed snapshot with
    fewer children than snapshots and no recorded errors at all — which
    derives ``COMPLETED`` and makes ``--wait`` exit 0 on a partial backup.
    """
    adv = _driver_version()
    busy = _deployment(environment_id=environment.id, adv=adv, name="busy-app")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy-app")
    assert busy.active_instance is not None
    uow = _make_uow(
        environment=environment,
        deployments=[busy, healthy],
        driver_versions=[adv],
        backups=[
            Backup(
                name="pre-existing",
                status=BackupStatus.IN_PROGRESS,
                instance_id=busy.active_instance.id,
            )
        ],
    )
    prefect_manager_mock.run_action.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await create_environment_backup(environment_id=environment.id, uow=uow)

    # The capture that was committed before the dispatch phase is complete.
    (persisted,) = uow.environment_backups.models
    errors = [
        ConstituentError.model_validate(raw)
        for raw in persisted.constituent_errors or []
    ]
    assert [error.deployment_name for error in errors] == ["busy-app"]
    # ... so the derived status is honest about the failed constituent instead
    # of reading COMPLETED.
    constituents = [
        backup
        for backup in uow.backups.models
        if backup.environment_backup_id == persisted.id
    ]
    constituents[0].status = BackupStatus.COMPLETED
    assert (
        derive_environment_operation_status(
            [backup.status for backup in constituents], error_count=len(errors)
        )
        == EnvironmentOperationStatus.PARTIAL
    )


@pytest.mark.asyncio
async def test_a_second_backup_is_rejected_from_the_moment_the_capture_commits(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-009: no window where a committed capture fails to hold the environment.

    The D6 guard is an EXISTS over non-terminal *children*, so it only holds
    the environment once the constituent rows exist. Committing the parent
    before them left a window in which a second ``createEnvironmentBackup``
    passed the guard; committing everything at once removes it — at the first
    externally observable moment after the commit (the dispatch) the guard
    already rejects.
    """
    adv = _driver_version()
    deployments = [
        _deployment(environment_id=environment.id, adv=adv, name="infrahub"),
        _deployment(environment_id=environment.id, adv=adv, name="netbox"),
    ]
    uow = _make_uow(
        environment=environment, deployments=deployments, driver_versions=[adv]
    )
    rejections: list[EnvironmentOperationInProgressError] = []

    async def _attempt_a_second_backup(**_):
        with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
            await create_environment_backup(environment_id=environment.id, uow=uow)
        rejections.append(excinfo.value)

    prefect_manager_mock.run_action.side_effect = _attempt_a_second_backup

    environment_backup = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )

    assert len(rejections) == 2
    assert {rejection.error_metadata["operation_id"] for rejection in rejections} == {
        str(environment_backup.id)
    }
    # The rejected attempts created nothing.
    assert len(uow.environment_backups.models) == 1
    assert len(uow.backups.models) == 2


@pytest.mark.asyncio
async def test_a_snapshot_deleted_mid_fan_out_raises_not_found(
    environment: Environment, prefect_manager_mock
) -> None:
    """FR-010's escape hatch is reachable while the fan-out is still running.

    ``delete_environment_backup`` deliberately has no status guard, so an
    operator clearing an in-flight snapshot can make the parent row vanish
    between the capture commit and the reload. That must surface as a typed
    NOT_FOUND, not as an ``AssertionError`` laundered into ``INTERNAL_ERROR``
    (and not as an ``AttributeError`` under ``python -O``).
    """
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    uow = _make_uow(
        environment=environment, deployments=[deployment], driver_versions=[adv]
    )
    prefect_manager_mock.run_action.side_effect = lambda **_: (
        uow.environment_backups.models.clear()
    )

    with pytest.raises(EnvironmentBackupNotFoundError):
        await create_environment_backup(environment_id=environment.id, uow=uow)


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


# ---------------------------------------------------------------------------
# restore_environment_backup — helpers
# ---------------------------------------------------------------------------
#
# The restore fan-out calls ``redeploy_for_environment_update`` (the full
# reconciliation chain: ``generate_instance_from_deployment`` + ``apply_state``)
# for the deployments that are NOT receiving a constituent restore. Driving
# that chain through fakes is brittle and duplicates coverage that already
# lives in ``test_environment_services.py``, so these tests patch it *at the
# call site* and assert on the exclusion set instead. Everything else — the
# classification, the config revert, the constituent restores — runs for real
# against the fakes.


def _snapshot_of(deployment: DeploymentEntity) -> dict:
    """The JSON snapshot entry the backup fan-out would have captured."""
    assert deployment.active_instance is not None
    return DeploymentSnapshot(
        deployment_id=deployment.id,
        deployment_name=deployment.name,
        instance_id=deployment.active_instance.id,
        driver_name="infrahub-driver",
        driver_version="1.2.0",
        application_version=deployment.application_version,
        config=deployment.config,
        parameters=deployment.parameters or None,
    ).model_dump(mode="json")


def _constituent(
    parent: EnvironmentBackup,
    deployment: DeploymentEntity,
    *,
    status: BackupStatus = BackupStatus.COMPLETED,
    expires_at: datetime | None = None,
) -> Backup:
    """A constituent backup linked to ``parent`` both ways.

    The FK is set explicitly on top of the relationship append: nothing
    flushes in these tests, so SQLAlchemy never syncs it, and the D6 guard
    fake reads the FK.
    """
    assert deployment.active_instance is not None
    backup = Backup(
        name=f"constituent-{deployment.name}-{uuid4().hex[:6]}",
        status=status,
        instance_id=deployment.active_instance.id,
        metadata_={"expires_at": expires_at.isoformat()} if expires_at else None,
    )
    parent.backups.append(backup)
    backup.environment_backup_id = parent.id
    return backup


def _environment_backup(
    *,
    environment: Environment,
    snapshots: list[dict],
    environment_config: dict | None,
    constituent_errors: list[dict] | None = None,
) -> EnvironmentBackup:
    return EnvironmentBackup(
        name=f"snapshot-{uuid4().hex[:8]}",
        environment_id=environment.id,
        environment_config=environment_config,
        deployment_snapshots=snapshots or None,
        constituent_errors=constituent_errors,
    )


def _skips(environment_restore: EnvironmentRestore) -> dict[str, str]:
    """Skip reasons keyed by deployment name."""
    return {
        SkippedConstituent.model_validate(
            raw
        ).deployment_name: SkippedConstituent.model_validate(raw).reason
        for raw in environment_restore.skipped_constituents or []
    }


@pytest.fixture
def no_config_fanout(mocker):
    """Patch the exclusion-aware config fan-out at its call site."""
    return mocker.patch(
        "styrmin_backend.services.backup.environment.redeploy_for_environment_update",
        autospec=True,
    )


# ---------------------------------------------------------------------------
# restore_environment_backup — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_reverts_config_and_restores_every_usable_constituent(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """FR-006/SC-002/SC-005: one action reverts config and restores in place."""
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    netbox = _deployment(environment_id=environment.id, adv=adv, name="netbox")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub), _snapshot_of(netbox)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    constituents = [_constituent(parent, infrahub), _constituent(parent, netbox)]
    # The environment drifted away from the captured config since the backup.
    environment.config = {"dns_zone": "drifted.example.com"}
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub, netbox],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    # SC-005: the environment config equals the captured value.
    assert environment.config == {"dns_zone": "captured.example.com"}
    # SC-002: every usable constituent got a restore, linked to the parent.
    assert len(uow.restores.models) == 2
    assert {restore.environment_restore_id for restore in uow.restores.models} == {
        environment_restore.id
    }
    assert {restore.target_namespace for restore in uow.restores.models} == {
        f"styrmin-{infrahub.id}",
        f"styrmin-{netbox.id}",
    }
    assert environment_restore.skipped_constituents is None

    dispatched = [
        call.kwargs for call in prefect_manager_mock.run_action.call_args_list
    ]
    assert {call["action"] for call in dispatched} == {PrefectAction.EXECUTE_RESTORE}
    assert {call["parameters"]["deployment_id"] for call in dispatched} == {
        str(infrahub.id),
        str(netbox.id),
    }
    # Every restored deployment is excluded from the config fan-out (D4).
    no_config_fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_restore_reverts_a_captured_none_config(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """Critique E3: a captured ``None`` config must actually revert to ``None``.

    Delegating to ``update_environment`` would treat ``config=None`` as an
    idempotent no-op and silently leave the drifted config in place.
    """
    parent = _environment_backup(
        environment=environment, snapshots=[], environment_config=None
    )
    environment.config = {"dns_zone": "drifted.example.com"}
    uow = _make_uow(
        environment=environment,
        deployments=[],
        driver_versions=[],
        environment_backups=[parent],
    )

    await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert environment.config is None


@pytest.mark.asyncio
async def test_restore_fans_config_out_only_to_deployments_not_being_restored(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """D4: a deployment gets either a Velero restore or a redeploy, never both."""
    adv = _driver_version()
    restored = _deployment(environment_id=environment.id, adv=adv, name="restored-app")
    # Created after the backup: no snapshot entry, so it only sees the config.
    newcomer = _deployment(environment_id=environment.id, adv=adv, name="newcomer")
    internal = _deployment(
        environment_id=environment.id, adv=adv, name="ingress", internal=True
    )
    instanceless = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="never-deployed",
        with_instance=False,
    )
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(restored)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    constituent = _constituent(parent, restored)
    uow = _make_uow(
        environment=environment,
        deployments=[restored, newcomer, internal, instanceless],
        driver_versions=[adv],
        backups=[constituent],
        environment_backups=[parent],
    )

    await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    fanned_out = [call.args[0].name for call in no_config_fanout.await_args_list]
    assert fanned_out == ["newcomer"]


@pytest.mark.asyncio
async def test_restore_survives_a_config_fanout_failure(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """ADR-0012 isolation: one laggard's redeploy failure is not an abort."""
    adv = _driver_version()
    restored = _deployment(environment_id=environment.id, adv=adv, name="restored-app")
    newcomer = _deployment(environment_id=environment.id, adv=adv, name="newcomer")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(restored)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    uow = _make_uow(
        environment=environment,
        deployments=[restored, newcomer],
        driver_versions=[adv],
        backups=[_constituent(parent, restored)],
        environment_backups=[parent],
    )
    no_config_fanout.side_effect = RuntimeError("driver render failed")

    await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    # The config still reverted and the constituent restore still ran.
    assert environment.config == {"dns_zone": "captured.example.com"}
    assert len(uow.restores.models) == 1


class _SavepointSession:
    """Keeps writes pending until commit; a savepoint undoes only the writes made in it."""

    def __init__(self) -> None:
        self.pending: list[str] = []
        self.committed: list[str] = []
        self.savepoints: list[int] = []

    async def refresh(self, obj: object) -> None:
        pass

    @contextlib.asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        self.savepoints.append(len(self.pending))
        try:
            yield
        except BaseException:
            del self.pending[self.savepoints[-1] :]
            raise
        finally:
            self.savepoints.pop()


class _SavepointUnitOfWork(FakeUnitOfWork):
    """Rolls back as ``SqlModelUnitOfWork`` does: a failing block undoes the open
    savepoint, or the whole transaction when no savepoint is open."""

    def __init__(self, **repositories: object) -> None:
        super().__init__(**repositories)  # type: ignore[arg-type]
        self.transaction = _SavepointSession()
        self.session = self.transaction  # type: ignore[assignment]

    async def __aexit__(
        self, exc_type: type[BaseException] | None, *args: object
    ) -> None:
        if exc_type is not None:
            savepoints = self.transaction.savepoints
            del self.transaction.pending[savepoints[-1] if savepoints else 0 :]

    async def commit(self) -> None:
        await super().commit()
        self.transaction.committed.extend(self.transaction.pending)
        self.transaction.pending.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("b_redeploys", ["first", "last"])
async def test_restore_keeps_a_redeploy_when_another_names_a_tombstoned_deployment(
    environment: Environment,
    prefect_manager_mock,
    no_config_fanout,
    mocker,
    b_redeploys: str,
) -> None:
    """027 US7 (FR-006): B's redeploy is refused because the captured term names
    tombstoned A. C's redeploy is committed, before or after B's, and the restore
    returns normally. B's failure is logged with the restore's id and the term's path,
    and counted apart from the dispatch of constituent restores."""
    adv = _driver_version()
    a = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="a",
        deleted_at=datetime.now(timezone.utc),
        status=DeploymentState.DELETED,
    )
    b = _deployment(environment_id=environment.id, adv=adv, name="b")
    c = _deployment(environment_id=environment.id, adv=adv, name="c")
    term_path = "environment.config.scheduling.pod_anti_affinity.preferred[0].term"
    captured = {
        "scheduling": {
            "pod_anti_affinity": {
                "preferred": [
                    {
                        "weight": 100,
                        "term": {
                            "topology_key": "kubernetes.io/hostname",
                            "deployment_ref": {"deployment_id": str(a.id)},
                        },
                    }
                ]
            }
        }
    }
    parent = _environment_backup(
        environment=environment, snapshots=[], environment_config=captured
    )
    uow = _make_uow(
        environment=environment,
        deployments=[a, b, c] if b_redeploys == "first" else [a, c, b],
        driver_versions=[adv],
        environment_backups=[parent],
        uow_type=_SavepointUnitOfWork,
    )
    assert isinstance(uow, _SavepointUnitOfWork)

    async def _redeploy(
        deployment: DeploymentEntity, uow: _SavepointUnitOfWork
    ) -> None:
        # The real redeploy expands the terms inside its own ``async with uow`` block.
        async with uow:
            uow.transaction.pending.append(deployment.name)
            if deployment.id == b.id:
                raise UnresolvableAffinityReferenceError(
                    deployment_id=str(a.id),
                    deployment_name="a",
                    path=term_path,
                    deleted=True,
                )

    no_config_fanout.side_effect = _redeploy
    log = mocker.patch("styrmin_backend.services.backup.environment.logger")

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert environment_restore.environment_backup_id == parent.id
    assert environment.config == captured
    redeployed = [call.args[0].name for call in no_config_fanout.await_args_list]
    assert redeployed == (["b", "c"] if b_redeploys == "first" else ["c", "b"])
    assert uow.transaction.committed == ["c"]
    assert uow.transaction.pending == []

    def _lines(method) -> list[str]:
        return [call.args[0].format(*call.args[1:]) for call in method.call_args_list]

    def _fields(line: str) -> dict[str, str]:
        return dict(part.split("=", 1) for part in line.split()[1:])

    [error_line] = _lines(log.exception)
    assert error_line.startswith("env_restore_fanout_dispatch_error ")
    assert _fields(error_line) == {
        "environment_id": str(environment.id),
        "environment_restore_id": str(environment_restore.id),
        "deployment_id": str(b.id),
        "error_code": "VALIDATION_ERROR",
        "path": term_path,
    }
    [summary] = [
        line
        for line in _lines(log.info)
        if line.startswith("env_restore_fanout_dispatched ")
    ]
    counts = _fields(summary)
    assert (
        counts["config_redeployed"],
        counts["config_redeploy_failed"],
        counts["dispatch_failed"],
    ) == ("1", "1", "1")
    metrics = [line for line in _lines(log.info) if line.startswith("metric=")]
    assert metrics == [
        "metric=env_restore_fanout_deployments_total "
        f"environment_id={environment.id} outcome={outcome} count=1"
        for outcome in ("config_redeployed", "config_redeploy_failed")
    ]


# ---------------------------------------------------------------------------
# restore_environment_backup — classification matrix (FR-007 / SC-004)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_constituent_that_failed_at_backup_creation_is_skipped(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    adv = _driver_version()
    busy_at_backup = _deployment(
        environment_id=environment.id, adv=adv, name="busy-at-backup"
    )
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(busy_at_backup), _snapshot_of(healthy)],
        environment_config=None,
        constituent_errors=[
            ConstituentError(
                deployment_id=busy_at_backup.id,
                deployment_name="busy-at-backup",
                error="backup already in progress (existing: 1234)",
            ).model_dump(mode="json")
        ],
    )
    uow = _make_uow(
        environment=environment,
        deployments=[busy_at_backup, healthy],
        driver_versions=[adv],
        backups=[_constituent(parent, healthy)],
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {
        "busy-at-backup": SkipReason.BACKUP_FAILED_AT_CREATION.value
    }
    assert len(uow.restores.models) == 1


@pytest.mark.asyncio
async def test_constituent_whose_backup_never_completed_is_skipped(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """A FAILED constituent has nothing to restore from.

    Only FAILED is exercised here: a ``PENDING``/``IN_PROGRESS`` constituent
    makes the *parent* non-terminal, which the restorability guard rejects
    before classification ever runs (see
    ``test_a_non_restorable_snapshot_is_rejected``).
    """
    adv = _driver_version()
    unfinished = _deployment(environment_id=environment.id, adv=adv, name="unfinished")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(unfinished), _snapshot_of(healthy)],
        environment_config=None,
    )
    constituents = [
        _constituent(parent, unfinished, status=BackupStatus.FAILED),
        _constituent(parent, healthy),
    ]
    uow = _make_uow(
        environment=environment,
        deployments=[unfinished, healthy],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {
        "unfinished": SkipReason.BACKUP_NOT_COMPLETED.value
    }
    assert len(uow.restores.models) == 1


@pytest.mark.asyncio
async def test_constituent_deleted_after_the_backup_is_skipped(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """US3: the snapshot keeps the entry; the missing row is a visible gap."""
    adv = _driver_version()
    gap = _deployment(environment_id=environment.id, adv=adv, name="deleted-backup")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(gap), _snapshot_of(healthy)],
        environment_config=None,
    )
    # Only ``healthy`` keeps a constituent row.
    uow = _make_uow(
        environment=environment,
        deployments=[gap, healthy],
        driver_versions=[adv],
        backups=[_constituent(parent, healthy)],
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {
        "deleted-backup": SkipReason.BACKUP_DELETED.value
    }


@pytest.mark.asyncio
async def test_a_snapshot_whose_constituents_were_all_deleted_stays_completed(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """FR-014: the parent outlives its constituents and stays restorable.

    Deriving the status from ``len(deployment_snapshots)`` instead of from the
    surviving children would flip this snapshot to a permanently non-terminal
    status and make it unrestorable, so the derivation deliberately counts only
    children plus recorded errors.
    """
    adv = _driver_version()
    a = _deployment(environment_id=environment.id, adv=adv, name="app-a")
    b = _deployment(environment_id=environment.id, adv=adv, name="app-b")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(a), _snapshot_of(b)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    # Every constituent backup was deleted individually after the snapshot.
    assert parent.backups == []
    environment.config = {"dns_zone": "drifted.example.com"}
    uow = _make_uow(
        environment=environment,
        deployments=[a, b],
        driver_versions=[adv],
        environment_backups=[parent],
    )

    assert (
        derive_environment_operation_status([], error_count=0)
        == EnvironmentOperationStatus.COMPLETED
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    # Restorable (the guard did not reject it), the config reverted, and both
    # gaps are attributed rather than silently dropped.
    assert environment.config == {"dns_zone": "captured.example.com"}
    assert _skips(environment_restore) == {
        "app-a": SkipReason.BACKUP_DELETED.value,
        "app-b": SkipReason.BACKUP_DELETED.value,
    }
    assert uow.restores.models == []


@pytest.mark.asyncio
async def test_expired_but_completed_constituent_is_skipped(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """Critique E4: Velero GC never touches the row, so it still reads COMPLETED.

    Classification must therefore compute expiry from the recorded TTL
    metadata rather than trusting the status — otherwise the restore
    dispatches a Velero restore against data that no longer exists.
    """
    adv = _driver_version()
    expired = _deployment(environment_id=environment.id, adv=adv, name="expired-app")
    fresh = _deployment(environment_id=environment.id, adv=adv, name="fresh-app")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(expired), _snapshot_of(fresh)],
        environment_config=None,
    )
    now = datetime.now(timezone.utc)
    constituents = [
        _constituent(parent, expired, expires_at=now - timedelta(hours=1)),
        _constituent(parent, fresh, expires_at=now + timedelta(days=30)),
    ]
    assert all(backup.status == BackupStatus.COMPLETED for backup in constituents), (
        "the whole point: the expired row still reads COMPLETED"
    )
    uow = _make_uow(
        environment=environment,
        deployments=[expired, fresh],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {
        "expired-app": SkipReason.BACKUP_EXPIRED.value
    }
    # The un-expired peer was restored.
    assert [restore.target_namespace for restore in uow.restores.models] == [
        f"styrmin-{fresh.id}"
    ]


@pytest.mark.asyncio
async def test_constituent_without_expiry_metadata_is_not_treated_as_expired(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """Unknown expiry must degrade to "restore it", not to a silent skip."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="no-ttl")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment)],
        environment_config=None,
    )
    constituent = _constituent(parent, deployment)
    constituent.metadata_ = {"timeout": 3600}
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[constituent],
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert environment_restore.skipped_constituents is None
    assert len(uow.restores.models) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tombstoned", [True, False])
async def test_constituent_whose_deployment_is_gone_is_skipped(
    environment: Environment,
    prefect_manager_mock,
    no_config_fanout,
    tombstoned: bool,
) -> None:
    """FR-008: a vanished deployment is reported, never recreated."""
    adv = _driver_version()
    departed = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="departed",
        deleted_at=datetime(2026, 8, 1, tzinfo=timezone.utc) if tombstoned else None,
    )
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(departed), _snapshot_of(healthy)],
        environment_config=None,
    )
    constituents = [_constituent(parent, departed), _constituent(parent, healthy)]
    # ``tombstoned=False`` models the row being deleted outright.
    deployments = [departed, healthy] if tombstoned else [healthy]
    uow = _make_uow(
        environment=environment,
        deployments=deployments,
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )
    deployment_count_before = len(uow.deployments._deployments)

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {"departed": SkipReason.DEPLOYMENT_GONE.value}
    # FR-008: the restore neither created nor deleted a deployment.
    assert len(uow.deployments._deployments) == deployment_count_before


@pytest.mark.asyncio
async def test_constituent_whose_deployment_is_mid_restore_is_skipped(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """Critique P2: a busy deployment is a skip, never an abort or a wait."""
    adv = _driver_version()
    busy = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="busy-app",
        status=DeploymentState.RESTORING,
    )
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(busy), _snapshot_of(healthy)],
        environment_config=None,
    )
    constituents = [_constituent(parent, busy), _constituent(parent, healthy)]
    uow = _make_uow(
        environment=environment,
        deployments=[busy, healthy],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {"busy-app": SkipReason.DEPLOYMENT_BUSY.value}
    assert len(uow.restores.models) == 1


@pytest.mark.asyncio
async def test_a_deployment_that_goes_busy_mid_dispatch_downgrades_to_a_skip(
    environment: Environment, prefect_manager_mock, no_config_fanout, mocker
) -> None:
    """The race window between classification and dispatch is a skip too."""
    adv = _driver_version()
    racer = _deployment(environment_id=environment.id, adv=adv, name="racer")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(racer), _snapshot_of(healthy)],
        environment_config=None,
    )
    racer_backup = _constituent(parent, racer)
    uow = _make_uow(
        environment=environment,
        deployments=[racer, healthy],
        driver_versions=[adv],
        backups=[racer_backup, _constituent(parent, healthy)],
        environment_backups=[parent],
    )

    async def _create_restore(*args, **kwargs):
        if kwargs["backup_id"] == racer_backup.id:
            raise RestoreAlreadyInProgressError(existing_restore_id=str(uuid4()))
        return await create_restore(*args, **kwargs)

    mocker.patch(
        "styrmin_backend.services.backup.environment.create_restore",
        side_effect=_create_restore,
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {"racer": SkipReason.DEPLOYMENT_BUSY.value}
    assert len(uow.restores.models) == 1


@pytest.mark.asyncio
async def test_every_non_restored_constituent_is_attributed(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """FR-007/SC-004: zero silent skips across the whole matrix at once."""
    adv = _driver_version()
    failed_at_creation = _deployment(
        environment_id=environment.id, adv=adv, name="failed-at-creation"
    )
    not_completed = _deployment(
        environment_id=environment.id, adv=adv, name="not-completed"
    )
    deleted_backup = _deployment(
        environment_id=environment.id, adv=adv, name="deleted-backup"
    )
    expired = _deployment(environment_id=environment.id, adv=adv, name="expired")
    gone = _deployment(environment_id=environment.id, adv=adv, name="gone")
    busy = _deployment(
        environment_id=environment.id,
        adv=adv,
        name="busy",
        status=DeploymentState.RESTORING,
    )
    usable = _deployment(environment_id=environment.id, adv=adv, name="usable")
    every = [
        failed_at_creation,
        not_completed,
        deleted_backup,
        expired,
        gone,
        busy,
        usable,
    ]
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment) for deployment in every],
        environment_config={"dns_zone": "captured.example.com"},
        constituent_errors=[
            ConstituentError(
                deployment_id=failed_at_creation.id,
                deployment_name="failed-at-creation",
                error="backup already in progress",
            ).model_dump(mode="json")
        ],
    )
    now = datetime.now(timezone.utc)
    constituents = [
        _constituent(parent, not_completed, status=BackupStatus.FAILED),
        _constituent(parent, expired, expires_at=now - timedelta(minutes=1)),
        _constituent(parent, gone),
        _constituent(parent, busy),
        _constituent(parent, usable),
    ]
    uow = _make_uow(
        environment=environment,
        deployments=[d for d in every if d is not gone],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {
        "failed-at-creation": SkipReason.BACKUP_FAILED_AT_CREATION.value,
        "not-completed": SkipReason.BACKUP_NOT_COMPLETED.value,
        "deleted-backup": SkipReason.BACKUP_DELETED.value,
        "expired": SkipReason.BACKUP_EXPIRED.value,
        "gone": SkipReason.DEPLOYMENT_GONE.value,
        "busy": SkipReason.DEPLOYMENT_BUSY.value,
    }
    # Every captured constituent is accounted for exactly once: restored or
    # skipped, never dropped.
    assert len(uow.restores.models) == 1
    assert len(environment_restore.skipped_constituents or []) + len(
        uow.restores.models
    ) == len(parent.deployment_snapshots or [])
    # The single dispatched restore is still PENDING, so the parent reads as
    # in progress despite the six terminal skips.
    assert (
        derive_environment_operation_status(
            [restore.status for restore in uow.restores.models],
            error_count=len(environment_restore.skipped_constituents or []),
        )
        == EnvironmentOperationStatus.IN_PROGRESS
    )


@pytest.mark.asyncio
async def test_a_snapshot_with_nothing_usable_still_reverts_the_config(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """Acceptance scenario US2-5: all constituents gone, config still reverts."""
    adv = _driver_version()
    a = _deployment(environment_id=environment.id, adv=adv, name="app-a")
    b = _deployment(environment_id=environment.id, adv=adv, name="app-b")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(a), _snapshot_of(b)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    now = datetime.now(timezone.utc)
    constituents = [
        _constituent(parent, a, expires_at=now - timedelta(days=1)),
        _constituent(parent, b, expires_at=now - timedelta(days=1)),
    ]
    environment.config = {"dns_zone": "drifted.example.com"}
    uow = _make_uow(
        environment=environment,
        deployments=[a, b],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert environment.config == {"dns_zone": "captured.example.com"}
    assert set(_skips(environment_restore)) == {"app-a", "app-b"}
    assert uow.restores.models == []
    # Nothing restored and everything skipped derives as FAILED.
    assert (
        derive_environment_operation_status(
            [], error_count=len(environment_restore.skipped_constituents or [])
        )
        == EnvironmentOperationStatus.FAILED
    )


# ---------------------------------------------------------------------------
# restore_environment_backup — guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restoring_an_unknown_environment_backup_raises_not_found(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    uow = _make_uow(environment=environment, deployments=[], driver_versions=[])

    with pytest.raises(EnvironmentBackupNotFoundError):
        await restore_environment_backup(environment_backup_id=uuid4(), uow=uow)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("child_statuses", "error_count"),
    [
        # Everything failed: nothing usable was ever captured.
        ([BackupStatus.FAILED], 0),
        ([], 1),
        # Still running: restoring a moving snapshot is not offered.
        ([BackupStatus.PENDING], 0),
        ([BackupStatus.COMPLETED, BackupStatus.IN_PROGRESS], 0),
    ],
)
async def test_a_non_restorable_snapshot_is_rejected(
    environment: Environment,
    prefect_manager_mock,
    no_config_fanout,
    child_statuses: list[BackupStatus],
    error_count: int,
) -> None:
    """FR-006: only COMPLETED / PARTIAL snapshots can be restored."""
    adv = _driver_version()
    deployments = [
        _deployment(environment_id=environment.id, adv=adv, name=f"app-{index}")
        for index in range(max(len(child_statuses), 1))
    ]
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment) for deployment in deployments],
        environment_config={"dns_zone": "captured.example.com"},
        constituent_errors=[
            ConstituentError(
                deployment_id=uuid4(),
                deployment_name=f"errored-{index}",
                error="backup already in progress",
            ).model_dump(mode="json")
            for index in range(error_count)
        ]
        or None,
    )
    constituents = [
        _constituent(parent, deployments[index], status=status)
        for index, status in enumerate(child_statuses)
    ]
    environment.config = {"dns_zone": "drifted.example.com"}
    uow = _make_uow(
        environment=environment,
        deployments=deployments,
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    with pytest.raises(EnvironmentBackupNotRestorableError) as excinfo:
        await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert excinfo.value.error_code == "OPERATION_DENIED"
    # Nothing was touched: no restore record, no config revert.
    assert uow.environment_restores.models == []
    assert environment.config == {"dns_zone": "drifted.example.com"}


@pytest.mark.asyncio
async def test_a_partial_snapshot_is_restorable(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """FR-006: PARTIAL is explicitly restorable — restore what is usable."""
    adv = _driver_version()
    ok = _deployment(environment_id=environment.id, adv=adv, name="ok")
    broken = _deployment(environment_id=environment.id, adv=adv, name="broken")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(ok), _snapshot_of(broken)],
        environment_config=None,
    )
    constituents = [
        _constituent(parent, ok),
        _constituent(parent, broken, status=BackupStatus.FAILED),
    ]
    uow = _make_uow(
        environment=environment,
        deployments=[ok, broken],
        driver_versions=[adv],
        backups=constituents,
        environment_backups=[parent],
    )

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert _skips(environment_restore) == {
        "broken": SkipReason.BACKUP_NOT_COMPLETED.value
    }
    assert len(uow.restores.models) == 1


@pytest.mark.asyncio
async def test_an_in_flight_environment_restore_blocks_a_second_restore(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """FR-009: the D6 guard covers the restore entry point too."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment)],
        environment_config=None,
    )
    constituent = _constituent(parent, deployment)
    in_flight = EnvironmentRestore(environment_backup_id=parent.id)
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[constituent],
        restores=[
            Restore(
                name="in-flight-restore",
                status=RestoreStatus.IN_PROGRESS,
                target_namespace=f"styrmin-{deployment.id}",
                backup_id=constituent.id,
                environment_restore_id=in_flight.id,
            )
        ],
        environment_backups=[parent],
        environment_restores=[in_flight],
    )

    with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
        await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert excinfo.value.error_metadata == {
        "operation_id": str(in_flight.id),
        "operation_kind": "environment_restore",
    }
    assert len(uow.environment_restores.models) == 1


@pytest.mark.asyncio
async def test_an_in_flight_environment_backup_blocks_a_restore(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """The guard is bidirectional (FR-009)."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment)],
        environment_config=None,
    )
    constituent = _constituent(parent, deployment)
    newer = EnvironmentBackup(name="newer-in-flight", environment_id=environment.id)
    in_flight_child = _constituent(newer, deployment, status=BackupStatus.IN_PROGRESS)
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[constituent, in_flight_child],
        environment_backups=[parent, newer],
    )

    with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
        await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert excinfo.value.error_metadata["operation_kind"] == "environment_backup"


# ---------------------------------------------------------------------------
# restore_environment_backup — ADR-0012 ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_config_revert_is_committed_before_any_dispatch(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """ADR-0012: a crash mid-fan-out must not lose the revert."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[_constituent(parent, deployment)],
        environment_backups=[parent],
    )
    config_at_dispatch: list[dict | None] = []
    commits_at_dispatch: list[int] = []
    prefect_manager_mock.run_action.side_effect = lambda **_: (
        config_at_dispatch.append(environment.config),
        commits_at_dispatch.append(uow.commit_count),
    )

    await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert config_at_dispatch == [{"dns_zone": "captured.example.com"}]
    assert commits_at_dispatch and commits_at_dispatch[0] >= 2


@pytest.mark.asyncio
async def test_every_constituent_restore_and_skip_is_durable_before_any_dispatch(
    environment: Environment, prefect_manager_mock, no_config_fanout, mocker
) -> None:
    """ADR-0012 made atomic on the restore side too.

    The constituent restores used to be created *and dispatched* one by one
    after the parent record was committed, with the late skips written only
    after the loop. At the first dispatch, therefore, later constituents had no
    row and the late skips existed only in memory. Both are durable up front
    now.
    """
    adv = _driver_version()
    racer = _deployment(environment_id=environment.id, adv=adv, name="racer")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(racer), _snapshot_of(healthy)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    racer_backup = _constituent(parent, racer)
    uow = _make_uow(
        environment=environment,
        deployments=[racer, healthy],
        driver_versions=[adv],
        backups=[racer_backup, _constituent(parent, healthy)],
        environment_backups=[parent],
    )

    async def _create_restore(*args, **kwargs):
        if kwargs["backup_id"] == racer_backup.id:
            raise RestoreAlreadyInProgressError(existing_restore_id=str(uuid4()))
        return await create_restore(*args, **kwargs)

    mocker.patch(
        "styrmin_backend.services.backup.environment.create_restore",
        side_effect=_create_restore,
    )
    observed: list[tuple[int, dict[str, str]]] = []
    prefect_manager_mock.run_action.side_effect = lambda **_: observed.append(
        (
            len(uow.restores.models),
            _skips(uow.environment_restores.models[0]),
        )
    )

    await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    # One dispatch, and by the time it runs the surviving constituent's restore
    # row exists and the racer's skip is already recorded on the parent.
    assert observed == [(1, {"racer": SkipReason.DEPLOYMENT_BUSY.value})]


@pytest.mark.asyncio
async def test_a_restore_deleted_mid_fan_out_raises_not_found(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """The restore mirrors the snapshot's FR-010 window (see the backup test)."""
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment)],
        environment_config=None,
    )
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[_constituent(parent, deployment)],
        environment_backups=[parent],
    )
    prefect_manager_mock.run_action.side_effect = lambda **_: (
        uow.environment_restores.models.clear()
    )

    with pytest.raises(EnvironmentRestoreNotFoundError):
        await restore_environment_backup(environment_backup_id=parent.id, uow=uow)


@pytest.mark.asyncio
async def test_late_skips_survive_a_cancellation_mid_dispatch(
    environment: Environment, prefect_manager_mock, no_config_fanout, mocker
) -> None:
    """FR-007 on the restore side: a disconnect must not drop a recorded skip."""
    adv = _driver_version()
    racer = _deployment(environment_id=environment.id, adv=adv, name="racer")
    healthy = _deployment(environment_id=environment.id, adv=adv, name="healthy")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(racer), _snapshot_of(healthy)],
        environment_config=None,
    )
    racer_backup = _constituent(parent, racer)
    uow = _make_uow(
        environment=environment,
        deployments=[racer, healthy],
        driver_versions=[adv],
        backups=[racer_backup, _constituent(parent, healthy)],
        environment_backups=[parent],
    )

    async def _create_restore(*args, **kwargs):
        if kwargs["backup_id"] == racer_backup.id:
            raise RestoreAlreadyInProgressError(existing_restore_id=str(uuid4()))
        return await create_restore(*args, **kwargs)

    mocker.patch(
        "styrmin_backend.services.backup.environment.create_restore",
        side_effect=_create_restore,
    )
    prefect_manager_mock.run_action.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await restore_environment_backup(environment_backup_id=parent.id, uow=uow)

    (persisted,) = uow.environment_restores.models
    assert _skips(persisted) == {"racer": SkipReason.DEPLOYMENT_BUSY.value}


@pytest.mark.asyncio
async def test_a_dispatch_failure_fails_the_constituent_restore_and_its_deployment(
    environment: Environment, prefect_manager_mock, no_config_fanout
) -> None:
    """A Prefect submission failure is a failed constituent, not a skip.

    Left ``PENDING``, the row would hold the deployment in ``RESTORING`` (status
    reports skip it) and keep the environment's operation guard closed.
    """
    adv = _driver_version()
    deployment = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(deployment)],
        environment_config=None,
    )
    uow = _make_uow(
        environment=environment,
        deployments=[deployment],
        driver_versions=[adv],
        backups=[_constituent(parent, deployment)],
        environment_backups=[parent],
    )
    prefect_manager_mock.run_action.side_effect = RuntimeError("prefect is down")

    environment_restore = await restore_environment_backup(
        environment_backup_id=parent.id, uow=uow
    )

    assert environment_restore.skipped_constituents is None
    (restore,) = uow.restores.models
    assert restore.status == RestoreStatus.FAILED
    assert restore.completed_at is not None
    assert restore.error_message is not None
    assert "never dispatched" in restore.error_message
    assert "prefect is down" in restore.error_message
    stored = await uow.deployments.find(deployment.id)
    assert stored is not None
    assert stored.status == DeploymentState.FAILED
    assert (
        await uow.environment_restores.has_in_progress_environment_restore(
            environment.id
        )
        is None
    )


# ---------------------------------------------------------------------------
# delete_environment_backup — cascade (US3 / FR-010)
# ---------------------------------------------------------------------------


def _constituent_restore(
    parent_restore: EnvironmentRestore,
    backup: Backup,
    *,
    status: RestoreStatus = RestoreStatus.COMPLETED,
) -> Restore:
    """A constituent restore linked to both its backup and its parent record.

    Both FKs are set explicitly on top of the relationship appends: nothing
    flushes in these tests, so SQLAlchemy never syncs them, and the cascade
    reads the FKs through the repositories.
    """
    restore = Restore(
        name=f"restore-{uuid4().hex[:6]}",
        status=status,
        target_namespace="styrmin-ns",
        backup_id=backup.id,
    )
    parent_restore.restores.append(restore)
    restore.environment_restore_id = parent_restore.id
    return restore


def _environment_restore(
    parent: EnvironmentBackup,
    *,
    skipped: list[dict] | None = None,
) -> EnvironmentRestore:
    environment_restore = EnvironmentRestore(
        environment_backup_id=parent.id, skipped_constituents=skipped
    )
    parent.restores.append(environment_restore)
    return environment_restore


@pytest.mark.asyncio
async def test_deleting_a_snapshot_cascades_to_constituents_and_their_restores(
    environment: Environment,
) -> None:
    """FR-010: the constituent backups and any restores of them go with it."""
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    netbox = _deployment(environment_id=environment.id, adv=adv, name="netbox")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub), _snapshot_of(netbox)],
        environment_config={"dns_zone": "captured.example.com"},
    )
    constituents = [_constituent(parent, infrahub), _constituent(parent, netbox)]
    environment_restore = _environment_restore(parent)
    constituent_restores = [
        _constituent_restore(environment_restore, backup) for backup in constituents
    ]
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub, netbox],
        driver_versions=[adv],
        backups=constituents,
        restores=constituent_restores,
        environment_backups=[parent],
        environment_restores=[environment_restore],
    )

    await delete_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert uow.environment_backups.models == []
    assert uow.environment_restores.models == []
    assert uow.backups.models == []
    assert uow.restores.models == []


@pytest.mark.asyncio
async def test_deleting_a_snapshot_leaves_sibling_snapshots_untouched(
    environment: Environment,
) -> None:
    """The cascade is scoped to one snapshot, not to the environment."""
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    doomed = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    keeper = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    doomed_constituent = _constituent(doomed, infrahub)
    keeper_constituent = _constituent(keeper, infrahub)
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub],
        driver_versions=[adv],
        backups=[doomed_constituent, keeper_constituent],
        environment_backups=[doomed, keeper],
    )

    await delete_environment_backup(environment_backup_id=doomed.id, uow=uow)

    assert [parent.id for parent in uow.environment_backups.models] == [keeper.id]
    assert [backup.id for backup in uow.backups.models] == [keeper_constituent.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
async def test_an_in_progress_snapshot_can_still_be_deleted(
    environment: Environment, status: BackupStatus
) -> None:
    """FR-010 escape hatch: deletion has no status guard.

    A constituent whose work was never picked up pins the snapshot
    non-terminal forever; deletion is the only way out.
    """
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    stuck = _constituent(parent, infrahub, status=status)
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub],
        driver_versions=[adv],
        backups=[stuck],
        environment_backups=[parent],
    )

    await delete_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert uow.environment_backups.models == []
    assert uow.backups.models == []


@pytest.mark.asyncio
async def test_deleting_a_stuck_snapshot_releases_the_environment(
    environment: Environment, prefect_manager_mock
) -> None:
    """The escape hatch has to actually unblock the D6 concurrency guard.

    A snapshot pinned ``IN_PROGRESS`` blocks every new environment-level
    operation (FR-009). Deleting it must let the next one through — that is
    the whole point of allowing deletion regardless of status.
    """
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    stuck_parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub],
        driver_versions=[adv],
        backups=[_constituent(stuck_parent, infrahub, status=BackupStatus.PENDING)],
        environment_backups=[stuck_parent],
    )

    with pytest.raises(EnvironmentOperationInProgressError):
        await create_environment_backup(environment_id=environment.id, uow=uow)

    await delete_environment_backup(environment_backup_id=stuck_parent.id, uow=uow)

    replacement = await create_environment_backup(
        environment_id=environment.id, uow=uow
    )
    assert replacement.id != stuck_parent.id
    assert len(uow.backups.models) == 1


@pytest.mark.asyncio
async def test_deleting_a_snapshot_tolerates_an_individually_deleted_constituent(
    environment: Environment,
) -> None:
    """A gap left by an individually deleted child is not an error (US3).

    The parent survives an individual constituent deletion with a visible gap,
    so the cascade must reach the same end state whether or not the child is
    still there.
    """
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    netbox = _deployment(environment_id=environment.id, adv=adv, name="netbox")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub), _snapshot_of(netbox)],
        environment_config=None,
    )
    surviving = _constituent(parent, infrahub)
    # Appended to the parent's relationship but never stored: the operator
    # deleted this constituent individually after the snapshot was taken.
    _constituent(parent, netbox)
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub, netbox],
        driver_versions=[adv],
        backups=[surviving],
        environment_backups=[parent],
    )

    await delete_environment_backup(environment_backup_id=parent.id, uow=uow)

    assert uow.environment_backups.models == []
    assert uow.backups.models == []


@pytest.mark.asyncio
async def test_deleting_an_unknown_snapshot_raises_not_found(
    environment: Environment,
) -> None:
    uow = _make_uow(environment=environment, deployments=[], driver_versions=[])

    with pytest.raises(EnvironmentBackupNotFoundError):
        await delete_environment_backup(environment_backup_id=uuid4(), uow=uow)


# ---------------------------------------------------------------------------
# delete_environment — cascade through the environment's snapshots (FR-015)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deleting_an_environment_cascades_its_environment_backups(
    environment: Environment,
) -> None:
    """FR-015: snapshots do not outlive their environment in v1.

    ``environmentbackup.environment_id`` is a non-nullable FK, so without the
    cascade this delete is a constraint violation rather than a delete.
    """
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    first = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    second = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    constituents = [_constituent(first, infrahub), _constituent(second, infrahub)]
    environment_restore = _environment_restore(first)
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub],
        driver_versions=[adv],
        backups=constituents,
        restores=[_constituent_restore(environment_restore, constituents[0])],
        environment_backups=[first, second],
        environment_restores=[environment_restore],
    )

    await delete_environment(environment_id=environment.id, uow=uow)

    assert uow.environments.models == []
    assert uow.environment_backups.models == []
    assert uow.environment_restores.models == []
    assert uow.backups.models == []
    assert uow.restores.models == []


@pytest.mark.asyncio
async def test_deleting_an_environment_cascades_an_in_progress_snapshot(
    environment: Environment,
) -> None:
    """The environment cascade inherits the escape hatch: no status guard."""
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    parent = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub],
        driver_versions=[adv],
        backups=[_constituent(parent, infrahub, status=BackupStatus.IN_PROGRESS)],
        environment_backups=[parent],
    )

    await delete_environment(environment_id=environment.id, uow=uow)

    assert uow.environments.models == []
    assert uow.environment_backups.models == []


@pytest.mark.asyncio
async def test_deleting_an_environment_leaves_another_environments_snapshots(
    environment: Environment,
) -> None:
    """The cascade is scoped by ``environment_id``, per spec FR-015."""
    other = Environment(name="production", cluster_id=environment.cluster_id)
    adv = _driver_version()
    infrahub = _deployment(environment_id=environment.id, adv=adv, name="infrahub")
    doomed = _environment_backup(
        environment=environment,
        snapshots=[_snapshot_of(infrahub)],
        environment_config=None,
    )
    keeper = _environment_backup(
        environment=other, snapshots=[], environment_config=None
    )
    uow = _make_uow(
        environment=environment,
        deployments=[infrahub],
        driver_versions=[adv],
        backups=[_constituent(doomed, infrahub)],
        environment_backups=[doomed, keeper],
    )
    await uow.environments.create(other)

    await delete_environment(environment_id=environment.id, uow=uow)

    assert [parent.id for parent in uow.environment_backups.models] == [keeper.id]


@pytest.mark.asyncio
async def test_deleting_an_environment_without_snapshots_still_deletes_it(
    environment: Environment,
) -> None:
    uow = _make_uow(environment=environment, deployments=[], driver_versions=[])

    await delete_environment(environment_id=environment.id, uow=uow)

    assert uow.environments.models == []


@pytest.mark.asyncio
async def test_deleting_an_unknown_environment_raises_before_any_cascade(
    environment: Environment,
) -> None:
    """The guard fires first, so a typo cannot delete another env's snapshots."""
    parent = _environment_backup(
        environment=environment, snapshots=[], environment_config=None
    )
    uow = _make_uow(
        environment=environment,
        deployments=[],
        driver_versions=[],
        environment_backups=[parent],
    )

    with pytest.raises(EnvironmentNotFoundError):
        await delete_environment(environment_id=uuid4(), uow=uow)

    assert uow.environment_backups.models == [parent]


# ---------------------------------------------------------------------------
# GraphQL enum mirror
# ---------------------------------------------------------------------------


def test_environment_restore_status_mirrors_the_service_enum() -> None:
    """``strawberry.enum`` binds one GraphQL name per class, so the restore
    surface declares its own mirror of ``EnvironmentOperationStatus``. Drift
    between the two would silently change what the API reports.
    """
    assert {member.name: member.value for member in EnvironmentRestoreStatus} == {
        member.name: member.value for member in EnvironmentOperationStatus
    }
