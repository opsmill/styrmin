"""Unit tests for cross-namespace service alias computation."""

from uuid import UUID, uuid4

from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.agent.tasks.service_aliases import (
    build_external_name_service,
    compute_service_aliases,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo


def _make_context(
    deployment_id: UUID,
    deployed_services: list[dict],
) -> GlobalContext:
    """Build a minimal GlobalContext for testing."""
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
    )


class TestBuildExternalNameService:
    def test_manifest_structure(self) -> None:
        manifest = build_external_name_service(
            resolved_name="intent",
            target_namespace="styrmin-aaa",
            owner_namespace="styrmin-bbb",
        )
        assert manifest["apiVersion"] == "v1"
        assert manifest["kind"] == "Service"
        assert manifest["metadata"]["name"] == "intent"
        assert manifest["metadata"]["namespace"] == "styrmin-bbb"
        assert manifest["spec"]["type"] == "ExternalName"
        assert (
            manifest["spec"]["externalName"] == "intent.styrmin-aaa.svc.cluster.local"
        )

    def test_labels(self) -> None:
        manifest = build_external_name_service(
            resolved_name="web",
            target_namespace="styrmin-aaa",
            owner_namespace="styrmin-bbb",
        )
        labels = manifest["metadata"]["labels"]
        assert labels["app.kubernetes.io/managed-by"] == "styrmin"
        assert labels["styrmin.io/service-alias"] == "true"


class TestComputeServiceAliases:
    def test_two_deployments_cross_aliases(self) -> None:
        """Two deployments should create aliases in each other's namespace."""
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        ns_b = get_kubernetes_reference(dep_b)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "executor",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # Should have 2 aliases:
        # 1. "executor" in ns_a (pointing to ns_b) — other service in our ns
        # 2. "intent" in ns_b (pointing to ns_a) — our service in other ns
        assert len(aliases) == 2

        names_and_namespaces = {
            (a["metadata"]["name"], a["metadata"]["namespace"]) for a in aliases
        }
        assert ("executor", ns_a) in names_and_namespaces
        assert ("intent", ns_b) in names_and_namespaces

    def test_single_deployment_no_aliases(self) -> None:
        """A single deployment alone should produce no aliases."""
        dep_a = uuid4()

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
        )

        aliases = compute_service_aliases(context)
        assert aliases == []

    def test_skips_self_aliases(self) -> None:
        """Should not create an alias for a service in its own namespace."""
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "executor",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # No alias should point to ns_a with name "intent" in ns_a (self)
        for alias in aliases:
            if alias["metadata"]["name"] == "intent":
                assert alias["metadata"]["namespace"] != ns_a

    def test_multiple_services_per_deployment(self) -> None:
        """Multiple services per deployment generate aliases for each."""
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        ns_b = get_kubernetes_reference(dep_b)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "web",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "api",
                    "port": 8080,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "cache",
                    "port": 6379,
                    "kind": "tcp",
                    "deployment_id": str(dep_b),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # 3 aliases:
        # "cache" in ns_a (from dep_b)
        # "web" in ns_b (from dep_a)
        # "api" in ns_b (from dep_a)
        assert len(aliases) == 3

        names_and_namespaces = {
            (a["metadata"]["name"], a["metadata"]["namespace"]) for a in aliases
        }
        assert ("cache", ns_a) in names_and_namespaces
        assert ("web", ns_b) in names_and_namespaces
        assert ("api", ns_b) in names_and_namespaces

    def test_three_deployments(self) -> None:
        """Three deployments: our services aliased into both other namespaces."""
        dep_a = uuid4()
        dep_b = uuid4()
        dep_c = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        ns_b = get_kubernetes_reference(dep_b)
        ns_c = get_kubernetes_reference(dep_c)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "svc-a",
                    "port": 80,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "svc-b",
                    "port": 80,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                },
                {
                    "resolved_name": "svc-c",
                    "port": 80,
                    "kind": "http",
                    "deployment_id": str(dep_c),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # In ns_a: "svc-b" and "svc-c" (other services)
        # In ns_b: "svc-a" (our service)
        # In ns_c: "svc-a" (our service)
        assert len(aliases) == 4

        names_and_namespaces = {
            (a["metadata"]["name"], a["metadata"]["namespace"]) for a in aliases
        }
        assert ("svc-b", ns_a) in names_and_namespaces
        assert ("svc-c", ns_a) in names_and_namespaces
        assert ("svc-a", ns_b) in names_and_namespaces
        assert ("svc-a", ns_c) in names_and_namespaces

    def test_empty_deployed_services(self) -> None:
        """No deployed services means no aliases."""
        dep_a = uuid4()
        context = _make_context(deployment_id=dep_a, deployed_services=[])
        aliases = compute_service_aliases(context)
        assert aliases == []

    def test_missing_deployment_id_skipped(self) -> None:
        """Services without deployment_id are safely skipped."""
        dep_a = uuid4()
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "orphan",
                    "port": 80,
                    "kind": "http",
                },
            ],
        )
        aliases = compute_service_aliases(context)
        assert aliases == []
