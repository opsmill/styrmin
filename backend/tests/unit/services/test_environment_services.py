from uuid import uuid4

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
from styrmin_backend.db.models import Cluster
from styrmin_backend.db.models import Environment
from styrmin_backend.domain.models import (
    Deployment as DeploymentEntity,
    Instance as InstanceEntity,
    InstanceStatus as InstanceStatusEntity,
)
from styrmin_backend.services.environments import (
    _deployment_already_at_config,
    _extract_environment_slice_from_context,
    create_environment,
    delete_environment,
    get_environment,
    get_environments,
    resolve_environment,
    update_environment,
)
from styrmin_backend.services.env_vars.exceptions import InvalidEnvVarNameError
from styrmin_backend.services.exceptions import (
    AmbiguousIdentifierError,
    ClusterNotFoundError,
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
)
from tests.unit.services.fakes import FakeEnvironmentRepository, FakeUnitOfWork


async def test_create_environment(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    cluster_id = fake_cluster.id
    environment = await create_environment(
        name="test_environment", cluster_id=cluster_id, uow=uow
    )

    assert len(fake_environment_repository.models) == 1
    assert fake_environment_repository.models[0] == environment
    assert environment.name == "test_environment"
    assert environment.cluster_id == cluster_id

    assert uow.committed


async def test_create_environment_with_already_existing_name(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    cluster_id = fake_cluster.id

    await create_environment(name="test_environment", cluster_id=cluster_id, uow=uow)
    assert uow.committed

    with pytest.raises(EnvironmentAlreadyExistsError):
        await create_environment(
            name="test_environment", cluster_id=cluster_id, uow=uow
        )
    assert not uow.committed


async def test_create_environment_with_valid_config(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    cluster_id = fake_cluster.id
    config = {
        "ingress_class": "value",
        "db_size": "10Gi",
    }

    environment = await create_environment(
        name="test_environment", cluster_id=cluster_id, config=config, uow=uow
    )
    assert uow.committed

    assert len(fake_environment_repository.models) == 1
    assert fake_environment_repository.models[0] == environment
    assert environment.config == config


async def test_create_environment_with_wrong_config(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    config = {
        "ingress_class": "value",
        "db_size": "10Gi",
        "runtime_class": "value",
        "node_selector": "value",
        "dedicated_ingress": "value",
        "wrong_key": "value",
    }

    with pytest.raises(InvalidContextError):
        await create_environment(
            name="test_environment", cluster_id=fake_cluster.id, config=config, uow=uow
        )
    assert not uow.committed


async def test_get_environment(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    environment = await create_environment(
        name="test_environment", cluster_id=fake_cluster.id, uow=uow
    )
    assert uow.committed

    result = await get_environment(environment_id=environment.id, uow=uow)

    assert result == environment


async def test_get_environment_that_does_not_exist(
    uow: FakeUnitOfWork,
):
    with pytest.raises(EnvironmentNotFoundError):
        await get_environment(environment_id=uuid4(), uow=uow)


async def test_get_all_environments(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    cluster_id = fake_cluster.id
    environment1 = await create_environment(
        name="test_environment1", cluster_id=cluster_id, uow=uow
    )
    assert uow.committed

    environment2 = await create_environment(
        name="test_environment2", cluster_id=cluster_id, uow=uow
    )
    assert uow.committed

    result = await get_environments(uow=uow)

    assert result == [environment1, environment2]


async def test_delete_environment(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    environment = await create_environment(
        name="test_environment", cluster_id=fake_cluster.id, uow=uow
    )
    assert uow.committed

    await delete_environment(environment_id=environment.id, uow=uow)
    assert uow.committed

    with pytest.raises(EnvironmentNotFoundError):
        await get_environment(environment_id=environment.id, uow=uow)


async def test_delete_environment_that_does_not_exist(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    with pytest.raises(EnvironmentNotFoundError):
        await delete_environment(environment_id=fake_cluster.id, uow=uow)
    assert not uow.committed


# --- resolve_environment tests ---


async def test_resolve_environment_by_id(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    env = await fake_environment_repository.create(
        Environment(name="staging", cluster_id=fake_cluster.id)
    )

    result = await resolve_environment(uow, environment_id=env.id)
    assert result.id == env.id
    assert result.name == "staging"


async def test_resolve_environment_by_name_and_cluster_name(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    env = await fake_environment_repository.create(
        Environment(name="staging", cluster_id=fake_cluster.id)
    )

    result = await resolve_environment(
        uow, environment_name="staging", cluster_name=fake_cluster.name
    )
    assert result.id == env.id


async def test_resolve_environment_by_name_and_cluster_id(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    env = await fake_environment_repository.create(
        Environment(name="staging", cluster_id=fake_cluster.id)
    )

    result = await resolve_environment(
        uow, environment_name="staging", cluster_id=fake_cluster.id
    )
    assert result.id == env.id


async def test_resolve_environment_raises_when_both_id_and_name(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    env = await fake_environment_repository.create(
        Environment(name="staging", cluster_id=fake_cluster.id)
    )

    with pytest.raises(AmbiguousIdentifierError, match="not both"):
        await resolve_environment(
            uow, environment_id=env.id, environment_name="staging"
        )


async def test_resolve_environment_raises_when_neither(uow: FakeUnitOfWork):
    with pytest.raises(AmbiguousIdentifierError, match="required"):
        await resolve_environment(uow)


async def test_resolve_environment_not_found_by_id(uow: FakeUnitOfWork):
    with pytest.raises(EnvironmentNotFoundError):
        await resolve_environment(uow, environment_id=uuid4())


async def test_resolve_environment_not_found_by_name(
    uow: FakeUnitOfWork, fake_cluster: Cluster
):
    with pytest.raises(EnvironmentNotFoundError):
        await resolve_environment(
            uow, environment_name="nonexistent", cluster_name=fake_cluster.name
        )


async def test_resolve_environment_name_requires_cluster_context(
    uow: FakeUnitOfWork,
):
    with pytest.raises(AmbiguousIdentifierError, match="required"):
        await resolve_environment(uow, environment_name="staging")


async def test_resolve_environment_name_with_nonexistent_cluster(
    uow: FakeUnitOfWork,
):
    with pytest.raises(ClusterNotFoundError):
        await resolve_environment(
            uow, environment_name="staging", cluster_name="nonexistent"
        )


# --- per-cluster uniqueness tests ---


async def test_create_environment_same_name_different_cluster_succeeds(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    from tests.unit.services.fakes import FakeClusterRepository

    cluster_repo: FakeClusterRepository = uow.clusters  # type: ignore[assignment]
    cluster2 = await cluster_repo.create(Cluster(name="other_cluster"))

    env1 = await create_environment(name="staging", cluster_id=fake_cluster.id, uow=uow)
    env2 = await create_environment(name="staging", cluster_id=cluster2.id, uow=uow)

    assert env1.name == env2.name
    assert env1.cluster_id != env2.cluster_id
    assert len(fake_environment_repository.models) == 2


# --- Phase 2 (T012) typed-error pipeline test ----------------------------
#
# Pins the post-008 invariant that an invalid env var name reaches the
# service-layer caller as ``InvalidEnvVarNameError`` (extensions.code =
# INVALID_ENV_VAR_NAME) rather than being collapsed into the generic
# ``InvalidContextError`` (INVALID_CONTEXT). The check exists so a future
# refactor that accidentally moves :func:`_prevalidate_environment_env_vars`
# to AFTER :func:`validate_environment_config` (or removes it entirely) is
# caught by a unit test instead of by SC-003 propagation tests downstream.


async def test_update_environment_invalid_env_var_name_surfaces_typed_error(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    """An invalid env var name MUST surface as ``InvalidEnvVarNameError``.

    Regression guard for FR-006/FR-007/FR-008/FR-009 / SC-003: the
    pre-validation hop (``_prevalidate_environment_env_vars``) runs ahead of
    Pydantic-driven ``validate_environment_config`` so the typed env-var
    error escapes intact instead of being wrapped into
    ``InvalidContextError``.
    """
    environment = await create_environment(
        name="staging", cluster_id=fake_cluster.id, uow=uow
    )

    with pytest.raises(InvalidEnvVarNameError):
        await update_environment(
            environment_id=environment.id,
            uow=uow,
            config={"env_vars": {"1invalid": "y"}},
        )


# --- Phase 2 (T013) `_deployment_already_at_config` tests -----------------


def _make_global_context(
    *,
    env_config: EnvironmentConfig | None = None,
) -> GlobalContext:
    """Build a minimal :class:`GlobalContext` carrying the supplied env config."""
    deployment_id = uuid4()
    chart_id = uuid4()
    repo_id = uuid4()
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(
            name="test", config=env_config or EnvironmentConfig()
        ),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace="test-ns",
            release_reference="test-ref",
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=chart_id,
                    name="test-chart",
                    version="0.1.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=repo_id, url="https://example.com"),
            ),
        ),
    )


def _make_deployment_with_active_instance(
    *,
    instance_env_config: EnvironmentConfig | None,
) -> DeploymentEntity:
    """Build a :class:`Deployment` whose active instance carries ``instance_env_config``.

    When ``instance_env_config`` is ``None``, the deployment has no active
    instance — exercising the "no active instance" code path.
    """
    deployment = DeploymentEntity.create(
        application_version="1.0.0",
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        name="test-deployment",
    )
    if instance_env_config is None:
        return deployment
    instance = InstanceEntity(
        id=uuid4(),
        name="test-instance",
        application_version="1.0.0",
        status=InstanceStatusEntity.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=deployment.application_driver_version_id,
        context=_make_global_context(env_config=instance_env_config),
    )
    deployment.set_active_instance(instance=instance)
    return deployment


def test_deployment_already_at_config_positive_match():
    """Active-instance env config canonically equal to ``new_config`` → True."""
    config = EnvironmentConfig(env_vars={"FOO": "bar"})
    deployment = _make_deployment_with_active_instance(instance_env_config=config)
    assert _deployment_already_at_config(deployment, config) is True


def test_deployment_already_at_config_negative_one_var_differs():
    """Active-instance env config differs by one env var → False."""
    instance_config = EnvironmentConfig(env_vars={"FOO": "bar"})
    deployment = _make_deployment_with_active_instance(
        instance_env_config=instance_config
    )
    new_config = EnvironmentConfig(env_vars={"FOO": "baz"})
    assert _deployment_already_at_config(deployment, new_config) is False


def test_deployment_already_at_config_no_active_instance_returns_false():
    """A deployment without an active instance always reports False (must redeploy)."""
    deployment = _make_deployment_with_active_instance(instance_env_config=None)
    new_config = EnvironmentConfig(env_vars={"FOO": "bar"})
    assert _deployment_already_at_config(deployment, new_config) is False


def test_deployment_already_at_config_canonical_none_vs_missing_drift():
    """Canonical equality flattens ``None`` vs missing-field drift.

    The instance's persisted slice and ``new_config`` may differ only by
    whether an optional field was explicitly ``None`` or simply omitted —
    after the canonical Pydantic round-trip both forms project the same
    dict and the deployment is considered converged.
    """
    instance_config = EnvironmentConfig(env_vars={"FOO": "bar"})
    deployment = _make_deployment_with_active_instance(
        instance_env_config=instance_config
    )
    # ``new_config`` explicitly sets unrelated optional fields to ``None``
    # while the instance slice simply omitted them. Canonical equality must
    # treat the two as equivalent.
    new_config = EnvironmentConfig(
        env_vars={"FOO": "bar"},
        ip_whitelist=None,
        dedicated_ingress=None,
    )
    assert _deployment_already_at_config(deployment, new_config) is True


def test_extract_environment_slice_from_context_handles_none():
    """Defensive: ``None`` context yields ``None`` (no slice)."""
    assert _extract_environment_slice_from_context(None) is None


def test_extract_environment_slice_from_context_dict_shape():
    """The JSON-serialised dict shape resolves through the dict branch."""
    raw = {"environment": {"config": {"env_vars": {"FOO": "bar"}}}}
    slice_dict = _extract_environment_slice_from_context(raw)
    assert slice_dict == {"env_vars": {"FOO": "bar"}}
