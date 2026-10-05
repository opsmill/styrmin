"""Tests for the deployment status service — displayState to Deployment.status mapping."""

from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationInstance,
    Backup,
    BackupStatus,
    InstanceStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.domain.models import Deployment, DeploymentState, Instance
from styrmin_backend.services.deployment_status import (
    extract_scheduling_conditions,
)
from styrmin_backend.services.deployment_status import report_deployment_statuses
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentStatusRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeRestoreRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _make_instance(instance_id: UUID | None = None) -> Instance:
    """Build a minimal Instance for tests that only read `instance.id`."""
    return Instance.model_construct(id=instance_id or uuid4())


def _make_uow(
    deployments: FakeDeploymentRepository | None = None,
    deployment_statuses: FakeDeploymentStatusRepository | None = None,
    deployed_services: "FakeDeployedServiceRepository | None" = None,
    restores: FakeRestoreRepository | None = None,
    instances: FakeApplicationInstanceRepository | None = None,
    backups: FakeBackupRepository | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=instances or FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployments=deployments,
        deployment_statuses=deployment_statuses,
        deployed_services=deployed_services,
        restores=restores,
        backups=backups,
    )


def _make_restore(
    target_namespace: str, status: RestoreStatus, backup_id: UUID | None = None
) -> Restore:
    restore_id = uuid4()
    return Restore(
        id=restore_id,
        name=f"styrmin-{restore_id}",
        status=status,
        target_namespace=target_namespace,
        backup_id=backup_id or uuid4(),
    )


async def _make_uow_with_own_backup_restore(
    dep: Deployment, target_namespace: str, restore_status: RestoreStatus
) -> tuple[FakeUnitOfWork, FakeDeploymentRepository]:
    """Build a uow holding *dep* and a restore of a backup of its instance."""
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    instance = ApplicationInstance(
        id=uuid4(),
        name="test-instance",
        application_version="1.0.0",
        status=InstanceStatus.RUNNING,
        deployment_id=dep.id,
        application_driver_version_id=uuid4(),
    )
    backup = Backup(
        id=uuid4(),
        name="test-backup",
        status=BackupStatus.COMPLETED,
        instance_id=instance.id,
    )
    restores = FakeRestoreRepository()
    await restores.create(_make_restore(target_namespace, restore_status, backup.id))
    uow = _make_uow(
        deployments=dep_repo,
        restores=restores,
        instances=FakeApplicationInstanceRepository([instance]),
        backups=FakeBackupRepository([backup]),
    )
    return uow, dep_repo


def _make_deployment(
    deployment_id=None,
    status: DeploymentState = DeploymentState.PENDING,
) -> Deployment:
    return Deployment(
        id=deployment_id or uuid4(),
        name="test-deployment",
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=status,
        created_by_user_id=uuid4(),
    )


def _make_deployed_service(deployment_id: UUID, environment_id: UUID, name: str):
    """Build a minimal DeployedService row owned by a deployment."""
    from styrmin_backend.db.models import DeployedService

    return DeployedService(
        id=uuid4(),
        driver_service_name=name,
        resolved_name=name,
        kind="http",
        scope="internal",
        port=8080,
        component="server",
        deployment_id=deployment_id,
        environment_id=environment_id,
    )


@pytest.mark.anyio
async def test_deploying_sets_deploying() -> None:
    dep = _make_deployment()
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "CreatingHelmRelease",
            "display_state": "Deploying",
        }
    ]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    assert statuses_updated == 1
    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.DEPLOYING


@pytest.mark.anyio
async def test_running_sets_running() -> None:
    dep = _make_deployment()
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    assert statuses_updated == 1
    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RUNNING


@pytest.mark.anyio
async def test_restoring_sets_restoring() -> None:
    """When the operator reports displayState=Restoring (during the
    velero window), the DB-side deployment.status should reflect that
    so the UI shows 'restoring' rather than 'deploying' or 'failed'.
    """
    dep = _make_deployment(status=DeploymentState.RUNNING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Restoring",
            "display_state": "Restoring",
        }
    ]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    assert statuses_updated == 1
    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RESTORING


