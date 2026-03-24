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
    DeploymentStatus as DeploymentStatusEntity,
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
        status=DeploymentStatusEntity.PENDING,
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
        status=DeploymentStatusEntity.PENDING,
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

    loaded.status = DeploymentStatusEntity.RUNNING
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
