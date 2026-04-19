"""Tests for the deployment CRD status service — displayState to Deployment.status mapping."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from styrmin_backend.domain.models import (
    Deployment,
    DeploymentStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.deployment_crd_status import report_crd_statuses
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeploymentCrdStatusRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _make_uow(
    deployments: FakeDeploymentRepository | None = None,
    crd_statuses: FakeDeploymentCrdStatusRepository | None = None,
    tasks: FakeTaskRepository | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=tasks if tasks is not None else FakeTaskRepository(),
        deployments=deployments,
        deployment_crd_statuses=crd_statuses,
    )


def _make_deployment(
    deployment_id=None,
    status: DeploymentStatus = DeploymentStatus.PENDING,
) -> Deployment:
    return Deployment(
        id=deployment_id or uuid4(),
        name="test-deployment",
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=status,
    )


@pytest.mark.anyio
async def test_deploying_keeps_pending() -> None:
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
    statuses_updated, deployments_updated = await report_crd_statuses(reports, uow)

    assert statuses_updated == 1
    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentStatus.PENDING


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
    statuses_updated, deployments_updated = await report_crd_statuses(reports, uow)

    assert statuses_updated == 1
    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentStatus.RUNNING


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
    statuses_updated, deployments_updated = await report_crd_statuses(reports, uow)

    assert statuses_updated == 1
    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentStatus.FAILED


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
    _, deployments_updated = await report_crd_statuses(reports, uow)

    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentStatus.PENDING


@pytest.mark.anyio
async def test_already_running_no_redundant_update() -> None:
    dep = _make_deployment(status=DeploymentStatus.RUNNING)
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
    _, deployments_updated = await report_crd_statuses(reports, uow)

    assert deployments_updated == 0


@pytest.mark.anyio
async def test_running_suppressed_while_task_active() -> None:
    """An in-flight task (e.g. UPGRADE_INSTANCE hook running stop_components)
    can make the CRD transiently report Running between nested pipeline runs.
    The deployment status must not flip to RUNNING until the task finishes."""
    dep = _make_deployment(status=DeploymentStatus.PENDING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)

    task_repo = FakeTaskRepository()
    await task_repo.save(
        Task(
            id=uuid4(),
            deployment_id=dep.id,
            type=TaskType.UPGRADE_INSTANCE,
            status=TaskStatus.RUNNING,
            updated_on=datetime.now(tz=timezone.utc),
        )
    )
    uow = _make_uow(deployments=dep_repo, tasks=task_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    _, deployments_updated = await report_crd_statuses(reports, uow)

    assert deployments_updated == 0
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentStatus.PENDING


@pytest.mark.anyio
async def test_running_allowed_when_task_is_stale() -> None:
    """A task that has been RUNNING without updates for longer than the
    staleness window is treated as orphaned (e.g., the agent crashed before
    callbacks fired) and no longer blocks the RUNNING transition."""
    dep = _make_deployment(status=DeploymentStatus.PENDING)
    dep_repo = FakeDeploymentRepository()
    await dep_repo.save(dep)

    task_repo = FakeTaskRepository()
    stale_update = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    await task_repo.save(
        Task(
            id=uuid4(),
            deployment_id=dep.id,
            type=TaskType.UPGRADE_INSTANCE,
            status=TaskStatus.RUNNING,
            updated_on=stale_update,
        )
    )
    uow = _make_uow(deployments=dep_repo, tasks=task_repo)

    reports = [
        {
            "deployment_id": dep.id,
            "phase": "Ready",
            "display_state": "Running",
        }
    ]
    _, deployments_updated = await report_crd_statuses(reports, uow)

    assert deployments_updated == 1
    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == DeploymentStatus.RUNNING
