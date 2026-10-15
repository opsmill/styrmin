"""Tests for native utility resource generation (IngressUtility.build_resources).

Covers T008 (Middleware CRDs), T009 (Secret), T010 (NetworkPolicies), T018 (post-rendering patches),
and T022 (extensibility).
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    IngressClassNameRemovalPatch,
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import PostRenderers
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
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
    """Build a minimal GlobalContext for testing utility resource generation."""
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
                ip_whitelist=["10.0.0.0/8", "192.168.1.0/24"],
            ),
        ),
        deployment=DeploymentContext(
            config=DeploymentConfig(),
        ),
        instance=InstanceContext(
            config=ResolvedConfig(
                ip_whitelist=["10.0.0.0/8", "192.168.1.0/24"],
                ingress_class="traefik",
                runtime_class="gvisor",
                dedicated_ingress=DedicatedIngressConfig(),
                fqdn_suffix="test.styrmin.com",
            ),
            deployment_id=uuid4(),
            namespace="test-namespace",
            release_reference="test-release",
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


@pytest.fixture
def ingress_utility() -> IngressUtility:
    return IngressUtility()


RELEASE_REF = "test-release"
NAMESPACE = "test-namespace"


class TestIngressUtilityBuildResources:
    """T008-T010: Test IngressUtility.build_resources() generates correct K8s manifests."""

    def test_returns_list_of_dicts(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        assert isinstance(resources, list)
        assert all(isinstance(r, dict) for r in resources)

    # --- T008: Middleware CRD generation ---

    def test_generates_acl_middleware(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        acl_middlewares = [
            r
            for r in resources
            if r["kind"] == "Middleware" and "acl" in r["metadata"]["name"]
        ]
        assert len(acl_middlewares) == 1
        acl = acl_middlewares[0]
        assert acl["apiVersion"] == "traefik.io/v1alpha1"
        assert acl["metadata"]["name"] == "acl"
        assert acl["metadata"]["namespace"] == NAMESPACE
        assert "ipAllowList" in acl["spec"]
        assert acl["spec"]["ipAllowList"]["sourceRange"] == [
            "10.0.0.0/8",
            "192.168.1.0/24",
        ]
        assert acl["spec"]["ipAllowList"]["ipStrategy"]["depth"] == 1

    def test_generates_auth_middleware(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        auth_middlewares = [
            r
            for r in resources
            if r["kind"] == "Middleware" and "auth" in r["metadata"]["name"]
        ]
        assert len(auth_middlewares) == 1
        auth = auth_middlewares[0]
        assert auth["apiVersion"] == "traefik.io/v1alpha1"
        assert auth["metadata"]["name"] == "auth"
        assert auth["metadata"]["namespace"] == NAMESPACE
        assert auth["spec"]["basicAuth"]["secret"] == "ingress-auth"
        assert auth["spec"]["basicAuth"]["removeHeader"] is True

    # --- T009: Secret generation ---

    def test_generates_ingress_auth_secret(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        secrets = [r for r in resources if r["kind"] == "Secret"]
        assert len(secrets) == 1
        secret = secrets[0]
        assert secret["apiVersion"] == "v1"
        assert secret["metadata"]["name"] == "ingress-auth"
        assert secret["metadata"]["namespace"] == NAMESPACE
        assert secret["type"] == "kubernetes.io/basic-auth"
        assert "username" in secret["data"]
        assert "password" in secret["data"]

    # --- T010: NetworkPolicy generation ---

    def test_generates_five_network_policies(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        netpols = [r for r in resources if r["kind"] == "NetworkPolicy"]
        assert len(netpols) == 6

    def test_generates_default_deny_egress(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        netpol = _find_resource(resources, "NetworkPolicy", "default-deny-egress")
        assert netpol is not None
        assert netpol["apiVersion"] == "networking.k8s.io/v1"
        assert netpol["spec"]["policyTypes"] == ["Egress"]
        assert netpol["spec"]["podSelector"] == {}

    def test_generates_default_deny_ingress(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        netpol = _find_resource(resources, "NetworkPolicy", "default-deny-ingress")
        assert netpol is not None
        assert netpol["spec"]["policyTypes"] == ["Ingress"]

    def test_generates_traefik_egress_policy(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        netpol = _find_resource(resources, "NetworkPolicy", "traefik-netpolicy-egress")
        assert netpol is not None
        assert netpol["spec"]["policyTypes"] == ["Egress"]

    def test_generates_prefect_egress_policy(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        netpol = _find_resource(resources, "NetworkPolicy", "prefect-netpolicy-egress")
        assert netpol is not None
        assert netpol["spec"]["policyTypes"] == ["Egress"]

    def test_generates_infrahub_egress_policy(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        netpol = _find_resource(resources, "NetworkPolicy", "infrahub-netpolicy-egress")
        assert netpol is not None
        assert netpol["spec"]["policyTypes"] == ["Egress"]

    def test_all_resources_have_namespace(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        for resource in resources:
            assert resource["metadata"]["namespace"] == NAMESPACE

    def test_resource_names_use_bare_template_names(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        for resource in resources:
            name = resource["metadata"]["name"]
            assert not name.startswith(f"{RELEASE_REF}-"), (
                f"Resource {name} should not be prefixed with release reference"
            )

    def test_total_resource_count(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        """2 middlewares + 1 secret + 6 network policies = 9 resources."""
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        assert len(resources) == 9

    @pytest.mark.parametrize("ip_whitelist", [None, []])
    def test_ingress_utility_resources_omits_acl_middleware_when_ip_whitelist_unset(
        self,
        ingress_utility: IngressUtility,
        global_context: GlobalContext,
        ip_whitelist: list[str] | None,
    ) -> None:
        """T009: When ip_whitelist is None or empty, the acl Middleware is not
        rendered, while the other resources (auth Middleware, Secret,
        NetworkPolicies) remain present."""
        global_context.instance.config.ip_whitelist = ip_whitelist
        resources = ingress_utility.build_resources(
            global_context, RELEASE_REF, NAMESPACE
        )
        acl_middlewares = [
            r
            for r in resources
            if r["kind"] == "Middleware" and r["metadata"]["name"] == "acl"
        ]
        assert acl_middlewares == []
        # Sanity-check that the other resources still render so we know the
        # gating is targeted, not a wholesale skip of the utility.
        auth_middlewares = [
            r
            for r in resources
            if r["kind"] == "Middleware" and r["metadata"]["name"] == "auth"
        ]
        assert len(auth_middlewares) == 1
        secrets = [r for r in resources if r["kind"] == "Secret"]
        assert len(secrets) == 1
        netpols = [r for r in resources if r["kind"] == "NetworkPolicy"]
        assert len(netpols) == 6


class TestIngressUtilityPostRenderingPatches:
    """T018: Test build_app_post_rendering_patches() produces correct TargetPatch list."""

    def test_returns_target_patches(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        assert isinstance(patches, list)
        assert all(isinstance(p, TargetPatch) for p in patches)

    def test_includes_traefik_entrypoints_annotation(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        # The annotation patch should contain traefik entrypoints
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        assert len(annotation_patches) >= 1
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert (
            annotations["traefik.ingress.kubernetes.io/router.entrypoints"]
            == "web,websecure"
        )

    def test_includes_external_dns_hostname(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert annotations["external-dns.alpha.kubernetes.io/hostname"] == (
            f"{RELEASE_REF}-testapp.test.styrmin.com"
        )

    def test_includes_cloudflare_proxied(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert (
            annotations["external-dns.alpha.kubernetes.io/cloudflare-proxied"] == "true"
        )

    def test_raises_without_fqdn_suffix(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        global_context.instance.config.fqdn_suffix = None
        with pytest.raises(ValueError, match="FQDN suffix is required"):
            ingress_utility.build_app_post_rendering_patches(
                global_context, RELEASE_REF
            )

    def test_ingress_utility_app_patches_includes_acl_annotation(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        """T002: When ip_whitelist is non-empty, the AnnotationPatch carries the
        router.middlewares annotation pointing at <namespace>-acl@kubernetescrd
        where <namespace> = styrmin-<deployment_id> (the deployment's own namespace,
        not the release reference)."""
        global_context.instance.config.ip_whitelist = ["10.0.0.0/8"]
        deployment_id = global_context.instance.deployment_id
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        assert len(annotation_patches) == 1
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert (
            annotations["traefik.ingress.kubernetes.io/router.middlewares"]
            == f"styrmin-{deployment_id}-acl@kubernetescrd"
        )

    @pytest.mark.parametrize("ip_whitelist", [None, []])
    def test_ingress_utility_app_patches_omits_acl_annotation_when_ip_whitelist_unset(
        self,
        ingress_utility: IngressUtility,
        global_context: GlobalContext,
        ip_whitelist: list[str] | None,
    ) -> None:
        """T008: When ip_whitelist is None or empty, no router.middlewares annotation
        is added. FR-006's third branch ("ingress utility not enabled at all") is
        enforced upstream by the caller iteration in
        backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py,
        which only invokes this method for utilities present in the deployment's
        utility set; no additional unit coverage is needed for that scenario."""
        global_context.instance.config.ip_whitelist = ip_whitelist
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        assert len(annotation_patches) == 1
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert "traefik.ingress.kubernetes.io/router.middlewares" not in annotations

    def test_includes_endpoints_type_when_node_external_ip(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        global_context.instance.config.external_dns_endpoints_type = "NodeExternalIP"
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert (
            annotations["external-dns.alpha.kubernetes.io/endpoints-type"]
            == "NodeExternalIP"
        )

    def test_includes_endpoints_type_when_cluster_ip(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        global_context.instance.config.external_dns_endpoints_type = "ClusterIP"
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert (
            annotations["external-dns.alpha.kubernetes.io/endpoints-type"]
            == "ClusterIP"
        )

    def test_omits_endpoints_type_when_unset(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        # Fixture leaves external_dns_endpoints_type at its None default.
        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert "external-dns.alpha.kubernetes.io/endpoints-type" not in annotations

    def test_deployment_overrides_cluster_endpoints_type(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        from styrmin_backend.context.resolvers import _resolve_instance_config

        cluster_config = ClusterConfig(
            external_dns_endpoints_type="NodeExternalIP",
            ingress_class="traefik",
            fqdn_suffix="test.styrmin.com",
            dedicated_ingress=DedicatedIngressConfig(),
        )
        environment_config = EnvironmentConfig()
        deployment_config = DeploymentConfig(external_dns_endpoints_type="ClusterIP")

        resolved = _resolve_instance_config(
            cluster=cluster_config,
            environment=environment_config,
            deployment=deployment_config,
        )
        global_context.instance.config = resolved

        patches = ingress_utility.build_app_post_rendering_patches(
            global_context, RELEASE_REF
        )
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert (
            annotations["external-dns.alpha.kubernetes.io/endpoints-type"]
            == "ClusterIP"
        )


class TestBuildExtraSpec:
    """Verify build_extra_spec returns empty list (Traefik out of scope)."""

    def test_returns_empty_list(
        self, ingress_utility: IngressUtility, global_context: GlobalContext
    ) -> None:
        result = ingress_utility.build_extra_spec(global_context)
        assert result == []


class TestUtilityExtensibility:
    """T022: Verify a custom utility subclass can implement all abstract methods."""

    def test_custom_utility_subclass(self, global_context: GlobalContext) -> None:
        class TestUtility(Utility):
            def __init__(self) -> None:
                super().__init__(kind="test", values_template_file="test.j2.yaml")

            def build_app_post_rendering_patches(
                self, context: GlobalContext, release_reference: str
            ) -> list[TargetPatch]:
                return []

            def build_extra_spec(self, context: GlobalContext) -> list[PostRenderers]:
                return []

            def build_resources(
                self, context: GlobalContext, release_reference: str, namespace: str
            ) -> list[dict[str, Any]]:
                return [
                    {
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "metadata": {
                            "name": f"{release_reference}-test",
                            "namespace": namespace,
                        },
                        "data": {"key": "value"},
                    }
                ]

        utility = TestUtility()
        resources = utility.build_resources(global_context, "rel", "ns")
        assert len(resources) == 1
        assert resources[0]["kind"] == "ConfigMap"
        assert resources[0]["metadata"]["name"] == "rel-test"


class TestIngressClassNameRemovalPatch:
    """023 research D-001: the strategic merge patch sets ``spec.ingressClassName`` to null."""

    def test_renders_ingress_class_name_null(self) -> None:
        rendered = IngressClassNameRemovalPatch().render_value()

        assert yaml.safe_load(rendered) == {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {"name": "any"},
            "spec": {"ingressClassName": None},
        }
        assert "ingressClassName: null" in rendered


def _removal_patches(patches: list[TargetPatch]) -> list[TargetPatch]:
    return [p for p in patches if isinstance(p.patch, IngressClassNameRemovalPatch)]


class TestDedicatedIngressPatching:
    """Ingress class patches per mode (023 contracts/post-render-patch.md).

    Dedicated ingress controller: remove ``spec.ingressClassName`` and set the
    annotation to the implementation. Otherwise: set both to the resolved
    ``ingress_class``, or neither when no class is resolved.
    """

    def test_dedicated_ingress_removes_ingress_class_name(
        self, ingress_utility: IngressUtility
    ) -> None:
        """FR-002: the class the chart rendered is removed, not replaced."""
        ctx = _make_context(
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik"),
            ingress_class="cluster-traefik",
        )
        patches = ingress_utility.build_app_post_rendering_patches(ctx, RELEASE_REF)

        removal_patches = _removal_patches(patches)
        assert len(removal_patches) == 1
        assert removal_patches[0].target.render_value() == {"kind": "Ingress"}
        spec_patches = [p for p in patches if hasattr(p.patch, "specs")]
        assert len(spec_patches) == 0

    def test_dedicated_ingress_sets_annotation(
        self, ingress_utility: IngressUtility
    ) -> None:
        """When dedicated_ingress is set, the kubernetes.io/ingress.class annotation is set."""
        ctx = _make_context(
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik"),
            ingress_class="cluster-traefik",
        )
        patches = ingress_utility.build_app_post_rendering_patches(ctx, RELEASE_REF)
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        assert len(annotation_patches) >= 1
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert annotations["kubernetes.io/ingress.class"] == "traefik"

    def test_dedicated_ingress_removes_class_when_no_class_resolved(
        self, ingress_utility: IngressUtility
    ) -> None:
        """FR-002: the removal and the annotation do not depend on a resolved ``ingress_class``."""
        ctx = _make_context(
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik"),
            ingress_class=None,
        )
        patches = ingress_utility.build_app_post_rendering_patches(ctx, RELEASE_REF)

        removal_patches = _removal_patches(patches)
        assert len(removal_patches) == 1
        assert removal_patches[0].target.render_value() == {"kind": "Ingress"}
        assert [p for p in patches if hasattr(p.patch, "specs")] == []
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert annotations["kubernetes.io/ingress.class"] == "traefik"

    def test_fallback_to_cluster_ingress_class(
        self, ingress_utility: IngressUtility
    ) -> None:
        """FR-001: When dedicated_ingress is not set, falls back to cluster ingress_class."""
        ctx = _make_context(dedicated_ingress=None, ingress_class="cluster-traefik")
        patches = ingress_utility.build_app_post_rendering_patches(ctx, RELEASE_REF)
        spec_patches = [p for p in patches if hasattr(p.patch, "specs")]
        assert len(spec_patches) == 1
        assert spec_patches[0].patch.specs["ingressClassName"] == "cluster-traefik"  # type: ignore[attr-defined]
        assert _removal_patches(patches) == []
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert annotations["kubernetes.io/ingress.class"] == "cluster-traefik"

    def test_shared_ingress_renders_class_then_annotation_patches(
        self, ingress_utility: IngressUtility
    ) -> None:
        """D-002: without a dedicated controller, the rendered patches and their order are the same as before 023.

        A change here changes the HelmRelease of every deployment without a dedicated ingress controller.
        """
        ctx = _make_context(dedicated_ingress=None, ingress_class="cluster-traefik")
        ctx.instance.deployment_id = UUID("00000000-0000-0000-0000-000000000001")
        patches = ingress_utility.build_app_post_rendering_patches(ctx, RELEASE_REF)

        assert [tp.render_value() for tp in patches] == [
            {
                "target": {"kind": "Ingress"},
                "patch": "- op: add\n  path: /spec/ingressClassName\n  value: cluster-traefik\n",
            },
            {
                "target": {"kind": "Ingress"},
                "patch": (
                    "- op: add\n"
                    "  path: /metadata/annotations/traefik.ingress.kubernetes.io~1router.entrypoints\n"
                    "  value: web,websecure\n"
                    "- op: add\n"
                    "  path: /metadata/annotations/external-dns.alpha.kubernetes.io~1hostname\n"
                    "  value: test-release-testapp.test.styrmin.com\n"
                    "- op: add\n"
                    "  path: /metadata/annotations/external-dns.alpha.kubernetes.io~1cloudflare-proxied\n"
                    "  value: true\n"
                    "- op: add\n"
                    "  path: /metadata/annotations/traefik.ingress.kubernetes.io~1router.middlewares\n"
                    "  value: styrmin-00000000-0000-0000-0000-000000000001-acl@kubernetescrd\n"
                    "- op: add\n"
                    "  path: /metadata/annotations/kubernetes.io~1ingress.class\n"
                    "  value: cluster-traefik\n"
                ),
            },
        ]

    def test_no_ingress_class_patch_when_neither_set(
        self, ingress_utility: IngressUtility
    ) -> None:
        """FR-006: no class patch, removal patch or class annotation, so the chart's class stays."""
        ctx = _make_context(dedicated_ingress=None, ingress_class=None)
        patches = ingress_utility.build_app_post_rendering_patches(ctx, RELEASE_REF)
        spec_patches = [p for p in patches if hasattr(p.patch, "specs")]
        assert len(spec_patches) == 0
        assert _removal_patches(patches) == []
        annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
        annotations = annotation_patches[0].patch.annotations  # type: ignore[attr-defined]
        assert "kubernetes.io/ingress.class" not in annotations


def _make_context(
    dedicated_ingress: DedicatedIngressConfig | None = None,
    ingress_class: str | None = "traefik",
) -> GlobalContext:
    """Build a GlobalContext with specific ingress settings."""
    return GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(
                ingress_class=ingress_class,
                dedicated_ingress=dedicated_ingress,
                fqdn_suffix="test.styrmin.com",
            ),
        ),
        environment=EnvironmentContext(
            name="test",
            config=EnvironmentConfig(
                ip_whitelist=["10.0.0.0/8"],
            ),
        ),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(
                ip_whitelist=["10.0.0.0/8"],
                ingress_class=ingress_class,
                dedicated_ingress=dedicated_ingress,
                fqdn_suffix="test.styrmin.com",
            ),
            deployment_id=uuid4(),
            namespace="test-namespace",
            release_reference="test-release",
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


def _find_resource(resources: list[dict], kind: str, name: str) -> dict | None:
    """Helper to find a resource by kind and name."""
    for r in resources:
        if r["kind"] == kind and r["metadata"]["name"] == name:
            return r
    return None
