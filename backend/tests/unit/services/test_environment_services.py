from datetime import datetime, timezone
from typing import Any
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
from styrmin_backend.db.models import Cluster
from styrmin_backend.db.models import Environment
from styrmin_backend.domain.models import (
    Deployment as DeploymentEntity,
    Instance as InstanceEntity,
    InstanceStatus as InstanceStatusEntity,
)
from styrmin_backend.services.capabilities import compute_environment_capabilities
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


# ---------------------------------------------------------------------------
# Phase 3 (T018-T021) — env-config fanout tests
# ---------------------------------------------------------------------------
#
# The fanout calls ``redeploy_for_environment_update`` which in turn calls
# ``generate_instance_from_deployment`` + ``apply_state`` (the full
# reconciliation chain). Driving that chain through fakes is brittle and
# duplicates infrastructure already covered by the propagation tests. The
# unit tests below patch ``redeploy_for_environment_update`` *as imported by
# styrmin_backend.services.environments* (the call site) and assert on the
# call pattern + counters.
#
# All fanout tests pre-seed:
# * one fake cluster (already provided by fixture)
# * one environment (created via service so the row is present in the
#   ``FakeEnvironmentRepository``)
# * N deployments via the ``FakeDeploymentRepository`` (so
#   ``find_all_by_environment`` returns them)
#
# Each deployment may carry an ``active_instance`` whose context's
# environment-config slice equals or differs from the target config; that
# decides whether ``_deployment_already_at_config`` returns True.


def _make_fanout_deployment(
    *,
    environment_id: UUID,
    name: str,
    active_env_config: EnvironmentConfig | None,
    internal: bool = False,
    deleted: bool = False,
) -> DeploymentEntity:
    """Build a domain ``Deployment`` for fanout tests.

    ``active_env_config`` controls the embedded slice: ``None`` means no
    active instance (the deployment will always dispatch). ``deleted=True``
    sets ``deleted_at`` on the deployment so it is filtered out of
    ``find_all_by_environment`` (matching DB semantics).
    """
    deployment = DeploymentEntity.create(
        application_version="1.0.0",
        application_driver_version_id=uuid4(),
        environment_id=environment_id,
        name=name,
        internal=internal,
    )
    if deleted:
        deployment.deleted_at = datetime.now(timezone.utc)
    if active_env_config is not None:
        instance = InstanceEntity(
            id=uuid4(),
            name=f"{name}-instance",
            application_version="1.0.0",
            status=InstanceStatusEntity.PENDING,
            deployment_id=deployment.id,
            application_driver_version_id=deployment.application_driver_version_id,
            context=_make_global_context(env_config=active_env_config),
        )
        deployment.set_active_instance(instance=instance)
    return deployment


async def _seed_environment_and_deployments(
    uow,
    *,
    cluster,
    deployments: list[DeploymentEntity],
):
    """Persist an environment + its deployments through the fakes.

    Returns the persisted ``Environment``. The deployments are inserted
    directly into the ``FakeDeploymentRepository`` (no go-through-the-
    service path; the service's ``deploy`` flow exercises infrastructure
    we don't need here).
    """
    environment = await create_environment(
        name=f"fanout-{uuid4().hex[:6]}",
        cluster_id=cluster.id,
        uow=uow,
    )
    # Re-bind deployments to this environment's id and persist them on the
    # fake repository so ``find_all_by_environment`` returns them.
    for deployment in deployments:
        deployment.environment_id = environment.id
        await uow.deployments.save(deployment=deployment)
    return environment


async def test_fanout_dispatches_to_all_fresh_deployments(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """3 deployments all fresh (no active instance) → 3 Tasks dispatched."""
    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(),  # rebound below
            name=f"fresh-{i}",
            active_env_config=None,
        )
        for i in range(3)
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )

    redeploy_mock = mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        autospec=True,
    )
    log_info = mocker.patch(
        "styrmin_backend.services.environments.logger.info",
    )

    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config={"env_vars": {"FOO": "bar"}},
    )

    assert redeploy_mock.await_count == 3
    # The structured log entry must reflect dispatched=3.
    fanout_log_calls = [
        call
        for call in log_info.call_args_list
        if call.args and "env_config_fanout_dispatched" in call.args[0]
    ]
    assert len(fanout_log_calls) == 1
    args = fanout_log_calls[0].args
    # args[0]=template, args[1..]=positional substitutions
    # (environment_id, evaluated, dispatched, skipped_noop, dispatch_failed)
    assert args[2] == 3  # evaluated
    assert args[3] == 3  # dispatched
    assert args[4] == 0  # skipped_noop
    assert args[5] == 0  # dispatch_failed


