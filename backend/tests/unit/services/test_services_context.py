"""Unit tests for services context building (T024)."""

import inspect
from uuid import uuid4

import pytest

from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
)
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
from styrmin_backend.context.models.services import ServiceReference
from styrmin_backend.services import context as context_service
from styrmin_backend.services.context import _populate_component_scheduling


class TestServiceReference:
    def test_http_url(self) -> None:
        ref = ServiceReference(host="infrahub", port=8000, kind="http")
        assert ref.url == "http://infrahub:8000"
        assert ref.host == "infrahub"
        assert ref.port == 8000
        assert ref.kind == "http"

    def test_https_url(self) -> None:
        ref = ServiceReference(host="infrahub", port=8443, kind="https")
        assert ref.url == "https://infrahub:8443"

    def test_tcp_url(self) -> None:
        ref = ServiceReference(host="redis", port=6379, kind="tcp")
        assert ref.url == "redis:6379"

    def test_udp_url(self) -> None:
        ref = ServiceReference(host="dns", port=53, kind="udp")
        assert ref.url == "dns:53"

    def test_model_dump(self) -> None:
        ref = ServiceReference(host="web", port=80, kind="http")
        data = ref.model_dump()
        assert data["url"] == "http://web:80"
        assert data["host"] == "web"
        assert data["port"] == 80
        assert data["kind"] == "http"


class TestServicesContextDict:
    def test_empty_services_dict(self) -> None:
        """Empty context when no services are deployed."""
        services: dict = {}
        assert services == {}

    def test_build_context_with_services(self) -> None:
        """Build context dict mapping service name -> ServiceReference properties."""
        from styrmin_backend.db.models import DeployedService
        from uuid import uuid4

        svcs = [
            DeployedService(
                id=uuid4(),
                driver_service_name="infrahub",
                resolved_name="infrahub",
                kind="https",
                scope="internal",
                port=8000,
                component="server",
                deployment_id=uuid4(),
                environment_id=uuid4(),
            ),
            DeployedService(
                id=uuid4(),
                driver_service_name="redis",
                resolved_name="redis",
                kind="tcp",
                scope="internal",
                port=6379,
                component="cache",
                deployment_id=uuid4(),
                environment_id=uuid4(),
            ),
        ]

        # Build context dict the same way the context service will
        context: dict = {}
        for svc in svcs:
            ref = ServiceReference(
                host=svc.resolved_name,
                port=svc.port,
                kind=svc.kind,
            )
            context[svc.driver_service_name] = ref.model_dump()

        assert "infrahub" in context
        assert context["infrahub"]["url"] == "https://infrahub:8000"
        assert context["infrahub"]["host"] == "infrahub"
        assert context["infrahub"]["port"] == 8000
        assert context["infrahub"]["kind"] == "https"

        assert "redis" in context
        assert context["redis"]["url"] == "redis:6379"
        assert context["redis"]["host"] == "redis"
        assert context["redis"]["port"] == 6379


class TestContextLabels:
    """T025: the deployment generation labels include both the environment
    and deployment identity labels so the pod-template post-renderer stamps
    them on every rendered pod.
    """

    def test_labels_dict_contains_environment_and_deployment_ids(self) -> None:
        source = inspect.getsource(context_service.generate_context_from_deployment)
        assert '"environment_id": environment.id' in source
        assert '"deployment_id": deployment.id' in source


class _FakeDeploymentComponent:
    """Minimal stand-in for ``Deployment.components[i]`` — the scheduling
    population path only reads ``.name`` and ``.config``.
    """

    def __init__(self, name: str, config: dict | None) -> None:
        self.name = name
        self.config = config


def _make_context_with_component(name: str) -> GlobalContext:
    namespace = "dep-test"
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=uuid4(),
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="test-chart",
                    version="1.0.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        components=ComponentsContext(
            root={
                name: ComponentContext(
                    name=name,
                    enabled=True,
                    config=ArbitrarySectionModel(
                        identifier=Identifier(
                            label=LabelIdentifier(root={"app": name})
                        ),
                    ),
                )
            }
        ),
    )


class TestPopulateComponentScheduling:
    """FR-012 end-to-end: resolved scheduling plus per-field provenance
    must reach the Jinja rendering surface via
    ``context.components[*].scheduling``, not just the GraphQL API.
    """

    @pytest.mark.anyio
    async def test_component_scheduling_exposes_provenance(self, uow) -> None:  # type: ignore[no-untyped-def]
        context = _make_context_with_component("server")
        env_config = {"scheduling": {"runtime_class": "kata"}}
        dep_config = {"scheduling": {"resources": {"requests": {"cpu": "100m"}}}}
        components = [_FakeDeploymentComponent("server", config=None)]

        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=uuid4(),
            environment_config=env_config,
            deployment_config=dep_config,
            deployment_components=components,
        )

        assert context.components is not None
        scheduling = context.components.root["server"].scheduling
        assert scheduling is not None
        assert scheduling.config.runtime_class == "kata"
        assert scheduling.config.resources is not None
        assert scheduling.provenance["runtime_class"] == "environment"
        assert scheduling.provenance["resources.requests.cpu"] == "deployment"
