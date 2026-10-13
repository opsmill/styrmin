"""One failing redeploy or controller check does not undo the rest of the transaction (021 review F1, F2, F5).

The tests drive ``updateCluster`` and ``reportDeploymentStatuses`` over HTTP on
the real SQLModel session. Context generation, which opens its own
``async with uow`` block, fails for the second deployment it runs for, so a
redeploy already written in the same transaction precedes the failure whatever
order the deployments are listed in.
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
    DeploymentStatus,
    Task,
    TaskType,
)
from styrmin_backend.services import cluster_config_fanout, deployment_status
from styrmin_backend.services import context as context_module
from styrmin_backend.services.env_vars.exceptions import EnvVarSizeLimitExceededError

from .conftest import gql
from .seeds import (
    seed_application_driver_version,
    seed_cluster,
    seed_deployment,
    seed_environment,
)


@pytest.fixture(autouse=True)
def prefect(prefect_manager_mock: MagicMock) -> MagicMock:
    prefect_manager_mock.run_action = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    return prefect_manager_mock


@pytest.fixture(autouse=True)
def patch_crd(mocker) -> AsyncMock:
    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource",
        new_callable=AsyncMock,
    )


def _fail_second_context_generation(mocker) -> list[UUID]:
    """Raise inside ``generate_context_from_deployment``'s ``async with uow`` block for the second deployment.

    Returns the list that receives the id of the deployment that failed.
    """
    original = context_module._populate_component_env_vars
    seen: list[UUID] = []
    failed: list[UUID] = []

    def _populate(*, context: Any, **kwargs: Any) -> None:
        seen.append(context.instance.deployment_id)
        if len(seen) == 2:
            failed.append(context.instance.deployment_id)
            raise EnvVarSizeLimitExceededError(scope="resolved", bytes=1, cap=0)
        original(context=context, **kwargs)

    mocker.patch.object(
        context_module, "_populate_component_env_vars", side_effect=_populate
    )
    return failed


async def _task_types(session: AsyncSession, deployment_id: UUID) -> list[TaskType]:
    rows = await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    return [task.type for task in rows.all()]


async def _status(session: AsyncSession, deployment_id: UUID) -> DeploymentState:
    row = await session.get(Deployment, deployment_id)
    assert row is not None
    return row.status


def _logged(log: MagicMock) -> list[str]:
    return [
        call.args[0].format(*call.args[1:]) for call in log.call_args_list if call.args
    ]


def _fields(line: str) -> dict[str, str]:
    return dict(part.split("=", 1) for part in line.split()[1:])


async def test_status_report_commits_when_a_continued_redeploy_fails(
    client: AsyncClient, session: AsyncSession, mocker
) -> None:
    """F1: the controller's RUNNING state and snapshot commit; the other application is redeployed."""
    cluster = await seed_cluster(session)
    environment = await seed_environment(session, cluster=cluster)
    adv = await seed_application_driver_version(session)
    controller = await seed_deployment(
        session,
        environment=environment,
        adv=adv,
        name="styrmin-ingress-controller",
        internal=True,
    )
    controller.status = DeploymentState.DEPLOYING
    session.add(controller)
    await session.commit()
    first = await seed_deployment(session, environment=environment, adv=adv)
    second = await seed_deployment(session, environment=environment, adv=adv)
    controller_id, application_ids = controller.id, {first.id, second.id}
    failed = _fail_second_context_generation(mocker)
    # Both modules share the loguru logger; the lines are told apart by their key.
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")
    log_exception = mocker.patch.object(cluster_config_fanout.logger, "exception")

    data = await gql(
        client,
        "report_deployment_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(controller_id),
                    "phase": "Ready",
                    "displayState": "Running",
                }
            ]
        },
    )

    result = data["reportDeploymentStatuses"]
    assert (result["statusesUpdated"], result["deploymentsUpdated"]) == (1, 1)
    session.expire_all()
    assert await _status(session, controller_id) == DeploymentState.RUNNING
    snapshot = (
        await session.exec(
            select(DeploymentStatus).where(
                DeploymentStatus.deployment_id == controller_id
            )
        )
    ).first()
    assert snapshot is not None
    assert snapshot.phase == "Ready"
    [bad_id] = failed
    [good_id] = application_ids - {bad_id}
    assert await _task_types(session, good_id) == [TaskType.UPDATE_INSTANCE]
    assert await _status(session, good_id) == DeploymentState.DEPLOYING
    assert await _task_types(session, bad_id) == []
    assert await _status(session, bad_id) == DeploymentState.PENDING
    [failure] = _logged(log_exception)
    assert failure.startswith("cluster_config_fanout_dispatch_error ")
    assert _fields(failure)["deployment_id"] == str(bad_id)
    [continued] = [
        line
        for line in _logged(log_info)
        if line.startswith("cluster_config_fanout_continued ")
    ]
    assert _fields(continued)["dispatched"] == "1"
    assert _fields(continued)["dispatch_failed"] == "1"


