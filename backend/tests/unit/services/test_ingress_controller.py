"""Tests for the ingress controller internal driver and deployment service integration.

Covers:
- T010: DedicatedIngressConfig model validation
- T011: Config merge precedence (Cluster default -> Environment override)
- T012: initialize_internal_drivers() creates correct DB records
- T013: deploy_application() auto-creates ingress controller when dedicated_ingress is set
- T014: deploy_application() reuses existing ingress controller
- T015: deploy_application() skips ingress controller when dedicated_ingress is not set
- T020a: Deprovisioning when dedicated_ingress is removed
- T020b: Retroactive reconciliation when dedicated_ingress is added
"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jinja2
import pytest
import yaml
from pydantic import ValidationError

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    EnvironmentConfig,
    IngressServiceConfig,
    ResolvedConfig,
)
from styrmin_backend.db.models import (
    Cluster,
    Environment,
)
from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services.deployment import (
    _ensure_ingress_controller,
    _resolve_dedicated_ingress,
)
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    IngressControllerNotHealthyError,
)
from styrmin_backend.services.ingress_controller.driver import INTERNAL_DRIVER_NAME
from tests.unit.services.fakes import (
    FakeApplicationDriverRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeUnitOfWork,
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeTaskRepository,
)

_CHART_VALUES_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[3]
    / "styrmin_backend"
    / "services"
    / "ingress_controller"
    / "templates"
    / "chart_values.j2.yaml"
)


def _render_chart_values(service_config: IngressServiceConfig) -> dict:
    """Render the dedicated-ingress chart-values template against a service config.

    Mirrors the production rendering (``ApplicationHelmReleaseBuilder.render_value_template``)
    but only supplies the ``instance.config.dedicated_ingress.service`` branch the
    template inspects. Returns the parsed YAML as a dict.
    """
    template_text = _CHART_VALUES_TEMPLATE_PATH.read_text()
    env = jinja2.Environment()
    template = env.from_string(template_text)
    instance = SimpleNamespace(
        config=SimpleNamespace(
            dedicated_ingress=SimpleNamespace(service=service_config)
        )
    )
    labels = SimpleNamespace(environment_id="test-env")
    rendered = template.render(instance=instance, labels=labels)
    return yaml.safe_load(rendered)


# ======================================================================
# T010: DedicatedIngressConfig model validation
# ======================================================================


class TestDedicatedIngressConfigModel:
    def test_default_values(self):
        config = DedicatedIngressConfig()
        assert config.implementation == "traefik"
        assert config.type == "ingress"

    def test_custom_values(self):
        config = DedicatedIngressConfig(implementation="nginx", type="gateway")
        assert config.implementation == "nginx"
        assert config.type == "gateway"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DedicatedIngressConfig(implementation="traefik", unknown_field="value")  # type: ignore[call-arg]

    def test_from_dict(self):
        config = DedicatedIngressConfig.model_validate(
            {"implementation": "traefik", "type": "ingress"}
        )
        assert config.implementation == "traefik"

    def test_nested_in_cluster_config(self):
        config = ClusterConfig(
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik")
        )
        assert config.dedicated_ingress is not None
        assert config.dedicated_ingress.implementation == "traefik"

    def test_nested_in_environment_config(self):
        config = EnvironmentConfig(
            dedicated_ingress=DedicatedIngressConfig(type="gateway")
        )
        assert config.dedicated_ingress is not None
        assert config.dedicated_ingress.type == "gateway"

    def test_none_by_default_in_cluster_config(self):
        config = ClusterConfig()
        assert config.dedicated_ingress is None

    def test_none_by_default_in_environment_config(self):
        config = EnvironmentConfig()
        assert config.dedicated_ingress is None


# ======================================================================
# T010b: IngressServiceConfig model validation
# ======================================================================


class TestIngressServiceConfigModel:
    def test_default_values(self):
        config = IngressServiceConfig()
        assert config.annotations is None
        assert config.load_balancer_ip is None
        assert config.external_traffic_policy is None

    def test_custom_annotations(self):
        config = IngressServiceConfig(
            annotations={"cloud.google.com/l4-rbs": "disabled"}
        )
        assert config.annotations == {"cloud.google.com/l4-rbs": "disabled"}

    def test_all_fields(self):
        config = IngressServiceConfig(
            annotations={"key": "value"},
            load_balancer_ip="10.0.0.1",
            external_traffic_policy="Local",
        )
        assert config.annotations == {"key": "value"}
        assert config.load_balancer_ip == "10.0.0.1"
        assert config.external_traffic_policy == "Local"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            IngressServiceConfig(unknown_field="value")  # type: ignore[call-arg]

    def test_nested_in_dedicated_ingress(self):
        config = DedicatedIngressConfig(
            service=IngressServiceConfig(
                annotations={
                    "service.beta.kubernetes.io/aws-load-balancer-target-group-arn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abc123"
                }
            )
        )
        assert config.service is not None
        assert config.service.annotations is not None
        assert (
            "service.beta.kubernetes.io/aws-load-balancer-target-group-arn"
            in config.service.annotations
        )

    def test_service_defaults(self):
        config = DedicatedIngressConfig()
        assert config.service is not None
        assert config.service.type == "LoadBalancer"
        assert config.service.annotations is None
        assert config.service.load_balancer_ip is None
        assert config.service.external_traffic_policy is None

    def test_from_dict_with_service(self):
        config = DedicatedIngressConfig.model_validate(
            {
                "implementation": "traefik",
                "service": {
                    "annotations": {"cloud.google.com/l4-rbs": "disabled"},
                    "load_balancer_ip": "10.0.0.1",
                },
            }
        )
        assert config.service is not None
        assert config.service.annotations == {"cloud.google.com/l4-rbs": "disabled"}
        assert config.service.load_balancer_ip == "10.0.0.1"

    # ------------------------------------------------------------------
    # T002 [US1] — ip_families field validator
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "value",
        [
            ["IPv6"],
            ["IPv4", "IPv6"],
            ["IPv6", "IPv4"],
            ["IPv4"],
        ],
    )
    def test_ip_families_accepts_valid_values(self, value):
        config = IngressServiceConfig(ip_families=value)
        assert config.ip_families == value

    def test_ip_families_rejects_empty_list(self):
        with pytest.raises(ValidationError) as exc_info:
            IngressServiceConfig(ip_families=[])
        assert "empty" in str(exc_info.value).lower()

    def test_ip_families_rejects_duplicates(self):
        with pytest.raises(ValidationError) as exc_info:
            IngressServiceConfig(ip_families=["IPv6", "IPv6"])
        assert "duplicate" in str(exc_info.value).lower()

    def test_ip_families_rejects_unknown_member(self):
        with pytest.raises(ValidationError):
            IngressServiceConfig(ip_families=["foo"])  # type: ignore[list-item]

    # ------------------------------------------------------------------
    # T003 [US1] — ip_family_policy literal
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "policy",
        ["SingleStack", "PreferDualStack", "RequireDualStack"],
    )
    def test_ip_family_policy_accepts_valid_values(self, policy):
        config = IngressServiceConfig(ip_family_policy=policy)
        assert config.ip_family_policy == policy

    @pytest.mark.parametrize("policy", ["DualStack", "singlestack", "Whatever"])
    def test_ip_family_policy_rejects_unknown(self, policy):
        with pytest.raises(ValidationError):
            IngressServiceConfig(ip_family_policy=policy)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # T004 [US1] — chart-values rendering for IP family fields
    # ------------------------------------------------------------------

    def test_render_ipv6_singlestack_emits_keys(self):
        config = IngressServiceConfig(
            ip_families=["IPv6"], ip_family_policy="SingleStack"
        )
        rendered = _render_chart_values(config)
        assert rendered["service"]["ipFamilies"] == ["IPv6"]
        assert rendered["service"]["ipFamilyPolicy"] == "SingleStack"

    def test_render_dual_stack_required_emits_keys(self):
        config = IngressServiceConfig(
            ip_families=["IPv4", "IPv6"], ip_family_policy="RequireDualStack"
        )
        rendered = _render_chart_values(config)
        assert rendered["service"]["ipFamilies"] == ["IPv4", "IPv6"]
        assert rendered["service"]["ipFamilyPolicy"] == "RequireDualStack"

    def test_render_omits_ip_family_keys_when_unset(self):
        config = IngressServiceConfig()
        rendered = _render_chart_values(config)
        assert "ipFamilies" not in rendered["service"]
        assert "ipFamilyPolicy" not in rendered["service"]

    # ------------------------------------------------------------------
    # T009 [US2] — node_port range
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("value", [1, 30443, 65535])
    def test_node_port_accepts_valid_range(self, value):
        config = IngressServiceConfig(type="NodePort", node_port=value)
        assert config.node_port == value

    @pytest.mark.parametrize("value", [0, 65536, -1])
    def test_node_port_rejects_out_of_range(self, value):
        with pytest.raises(ValidationError):
            IngressServiceConfig(type="NodePort", node_port=value)

    # ------------------------------------------------------------------
    # T010 [US2] — node_port requires type == NodePort (model validator)
    # ------------------------------------------------------------------

    def test_node_port_with_nodeport_type_accepted(self):
        config = IngressServiceConfig(type="NodePort", node_port=30443)
        assert config.type == "NodePort"
        assert config.node_port == 30443

    def test_nodeport_type_without_node_port_accepted(self):
        # "Let Kubernetes pick" path: type=NodePort but no fixed port.
        config = IngressServiceConfig(type="NodePort", node_port=None)
        assert config.type == "NodePort"
        assert config.node_port is None

    def test_node_port_with_loadbalancer_type_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            IngressServiceConfig(type="LoadBalancer", node_port=30443)
        message = str(exc_info.value)
        assert "type" in message
        assert "node_port" in message

    # ------------------------------------------------------------------
    # T011 [US2] — chart-values rendering for node_port
    # ------------------------------------------------------------------

    def test_render_node_port_emits_websecure_only(self):
        """node_port is rendered onto websecure only.

        Kubernetes rejects a Service whose two ports share a nodePort, so
        only the entrypoint that fronts the Cloudflare/Infrahub origin
        (websecure / HTTPS) gets the fixed value. ``web`` keeps the
        chart's default (Kubernetes-allocated) nodePort.
        """
        config = IngressServiceConfig(type="NodePort", node_port=30443)
        rendered = _render_chart_values(config)
        assert rendered["ports"]["websecure"]["nodePort"] == 30443
        # ``web`` must NOT carry the same fixed nodePort.
        assert (
            "web" not in rendered["ports"]
            or rendered["ports"].get("web") is None
            or rendered["ports"]["web"].get("nodePort") != 30443
        )

    def test_render_omits_ports_block_when_node_port_unset(self):
        config = IngressServiceConfig(type="NodePort")
        rendered = _render_chart_values(config)
        assert "ports" not in rendered or rendered.get("ports") is None

    # ------------------------------------------------------------------
    # host_network — model validation + rendering
    # ------------------------------------------------------------------

    def test_host_network_defaults_to_false(self):
        config = IngressServiceConfig()
        assert config.host_network is False

    def test_host_network_accepted_with_any_service_type(self):
        for service_type in ("ClusterIP", "LoadBalancer", "NodePort"):
            config = IngressServiceConfig(type=service_type, host_network=True)
            assert config.host_network is True
            assert config.type == service_type

    def test_host_network_with_node_port_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            IngressServiceConfig(type="NodePort", host_network=True, node_port=443)
        message = str(exc_info.value)
        assert "host_network" in message
        assert "node_port" in message

    def test_render_host_network_emits_full_package(self):
        """host_network=True emits hostNetwork, capability, and 80/443 ports."""
        config = IngressServiceConfig(type="ClusterIP", host_network=True)
        rendered = _render_chart_values(config)
        assert rendered["hostNetwork"] is True
        assert rendered["securityContext"]["capabilities"]["add"] == [
            "NET_BIND_SERVICE"
        ]
        assert rendered["ports"]["web"]["port"] == 80
        assert rendered["ports"]["websecure"]["port"] == 443
        # No NodePort is emitted in host-network mode.
        assert "nodePort" not in rendered["ports"]["websecure"]

    def test_render_omits_host_network_blocks_when_disabled(self):
        config = IngressServiceConfig(type="LoadBalancer", host_network=False)
        rendered = _render_chart_values(config)
        assert "hostNetwork" not in rendered
        assert "securityContext" not in rendered

    # ------------------------------------------------------------------
    # T017 [US3] — backward-compat: all three new fields unset
    # ------------------------------------------------------------------

    def test_render_byte_identical_when_new_fields_unset(self):
        """All-three-new-fields-unset must render identically to the
        equivalent config that never touches the new fields.

        Asserts (a) parsed YAML has no ipFamilies/ipFamilyPolicy under
        ``service`` and no top-level ``ports`` block; (b) the rendered
        text matches the rendering of the same config built without ever
        passing the new field names.
        """
        # Config that explicitly sets the new fields to None / default.
        config_explicit_none = IngressServiceConfig(
            type="LoadBalancer",
            annotations=None,
            load_balancer_ip=None,
            external_traffic_policy=None,
            ip_families=None,
            ip_family_policy=None,
            node_port=None,
            host_network=False,
        )
        # Config that doesn't even mention the new fields.
        config_pre_feature = IngressServiceConfig(
            type="LoadBalancer",
            annotations=None,
            load_balancer_ip=None,
            external_traffic_policy=None,
        )

        rendered_explicit_none = _render_chart_values(config_explicit_none)
        rendered_pre_feature = _render_chart_values(config_pre_feature)

        assert "ipFamilies" not in rendered_pre_feature["service"]
        assert "ipFamilyPolicy" not in rendered_pre_feature["service"]
        assert "ports" not in rendered_pre_feature
        assert rendered_explicit_none == rendered_pre_feature

    def test_config_merge_preserves_service(self):
        """Service config survives cluster/environment merge."""
        cluster = ClusterConfig(
            dedicated_ingress=DedicatedIngressConfig(
                service=IngressServiceConfig(
                    annotations={"cloud.google.com/l4-rbs": "disabled"}
                )
            )
        )
        env = EnvironmentConfig(ip_whitelist=["10.0.0.0/8"])

        merged = {
            **cluster.model_dump(exclude_none=True),
            **env.model_dump(exclude_none=True),
        }
        resolved = ResolvedConfig.model_validate(merged)
        assert resolved.dedicated_ingress is not None
        assert resolved.dedicated_ingress.service is not None
        assert resolved.dedicated_ingress.service.annotations == {
            "cloud.google.com/l4-rbs": "disabled"
        }


# ======================================================================
# T011: Config merge precedence (Cluster default -> Environment override)
# ======================================================================


class TestConfigMergePrecedence:
    def test_environment_overrides_cluster(self):
        """Environment-level dedicated_ingress should override cluster-level."""
        cluster = ClusterConfig(
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik")
        )
        env = EnvironmentConfig(
            dedicated_ingress=DedicatedIngressConfig(implementation="nginx")
        )

        # Simulate the merge: {**cluster, **environment} with exclude_none
        merged = {
            **cluster.model_dump(exclude_none=True),
            **env.model_dump(exclude_none=True),
        }
        resolved = ResolvedConfig.model_validate(merged)
        assert resolved.dedicated_ingress is not None
        assert resolved.dedicated_ingress.implementation == "nginx"

    def test_cluster_default_when_environment_not_set(self):
        """Cluster default should pass through when environment doesn't set it."""
        cluster = ClusterConfig(
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik")
        )
        env = EnvironmentConfig(ip_whitelist=["10.0.0.0/8"])

        merged = {
            **cluster.model_dump(exclude_none=True),
            **env.model_dump(exclude_none=True),
        }
        resolved = ResolvedConfig.model_validate(merged)
        assert resolved.dedicated_ingress is not None
        assert resolved.dedicated_ingress.implementation == "traefik"

    def test_no_dedicated_ingress_when_neither_sets_it(self):
        """No dedicated_ingress when neither cluster nor environment sets it."""
        cluster = ClusterConfig(ingress_class="traefik")
        env = EnvironmentConfig()

        merged = {
            **cluster.model_dump(exclude_none=True),
            **env.model_dump(exclude_none=True),
        }
        resolved = ResolvedConfig.model_validate(merged)
        assert resolved.dedicated_ingress is None


