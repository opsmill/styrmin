"""Tests for UtilityResourceBuilder (T011) and ApplicationHelmReleaseBuilder integration (T019)."""

from uuid import uuid4

import pytest

from styrmin_backend.agent.service.kubernetes.resources.builders.utility import (
    UtilityResourceBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.ingress import (
    IngressUtility,
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
    DedicatedIngressConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo


@pytest.fixture
def global_context() -> GlobalContext:
    return GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(
                ingress_class="traefik",
                runtime_class="gvisor",
                dedicated_ingress=DedicatedIngressConfig(),
                fqdn_suffix="test.styrmin.com",
            ),
        ),
        environment=EnvironmentContext(
            name="test",
            config=EnvironmentConfig(
                ip_whitelist=["10.0.0.0/8"],
            ),
        ),
        deployment=DeploymentContext(
            config=DeploymentConfig(),
        ),
        instance=InstanceContext(
            config=ResolvedConfig(
                ip_whitelist=["10.0.0.0/8"],
                ingress_class="traefik",
                runtime_class="gvisor",
                dedicated_ingress=DedicatedIngressConfig(),
                fqdn_suffix="test.styrmin.com",
            ),
            deployment_id=uuid4(),
            namespace="test-ns",
            release_reference="test-rel",
        ),
        app=ApplicationContext(
            name="testapp",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="testapp", version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(
                    id=uuid4(), url="oci://charts.example.com/test"
                ),
            ),
        ),
    )


class TestUtilityResourceBuilder:
    """T011: Test UtilityResourceBuilder.build()."""

    def test_build_returns_list(self, global_context: GlobalContext) -> None:
        builder = UtilityResourceBuilder(context=global_context)
        utility = IngressUtility()
        resources = builder.build(
            utility=utility, release_reference="test-rel", namespace="test-ns"
        )
        assert isinstance(resources, list)
        assert len(resources) > 0

    def test_build_adds_ownership_labels(self, global_context: GlobalContext) -> None:
        builder = UtilityResourceBuilder(context=global_context)
        utility = IngressUtility()
        resources = builder.build(
            utility=utility, release_reference="test-rel", namespace="test-ns"
        )
        for resource in resources:
            labels = resource["metadata"]["labels"]
            assert labels["app.kubernetes.io/managed-by"] == "styrmin"
            assert labels["styrmin.io/utility-kind"] == "ingress"
            assert labels["styrmin.io/release-reference"] == "test-rel"

    def test_build_delegates_to_utility(self, global_context: GlobalContext) -> None:
        builder = UtilityResourceBuilder(context=global_context)
        utility = IngressUtility()
        resources = builder.build(
            utility=utility, release_reference="rel", namespace="ns"
        )
        # Should contain middleware, secret, and network policy resources
        kinds = {r["kind"] for r in resources}
        assert "Middleware" in kinds
        assert "Secret" in kinds
        assert "NetworkPolicy" in kinds