async def test_fanout_skips_deployments_already_at_config(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """3 deployments where 2 are at config + 1 isn't → 1 Task dispatched."""
    target_config = EnvironmentConfig(env_vars={"FOO": "bar"})
    other_config = EnvironmentConfig(env_vars={"FOO": "baz"})

    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="at-config-1",
            active_env_config=target_config,
        ),
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="at-config-2",
            active_env_config=target_config,
        ),
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="laggard",
            active_env_config=other_config,
        ),
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )

    redeploy_mock = mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        autospec=True,
    )
    log_info = mocker.patch(
        "styrmin_backend.services.environments.logger.info",
    )

    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config=target_config.model_dump(mode="json", exclude_none=True),
    )

    assert redeploy_mock.await_count == 1
    # The dispatched call must be the laggard.
    assert redeploy_mock.await_args_list[0].args[0].name == "laggard"

    fanout_log_calls = [
        call
        for call in log_info.call_args_list
        if call.args and "env_config_fanout_dispatched" in call.args[0]
    ]
    assert len(fanout_log_calls) == 1
    args = fanout_log_calls[0].args
    assert args[2] == 3  # evaluated
    assert args[3] == 1  # dispatched
    assert args[4] == 2  # skipped_noop
    assert args[5] == 0  # dispatch_failed


async def test_fanout_excludes_tombstoned_deployments(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """3 deployments where 1 is tombstoned → 2 Tasks dispatched (FR-012)."""
    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(), name="alive-1", active_env_config=None
        ),
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="tombstoned",
            active_env_config=None,
            deleted=True,
        ),
        _make_fanout_deployment(
            environment_id=uuid4(), name="alive-2", active_env_config=None
        ),
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )

    redeploy_mock = mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        autospec=True,
    )

    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config={"env_vars": {"FOO": "bar"}},
    )

    # The fake's ``find_all_by_environment`` excludes tombstoned rows by
    # default (matching the SQL repo). Two alive deployments dispatch.
    assert redeploy_mock.await_count == 2
    dispatched_names = {call.args[0].name for call in redeploy_mock.await_args_list}
    assert dispatched_names == {"alive-1", "alive-2"}


async def test_fanout_excludes_internal_deployments(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """3 deployments where 1 is internal → 2 Tasks dispatched (FR-013)."""
    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(), name="user-1", active_env_config=None
        ),
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="ingress-controller",
            active_env_config=None,
            internal=True,
        ),
        _make_fanout_deployment(
            environment_id=uuid4(), name="user-2", active_env_config=None
        ),
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )

    redeploy_mock = mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        autospec=True,
    )

    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config={"env_vars": {"FOO": "bar"}},
    )

    assert redeploy_mock.await_count == 2
    dispatched_names = {call.args[0].name for call in redeploy_mock.await_args_list}
    assert dispatched_names == {"user-1", "user-2"}


async def test_fanout_partial_recovery_dispatches_only_laggards(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """Critique X1 regression: re-submitting the current config redeploys
    only the deployment whose active instance is still at the previous
    config, leaving already-converged peers untouched.
    """
    target_config = EnvironmentConfig(env_vars={"FOO": "v2"})
    stale_config = EnvironmentConfig(env_vars={"FOO": "v1"})

    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="at-v2-a",
            active_env_config=target_config,
        ),
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="laggard-b",
            active_env_config=stale_config,
        ),
        _make_fanout_deployment(
            environment_id=uuid4(),
            name="at-v2-c",
            active_env_config=target_config,
        ),
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )
    # Pre-seed the environment row at v2 (the partial-fanout starting state).
    environment.config = target_config.model_dump(mode="json", exclude_none=True)
    environment.capabilities = compute_environment_capabilities(environment)

    redeploy_mock = mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        autospec=True,
    )

    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config=target_config.model_dump(mode="json", exclude_none=True),
    )

    assert redeploy_mock.await_count == 1
    assert redeploy_mock.await_args_list[0].args[0].name == "laggard-b"


