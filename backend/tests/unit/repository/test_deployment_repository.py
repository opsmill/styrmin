from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    Deployment as DeploymentModel,
    Environment,
    HelmChart,
    HelmRepository,
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
from styrmin_backend.domain.models import (
    Deployment as DeploymentEntity,
    DeploymentState as DeploymentStateEntity,
    Instance as InstanceEntity,
    InstanceStatus as InstanceStatusEntity,
)
from styrmin_backend.repository.deployment import SQLModelDeploymentRepository


def _make_global_context(deployment_id, chart_id, repo_id) -> GlobalContext:
    """Build a minimal GlobalContext for testing."""
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
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


@pytest.fixture
async def prerequisites(session: AsyncSession):
    """Create all prerequisite DB records for a deployment."""
    helm_repo = HelmRepository(id=uuid4(), url="https://example.com/charts")
    session.add(helm_repo)

    helm_chart = HelmChart(
        id=uuid4(),
        name="test-chart",
        version="0.1.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    session.add(helm_chart)

    app_driver = ApplicationDriver(id=uuid4(), name="test-driver")
    session.add(app_driver)

    app_driver_version = ApplicationDriverVersion(
        id=uuid4(),
        application_driver_id=app_driver.id,
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        source_repository="https://example.com/repo",
        source_branch="main",
        helm_chart_id=helm_chart.id,
    )
    session.add(app_driver_version)

    cluster = Cluster(id=uuid4(), name="test-cluster")
    session.add(cluster)

    environment = Environment(id=uuid4(), name="test-env", cluster_id=cluster.id)
    session.add(environment)

    await session.flush()

    return {
        "helm_repo": helm_repo,
        "helm_chart": helm_chart,
        "app_driver_version": app_driver_version,
        "environment": environment,
    }


@pytest.mark.asyncio
async def test_save_deployment_with_new_instance(session: AsyncSession, prerequisites):
    """Saving a deployment with a new active instance should persist the FK."""
    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]
    helm_chart = prerequisites["helm_chart"]
    helm_repo = prerequisites["helm_repo"]

    deployment_id = uuid4()
    instance_id = uuid4()

    context = _make_global_context(deployment_id, helm_chart.id, helm_repo.id)

    deployment = DeploymentEntity(
        id=deployment_id,
        name="test-deployment",
        application_version="1.0.0",
        config={},
        application_driver_version_id=adv.id,
        environment_id=env.id,
        status=DeploymentStateEntity.PENDING,
    )
    deployment.set_active_instance(
        InstanceEntity(
            id=instance_id,
            name="test-instance",
            application_version="1.0.0",
            status=InstanceStatusEntity.PENDING,
            deployment_id=deployment_id,
            application_driver_version_id=adv.id,
            context=context,
        )
    )

    await repo.save(deployment)
    await session.commit()

    # Verify the FK was set in the database
    result = await session.exec(
        select(DeploymentModel).where(DeploymentModel.id == deployment_id)
    )
    db_deployment = result.first()
    assert db_deployment is not None
    assert db_deployment.active_application_instance_id == instance_id


@pytest.mark.asyncio
async def test_save_preserves_active_instance_on_round_trip(
    session: AsyncSession, prerequisites
):
    """find() then save() must not null out active_application_instance_id.

    This is the core regression test: load a deployment that already has an
    active instance, change an unrelated field (status), save it back, and
    verify the FK is still set.
    """
    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]
    helm_chart = prerequisites["helm_chart"]
    helm_repo = prerequisites["helm_repo"]

    deployment_id = uuid4()
    instance_id = uuid4()

    context = _make_global_context(deployment_id, helm_chart.id, helm_repo.id)

    # --- Step 1: create a deployment with an active instance ---
    deployment = DeploymentEntity(
        id=deployment_id,
        name="roundtrip-deployment",
        application_version="1.0.0",
        config={},
        application_driver_version_id=adv.id,
        environment_id=env.id,
        status=DeploymentStateEntity.PENDING,
    )
    deployment.set_active_instance(
        InstanceEntity(
            id=instance_id,
            name="roundtrip-instance",
            application_version="1.0.0",
            status=InstanceStatusEntity.PENDING,
            deployment_id=deployment_id,
            application_driver_version_id=adv.id,
            context=context,
        )
    )
    await repo.save(deployment)
    await session.commit()

    # --- Step 2: load it back, modify only the status, and save again ---
    loaded = await repo.find(id=deployment_id)
    assert loaded is not None
    assert loaded.active_instance is not None
    assert loaded.active_instance.id == instance_id

    loaded.status = DeploymentStateEntity.RUNNING
    await repo.save(loaded)
    await session.commit()

    # --- Step 3: verify FK is still set ---
    result = await session.exec(
        select(DeploymentModel).where(DeploymentModel.id == deployment_id)
    )
    db_deployment = result.first()
    assert db_deployment is not None
    assert db_deployment.active_application_instance_id == instance_id, (
        "active_application_instance_id was nulled out after a find() -> save() round-trip"
    )


# ---------------------------------------------------------------------------
# Scoped + tombstone-aware uniqueness queries (spec 008 follow-up)
# ---------------------------------------------------------------------------


