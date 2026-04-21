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
# Name uniqueness relaxed to live deployments only
# ---------------------------------------------------------------------------


def _make_deployment(
    name: str,
    adv_id,
    env_id,
    *,
    status: DeploymentStateEntity = DeploymentStateEntity.RUNNING,
    deleted_at=None,
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
async def test_get_by_name_ignores_tombstoned(
    session: AsyncSession, prerequisites
) -> None:
    """A tombstoned deployment must not match ``get_by_name`` — the
    name is free for reuse by a new deployment."""
    from datetime import datetime, timezone

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    tombstoned = _make_deployment(
        "shared",
        adv.id,
        env.id,
        status=DeploymentStateEntity.DELETED,
        deleted_at=datetime.now(tz=timezone.utc),
    )
    await repo.save(tombstoned)
    await session.commit()

    assert await repo.get_by_name("shared") is None


@pytest.mark.asyncio
async def test_get_by_name_still_matches_in_progress_deletion(
    session: AsyncSession, prerequisites
) -> None:
    """A deployment mid-delete (``DELETION_REQUESTED`` /
    ``DELETION_IN_PROGRESS``, where ``deleted_at`` is still ``None``)
    still reserves its name — the slot only frees when teardown
    completes and ``deleted_at`` is set."""
    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    mid_delete = _make_deployment(
        "shared",
        adv.id,
        env.id,
        status=DeploymentStateEntity.DELETION_REQUESTED,
        deleted_at=None,
    )
    await repo.save(mid_delete)
    await session.commit()

    match = await repo.get_by_name("shared")
    assert match is not None
    assert match.id == mid_delete.id


@pytest.mark.asyncio
async def test_find_names_with_prefix_skips_tombstoned(
    session: AsyncSession, prerequisites
) -> None:
    """Auto-naming (``driver-N``) must reuse slots freed by deletion."""
    from datetime import datetime, timezone

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    tombstoned = _make_deployment(
        "driver-1",
        adv.id,
        env.id,
        status=DeploymentStateEntity.DELETED,
        deleted_at=datetime.now(tz=timezone.utc),
    )
    await repo.save(tombstoned)
    await session.commit()

    assert await repo.find_names_with_prefix("driver") == []


@pytest.mark.asyncio
async def test_partial_unique_index_allows_reusing_tombstoned_name(
    session: AsyncSession, prerequisites
) -> None:
    """Two deployments with the same name can coexist as long as one
    is tombstoned — the partial unique index only covers
    ``deleted_at IS NULL`` rows."""
    from datetime import datetime, timezone

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    tombstoned = _make_deployment(
        "shared",
        adv.id,
        env.id,
        status=DeploymentStateEntity.DELETED,
        deleted_at=datetime.now(tz=timezone.utc),
    )
    await repo.save(tombstoned)
    await session.commit()

    live = _make_deployment(
        "shared", adv.id, env.id, status=DeploymentStateEntity.RUNNING
    )
    await repo.save(live)
    await session.commit()

    # Both rows exist; only the live one is returned by name lookup.
    assert await repo.get_by_name("shared") is not None
    result = await session.exec(select(DeploymentModel))
    all_names = sorted(d.name for d in result.all())
    assert all_names == ["shared", "shared"]


@pytest.mark.asyncio
async def test_partial_unique_index_still_rejects_duplicate_live_names(
    session: AsyncSession, prerequisites
) -> None:
    """Two *live* deployments with the same name must still fail at
    the DB layer — the partial index enforces uniqueness on
    non-tombstoned rows."""
    from sqlalchemy.exc import IntegrityError

    repo = SQLModelDeploymentRepository(session)
    adv = prerequisites["app_driver_version"]
    env = prerequisites["environment"]

    first = _make_deployment(
        "shared", adv.id, env.id, status=DeploymentStateEntity.RUNNING
    )
    await repo.save(first)
    await session.commit()

    second = _make_deployment(
        "shared", adv.id, env.id, status=DeploymentStateEntity.RUNNING
    )
    with pytest.raises(IntegrityError):
        await repo.save(second)
        await session.commit()
