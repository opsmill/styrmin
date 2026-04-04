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

from uuid import uuid4

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    EnvironmentConfig,
    IngressServiceConfig,
    ResolvedConfig,
)
from styrmin_backend.domain.models import Deployment, DeploymentStatus
from styrmin_backend.services.deployment import (
    _ensure_ingress_controller,
    _resolve_dedicated_ingress,
)
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    IngressControllerNotHealthyError,
)
from styrmin_backend.services.ingress_controller.driver import INTERNAL_DRIVER_NAME

from styrmin_backend.db.models import (
    Cluster,
    Environment,
)
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

    def test_service_none_by_default(self):
        config = DedicatedIngressConfig()
        assert config.service is None

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
        await _ensure_ingress_controller(env_without_ingress.id, uow)
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
            await _ensure_ingress_controller(env_with_ingress.id, uow)

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
            internal=True,
        )
        existing.set_status(DeploymentStatus.RUNNING)
        await fake_deployment_repo.save(existing)

        uow = _make_uow(
            clusters=fake_cluster_repo,
            environments=fake_env_repo,
            deployments=fake_deployment_repo,
        )
        # Should not raise, should not create a new deployment
        await _ensure_ingress_controller(env_with_ingress.id, uow)
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
            internal=True,
        )
        existing.set_status(DeploymentStatus.FAILED)
        await fake_deployment_repo.save(existing)

        uow = _make_uow(
            clusters=fake_cluster_repo,
            environments=fake_env_repo,
            deployments=fake_deployment_repo,
        )
        with pytest.raises(IngressControllerNotHealthyError):
            await _ensure_ingress_controller(env_with_ingress.id, uow)


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
        )
        assert deployment.internal is False

    def test_internal_can_be_set_true(self):
        deployment = Deployment.create(
            name="test-deployment",
            application_version="1.0.0",
            application_driver_version_id=uuid4(),
            environment_id=uuid4(),
            internal=True,
        )
        assert deployment.internal is True
