"""A deployment write stores the id of each deployment that an affinity term names.

Covers ``deploy_application``, ``update_deployment`` and ``update_deployment_version``
(027 plan D-002, FR-001, FR-007): a name in a deployment reference is replaced with
the id of the named deployment before anything is saved, also in the component
configs copied from a driver version. The context resolver is stubbed, as in
``test_task_types.py``, so each test observes what the service stores.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
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
    ComponentConfig,
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
)
from styrmin_backend.services import deployment as deployment_service
from styrmin_backend.services.deployment import (
    deploy_application,
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.exceptions import UnresolvableAffinityReferenceError
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
TOPOLOGY_KEY = "kubernetes.io/hostname"


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


def _scheduling(deployment_ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "scheduling": {
            "pod_affinity": {
                "required": [
                    {"topology_key": TOPOLOGY_KEY, "deployment_ref": deployment_ref}
                ]
            }
        }
    }


def _stored_ref(config: dict[str, Any] | None) -> dict[str, Any]:
    assert config is not None
    return config["scheduling"]["pod_affinity"]["required"][0]["deployment_ref"]


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(return_value=MagicMock(id=uuid4()))
    return prefect_manager_mock


@pytest.fixture(autouse=True)
def generated(monkeypatch: pytest.MonkeyPatch) -> list[Mapping[UUID, str] | None]:
    """Stub the context resolver; record the upcoming deployments of each call."""
    calls: list[Mapping[UUID, str] | None] = []

    async def _generate(
        *,
        deployment: Deployment,
        uow: object,  # noqa: ARG001
        release_reference: str | None = None,  # noqa: ARG001
        upcoming_deployments: Mapping[UUID, str] | None = None,
    ) -> Instance:
        calls.append(upcoming_deployments)
        return _make_instance(deployment, environment_name="after")

    monkeypatch.setattr(
        deployment_service, "generate_instance_from_deployment", _generate
    )
    return calls


def _driver_version(
    driver: ApplicationDriver,
    chart: HelmChart,
    version: str,
    component_configs: dict[str, dict[str, Any]] | None = None,
) -> ApplicationDriverVersion:
    driver_version = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=">=1.0.0,<2.0.0",
        default_version="1.0.0",
        source_repository="https://example.com/driver",
        helm_chart_id=chart.id,
    )
    driver_version.component_configs = [
        ComponentConfig(
            name=name, config=config, application_driver_version_id=driver_version.id
        )
        for name, config in (component_configs or {}).items()
    ]
    return driver_version


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
    driver = ApplicationDriver(name=DRIVER_NAME)
    driver.versions = [_driver_version(driver, chart, "1.0.0")]
    return SimpleNamespace(
        cluster=cluster,
        environment=environment,
        repository=repository,
        chart=chart,
        driver=driver,
    )


def _make_uow(graph: SimpleNamespace, deployments: list[Deployment]) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository([graph.cluster]),
        environments=FakeEnvironmentRepository([graph.environment]),
        helm_repositories=FakeHelmRepositoryRepository([graph.repository]),
        helm_charts=FakeHelmChartRepository([graph.chart]),
        application_driver_versions=FakeApplicationRepository(
            list(graph.driver.versions)
        ),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        application_drivers=FakeApplicationDriverRepository([graph.driver]),
        deployments=FakeDeploymentRepository(deployments),
    )


def _running_deployment(
    graph: SimpleNamespace,
    name: str,
    *,
    driver_version: ApplicationDriverVersion | None = None,
) -> Deployment:
    driver_version = driver_version or graph.driver.versions[0]
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=driver_version.id,
        environment_id=graph.environment.id,
        created_by_user_id=uuid4(),
        name=name,
    )
    for component in driver_version.component_configs:
        deployment.add_component(
            Component.create(name=component.name, config=component.config)
        )
    deployment.set_active_instance(
        _make_instance(deployment, environment_name="before")
    )
    deployment.set_status(DeploymentState.RUNNING)
    return deployment


async def _deploy(
    graph: SimpleNamespace,
    uow: FakeUnitOfWork,
    *,
    name: str,
    config: dict[str, Any] | None = None,
    deployment_id: UUID | None = None,
) -> Deployment:
    task = await deploy_application(
        driver_name=DRIVER_NAME,
        version="1.0.0",
        environment_id=graph.environment.id,
        uow=uow,
        created_by_user_id=uuid4(),
        deployment_config=config,
        deployment_name=name,
        deployment_id=deployment_id,
    )
    assert task is not None
    created = await uow.deployments.find(id=task.deployment_id)
    assert created is not None
    return created


async def test_deploy_stores_the_id_of_the_deployment_a_term_names(
    graph: SimpleNamespace,
) -> None:
    db = _running_deployment(graph, "db")
    uow = _make_uow(graph, [db])

    created = await _deploy(
        graph,
        uow,
        name="api",
        config=_scheduling({"deployment_name": "db", "components": ["primary"]}),
    )

    assert _stored_ref(created.config) == {
        "deployment_id": str(db.id),
        "components": ["primary"],
    }


async def test_deploy_term_that_names_the_new_deployment_stores_its_new_id(
    graph: SimpleNamespace, generated: list[Mapping[UUID, str] | None]
) -> None:
    uow = _make_uow(graph, [])
    chosen_id = uuid4()

    created = await _deploy(
        graph,
        uow,
        name="api",
        config=_scheduling({"deployment_name": "api"}),
        deployment_id=chosen_id,
    )

    assert created.id == chosen_id
    assert _stored_ref(created.config) == {"deployment_id": str(chosen_id)}
    assert generated == [{chosen_id: "api"}]


async def test_deploy_refuses_a_term_that_names_a_missing_deployment(
    graph: SimpleNamespace, prefect: MagicMock
) -> None:
    uow = _make_uow(graph, [])

    with pytest.raises(UnresolvableAffinityReferenceError) as exc:
        await _deploy(
            graph, uow, name="api", config=_scheduling({"deployment_name": "nope"})
        )

    assert exc.value.error_metadata == {
        "deployment_name": "nope",
        "path": "deployment.config.scheduling.pod_affinity.required[0]",
    }
    assert await uow.deployments.count() == 0
    assert uow.commit_count == 0
    prefect.run_action.assert_not_called()


async def test_deploy_binds_the_component_configs_copied_from_the_driver_version(
    graph: SimpleNamespace,
) -> None:
    db = _running_deployment(graph, "db")
    graph.driver.versions = [
        _driver_version(
            graph.driver,
            graph.chart,
            "1.0.0",
            {COMPONENT: _scheduling({"deployment_name": "db"})},
        )
    ]
    uow = _make_uow(graph, [db])

    created = await _deploy(graph, uow, name="api")

    [component] = created.components
    assert component.name == COMPONENT
    assert _stored_ref(component.config) == {"deployment_id": str(db.id)}
    # The driver version keeps the name it was loaded with.
    assert _stored_ref(graph.driver.versions[0].component_configs[0].config) == {
        "deployment_name": "db"
    }


async def test_update_deployment_rename_resolves_a_term_against_the_new_name(
    graph: SimpleNamespace,
) -> None:
    b = _running_deployment(graph, "b")
    uow = _make_uow(graph, [b])

    task = await update_deployment(
        deployment_id=b.id,
        uow=uow,
        deployment_name="b2",
        deployment_config=_scheduling({"deployment_name": "b2"}),
    )

    assert task is not None
    stored = await uow.deployments.find(id=b.id)
    assert stored is not None
    assert stored.name == "b2"
    assert _stored_ref(stored.config) == {"deployment_id": str(b.id)}


async def test_update_deployment_rename_refuses_a_term_that_names_the_old_name(
    graph: SimpleNamespace, prefect: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = _running_deployment(graph, "b")
    uow = _make_uow(graph, [b])
    save = AsyncMock()
    monkeypatch.setattr(uow.deployments, "save", save)

    with pytest.raises(UnresolvableAffinityReferenceError) as exc:
        await update_deployment(
            deployment_id=b.id,
            uow=uow,
            deployment_name="b2",
            deployment_config=_scheduling({"deployment_name": "b"}),
        )

    assert exc.value.error_metadata == {
        "deployment_name": "b",
        "path": "deployment.config.scheduling.pod_affinity.required[0]",
    }
    save.assert_not_called()
    assert uow.commit_count == 0
    prefect.run_action.assert_not_called()


async def test_update_deployment_version_stores_the_id_of_the_deployment_a_term_names(
    graph: SimpleNamespace,
) -> None:
    a = _running_deployment(graph, "a")
    b = _running_deployment(graph, "b")
    uow = _make_uow(graph, [a, b])

    task = await update_deployment_version(
        deployment_id=b.id,
        version="1.1.0",
        uow=uow,
        deployment_config=_scheduling({"deployment_name": "a"}),
    )

    assert task is not None
    stored = await uow.deployments.find(id=b.id)
    assert stored is not None
    assert _stored_ref(stored.config) == {"deployment_id": str(a.id)}


async def test_update_deployment_version_binds_the_component_configs_of_a_new_driver_version(
    graph: SimpleNamespace,
) -> None:
    v2 = _driver_version(
        graph.driver,
        graph.chart,
        "1.1.0",
        {COMPONENT: _scheduling({"deployment_name": "a"})},
    )
    graph.driver.versions = [graph.driver.versions[0], v2]
    a = _running_deployment(graph, "a")
    b = _running_deployment(graph, "b")
    uow = _make_uow(graph, [a, b])

    task = await update_deployment_version(
        deployment_id=b.id, version="1.0.0", uow=uow, driver_version_id=v2.id
    )

    assert task is not None
    stored = await uow.deployments.find(id=b.id)
    assert stored is not None
    assert stored.application_driver_version_id == v2.id
    [component] = stored.components
    assert _stored_ref(component.config) == {"deployment_id": str(a.id)}