def _seed_deployment(
    *,
    name: str,
    env_id,
    adv_id,
    deleted_at=None,
    status: DeploymentStateEntity = DeploymentStateEntity.PENDING,
) -> DeploymentEntity:
    return DeploymentEntity(
        id=uuid4(),
        name=name,
        application_version="1.0.0",
        config={},
        application_driver_version_id=adv_id,
        environment_id=env_id,
        status=status,
        deleted_at=deleted_at,
    )


@pytest.mark.asyncio
async def test_get_by_name_scopes_to_environment(session: AsyncSession, prerequisites):
    """``ansible`` in env A must not be returned when querying env B —
    name uniqueness is per-environment after spec 008's follow-up."""
    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env_a = prerequisites["environment"]

    cluster_b = Cluster(id=uuid4(), name="cluster-b")
    session.add(cluster_b)
    env_b = Environment(id=uuid4(), name="env-b", cluster_id=cluster_b.id)
    session.add(env_b)
    await session.flush()

    await repo.save(_seed_deployment(name="ansible", env_id=env_a.id, adv_id=adv.id))
    await session.commit()

    found_in_a = await repo.get_by_name("ansible", env_a.id)
    assert found_in_a is not None

    found_in_b = await repo.get_by_name("ansible", env_b.id)
    assert found_in_b is None, (
        "name lookup must not leak across environments — uniqueness is "
        "scoped per (environment_id, name)"
    )


@pytest.mark.asyncio
async def test_get_by_name_excludes_tombstoned_by_default(
    session: AsyncSession, prerequisites
):
    """A tombstoned deployment named ``ansible`` does NOT block a fresh
    ``ansible`` from being created — get_by_name returns None for the
    name-conflict check by default."""
    from datetime import datetime, timezone

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    tombstoned = _seed_deployment(
        name="ansible",
        env_id=env.id,
        adv_id=adv.id,
        deleted_at=datetime.now(tz=timezone.utc),
        status=DeploymentStateEntity.DELETED,
    )
    await repo.save(tombstoned)
    await session.commit()

    # Default lookup (used for name-conflict checks): tombstone is invisible.
    assert await repo.get_by_name("ansible", env.id) is None

    # Forensic / cleanup lookup with include_deleted=True: tombstone is found.
    forensic = await repo.get_by_name("ansible", env.id, include_deleted=True)
    assert forensic is not None
    assert forensic.id == tombstoned.id


@pytest.mark.asyncio
async def test_find_names_with_prefix_scopes_to_environment_and_excludes_tombstones(
    session: AsyncSession, prerequisites
):
    from datetime import datetime, timezone

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env_a = prerequisites["environment"]

    cluster_b = Cluster(id=uuid4(), name="cluster-b-2")
    session.add(cluster_b)
    env_b = Environment(id=uuid4(), name="env-b-2", cluster_id=cluster_b.id)
    session.add(env_b)
    await session.flush()

    # env A: one active "ansible-1", one tombstoned "ansible-2"
    await repo.save(_seed_deployment(name="ansible-1", env_id=env_a.id, adv_id=adv.id))
    await repo.save(
        _seed_deployment(
            name="ansible-2",
            env_id=env_a.id,
            adv_id=adv.id,
            deleted_at=datetime.now(tz=timezone.utc),
            status=DeploymentStateEntity.DELETED,
        )
    )
    # env B: one active "ansible-99" — must not show up in env A's prefix search.
    await repo.save(_seed_deployment(name="ansible-99", env_id=env_b.id, adv_id=adv.id))
    await session.commit()

    names_in_a = await repo.find_names_with_prefix("ansible", env_a.id)
    assert names_in_a == ["ansible-1"], (
        f"prefix search in env A must exclude tombstones AND env-B rows; "
        f"got {names_in_a}"
    )

    names_in_a_with_deleted = await repo.find_names_with_prefix(
        "ansible", env_a.id, include_deleted=True
    )
    assert sorted(names_in_a_with_deleted) == ["ansible-1", "ansible-2"]


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_active_collisions(
    session: AsyncSession, prerequisites
):
    """The DB-level partial index must reject two active deployments
    sharing (environment_id, name). This is the authoritative gate
    against races between concurrent service-layer checks."""
    from sqlalchemy.exc import IntegrityError

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    await repo.save(_seed_deployment(name="ansible", env_id=env.id, adv_id=adv.id))
    await session.commit()

    # The IntegrityError can fire on either the repo.save() (which
    # flushes) or the commit() — either way the partial unique index
    # is doing its job. Wrap both so the test captures the violation
    # regardless of when SQLite chooses to enforce it.
    with pytest.raises(IntegrityError):
        await repo.save(_seed_deployment(name="ansible", env_id=env.id, adv_id=adv.id))
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_partial_unique_index_allows_tombstone_then_recreate(
    session: AsyncSession, prerequisites
):
    """The user-visible promise: after deleting ``ansible``, an operator
    can create a new ``ansible`` in the same env. The partial index lets
    a tombstoned row coexist with a fresh active row of the same name."""
    from datetime import datetime, timezone

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    tombstoned = _seed_deployment(
        name="ansible",
        env_id=env.id,
        adv_id=adv.id,
        deleted_at=datetime.now(tz=timezone.utc),
        status=DeploymentStateEntity.DELETED,
    )
    await repo.save(tombstoned)
    await session.commit()

    # New active deployment with the same name — must succeed.
    fresh = _seed_deployment(name="ansible", env_id=env.id, adv_id=adv.id)
    await repo.save(fresh)
    await session.commit()  # would raise IntegrityError if the index was wrong
