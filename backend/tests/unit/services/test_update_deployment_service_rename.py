"""Repro for #237 at the service layer.

Bug: `update_deployment(service_name_overrides=…)` previously called
`reconcile_services_on_upgrade` AFTER `generate_instance_from_deployment`,
so the generated instance carried the OLD service name. The Prefect flow
then reconciled K8s against the old name and never created the new Service.

Fix: writes that affect context (service rename, parameter merge, config
update) must be COMMITTED before instance generation. This test pins that
invariant at the service-layer boundary, so future reorderings can't
silently regress.
"""

from uuid import UUID, uuid4
from unittest.mock import AsyncMock, patch

import pytest

from styrmin_backend.domain.models import Deployment, DeploymentState, Task, TaskType
from styrmin_backend.services.deployment import update_deployment
from tests.unit.services.fakes import (
    FakeUnitOfWork,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmRepositoryRepository,
    FakeHelmChartRepository,
    FakeApplicationRepository,
    FakeApplicationDriverVersionRepository,
    FakeApplicationInstanceRepository,
    FakeActionRepository,
    FakeTaskRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
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


async def _seed_deployment_with_service(
    *,
    uow: FakeUnitOfWork,
    deployment_id: UUID,
    environment_id: UUID,
    driver_service_name: str,
) -> None:
    """Seed a minimal deployment and one DeployedService row into the fake repos.

    Places:
    - A ``Deployment`` domain entity (status=RUNNING) in ``uow.deployments``
    - A ``DeployedService`` DB row (driver_service_name=driver_service_name,
      resolved_name=driver_service_name) in ``uow.deployed_services``
    - An ``ApplicationDriverVersion`` row in ``uow.application_driver_versions``
      with a ``services`` list that declares the same service name.

    The ``ApplicationDriverVersion`` is kept as minimal as possible so
    ``reconcile_services_on_upgrade`` can re-read it.
    """
    from styrmin_backend.db.models import (
        ApplicationDriver,
        ApplicationDriverVersion,
        Cluster,
        DeployedService,
        Environment,
        HelmChart,
        HelmRepository,
    )

    # --- Cluster / Environment ---
    cluster = Cluster(name="test-cluster")
    await uow.clusters.create(cluster)

    env = Environment(name="test-env", cluster_id=cluster.id, id=environment_id)
    await uow.environments.create(env)

    # --- Helm plumbing (needed by generate_context_from_deployment) ---
    helm_repo = HelmRepository(url="https://charts.example.com")
    await uow.helm_repositories.create(helm_repo)

    helm_chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    await uow.helm_charts.create(helm_chart)

    # --- ApplicationDriver + Version ---
    app_driver = ApplicationDriver(name="test-app")
    adv = ApplicationDriverVersion(
        id=uuid4(),
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        helm_chart_id=helm_chart.id,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        source_path=None,
        application_driver_id=app_driver.id,
        services=[
            {
                "name": driver_service_name,
                "kind": "http",
                "scope": "internal",
                "port": 8080,
                "component": "server",
            }
        ],
        component_configs=[],
    )
    adv.application_driver = app_driver
    await uow.application_driver_versions.create(adv)
    await uow.application_drivers.create(app_driver)

    # --- Deployment domain entity ---
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=adv.id,
        environment_id=environment_id,
        created_by_user_id=uuid4(),
        name="test-deploy",
    )
    # Force to the specific ID so tests can look it up
    object.__setattr__(deployment, "id", deployment_id)
    deployment.set_status(DeploymentState.RUNNING)
    await uow.deployments.save(deployment)

    # --- Existing DeployedService row (old name = driver_service_name) ---
    svc = DeployedService(
        id=uuid4(),
        driver_service_name=driver_service_name,
        resolved_name=driver_service_name,
        kind="http",
        scope="internal",
        port=8080,
        component="server",
        deployment_id=deployment_id,
        environment_id=environment_id,
    )
    await uow.deployed_services.create(svc)


def _stub_task(*, deployment_id: UUID) -> Task:
    """Return a minimal domain Task so the service's ``tasks.find`` lookup succeeds."""
    return Task.create(
        type=TaskType.UPDATE_INSTANCE,
        deployment_id=deployment_id,
    )


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_service_rename_produces_instance_with_new_name(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    env_id = uuid4()

    # Seed an existing deployment with a single service "api".
    await _seed_deployment_with_service(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=env_id,
        driver_service_name="api",
    )

    # Stub apply_state so we don't touch Prefect.  The side_effect saves the
    # stub task into the fake repo so that the service's subsequent
    # ``tasks.find(id=task.id)`` round-trip succeeds.
    async def _fake_apply_state(deployment, current_instance, uow, task_type):  # noqa: ANN001
        stub = _stub_task(deployment_id=deployment.id)
        await uow.tasks.save(stub)
        return stub

    mock_apply_state.side_effect = _fake_apply_state

    async with uow:
        await update_deployment(
            deployment_id=deployment_id,
            uow=uow,
            service_name_overrides={"api": "api-v2"},
        )

    # Pull the deployment back out of the fake repo.
    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)

    assert deployment is not None
    assert deployment.active_instance is not None
    deployed_services = deployment.active_instance.context.deployed_services
    resolved_names = {svc["resolved_name"] for svc in deployed_services}
    assert resolved_names == {"api-v2"}, (
        f"Expected the new instance context to carry the renamed service "
        f"'api-v2', got {resolved_names}. This is #237."
    )
    # Phase separation invariant: update_deployment must commit twice — once
    # for user intent (parameters/config/services) and once for the new
    # instance. If a future refactor collapses these into a single UoW we
    # regress to #237; this assertion is the canary.
    assert uow.commit_count == 2, (
        f"Expected 2 commits (phase 1 + phase 2), got {uow.commit_count}"
    )
