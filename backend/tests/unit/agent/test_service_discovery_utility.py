"""Unit tests for the ServiceDiscoveryUtility."""

from uuid import uuid4

from styrmin_backend.agent.service.kubernetes.resources.utilities.service_discovery import (
    ServiceDiscoveryUtility,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
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


def _make_components(
    *names_and_labels: tuple[str, dict[str, str]],
) -> ComponentsContext:
    """Build a ComponentsContext from (name, label_dict) pairs."""
    return ComponentsContext(
        root={
            name: ComponentContext(
                name=name,
                enabled=True,
                config=ArbitrarySectionModel(
                    identifier=Identifier(label=LabelIdentifier(root=labels)),
                ),
            )
            for name, labels in names_and_labels
        }
    )


def _make_context(
    deployed_services: list[dict],
    components: ComponentsContext | None = None,
    deployment_id=None,
) -> GlobalContext:
    """Build a minimal GlobalContext for testing."""
    deployment_id = deployment_id or uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
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
                repository=RepositoryInfo(
                    id=uuid4(),
                    url="https://example.com/charts",
                ),
            ),
        ),
        deployed_services=deployed_services,
        components=components,
    )


class TestServiceDiscoveryUtility:
    def setup_method(self) -> None:
        self.utility = ServiceDiscoveryUtility()

    def test_kind(self) -> None:
        assert self.utility.kind == "service-discovery"

    def test_no_post_rendering_patches(self) -> None:
        context = _make_context(deployed_services=[])
        patches = self.utility.build_app_post_rendering_patches(context, "ref")
        assert patches == []

    def test_no_extra_spec(self) -> None:
        context = _make_context(deployed_services=[])
        specs = self.utility.build_extra_spec(context)
        assert specs == []

    def test_builds_clusterip_for_own_services(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("server", {"app.kubernetes.io/name": "simple-app"}),
        )

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                    "component": "server",
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)

        assert len(resources) == 1
        svc = resources[0]
        assert svc["apiVersion"] == "v1"
        assert svc["kind"] == "Service"
        assert svc["metadata"]["name"] == "intent"
        assert svc["metadata"]["namespace"] == ns_a
        assert svc["spec"]["type"] == "ClusterIP"
        assert svc["spec"]["selector"] == {"app.kubernetes.io/name": "simple-app"}
        assert svc["spec"]["ports"] == [
            {"port": 8000, "targetPort": 8000, "protocol": "TCP"}
        ]

    def test_skips_other_deployments_services(self) -> None:
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("server", {"app.kubernetes.io/name": "simple-app"}),
        )

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "executor",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                    "component": "server",
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)
        assert resources == []

    def test_skips_when_components_none(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                    "component": "server",
                },
            ],
            components=None,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)
        assert resources == []

    def test_skips_unknown_component(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("database", {"app.kubernetes.io/name": "postgresql"}),
        )

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                    "component": "server",
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)
        assert resources == []

    def test_skips_missing_component_field(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("server", {"app.kubernetes.io/name": "simple-app"}),
        )

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)
        assert resources == []

    def test_udp_protocol(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(("dns", {"app": "dns"}))

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "dns",
                    "port": 53,
                    "kind": "udp",
                    "deployment_id": str(dep_a),
                    "component": "dns",
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)
        assert resources[0]["spec"]["ports"][0]["protocol"] == "UDP"

    def test_tcp_protocol_for_https(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(("api", {"app": "api"}))

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "api",
                    "port": 443,
                    "kind": "https",
                    "deployment_id": str(dep_a),
                    "component": "api",
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)
        assert resources[0]["spec"]["ports"][0]["protocol"] == "TCP"

    def test_multiple_services_different_components(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("server", {"app.kubernetes.io/name": "simple-app"}),
            ("cache", {"app.kubernetes.io/name": "redis"}),
        )

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "web",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                    "component": "server",
                },
                {
                    "resolved_name": "redis",
                    "port": 6379,
                    "kind": "tcp",
                    "deployment_id": str(dep_a),
                    "component": "cache",
                },
            ],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)

        assert len(resources) == 2
        by_name = {r["metadata"]["name"]: r for r in resources}

        assert by_name["web"]["spec"]["selector"] == {
            "app.kubernetes.io/name": "simple-app"
        }
        assert by_name["redis"]["spec"]["selector"] == {
            "app.kubernetes.io/name": "redis"
        }
        assert by_name["redis"]["spec"]["ports"][0]["port"] == 6379
