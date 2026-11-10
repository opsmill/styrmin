"""A context lists the services of a peer that is being deleted (#503, FR-010).

The alias flow skips a departing peer by reading the cluster (research R-003), so the
context that driver templates render with keeps the peer's services until it is DELETED.
"""

from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    DeployedService,
    Environment,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services.context import generate_context_from_deployment
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverVersionRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


def _make_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationDriverVersionRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployed_services=FakeDeployedServiceRepository(),
        deployments=FakeDeploymentRepository(),
        application_drivers=FakeApplicationRepository(),
    )


async def _seed_environment(uow: FakeUnitOfWork) -> tuple[UUID, UUID]:
    """One environment and one driver version; returns their ids."""
    cluster = Cluster(name="test-cluster")
    await uow.clusters.create(cluster)
    environment = Environment(name="test-env", cluster_id=cluster.id)
    await uow.environments.create(environment)

    helm_repo = HelmRepository(url="https://charts.example.com")
    await uow.helm_repositories.create(helm_repo)
    helm_chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    await uow.helm_charts.create(helm_chart)

    app_driver = ApplicationDriver(name="test-app")
    driver_version = ApplicationDriverVersion(
        id=uuid4(),
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        helm_chart_id=helm_chart.id,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        source_path=None,
        application_driver_id=app_driver.id,
        services=[],
        component_configs=[],
    )
    driver_version.application_driver = app_driver
    await uow.application_driver_versions.create(driver_version)
    await uow.application_drivers.create(app_driver)
    return environment.id, driver_version.id


async def _seed_deployment(
    uow: FakeUnitOfWork,
    *,
    environment_id: UUID,
    driver_version_id: UUID,
    status: DeploymentState,
    driver_service_name: str,
    resolved_name: str,
) -> Deployment:
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=driver_version_id,
        environment_id=environment_id,
        created_by_user_id=uuid4(),
        name=f"deploy-{resolved_name}",
    )
    deployment.set_status(status)
    await uow.deployments.save(deployment)
    await uow.deployed_services.create(
        DeployedService(
            id=uuid4(),
            driver_service_name=driver_service_name,
            resolved_name=resolved_name,
            kind="http",
            scope="internal",
            port=8080,
            component="server",
            deployment_id=deployment.id,
            environment_id=environment_id,
        )
    )
    return deployment


@pytest.mark.asyncio
async def test_generate_context_lists_the_services_of_a_deleting_peer() -> None:
    uow = _make_uow()
    environment_id, driver_version_id = await _seed_environment(uow)
    deployment = await _seed_deployment(
        uow,
        environment_id=environment_id,
        driver_version_id=driver_version_id,
        status=DeploymentState.RUNNING,
        driver_service_name="executor",
        resolved_name="executor",
    )
    peer = await _seed_deployment(
        uow,
        environment_id=environment_id,
        driver_version_id=driver_version_id,
        status=DeploymentState.DELETING,
        driver_service_name="intent",
        resolved_name="intent-renamed",
    )

    context = await generate_context_from_deployment(deployment, uow)

    assert context.services["intent"]["host"] == "intent-renamed"
    assert {
        "driver_service_name": "intent",
        "resolved_name": "intent-renamed",
        "port": 8080,
        "kind": "http",
        "scope": "internal",
        "deployment_id": str(peer.id),
        "component": "server",
        "ingress_class": None,
        "fqdn_suffix": None,
    } in context.deployed_services