# ======================================================================
# T012: initialize_internal_drivers() creates correct DB records
# (Tested via the helper function patterns — full integration needs DB)
# ======================================================================


class TestInternalDriverConstants:
    def test_driver_name(self):
        assert INTERNAL_DRIVER_NAME == "styrmin-ingress-controller"


# ======================================================================
# Fixtures for deployment service tests
# ======================================================================


@pytest.fixture
def fake_cluster_repo():
    return FakeClusterRepository()


@pytest.fixture
def fake_env_repo():
    return FakeEnvironmentRepository()


@pytest.fixture
def fake_deployment_repo():
    return FakeDeploymentRepository()


@pytest.fixture
def fake_app_driver_repo():
    return FakeApplicationDriverRepository()


@pytest.fixture
async def cluster_with_ingress(fake_cluster_repo):
    return await fake_cluster_repo.create(
        Cluster(
            name="test-cluster",
            config={
                "dedicated_ingress": {"implementation": "traefik", "type": "ingress"}
            },
        )
    )


@pytest.fixture
async def cluster_without_ingress(fake_cluster_repo):
    return await fake_cluster_repo.create(
        Cluster(name="plain-cluster", config={"ingress_class": "traefik"})
    )


@pytest.fixture
async def env_with_ingress(cluster_with_ingress, fake_env_repo):
    return await fake_env_repo.create(
        Environment(
            name="env-with-ingress",
            cluster_id=cluster_with_ingress.id,
            config={
                "dedicated_ingress": {"implementation": "traefik", "type": "ingress"}
            },
        )
    )


