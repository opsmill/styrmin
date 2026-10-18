"""``restoreEnvironmentBackup`` manages the environment's dedicated ingress controller (#467).

The restore applies the reverted config with the fan-out of ``updateEnvironment``.
The tests restore config-only snapshots over HTTP on the real SQLModel session, so
every deployment of the environment gets the config fan-out and none a Velero
restore.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    ApplicationInstance,
    Deployment,
    DeploymentState,
    Environment,
    Task,
    TaskType,
    User,
)
from styrmin_backend.services.ingress_controller.driver import INTERNAL_DRIVER_NAME

from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_cluster,
    seed_deployment,
    seed_environment,
)

_LOAD_BALANCER = {"dedicated_ingress": {"service": {"type": "LoadBalancer"}}}
_NODE_PORT = {"dedicatedIngress": {"service": {"type": "NodePort", "nodePort": 30443}}}


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock):
    prefect_manager_mock.run_action.return_value = SimpleNamespace(id=uuid4())
    return prefect_manager_mock


async def _task_types(session: AsyncSession, deployment_id: UUID) -> list[TaskType]:
    rows = await session.exec(
        select(Task)
        .where(Task.deployment_id == deployment_id)
        .order_by(Task.created_on)
    )
    return [task.type for task in rows.all()]


async def _controllers(session: AsyncSession, environment_id: UUID) -> list[Deployment]:
    rows = await session.exec(
        select(Deployment).where(
            Deployment.environment_id == environment_id,
            Deployment.internal == True,  # noqa: E712 — SQL expression
        )
    )
    return list(rows.all())


async def _seed_environment_with_application(
    session: AsyncSession, config: dict
) -> tuple[Environment, Deployment]:
    environment = await seed_environment(session, cluster=await seed_cluster(session))
    environment.config = config
    session.add(environment)
    await session.commit()
    await seed_application_driver_version(session, driver_name=INTERNAL_DRIVER_NAME)
    application = await seed_deployment(
        session,
        environment=environment,
        adv=await seed_application_driver_version(session),
    )
    return environment, application


async def _back_up_and_restore_later(client: AsyncClient, environment_id: UUID):
    """Take a config-only snapshot now; return the coroutine function that restores it."""
    data = await gql(
        client, "create_environment_backup", {"environmentId": str(environment_id)}
    )
    snapshot = data["createEnvironmentBackup"]
    assert snapshot["status"] == "COMPLETED", snapshot
    assert snapshot["constituents"] == []

    async def restore() -> None:
        await gql(
            client,
            "restore_environment_backup",
            {"environmentBackupId": snapshot["id"]},
        )

    return restore


async def test_restore_that_turns_dedicated_ingress_on_creates_the_controller_for_the_caller(
    client: AsyncClient, session: AsyncSession, admin_user: User
) -> None:
    """The controller is created first; the application waits for it."""
    environment, application = await _seed_environment_with_application(
        session, _LOAD_BALANCER
    )
    environment_id, application_id, admin_id = (
        environment.id,
        application.id,
        admin_user.id,
    )
    restore = await _back_up_and_restore_later(client, environment_id)
    # Turned off since the snapshot, with no controller left.
    environment.config = {}
    session.add(environment)
    await session.commit()

    await restore()

    session.expire_all()
    assert (await session.get(Environment, environment_id)).config == _LOAD_BALANCER
    [controller] = await _controllers(session, environment_id)
    assert controller.created_by_user_id == admin_id
    assert await _task_types(session, controller.id) == [TaskType.CREATE_INSTANCE]
    assert await _task_types(session, application_id) == []


async def test_restore_that_changes_dedicated_ingress_redeploys_the_controller_first(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The steps to reproduce of #467: the controller goes back from NodePort to LoadBalancer."""
    environment, application = await _seed_environment_with_application(
        session, _LOAD_BALANCER
    )
    environment_id, application_id = environment.id, application.id
    restore = await _back_up_and_restore_later(client, environment_id)
    await gql(
        client,
        "update_environment",
        {"environmentId": str(environment_id), "input": _NODE_PORT},
    )
    session.expire_all()
    [controller] = await _controllers(session, environment_id)
    controller_id = controller.id
    controller.status = DeploymentState.RUNNING
    session.add(controller)
    await session.commit()

    await restore()

    session.expire_all()
    assert await _task_types(session, controller_id) == [
        TaskType.CREATE_INSTANCE,
        TaskType.UPDATE_INSTANCE,
    ]
    assert await _task_types(session, application_id) == []
    controller = await session.get(Deployment, controller_id)
    assert controller.status == DeploymentState.DEPLOYING
    instance = await session.get(
        ApplicationInstance, controller.active_application_instance_id
    )
    rendered = instance.context["instance"]["config"]["dedicated_ingress"]
    assert rendered["service"]["type"] == "LoadBalancer", rendered