async def test_fanout_per_deployment_failure_isolation(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """A dispatch raise on one deployment must not abort the fanout.

    The env-config row stays persisted, peer deployments dispatch
    successfully, the failed deployment's failure is logged, and the
    exception does not escape ``update_environment``.
    """
    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(), name="dep-a", active_env_config=None
        ),
        _make_fanout_deployment(
            environment_id=uuid4(), name="dep-b", active_env_config=None
        ),
        _make_fanout_deployment(
            environment_id=uuid4(), name="dep-c", active_env_config=None
        ),
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )

    async def fake_redeploy(deployment, uow):  # noqa: ARG001
        if deployment.name == "dep-b":
            raise RuntimeError("simulated render failure on B")
        return None

    redeploy_mock = mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        side_effect=fake_redeploy,
    )
    log_info = mocker.patch(
        "styrmin_backend.services.environments.logger.info",
    )
    log_exception = mocker.patch(
        "styrmin_backend.services.environments.logger.exception",
    )

    new_config = {"env_vars": {"FOO": "bar"}}
    # MUST NOT raise.
    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config=new_config,
    )

    # All three were attempted (B raised but A and C dispatched).
    assert redeploy_mock.await_count == 3
    # The exception logger fired exactly once for B.
    assert log_exception.call_count == 1
    failure_log_args = log_exception.call_args.args
    assert "env_config_fanout_dispatch_error" in failure_log_args[0]

    # The structured fanout log shows dispatched=2, dispatch_failed=1.
    fanout_log_calls = [
        call
        for call in log_info.call_args_list
        if call.args and "env_config_fanout_dispatched" in call.args[0]
    ]
    assert len(fanout_log_calls) == 1
    args = fanout_log_calls[0].args
    assert args[2] == 3  # evaluated
    assert args[3] == 2  # dispatched
    assert args[4] == 0  # skipped_noop
    assert args[5] == 1  # dispatch_failed

    # The env-config row persisted despite B's failure.
    refreshed = await uow.environments.get(environment.id)
    assert refreshed is not None
    assert refreshed.config == new_config


async def test_fanout_commits_env_config_before_dispatch(
    uow,
    fake_cluster: Cluster,
    mocker,
):
    """FR-009a: env-config row MUST be committed before any redeploy
    dispatch runs. Pin by raising on the first dispatch and asserting the
    row is observable through ``uow.environments.get`` after the call
    despite the failure (and despite the per-deployment isolation
    swallowing the error).
    """
    deployments = [
        _make_fanout_deployment(
            environment_id=uuid4(), name="first", active_env_config=None
        ),
        _make_fanout_deployment(
            environment_id=uuid4(), name="second", active_env_config=None
        ),
    ]
    environment = await _seed_environment_and_deployments(
        uow, cluster=fake_cluster, deployments=deployments
    )

    new_config = {"env_vars": {"COMMIT_FIRST": "yes"}}

    # Snapshot the persisted config inside the redeploy callback. If the
    # commit happens AFTER the loop, the snapshot will not reflect the
    # new value.
    persisted_during_dispatch: dict[str, Any] = {}

    async def first_dispatch_raises(deployment, uow):  # noqa: ARG001
        # Read the env row through the same UoW; it must already show
        # the new config because the commit is supposed to have run
        # before this loop iteration.
        env = await uow.environments.get(environment.id)
        assert env is not None
        persisted_during_dispatch["config"] = env.config
        if deployment.name == "first":
            raise RuntimeError("boom")

    mocker.patch(
        "styrmin_backend.services.environments.redeploy_for_environment_update",
        side_effect=first_dispatch_raises,
    )
    # Suppress the structured exception log to keep test output clean.
    mocker.patch("styrmin_backend.services.environments.logger.exception")

    await update_environment(
        environment_id=environment.id,
        uow=uow,
        config=new_config,
    )

    # The snapshot taken BEFORE any dispatch attempt finished must already
    # show the new config — i.e. the commit ran before the loop body.
    assert persisted_during_dispatch["config"] == new_config
    # And the row is still persisted at the new config after the failure.
    refreshed = await uow.environments.get(environment.id)
    assert refreshed is not None
    assert refreshed.config == new_config