async def test_update_cluster_returns_normally_when_one_redeploy_fails(
    client: AsyncClient, session: AsyncSession, prefect: MagicMock, mocker
) -> None:
    """F2: the other applications of both environments keep their redeploy and the update succeeds."""
    cluster = await seed_cluster(session)
    first_environment = await seed_environment(session, cluster=cluster)
    second_environment = await seed_environment(session, cluster=cluster)
    adv = await seed_application_driver_version(session)
    deployment_ids = {
        (await seed_deployment(session, environment=environment, adv=adv)).id
        for environment in (first_environment, first_environment, second_environment)
    }
    cluster_id = cluster.id
    failed = _fail_second_context_generation(mocker)
    log_info = mocker.patch.object(cluster_config_fanout.logger, "info")

    data = await gql(
        client,
        "update_cluster",
        {"clusterId": str(cluster_id), "input": {"fqdnSuffix": "apps.example.com"}},
    )

    result = data["updateCluster"]
    assert result["cluster"]["config"]["fqdn_suffix"] == "apps.example.com"
    session.expire_all()
    [bad_id] = failed
    assert {UUID(entry["deploymentId"]) for entry in result["redeployed"]} == (
        deployment_ids - {bad_id}
    )
    assert all(entry["taskId"] for entry in result["redeployed"])
    assert [entry["deploymentId"] for entry in result["failedToStart"]] == [str(bad_id)]
    for redeployed in deployment_ids - {bad_id}:
        assert await _task_types(session, redeployed) == [TaskType.UPDATE_INSTANCE]
        assert await _status(session, redeployed) == DeploymentState.DEPLOYING
    assert await _task_types(session, bad_id) == []
    assert await _status(session, bad_id) == DeploymentState.PENDING
    assert prefect.run_action.await_count == 2
    [line] = [
        line for line in _logged(log_info) if line.startswith("cluster_config_fanout ")
    ]
    fields = _fields(line)
    assert fields["environments"] == "2"
    assert fields["environments_failed"] == "0"
    assert fields["dispatched"] == "2"
    assert fields["dispatch_failed"] == "1"


async def test_status_report_commits_when_the_removal_check_fails_after_a_deletion(
    client: AsyncClient, session: AsyncSession, patch_crd: AsyncMock, mocker
) -> None:
    """F5: an application reaching DELETED is tombstoned although the controller check raises."""
    cluster = await seed_cluster(session)
    environment = await seed_environment(session, cluster=cluster)
    # A stored value that no longer validates makes the removal check raise.
    environment.config = {"dedicated_ingress": {"removed_field": True}}
    session.add(environment)
    await session.commit()
    adv = await seed_application_driver_version(session)
    await seed_deployment(
        session,
        environment=environment,
        adv=adv,
        name="styrmin-ingress-controller",
        internal=True,
    )
    remaining = await seed_deployment(
        session, environment=environment, adv=adv, name="remaining"
    )
    remaining.status = DeploymentState.RUNNING
    deleted = await seed_deployment(
        session, environment=environment, adv=adv, name="deleted"
    )
    deleted.status = DeploymentState.DELETING
    session.add_all([remaining, deleted])
    await session.commit()
    deleted_id = deleted.id
    log_exception = mocker.patch.object(deployment_status.logger, "exception")

    data = await gql(
        client,
        "report_deployment_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(deleted_id),
                    "phase": "Deleted",
                    "displayState": "Deleted",
                }
            ]
        },
    )

    result = data["reportDeploymentStatuses"]
    assert (result["statusesUpdated"], result["deploymentsUpdated"]) == (1, 1)
    session.expire_all()
    row = await session.get(Deployment, deleted_id)
    assert row is not None
    assert row.status == DeploymentState.DELETED
    assert row.deleted_at is not None
    patch_crd.assert_not_awaited()
    [failure] = _logged(log_exception)
    assert failure.startswith("cluster_config_fanout_hook_error ")


async def test_update_cluster_continues_after_an_environment_transaction_rolls_back(
    client: AsyncClient, session: AsyncSession, mocker
) -> None:
    """Review: each environment commits on its own, and a rolled-back environment does not stop the next."""
    cluster = await seed_cluster(session)
    broken = await seed_environment(session, cluster=cluster, name="broken")
    healthy = await seed_environment(session, cluster=cluster, name="healthy")
    adv = await seed_application_driver_version(session)
    stuck = await seed_deployment(session, environment=broken, adv=adv)
    redeployed = await seed_deployment(session, environment=healthy, adv=adv)
    broken.config = {"removed_field": True}
    session.add(broken)
    await session.commit()
    cluster_id, stuck_id, redeployed_id = cluster.id, stuck.id, redeployed.id
    log_exception = mocker.patch.object(cluster_config_fanout.logger, "exception")

    data = await gql(
        client,
        "update_cluster",
        {"clusterId": str(cluster_id), "input": {"fqdnSuffix": "apps.example.com"}},
    )

    result = data["updateCluster"]
    assert result["cluster"]["config"]["fqdn_suffix"] == "apps.example.com"
    assert result["failedEnvironments"] == [{"environmentName": "broken"}]
    assert [entry["deploymentId"] for entry in result["redeployed"]] == [
        str(redeployed_id)
    ]
    session.expire_all()
    assert await _task_types(session, redeployed_id) == [TaskType.UPDATE_INSTANCE]
    assert await _task_types(session, stuck_id) == []
    [failure] = _logged(log_exception)
    assert failure.startswith("cluster_config_fanout_environment_error ")
