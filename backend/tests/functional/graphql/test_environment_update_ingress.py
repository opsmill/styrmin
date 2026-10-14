"""``updateEnvironment`` manages the environment's dedicated ingress controller (#424).

The tests drive the mutation over HTTP on the real SQLModel session, so the
controller is attributed to the calling administrator and each redeploy runs
in its own savepoint, as in the cluster config fan-out (ADR-066).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import (
    Deployment,
    DeploymentState,
    Task,
    TaskType,
    User,
)
from styrmin_backend.services import cluster_config_fanout
from styrmin_backend.services import context as context_module
from styrmin_backend.services.env_vars.exceptions import EnvVarSizeLimitExceededError
from styrmin_backend.services.ingress_controller.driver import INTERNAL_DRIVER_NAME

from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_cluster,
    seed_deployment,
    seed_environment,
)

_LOAD_BALANCER = {"dedicatedIngress": {"service": {"type": "LoadBalancer"}}}


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    return prefect_manager_mock


async def _task_types(session: AsyncSession, deployment_id: UUID) -> list[TaskType]:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return [task.type for task in rows.all()]


async def _controllers(session: AsyncSession, environment_id: UUID) -> list[Deployment]:
    rows = await session.exec(
        select(Deployment).where(
            Deployment.environment_id == environment_id,
            Deployment.internal == True,  # noqa: E712 — SQL expression
        )
    )
    return list(rows.all())


def _logged(log: MagicMock) -> list[str]:
    return [
        call.args[0].format(*call.args[1:]) for call in log.call_args_list if call.args
    ]


def _fields(line: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in line.split()[1:])


async def test_adding_dedicated_ingress_creates_the_controller_for_the_caller(
    client: AsyncClient, session: AsyncSession, admin_user: User
) -> None:
    """The controller is created first; the application waits for it."""
    cluster = await seed_cluster(session)
    environment = await seed_environment(session, cluster=cluster)
    await seed_application_driver_version(session, driver_name=INTERNAL_DRIVER_NAME)
    adv = await seed_application_driver_version(session)
    application = await seed_deployment(session, environment=environment, adv=adv)
    environment_id, application_id, admin_id = (
        environment.id,
        application.id,
        admin_user.id,
    )

    data = await gql(
        client,
        "update_environment",
        {"environmentId": str(environment_id), "input": _LOAD_BALANCER},
    )

    assert data["updateEnvironment"]["config"] == {
        "dedicated_ingress": {"service": {"type": "LoadBalancer"}}
    }
    session.expire_all()
    [controller] = await _controllers(session, environment_id)
    assert controller.created_by_user_id == admin_id
    assert await _task_types(session, controller.id) == [TaskType.CREATE_INSTANCE]
    assert await _task_types(session, application_id) == []


async def test_one_failing_redeploy_keeps_the_others(
    client: AsyncClient, session: AsyncSession, prefect: MagicMock, mocker
) -> None:
    """The redeploy written before the failure is committed with the update."""
    cluster = await seed_cluster(session)
    environment = await seed_environment(session, cluster=cluster)
    adv = await seed_application_driver_version(session)
    deployment_ids = {
        (await seed_deployment(session, environment=environment, adv=adv)).id
        for _ in range(2)
    }
    environment_id = environment.id
    original = context_module._populate_component_env_vars
    seen: list[UUID] = []

    def _fail_the_second(*, context: Any, **kwargs: Any) -> None:  # noqa: ANN401
        seen.append(context.instance.deployment_id)
        if len(seen) == 2:
            raise EnvVarSizeLimitExceededError(scope="resolved", bytes=1, cap=0)
        original(context=context, **kwargs)

    mocker.patch.object(
        context_module, "_populate_component_env_vars", side_effect=_fail_the_second
    )
    # Both modules share the loguru logger; the lines are told apart by their key.
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")
    log_exception = mocker.patch.object(cluster_config_fanout.logger, "exception")

    await gql(
        client,
        "update_environment",
        {
            "environmentId": str(environment_id),
            "input": {"envVars": [{"name": "FOO", "value": "bar"}]},
        },
    )

    session.expire_all()
    good_id, bad_id = seen
    assert await _task_types(session, good_id) == [TaskType.UPDATE_INSTANCE]
    assert (await session.get(Deployment, good_id)).status == DeploymentState.DEPLOYING
    assert await _task_types(session, bad_id) == []
    assert {good_id, bad_id} == deployment_ids
    assert prefect.run_action.await_count == 1
    [failure] = _logged(log_exception)
    assert failure.startswith("env_config_fanout_dispatch_error ")
    assert _fields(failure)["deployment_id"] == str(bad_id)
    [line] = [
        line
        for line in _logged(log_info)
        if line.startswith("env_config_fanout_dispatched ")
    ]
    assert _fields(line)["dispatched"] == "1"
    assert _fields(line)["dispatch_failed"] == "1"