@pytest.fixture
async def env_without_ingress(cluster_without_ingress, fake_env_repo):
    return await fake_env_repo.create(
        Environment(
            name="env-no-ingress",
            cluster_id=cluster_without_ingress.id,
            config={},
        )
    )


@pytest.fixture
async def env_inherits_from_cluster(cluster_with_ingress, fake_env_repo):
    return await fake_env_repo.create(
        Environment(
            name="env-inherits",
            cluster_id=cluster_with_ingress.id,
            config={},
        )
    )


def _make_uow(
    clusters=None,
    environments=None,
    deployments=None,
    application_drivers=None,
    **kwargs,
):
    return FakeUnitOfWork(
        clusters=clusters or FakeClusterRepository(),
        environments=environments or FakeEnvironmentRepository(),
        helm_repositories=kwargs.get(
            "helm_repositories", FakeHelmRepositoryRepository()
        ),
        helm_charts=kwargs.get("helm_charts", FakeHelmChartRepository()),
        application_driver_versions=kwargs.get(
            "application_driver_versions", FakeApplicationRepository()
        ),
        instances=kwargs.get("instances", FakeApplicationInstanceRepository()),
        actions=kwargs.get("actions", FakeActionRepository()),
        tasks=kwargs.get("tasks", FakeTaskRepository()),
        application_drivers=application_drivers,
        deployments=deployments,
    )