@pytest.mark.anyio
@pytest.mark.parametrize(
    "restore_status", [RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS]
)
@pytest.mark.parametrize(
    "display_state", ["Running", "Deploying", "Error", "Deleting", "Deleted"]
)
async def test_in_flight_restore_keeps_restoring(
    restore_status: RestoreStatus, display_state: str
) -> None:
    """#389: until Velero finishes, the CR still reads its pre-restore state
    (or the teardown's, or none at all), so a report must not move the
    deployment out of RESTORING while its restore is in flight."""
    dep = _make_deployment(status=DeploymentState.RESTORING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    restores = FakeRestoreRepository()
    await restores.create(_make_restore(f"styrmin-{dep.id}", restore_status))
    uow = _make_uow(deployments=dep_repo, restores=restores)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": display_state,
        }
    ]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    assert statuses_updated == 1
    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RESTORING
    assert found.deleted_at is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("namespace_of", "restore_status"),
    [
        pytest.param("self", RestoreStatus.COMPLETED, id="restore-completed"),
        pytest.param("self", RestoreStatus.FAILED, id="restore-failed"),
        pytest.param("other", RestoreStatus.IN_PROGRESS, id="other-deployment"),
    ],
)
async def test_restoring_without_in_flight_restore_accepts_report(
    namespace_of: str, restore_status: RestoreStatus
) -> None:
    """Once no restore into the deployment is in flight, reports apply again,
    so a restore workflow that settled its row but not the deployment still
    converges on the CR's state."""
    dep = _make_deployment(status=DeploymentState.RESTORING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    target_id = dep.id if namespace_of == "self" else uuid4()
    restores = FakeRestoreRepository()
    await restores.create(_make_restore(f"styrmin-{target_id}", restore_status))
    uow = _make_uow(deployments=dep_repo, restores=restores)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RUNNING


@pytest.mark.anyio
@pytest.mark.parametrize(
    "restore_status", [RestoreStatus.PENDING, RestoreStatus.IN_PROGRESS]
)
async def test_in_flight_restore_into_other_namespace_keeps_restoring(
    restore_status: RestoreStatus,
) -> None:
    """``createRestore`` accepts any ``target_namespace``: an in-flight restore
    of the deployment's own backup into another namespace still holds
    RESTORING, since ``create_restore`` flipped the deployment for it."""
    dep = _make_deployment(status=DeploymentState.RESTORING)
    uow, dep_repo = await _make_uow_with_own_backup_restore(
        dep, "custom-ns", restore_status
    )

    reports = [{"deployment_id": dep.id, "phase": "Ready", "display_state": "Running"}]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    assert statuses_updated == 1
    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RESTORING


@pytest.mark.anyio
@pytest.mark.parametrize(
    "restore_status", [RestoreStatus.COMPLETED, RestoreStatus.FAILED]
)
async def test_settled_restore_into_other_namespace_accepts_report(
    restore_status: RestoreStatus,
) -> None:
    """Once that restore is terminal, reports apply again."""
    dep = _make_deployment(status=DeploymentState.RESTORING)
    uow, dep_repo = await _make_uow_with_own_backup_restore(
        dep, "custom-ns", restore_status
    )

    reports = [{"deployment_id": dep.id, "phase": "Ready", "display_state": "Running"}]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RUNNING


@pytest.mark.anyio
async def test_error_sets_failed() -> None:
    dep = _make_deployment()
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "CreatingHelmRelease",
            "display_state": "Error",
        }
    ]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    assert statuses_updated == 1
    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.FAILED


@pytest.mark.anyio
async def test_deleting_sets_deleting() -> None:
    """displayState=Deleting projects to DeploymentState.DELETING and
    must NOT touch deleted_at — the row stays "live" until the terminal
    transition."""
    dep = _make_deployment(status=DeploymentState.RUNNING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Deleting",
            "display_state": "Deleting",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.DELETING
    assert found.deleted_at is None


@pytest.mark.anyio
async def test_deleted_sets_deleted_and_stamps_deleted_at() -> None:
    """displayState=Deleted projects to DeploymentState.DELETED and
    atomically stamps deleted_at — this is the SOLE writer of
    deleted_at, so readers cannot see DELETED with a NULL timestamp."""
    dep = _make_deployment(status=DeploymentState.DELETING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Deleted",
            "display_state": "Deleted",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.DELETED
    assert found.deleted_at is not None


@pytest.mark.anyio
async def test_deleted_does_not_overwrite_deleted_at_on_redundant_report() -> None:
    """If a report comes in for an already-DELETED deployment (e.g. a
    duplicate event from the reconciler), we must not stomp the existing
    deleted_at with a fresh now()."""
    from datetime import datetime, timezone

    original_ts = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
    dep = _make_deployment(status=DeploymentState.DELETED)
    dep.deleted_at = original_ts
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Deleted",
            "display_state": "Deleted",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    # Already at the target state, so no update fires.
    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.deleted_at == original_ts


@pytest.mark.anyio
async def test_deleted_cleans_up_deployed_services() -> None:
    """On the terminal DELETED transition, the deployment's DeployedService
    rows are removed so a later deployment can reclaim the same service name
    and the deleted deployment's services stop leaking into other
    deployments' service-discovery context. Other deployments' services
    are left untouched."""
    env_id = uuid4()
    dep = _make_deployment(status=DeploymentState.DELETING)
    dep.environment_id = env_id
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)

    other_deployment_id = uuid4()
    svc_repo = FakeDeployedServiceRepository(
        [
            _make_deployed_service(dep.id, env_id, "api"),
            _make_deployed_service(dep.id, env_id, "worker"),
            # A different deployment's service in the same environment.
            _make_deployed_service(other_deployment_id, env_id, "other-api"),
        ]
    )
    uow = _make_uow(deployments=dep_repo, deployed_services=svc_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Deleted",
            "display_state": "Deleted",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    # The tombstoned deployment's services are gone...
    assert await svc_repo.get_by_deployment_id(dep.id) == []
    # ...but the sibling deployment's service survives.
    survivors = await svc_repo.get_by_deployment_id(other_deployment_id)
    assert len(survivors) == 1
    assert survivors[0].resolved_name == "other-api"


@pytest.mark.anyio
async def test_deleting_does_not_clean_up_deployed_services() -> None:
    """The non-terminal DELETING transition must NOT remove services — the
    deployment is still being torn down on the cluster; cleanup is gated on
    the terminal DELETED transition alongside the deleted_at stamp."""
    env_id = uuid4()
    dep = _make_deployment(status=DeploymentState.RUNNING)
    dep.environment_id = env_id
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)

    svc_repo = FakeDeployedServiceRepository(
        [_make_deployed_service(dep.id, env_id, "api")]
    )
    uow = _make_uow(deployments=dep_repo, deployed_services=svc_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Deleting",
            "display_state": "Deleting",
        }
    ]
    await report_deployment_statuses(reports, uow)

    assert len(await svc_repo.get_by_deployment_id(dep.id)) == 1


