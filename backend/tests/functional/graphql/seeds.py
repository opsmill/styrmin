"""Shared seed helpers for propagation tests.

These helpers build minimum viable persisted graphs so a propagation test can
focus on the GraphQL boundary it cares about. All seeds use the *real*
DB session passed in by the ``session`` fixture — no fakes, per the
propagation test contract.
"""

from __future__ import annotations

from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    ApplicationInstance,
    BackupStorageLocation,
    Cluster,
    Deployment,
    DeploymentState,
    Environment,
    HelmChart,
    HelmRepository,
    InstanceStatus,
    Task,
    TaskStatus,
    TaskType,
)

VALID_CLUSTER_CONFIG = {"runtime_class": "example_runtime_class"}


async def seed_cluster(session: AsyncSession, name: str | None = None) -> Cluster:
    cluster = Cluster(
        name=name or f"cluster-{uuid4().hex[:8]}",
        config=VALID_CLUSTER_CONFIG,
    )
    session.add(cluster)
    await session.commit()
    return cluster


async def seed_environment(
    session: AsyncSession,
    *,
    cluster: Cluster | None = None,
    name: str | None = None,
    bsl: BackupStorageLocation | None = None,
) -> Environment:
    if cluster is None:
        cluster = await seed_cluster(session)
    env = Environment(
        name=name or f"env-{uuid4().hex[:8]}",
        cluster_id=cluster.id,
        backup_storage_location_id=bsl.id if bsl else None,
    )
    session.add(env)
    await session.commit()
    return env


async def seed_application_driver_version(
    session: AsyncSession,
    *,
    driver_name: str | None = None,
    version: str = "1.0.0",
) -> ApplicationDriverVersion:
    repo = HelmRepository(url=f"https://helm.example.com/{uuid4().hex[:6]}")
    session.add(repo)
    await session.commit()
    chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="name: {{ app.name }}",
        repository_id=repo.id,
    )
    session.add(chart)
    await session.commit()
    driver = ApplicationDriver(name=driver_name or f"driver-{uuid4().hex[:8]}")
    session.add(driver)
    await session.commit()
    adv = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        helm_chart_id=chart.id,
    )
    session.add(adv)
    await session.commit()
    return adv


async def seed_deployment(
    session: AsyncSession,
    *,
    environment: Environment | None = None,
    adv: ApplicationDriverVersion | None = None,
    name: str | None = None,
    internal: bool = False,
) -> Deployment:
    if environment is None:
        environment = await seed_environment(session)
    if adv is None:
        adv = await seed_application_driver_version(session)
    deployment = Deployment(
        name=name or f"deployment-{uuid4().hex[:8]}",
        application_version="1.0.0",
        status=DeploymentState.PENDING,
        environment_id=environment.id,
        application_driver_version_id=adv.id,
        internal=internal,
    )
    session.add(deployment)
    await session.commit()
    return deployment


async def seed_application_instance(
    session: AsyncSession,
    *,
    deployment: Deployment | None = None,
    name: str | None = None,
    adv: ApplicationDriverVersion | None = None,
) -> ApplicationInstance:
    if deployment is None:
        deployment = await seed_deployment(session)
    if adv is None:
        adv = await session.get(
            ApplicationDriverVersion, deployment.application_driver_version_id
        )
    assert adv is not None
    instance = ApplicationInstance(
        name=name or f"instance-{uuid4().hex[:8]}",
        application_version=adv.version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=adv.id,
    )
    session.add(instance)
    await session.commit()
    return instance


async def seed_task(
    session: AsyncSession,
    *,
    deployment: Deployment | None = None,
    task_type: TaskType = TaskType.NOOP,
    status: TaskStatus = TaskStatus.PENDING,
    message: str | None = None,
) -> Task:
    if deployment is None:
        deployment = await seed_deployment(session)
    task = Task(
        type=task_type,
        status=status,
        message=message,
        deployment_id=deployment.id,
    )
    session.add(task)
    await session.commit()
    return task