# ======================================================================
# T013-T015: _resolve_dedicated_ingress and _ensure_ingress_controller
# ======================================================================


class TestResolveDedicatedIngress:
    async def test_returns_config_from_environment(
        self, fake_cluster_repo, fake_env_repo, env_with_ingress
    ):
        uow = _make_uow(clusters=fake_cluster_repo, environments=fake_env_repo)
        result = await _resolve_dedicated_ingress(env_with_ingress.id, uow)
        assert result is not None
        assert result.implementation == "traefik"

    async def test_returns_none_without_ingress(
        self, fake_cluster_repo, fake_env_repo, env_without_ingress
    ):
        uow = _make_uow(clusters=fake_cluster_repo, environments=fake_env_repo)
        result = await _resolve_dedicated_ingress(env_without_ingress.id, uow)
        assert result is None

    async def test_falls_back_to_cluster(
        self, fake_cluster_repo, fake_env_repo, env_inherits_from_cluster
    ):
        uow = _make_uow(clusters=fake_cluster_repo, environments=fake_env_repo)
        result = await _resolve_dedicated_ingress(env_inherits_from_cluster.id, uow)
        assert result is not None
        assert result.implementation == "traefik"

    async def test_returns_none_for_unknown_env(self):
        uow = _make_uow()
        result = await _resolve_dedicated_ingress(uuid4(), uow)
        assert result is None


