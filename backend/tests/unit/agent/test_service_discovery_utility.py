"""Unit tests for the ServiceDiscoveryUtility."""

from uuid import uuid4

from styrmin_backend.agent.service.kubernetes.resources.utilities.service_discovery import (
    ServiceDiscoveryUtility,
    environment_policy_name,
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
    labels: dict | None = None,
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
        labels=labels or {},
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


def _service(
    name: str, port: int, component: str, deployment_id, kind: str = "http"
) -> dict:
    return {
        "resolved_name": name,
        "port": port,
        "kind": kind,
        "deployment_id": str(deployment_id),
        "component": component,
    }


def _policies(resources: list[dict]) -> dict[str, dict]:
    return {r["metadata"]["name"]: r for r in resources if r["kind"] == "NetworkPolicy"}


class TestEnvironmentPolicies:
    """#557: the other deployments of the environment reach the declared services only."""

    def setup_method(self) -> None:
        self.utility = ServiceDiscoveryUtility()

    def test_one_policy_per_component_with_a_service(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("server", {"service": "infrahub-server"}),
            ("task-manager", {"app.kubernetes.io/name": "prefect-server"}),
            ("database", {"infrahub/service": "database"}),
        )
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                _service("infrahub", 8000, "server", dep_a),
                _service("task-manager", 4200, "task-manager", dep_a),
            ],
            components=components,
            labels={"environment_id": "env-1"},
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)

        policies = _policies(resources)
        assert set(policies) == {
            "allow-environment-to-server",
            "allow-environment-to-task-manager",
        }
        server = policies["allow-environment-to-server"]
        assert server["apiVersion"] == "networking.k8s.io/v1"
        assert server["metadata"]["namespace"] == ns_a
        assert server["spec"] == {
            "podSelector": {"matchLabels": {"service": "infrahub-server"}},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"styrmin/environment_id": "env-1"}
                            }
                        }
                    ],
                    "ports": [{"port": 8000, "protocol": "TCP"}],
                }
            ],
        }

    def test_component_without_a_service_gets_no_policy(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(
            ("server", {"service": "infrahub-server"}),
            ("database", {"infrahub/service": "database"}),
        )
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[_service("infrahub", 8000, "server", dep_a)],
            components=components,
            labels={"environment_id": "env-1"},
        )

        policies = _policies(self.utility.build_resources(context, ns_a, ns_a))

        assert "allow-environment-to-database" not in policies

    def test_services_of_one_component_share_a_policy(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(("server", {"app": "web"}))
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                _service("web", 8000, "server", dep_a),
                _service("metrics", 9090, "server", dep_a),
                _service("web-again", 8000, "server", dep_a),
                _service("dns", 53, "server", dep_a, kind="udp"),
            ],
            components=components,
            labels={"environment_id": "env-1"},
        )

        policies = _policies(self.utility.build_resources(context, ns_a, ns_a))

        assert list(policies) == ["allow-environment-to-server"]
        assert policies["allow-environment-to-server"]["spec"]["ingress"][0][
            "ports"
        ] == [
            {"port": 8000, "protocol": "TCP"},
            {"port": 9090, "protocol": "TCP"},
            {"port": 53, "protocol": "UDP"},
        ]

    def test_other_deployments_services_get_no_policy(self) -> None:
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(("server", {"app": "web"}))
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[_service("peer", 8000, "server", dep_b)],
            components=components,
            labels={"environment_id": "env-1"},
        )

        assert self.utility.build_resources(context, ns_a, ns_a) == []

    def test_no_policy_without_environment_id(self) -> None:
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(("server", {"app": "web"}))
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[_service("web", 8000, "server", dep_a)],
            components=components,
        )

        resources = self.utility.build_resources(context, ns_a, ns_a)

        assert [r["kind"] for r in resources] == ["Service"]

    def test_policy_named_after_component_not_service_name(self) -> None:
        """A service-name override changes the Service name, not the policy name (ADR-073)."""
        dep_a = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        components = _make_components(("app", {"styrmin/component": "app"}))
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[_service("portal", 8080, "app", dep_a)],
            components=components,
            labels={"environment_id": "env-1"},
        )

        policies = _policies(self.utility.build_resources(context, ns_a, ns_a))

        assert list(policies) == ["allow-environment-to-app"]

    def test_policy_name_is_a_valid_kubernetes_name(self) -> None:
        assert environment_policy_name("Task_Worker") == (
            "allow-environment-to-task-worker"
        )
