"""Reconcile tasks carry the type their caller means (019 research D19, FR-019).

The real ``apply_state`` service function runs against a mocked Prefect
manager; only the context resolver is stubbed, so each test observes the
task the caller actually stores.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
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
    Cluster,
    Environment,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.domain.models import (
    Component,
    Deployment,
    DeploymentState,
    Instance,
    InstanceStatus,
    Task,
    TaskType,
)
from styrmin_backend.services import deployment as deployment_service
from styrmin_backend.services import primitives as primitives_service
from styrmin_backend.services.deployment import (
    _ensure_ingress_controller,
    deploy_application,
    redeploy_for_environment_update,
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.ingress_controller.driver import INTERNAL_DRIVER_NAME
from styrmin_backend.services.primitives import start_components, stop_components
from styrmin_backend.services.reconciliation import apply_state
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)

DRIVER_NAME = "simple-app"
COMPONENT = "web"


def _make_instance(deployment: Deployment, *, environment_name: str) -> Instance:
    context = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(
            name=environment_name, config=EnvironmentConfig()
        ),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment.id,
            namespace=f"styrmin-{deployment.id}",
            release_reference=f"styrmin-{deployment.id}",
        ),
        app=ApplicationContext(
            name="test-app",
            version=deployment.application_version,
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="test-chart", version="0.1.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )
    return Instance(
        id=uuid4(),
        name=f"instance-{uuid4().hex[:6]}",
        application_version=deployment.application_version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=context,
    )


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(return_value=MagicMock(id=uuid4()))
    return prefect_manager_mock


@pytest.fixture(autouse=True)
def stub_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    # "after" differs from the seeded instance's "before", so no update is a no-op.
    async def _generate(
        *, deployment: Deployment, uow: object, release_reference: str | None = None
    ) -> Instance:
        return _make_instance(deployment, environment_name="after")

    for module in (deployment_service, primitives_service):
        monkeypatch.setattr(module, "generate_instance_from_deployment", _generate)


def _driver(name: str, chart: HelmChart) -> ApplicationDriver:
    driver = ApplicationDriver(name=name)
    version = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version="1.0.0",
        application_supported_versions=">=1.0.0,<2.0.0",
        default_version="1.0.0",
        source_repository="https://example.com/driver",
        helm_chart_id=chart.id,
    )
    version.component_configs = []
    driver.versions = [version]
    return driver


@pytest.fixture
def graph() -> SimpleNamespace:
    cluster = Cluster(name="test-cluster", config={})
    environment = Environment(name="test-env", cluster_id=cluster.id, config={})
    repository = HelmRepository(url="https://helm.example.com/test")
    chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=repository.id,
    )
    driver = _driver(DRIVER_NAME, chart)
    return SimpleNamespace(
        cluster=cluster,
        environment=environment,
        repository=repository,
        chart=chart,
        driver=driver,
        driver_version=driver.versions[0],
    )


def _make_uow(
    graph: SimpleNamespace,
    *,
    deployments: list[Deployment] | None = None,
    drivers: list[ApplicationDriver] | None = None,
) -> FakeUnitOfWork:
    drivers = drivers or [graph.driver]
    return FakeUnitOfWork(
        clusters=FakeClusterRepository([graph.cluster]),
        environments=FakeEnvironmentRepository([graph.environment]),
        helm_repositories=FakeHelmRepositoryRepository([graph.repository]),
        helm_charts=FakeHelmChartRepository([graph.chart]),
        application_driver_versions=FakeApplicationRepository(
            [v for d in drivers for v in d.versions]
        ),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        application_drivers=FakeApplicationDriverRepository(drivers),
        deployments=FakeDeploymentRepository(deployments or []),
    )


def _seed_deployment(graph: SimpleNamespace) -> tuple[Deployment, Instance]:
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=graph.driver_version.id,
        environment_id=graph.environment.id,
        created_by_user_id=uuid4(),
        name="web-app",
    )
    deployment.add_component(Component.create(name=COMPONENT, config={}))
    previous = _make_instance(deployment, environment_name="before")
    deployment.set_active_instance(previous)
    deployment.set_status(DeploymentState.RUNNING)
    return deployment, previous


async def _assert_rolls_out_new_instance(
    uow: FakeUnitOfWork, task: Task, deployment_id: UUID, expected: TaskType
) -> UUID:
    stored = await uow.deployments.find(id=deployment_id)
    assert stored is not None and stored.active_instance is not None
    assert task.type == expected
    assert task.instance_id == stored.active_instance.id
    assert await uow.tasks.find(id=task.id) is not None
    return stored.active_instance.id


# ---------------------------------------------------------------------------
# apply_state
# ---------------------------------------------------------------------------


async def test_apply_state_defaults_to_noop_and_records_the_new_instance(
    graph: SimpleNamespace,
) -> None:
    deployment, previous = _seed_deployment(graph)
    new_instance = _make_instance(deployment, environment_name="after")
    deployment.set_active_instance(new_instance)

    task = await apply_state(
        deployment=deployment, current_instance=previous, uow=_make_uow(graph)
    )

    assert task.type == TaskType.NOOP
    assert task.instance_id == new_instance.id


async def test_apply_state_stores_the_given_task_type(
    graph: SimpleNamespace,
) -> None:
    deployment, previous = _seed_deployment(graph)
    new_instance = _make_instance(deployment, environment_name="after")
    deployment.set_active_instance(new_instance)

    task = await apply_state(
        deployment=deployment,
        current_instance=previous,
        uow=_make_uow(graph),
        task_type=TaskType.UPGRADE_INSTANCE,
    )

    assert task.type == TaskType.UPGRADE_INSTANCE
    assert task.instance_id == new_instance.id


# ---------------------------------------------------------------------------
# Callers of apply_state (research D19)
# ---------------------------------------------------------------------------

Caller = Callable[[FakeUnitOfWork, Deployment], Awaitable[Task | None]]


async def _update(uow: FakeUnitOfWork, deployment: Deployment) -> Task | None:
    return await update_deployment(
        deployment_id=deployment.id, uow=uow, deployment_name="web-app-renamed"
    )


async def _update_version(uow: FakeUnitOfWork, deployment: Deployment) -> Task | None:
    return await update_deployment_version(
        deployment_id=deployment.id, version="1.1.0", uow=uow
    )


async def _redeploy(uow: FakeUnitOfWork, deployment: Deployment) -> Task | None:
    async with uow:
        return await redeploy_for_environment_update(deployment=deployment, uow=uow)


async def _stop(uow: FakeUnitOfWork, deployment: Deployment) -> Task | None:
    return await stop_components(
        deployment_id=deployment.id, components=[COMPONENT], uow=uow
    )


async def _start(uow: FakeUnitOfWork, deployment: Deployment) -> Task | None:
    return await start_components(
        deployment_id=deployment.id, components=[COMPONENT], uow=uow
    )


@pytest.mark.parametrize(
    ("caller", "expected"),
    [
        pytest.param(_update, TaskType.UPDATE_INSTANCE, id="update_deployment"),
        pytest.param(
            _update_version, TaskType.UPGRADE_INSTANCE, id="update_deployment_version"
        ),
        pytest.param(
            _redeploy, TaskType.UPDATE_INSTANCE, id="redeploy_for_environment_update"
        ),
        pytest.param(_stop, TaskType.STOP_COMPONENTS, id="stop_components"),
        pytest.param(_start, TaskType.START_COMPONENTS, id="start_components"),
    ],
)
async def test_caller_creates_its_task_type(
    graph: SimpleNamespace, caller: Caller, expected: TaskType
) -> None:
    deployment, previous = _seed_deployment(graph)
    uow = _make_uow(graph, deployments=[deployment])

    task = await caller(uow, deployment)

    assert task is not None
    instance_id = await _assert_rolls_out_new_instance(
        uow, task, deployment.id, expected
    )
    assert instance_id != previous.id


async def test_deploy_application_creates_a_create_instance_task(
    graph: SimpleNamespace,
) -> None:
    uow = _make_uow(graph)

    task = await deploy_application(
        driver_name=DRIVER_NAME,
        version="1.0.0",
        environment_id=graph.environment.id,
        uow=uow,
        created_by_user_id=uuid4(),
        deployment_name="fresh",
    )

    assert task is not None
    await _assert_rolls_out_new_instance(
        uow, task, task.deployment_id, TaskType.CREATE_INSTANCE
    )


async def test_new_ingress_controller_gets_a_create_instance_task(
    graph: SimpleNamespace,
) -> None:
    graph.environment.config = {
        "dedicated_ingress": {"implementation": "traefik", "type": "ingress"}
    }
    ingress_driver = _driver(INTERNAL_DRIVER_NAME, graph.chart)
    uow = _make_uow(graph, drivers=[graph.driver, ingress_driver])

    await _ensure_ingress_controller(
        environment_id=graph.environment.id, uow=uow, created_by_user_id=uuid4()
    )

    internal = await uow.deployments.find_internal_by_environment(graph.environment.id)
    assert internal is not None
    [task] = uow.tasks.models
    assert task.deployment_id == internal.id
    await _assert_rolls_out_new_instance(
        uow, task, internal.id, TaskType.CREATE_INSTANCE
    )