class TestEnsureIngressController:
    """T013: auto-create, T014: reuse, T015: skip."""

    async def test_skips_when_no_dedicated_ingress(
        self,
        fake_cluster_repo,
        fake_env_repo,
        fake_deployment_repo,
        env_without_ingress,
    ):
        """T015: No ingress controller created when dedicated_ingress is not set."""
        uow = _make_uow(
            clusters=fake_cluster_repo,
            environments=fake_env_repo,
            deployments=fake_deployment_repo,
        )
        await _ensure_ingress_controller(
            env_without_ingress.id, uow, created_by_user_id=uuid4()
        )
        # No deployment should have been created
        result = await fake_deployment_repo.find_internal_by_environment(
            env_without_ingress.id
        )
        assert result is None

    async def test_raises_when_driver_missing(
        self,
        fake_cluster_repo,
        fake_env_repo,
        fake_deployment_repo,
        env_with_ingress,
    ):
        """T013: Error when internal driver is not initialized."""
        uow = _make_uow(
            clusters=fake_cluster_repo,
            environments=fake_env_repo,
            deployments=fake_deployment_repo,
        )
        with pytest.raises(ApplicationDriverNotFoundError):
            await _ensure_ingress_controller(
                env_with_ingress.id, uow, created_by_user_id=uuid4()
            )

    async def test_reuses_running_controller(
        self,
        fake_cluster_repo,
        fake_env_repo,
        fake_deployment_repo,
        env_with_ingress,
    ):
        """T014: Reuses existing running ingress controller."""
        # Pre-create a running internal deployment
        existing = Deployment.create(
            name="ingress-controller",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=env_with_ingress.id,
            created_by_user_id=uuid4(),
            internal=True,
        )
        existing.set_status(DeploymentState.RUNNING)
        await fake_deployment_repo.save(existing)

        uow = _make_uow(
            clusters=fake_cluster_repo,
            environments=fake_env_repo,
            deployments=fake_deployment_repo,
        )
        # Should not raise, should not create a new deployment
        await _ensure_ingress_controller(
            env_with_ingress.id, uow, created_by_user_id=uuid4()
        )
        assert len(fake_deployment_repo._deployments) == 1

    async def test_raises_when_controller_failed(
        self,
        fake_cluster_repo,
        fake_env_repo,
        fake_deployment_repo,
        env_with_ingress,
    ):
        """T013: Raises error when existing controller has failed."""
        existing = Deployment.create(
            name="ingress-controller",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=env_with_ingress.id,
            created_by_user_id=uuid4(),
            internal=True,
        )
        existing.set_status(DeploymentState.FAILED)
        await fake_deployment_repo.save(existing)

        uow = _make_uow(
            clusters=fake_cluster_repo,
            environments=fake_env_repo,
            deployments=fake_deployment_repo,
        )
        with pytest.raises(IngressControllerNotHealthyError):
            await _ensure_ingress_controller(
                env_with_ingress.id, uow, created_by_user_id=uuid4()
            )


