"""Tests for the deployment status service — displayState to Deployment.status mapping."""

from uuid import UUID, uuid4

import pytest

from styrmin_backend.domain.models import Deployment, DeploymentState, Instance
from styrmin_backend.services.deployment_status import (
    extract_scheduling_conditions,
)
from styrmin_backend.services.deployment_status import report_deployment_statuses
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeploymentStatusRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _make_instance(instance_id: UUID | None = None) -> Instance:
    """Build a minimal Instance for tests that only read `instance.id`."""
    return Instance.model_construct(id=instance_id or uuid4())


def _make_uow(
    deployments: FakeDeploymentRepository | None = None,
    deployment_statuses: FakeDeploymentStatusRepository | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployments=deployments,
        deployment_statuses=deployment_statuses,
    )


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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "terminal_state",
    [
        DeploymentState.DELETION_REQUESTED,
        DeploymentState.DELETION_IN_PROGRESS,
        DeploymentState.DELETED,
    ],
)
async def test_deletion_lifecycle_ignores_incoming_reports(
    terminal_state: DeploymentState,
) -> None:
    """A deployment that has entered the deletion lifecycle must not
    have its status overwritten by a stale CRD report racing the
    teardown (e.g., an agent emitting ``Deploying`` while the CRD is
    still briefly present)."""
    dep = _make_deployment(status=terminal_state)
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

    # CRD snapshot still updates — operators need to see phase — but
    # the Deployment.status must NOT regress out of the deletion
    # lifecycle.
    assert statuses_updated == 1
    assert deployments_updated == 0

    found = await dep_repo.find(dep.id)
    assert found is not None
    assert found.status == terminal_state
