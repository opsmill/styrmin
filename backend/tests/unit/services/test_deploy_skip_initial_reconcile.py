"""Unit tests for the clone-counterpart deployment primitives (research D5/D8).

Two changes, both scoped to ``services/deployment.py``:

* ``deploy_application(skip_initial_reconcile=True)`` creates the deployment,
  its services and its active instance but dispatches **no** reconciliation,
  and starts the deployment in ``RESTORING`` rather than ``PENDING``.
* ``redeploy_for_environment_update`` refuses to redeploy a ``RESTORING``
  deployment, because a restore is about to delete and recreate that
  namespace wholesale.

``generate_instance_from_deployment`` (full context resolution) and
``apply_state`` (Prefect dispatch) are patched as imported by
``services.deployment`` — the same technique the environment-fanout tests use
— so these tests observe the branch under test rather than the context
resolver.
"""

from __future__ import annotations

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
    Deployment,
    DeploymentState,
    Instance,
    InstanceStatus,
    Task,
    TaskType,
)
from styrmin_backend.services import deployment as deployment_service
from styrmin_backend.services.deployment import (
    deploy_application,
    redeploy_for_environment_update,
)
from styrmin_backend.services.exceptions import ApplicationDriverNotFoundError
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


def _make_global_context(deployment_id: UUID) -> GlobalContext:
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="clone", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=f"styrmin-{deployment_id}",
            release_reference=f"styrmin-{deployment_id}",
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="test-chart",
                    version="0.1.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )


def _make_instance(deployment: Deployment) -> Instance:
    return Instance(
        id=uuid4(),
        name=f"instance-{uuid4().hex[:6]}",
        application_version=deployment.application_version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=_make_global_context(deployment.id),
    )