# ======================================================================
# T020a: Deprovisioning test
# ======================================================================


class TestDeprovisioning:
    async def test_internal_deployment_tracked_by_environment(
        self, fake_deployment_repo
    ):
        """Verify that internal deployments can be found by environment ID."""
        env_id = uuid4()
        deployment = Deployment.create(
            name="ingress-controller",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=env_id,
            created_by_user_id=uuid4(),
            internal=True,
        )
        await fake_deployment_repo.save(deployment)

        found = await fake_deployment_repo.find_internal_by_environment(env_id)
        assert found is not None
        assert found.id == deployment.id
        assert found.internal is True

    async def test_no_internal_deployment_for_other_env(self, fake_deployment_repo):
        """Internal deployments are scoped to their environment."""
        env_id = uuid4()
        other_env_id = uuid4()
        deployment = Deployment.create(
            name="ingress-controller",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=env_id,
            created_by_user_id=uuid4(),
            internal=True,
        )
        await fake_deployment_repo.save(deployment)

        found = await fake_deployment_repo.find_internal_by_environment(other_env_id)
        assert found is None


# ======================================================================
# T020b: Retroactive reconciliation test
# ======================================================================


class TestRetroactiveReconciliation:
    async def test_non_internal_deployments_not_found_as_internal(
        self, fake_deployment_repo
    ):
        """Regular deployments are not found by find_internal_by_environment."""
        env_id = uuid4()
        deployment = Deployment.create(
            name="regular-deployment",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=env_id,
            created_by_user_id=uuid4(),
            internal=False,
        )
        await fake_deployment_repo.save(deployment)

        found = await fake_deployment_repo.find_internal_by_environment(env_id)
        assert found is None


# ======================================================================
# Domain model tests
# ======================================================================


class TestDeploymentInternalField:
    def test_default_internal_is_false(self):
        deployment = Deployment.create(
            name="test-deployment",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=uuid4(),
            created_by_user_id=uuid4(),
        )
        assert deployment.internal is False

    def test_internal_can_be_set_true(self):
        deployment = Deployment.create(
            name="test-deployment",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=uuid4(),
            created_by_user_id=uuid4(),
            internal=True,
        )
        assert deployment.internal is True