@pytest.mark.anyio
async def test_no_display_state_defaults_to_deploying() -> None:
    dep = _make_deployment()
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Pending",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.DEPLOYING


@pytest.mark.anyio
async def test_already_running_no_redundant_update() -> None:
    dep = _make_deployment(status=DeploymentState.RUNNING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 0


@pytest.mark.anyio
async def test_stale_instance_id_skips_status_update() -> None:
    """A report for a superseded instance must not flip the deployment
    back to RUNNING while the new instance is still rolling out."""
    active_instance = _make_instance()
    stale_instance_id = uuid4()
    dep = _make_deployment(status=DeploymentState.DEPLOYING)
    dep.set_active_instance(active_instance)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "instance_id": stale_instance_id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    statuses_updated, deployments_updated = await report_deployment_statuses(
        reports, uow
    )

    # CRD status record is still upserted (kept for observability) but the
    # deployment status is not advanced.
    assert statuses_updated == 1
    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.DEPLOYING


@pytest.mark.anyio
async def test_matching_instance_id_allows_status_update() -> None:
    active_instance = _make_instance()
    dep = _make_deployment(status=DeploymentState.DEPLOYING)
    dep.set_active_instance(active_instance)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "instance_id": active_instance.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RUNNING


@pytest.mark.anyio
async def test_missing_instance_id_backcompat() -> None:
    """Reports without instance_id bypass the guard (legacy CRDs)."""
    active_instance = _make_instance()
    dep = _make_deployment(status=DeploymentState.DEPLOYING)
    dep.set_active_instance(active_instance)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)
    uow = _make_uow(deployments=dep_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    _, deployments_updated = await report_deployment_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentState.RUNNING


class TestExtractSchedulingConditions:
    """T044: conditions whose ``message`` / ``reason`` mentions
    affinity / tolerations / topology spread / runtime class are surfaced
    so the deployment status view can highlight them separately.
    """

    def test_extracts_affinity_unsatisfied(self) -> None:
        conds = [
            {
                "type": "PodScheduled",
                "status": "False",
                "reason": "Unschedulable",
                "message": (
                    "0/3 nodes are available: 3 node(s) didn't match pod "
                    "affinity rules."
                ),
            },
            {
                "type": "Ready",
                "status": "True",
                "message": "all good",
            },
        ]

        filtered = extract_scheduling_conditions(conds)

        assert len(filtered) == 1
        assert filtered[0]["scheduling"] is True
        assert "affinity" in filtered[0]["message"].lower()

    def test_extracts_toleration_and_taint_conditions(self) -> None:
        conds = [
            {
                "message": "node(s) had taint {dedicated: batch}, that the pod didn't tolerate"
            },
        ]

        filtered = extract_scheduling_conditions(conds)

        assert len(filtered) == 1

    def test_drops_non_scheduling_conditions(self) -> None:
        conds = [
            {"message": "container image pull backoff"},
            {"message": "ready"},
        ]
        assert extract_scheduling_conditions(conds) == []

    def test_handles_none(self) -> None:
        assert extract_scheduling_conditions(None) == []

    def test_matches_case_insensitively(self) -> None:
        conds = [{"reason": "TOLERATION_MISMATCH", "message": "x"}]
        assert extract_scheduling_conditions(conds)
