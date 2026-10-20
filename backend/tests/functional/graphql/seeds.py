"""Shared seed helpers for propagation tests.

These helpers build minimum viable persisted graphs so a propagation test can
focus on the GraphQL boundary it cares about. All seeds use the *real*
DB session passed in by the ``session`` fixture — no fakes, per the
propagation test contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

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
    Role,
    Task,
    TaskStatus,
    TaskType,
    User,
)
from styrmin_backend.services.auth.password import hash_password

VALID_CLUSTER_CONFIG = {"runtime_class": "example_runtime_class"}


def global_context_dict(
    *,
    deployment_id: UUID | None = None,
    environment_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A serialised ``GlobalContext`` for an instance's ``context`` column.

    The deployment repository rehydrates an active instance through
    ``GlobalContext.model_validate``, so an active instance without a valid
    context cannot be loaded. ``deployment_id`` sets the instance's deployment
    and its ``styrmin-<deployment id>`` namespace; ``environment_config`` sets
    the ``environment.config`` slice.
    """
    deployment_id = deployment_id or uuid4()
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(
            name="seed-env",
            config=EnvironmentConfig.model_validate(environment_config or {}),
        ),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=f"styrmin-{deployment_id}",
            release_reference="seed-ref",
        ),
        app=ApplicationContext(
            name="seed-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="seed-chart",
                    version="0.1.0",
                    values_template="",
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    ).model_dump(mode="json")


async def seed_backup_storage_location(
    session: AsyncSession, name: str | None = None
) -> BackupStorageLocation:
    bsl = BackupStorageLocation(
        name=name or f"bsl-{uuid4().hex[:8]}",
        endpoint="https://s3.example.com",
        bucket="seed-bucket",
        region="eu-west-1",
        access_key_id="seed-key",
        secret_access_key="seed-secret",
    )
    session.add(bsl)
    await session.commit()
    return bsl


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
    driver: ApplicationDriver | None = None,
    application_supported_versions: str = ">=1.0.0",
    default_version: str | None = None,
    content_hash: str | None = None,
    source_commit_sha: str | None = None,
    created_on: datetime | None = None,
) -> ApplicationDriverVersion:
    """Seed a driver version (and its driver/chart graph).

    Pass ``driver`` to attach a second version to an existing driver —
    e.g. for overlapping ``application_supported_versions`` reselection
    tests. Distinct rows on the same driver must differ in ``version`` or
    fingerprint (``content_hash``/``source_commit_sha``) to satisfy the
    identity index. ``created_on`` overrides the server default for
    deterministic latest-wins tie-break tests.
    """
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
    if driver is None:
        driver = ApplicationDriver(name=driver_name or f"driver-{uuid4().hex[:8]}")
        session.add(driver)
        await session.commit()
    adv = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=application_supported_versions,
        default_version=default_version,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        content_hash=content_hash,
        source_commit_sha=source_commit_sha,
        helm_chart_id=chart.id,
    )
    if created_on is not None:
        adv.created_on = created_on
    session.add(adv)
    await session.commit()
    return adv


async def seed_user(
    session: AsyncSession,
    *,
    username: str | None = None,
    role: Role = Role.ADMIN,
    display_name: str | None = None,
) -> User:
    """Seed a User row used as the ``created_by`` target for a deployment.

    The default role is ADMIN so seeded deployments default to an
    attribution that satisfies admin-only User field gates when those
    are exercised by the test.
    """
    resolved_username = username or f"user-{uuid4().hex[:8]}"
    user = User(
        username=resolved_username,
        password_hash=hash_password("seed-password-not-used"),
        display_name=display_name or resolved_username,
        active=True,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def seed_deployment(
    session: AsyncSession,
    *,
    environment: Environment | None = None,
    adv: ApplicationDriverVersion | None = None,
    name: str | None = None,
    internal: bool = False,
    creator: User | None = None,
) -> Deployment:
    if environment is None:
        environment = await seed_environment(session)
    if adv is None:
        adv = await seed_application_driver_version(session)
    if creator is None:
        creator = await seed_user(session)
    deployment = Deployment(
        name=name or f"deployment-{uuid4().hex[:8]}",
        application_version="1.0.0",
        status=DeploymentState.PENDING,
        environment_id=environment.id,
        application_driver_version_id=adv.id,
        internal=internal,
        created_by_user_id=creator.id,
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
    existing = await session.exec(
        select(func.count()).where(ApplicationInstance.deployment_id == deployment.id)
    )
    instance = ApplicationInstance(
        name=name or f"instance-{uuid4().hex[:8]}",
        application_version=adv.version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment.id,
        application_driver_version_id=adv.id,
        sequence=existing.one() + 1,
    )
    deployment.last_instance_sequence = instance.sequence
    session.add_all([instance, deployment])
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