@pytest.fixture
def stub_reconcile(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Stub the context resolver and the Prefect dispatch boundary."""
    calls: dict[str, list] = {"generate": [], "apply_state": []}
    calls["release_reference"] = []

    async def _generate(
        *, deployment: Deployment, uow: object, release_reference: str | None = None
    ) -> Instance:
        calls["generate"].append(deployment.id)
        calls["release_reference"].append(release_reference)
        return _make_instance(deployment)

    async def _apply_state(
        *,
        deployment: Deployment,
        current_instance: Instance | None,
        uow: object,
        task_type: TaskType,
    ) -> Task:
        calls["apply_state"].append(deployment.id)
        return Task.create(type=task_type, deployment_id=deployment.id)

    monkeypatch.setattr(
        deployment_service, "generate_instance_from_deployment", _generate
    )
    monkeypatch.setattr(deployment_service, "apply_state", _apply_state)
    return calls


def _make_uow(
    *,
    cluster: Cluster,
    environment: Environment,
    driver: ApplicationDriver,
    driver_version: ApplicationDriverVersion,
    chart: HelmChart,
    repository: HelmRepository,
    deployments: list[Deployment] | None = None,
) -> FakeUnitOfWork:
    return FakeUnitOfWork(
        clusters=FakeClusterRepository([cluster]),
        environments=FakeEnvironmentRepository([environment]),
        helm_repositories=FakeHelmRepositoryRepository([repository]),
        helm_charts=FakeHelmChartRepository([chart]),
        application_driver_versions=FakeApplicationRepository([driver_version]),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        application_drivers=FakeApplicationDriverRepository([driver]),
        deployments=FakeDeploymentRepository(deployments or []),
    )


@pytest.fixture
def driver_graph() -> dict[str, object]:
    """A single-version driver bound to a chart, with no dedicated ingress."""
    cluster = Cluster(name="test-cluster", config={})
    environment = Environment(name="clone-env", cluster_id=cluster.id, config={})
    repository = HelmRepository(url="https://helm.example.com/test")
    chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="name: {{ app.name }}",
        repository_id=repository.id,
    )
    driver = ApplicationDriver(name=DRIVER_NAME)
    driver_version = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        default_version="1.0.0",
        source_repository="https://example.com/driver",
        helm_chart_id=chart.id,
    )
    driver_version.component_configs = []
    driver.versions = [driver_version]
    return {
        "cluster": cluster,
        "environment": environment,
        "repository": repository,
        "chart": chart,
        "driver": driver,
        "driver_version": driver_version,
    }


class TestDeployApplicationSkipInitialReconcile:
    @pytest.mark.anyio
    async def test_skip_creates_a_restoring_deployment_without_dispatching(
        self, driver_graph: dict, stub_reconcile: dict[str, list]
    ) -> None:
        uow = _make_uow(**driver_graph)  # type: ignore[arg-type]
        environment = driver_graph["environment"]

        result = await deploy_application(
            driver_name=DRIVER_NAME,
            version="1.0.0",
            environment_id=environment.id,  # type: ignore[union-attr]
            uow=uow,
            created_by_user_id=uuid4(),
            deployment_name="counterpart",
            skip_initial_reconcile=True,
        )

        # No Task is dispatched, and the caller is told so explicitly.
        assert result is None
        assert stub_reconcile["apply_state"] == []
        assert uow.tasks.models == []

        stored = await uow.deployments.get_by_name(
            "counterpart",
            environment.id,  # type: ignore[union-attr]
        )
        assert stored is not None
        # RESTORING, not PENDING: the existing restoring-deployment guards
        # protect the counterpart until its cross-target restore lands (D8).
        assert stored.status == DeploymentState.RESTORING
        # The instance context the recovery step needs still exists.
        assert stored.active_instance is not None
        assert stub_reconcile["generate"] == [stored.id]
        assert uow.committed is True

    @pytest.mark.anyio
    async def test_default_mode_still_dispatches_a_task(
        self, driver_graph: dict, stub_reconcile: dict[str, list]
    ) -> None:
        """Regression: omitting the flag reproduces the shipped behaviour."""
        uow = _make_uow(**driver_graph)  # type: ignore[arg-type]
        environment = driver_graph["environment"]

        result = await deploy_application(
            driver_name=DRIVER_NAME,
            version="1.0.0",
            environment_id=environment.id,  # type: ignore[union-attr]
            uow=uow,
            created_by_user_id=uuid4(),
            deployment_name="ordinary",
        )

        assert result is not None
        stored = await uow.deployments.get_by_name(
            "ordinary",
            environment.id,  # type: ignore[union-attr]
        )
        assert stored is not None
        assert stored.status == DeploymentState.PENDING
        assert stub_reconcile["apply_state"] == [stored.id]

    @pytest.mark.anyio
    async def test_skip_still_creates_service_rows(
        self, driver_graph: dict, stub_reconcile: dict[str, list]
    ) -> None:
        """FR-005/FR-007: counterpart service rows are required by the restore.

        The recovery step builds the counterpart's CR body from its instance
        context, and sibling FQDNs resolve through the deployed-service rows —
        so skipping the reconcile must not skip service creation.
        """
        driver_version = driver_graph["driver_version"]
        driver_version.services = [  # type: ignore[union-attr]
            {
                "name": "api",
                "kind": "http",
                "scope": "internal",
                "port": 8080,
                "component": "server",
            }
        ]
        uow = _make_uow(**driver_graph)  # type: ignore[arg-type]
        environment = driver_graph["environment"]

        await deploy_application(
            driver_name=DRIVER_NAME,
            version="1.0.0",
            environment_id=environment.id,  # type: ignore[union-attr]
            uow=uow,
            created_by_user_id=uuid4(),
            deployment_name="counterpart-with-services",
            service_name_overrides={"api": "renamed-api"},
            skip_initial_reconcile=True,
        )

        stored = await uow.deployments.get_by_name(
            "counterpart-with-services",
            environment.id,  # type: ignore[union-attr]
        )
        assert stored is not None
        services = await uow.deployed_services.get_by_deployment_id(stored.id)
        assert [service.resolved_name for service in services] == ["renamed-api"]

    @pytest.mark.anyio
    async def test_skip_still_ensures_the_ingress_controller(
        self, driver_graph: dict, stub_reconcile: dict[str, list]
    ) -> None:
        """research D5: the internal ingress deployment is never in a capture.

        It therefore still has to be reconciled for the counterpart's
        environment. Proven here by the environment declaring
        ``dedicated_ingress`` with the internal driver absent: if
        ``_ensure_ingress_controller`` were skipped along with the reconcile,
        no error would surface.
        """
        environment = driver_graph["environment"]
        environment.config = {  # type: ignore[union-attr]
            "dedicated_ingress": {"implementation": "traefik", "type": "ingress"}
        }
        uow = _make_uow(**driver_graph)  # type: ignore[arg-type]

        with pytest.raises(ApplicationDriverNotFoundError, match="Internal driver"):
            await deploy_application(
                driver_name=DRIVER_NAME,
                version="1.0.0",
                environment_id=environment.id,  # type: ignore[union-attr]
                uow=uow,
                created_by_user_id=uuid4(),
                deployment_name="counterpart-needs-ingress",
                skip_initial_reconcile=True,
            )


class TestRedeployForEnvironmentUpdateSkipsRestoring:
    @pytest.mark.anyio
    async def test_restoring_deployment_is_skipped(
        self, stub_reconcile: dict[str, list]
    ) -> None:
        deployment = Deployment.create(
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=uuid4(),
            created_by_user_id=uuid4(),
            name="restoring-deployment",
        )
        deployment.set_status(DeploymentState.RESTORING)
        uow = FakeUnitOfWork(
            clusters=FakeClusterRepository(),
            environments=FakeEnvironmentRepository(),
            helm_repositories=FakeHelmRepositoryRepository(),
            helm_charts=FakeHelmChartRepository(),
            application_driver_versions=FakeApplicationRepository(),
            instances=FakeApplicationInstanceRepository(),
            actions=FakeActionRepository(),
            tasks=FakeTaskRepository(),
            deployments=FakeDeploymentRepository([deployment]),
        )

        result = await redeploy_for_environment_update(deployment, uow)

        assert result is None
        # No instance regenerated, no reconciliation dispatched, no Task row.
        assert stub_reconcile["generate"] == []
        assert stub_reconcile["apply_state"] == []
        assert uow.tasks.models == []
        # The deployment is left exactly as found — in particular it is NOT
        # moved to DEPLOYING, which would race the in-flight restore.
        assert deployment.status == DeploymentState.RESTORING

    @pytest.mark.anyio
    async def test_running_deployment_is_still_redeployed(
        self, stub_reconcile: dict[str, list]
    ) -> None:
        """Regression: every non-RESTORING deployment behaves as before."""
        deployment = Deployment.create(
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=uuid4(),
            created_by_user_id=uuid4(),
            name="running-deployment",
        )
        deployment.set_status(DeploymentState.RUNNING)
        uow = FakeUnitOfWork(
            clusters=FakeClusterRepository(),
            environments=FakeEnvironmentRepository(),
            helm_repositories=FakeHelmRepositoryRepository(),
            helm_charts=FakeHelmChartRepository(),
            application_driver_versions=FakeApplicationRepository(),
            instances=FakeApplicationInstanceRepository(),
            actions=FakeActionRepository(),
            tasks=FakeTaskRepository(),
            deployments=FakeDeploymentRepository([deployment]),
        )

        result = await redeploy_for_environment_update(deployment, uow)

        assert result is not None
        assert stub_reconcile["apply_state"] == [deployment.id]
        assert deployment.status == DeploymentState.DEPLOYING
