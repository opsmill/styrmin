"""Propagation tests for the PodStatus GraphQL surface."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import Deployment, DeploymentState, PodPhase, PodStatus

from .conftest import gql
from .seeds import seed_cluster, seed_deployment, seed_environment


@pytest.mark.asyncio
async def test_report_pod_statuses_upserts_and_removes_stale(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    # Stale row exercises the remove-stale branch of the upsert.
    stale = PodStatus(
        pod_name="stale-pod",
        namespace="ns",
        phase=PodPhase.RUNNING,
        ready=True,
        restart_count=0,
        deployment_id=deployment_id,
    )
    session.add(stale)
    await session.commit()

    data = await gql(
        client,
        "report_pod_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(deployment_id),
                    "pods": [
                        {
                            "podName": "fresh-pod",
                            "namespace": "ns",
                            "phase": "RUNNING",
                            "ready": True,
                            "restartCount": 2,
                            "containerStatuses": None,
                            "nodeName": "node-1",
                            "startedAt": None,
                        }
                    ],
                }
            ]
        },
    )
    response_data = data["reportPodStatuses"]
    assert response_data["success"] is True
    assert response_data["podsUpdated"] == 1
    assert response_data["podsRemoved"] == 1

    session.expire_all()
    rows = (
        await session.exec(
            select(PodStatus).where(PodStatus.deployment_id == deployment_id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].pod_name == "fresh-pod"
    assert rows[0].namespace == "ns"
    assert rows[0].phase == PodPhase.RUNNING
    assert rows[0].ready is True
    assert rows[0].restart_count == 2
    assert rows[0].node_name == "node-1"


@pytest.mark.parametrize("filter_arg", ["deploymentId", "environmentId", "clusterId"])
@pytest.mark.asyncio
async def test_pod_statuses_filters_by_each_arg(
    client: AsyncClient, session: AsyncSession, filter_arg: str
) -> None:
    cluster_a = await seed_cluster(session, name="cluster-a")
    cluster_b = await seed_cluster(session, name="cluster-b")
    env_a = await seed_environment(session, cluster=cluster_a)
    env_b = await seed_environment(session, cluster=cluster_b)
    deployment_a = await seed_deployment(session, environment=env_a)
    deployment_b = await seed_deployment(session, environment=env_b)

    pod_a = PodStatus(
        pod_name="pod-a",
        namespace="ns",
        phase=PodPhase.RUNNING,
        ready=True,
        restart_count=0,
        deployment_id=deployment_a.id,
    )
    pod_b = PodStatus(
        pod_name="pod-b",
        namespace="ns",
        phase=PodPhase.RUNNING,
        ready=True,
        restart_count=0,
        deployment_id=deployment_b.id,
    )
    session.add_all([pod_a, pod_b])
    await session.commit()

    if filter_arg == "deploymentId":
        variables = {"deploymentId": str(deployment_a.id)}
    elif filter_arg == "environmentId":
        variables = {"environmentId": str(env_a.id)}
    else:
        variables = {"clusterId": str(cluster_a.id)}

    data = await gql(client, "list_pod_statuses", variables)
    names = {row["podName"] for row in data["podStatuses"]}
    assert names == {"pod-a"}, (
        f"filter_arg={filter_arg} should restrict to pod-a; got {names}"
    )


def _pod_report(deployment_id: UUID, pod_name: str) -> dict[str, Any]:
    return {
        "deploymentId": str(deployment_id),
        "pods": [
            {
                "podName": pod_name,
                "namespace": f"styrmin-{deployment_id}",
                "phase": "RUNNING",
                "ready": True,
                "restartCount": 0,
                "containerStatuses": None,
                "nodeName": "node-1",
                "startedAt": None,
            }
        ],
    }


@pytest.mark.parametrize("filter_arg", ["environmentId", "clusterId"])
@pytest.mark.asyncio
async def test_pod_statuses_of_environment_and_cluster_leave_out_deleted_deployments(
    client: AsyncClient, session: AsyncSession, filter_arg: str
) -> None:
    """A deployment that becomes DELETED keeps the pods of the agent's last report.

    The agent stops reporting a DELETED deployment, so nothing removes those rows.
    """
    cluster = await seed_cluster(session)
    environment = await seed_environment(session, cluster=cluster)
    remaining = await seed_deployment(session, environment=environment)
    deleted = await seed_deployment(session, environment=environment)
    deleted.status = DeploymentState.DELETING
    session.add(deleted)
    await session.commit()
    cluster_id, environment_id = cluster.id, environment.id
    remaining_id, deleted_id = remaining.id, deleted.id

    await gql(
        client,
        "report_pod_statuses",
        {
            "reports": [
                _pod_report(remaining_id, "remaining-pod"),
                _pod_report(deleted_id, "terminating-pod"),
            ]
        },
    )
    reported = await gql(
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
    assert reported["reportDeploymentStatuses"]["deploymentsUpdated"] == 1
    session.expire_all()
    tombstoned = await session.get(Deployment, deleted_id)
    assert tombstoned is not None
    assert tombstoned.deleted_at is not None

    if filter_arg == "environmentId":
        variables = {"environmentId": str(environment_id)}
    else:
        variables = {"clusterId": str(cluster_id)}
    data = await gql(client, "list_pod_statuses", variables)

    assert {row["podName"] for row in data["podStatuses"]} == {"remaining-pod"}
    # The deployment's own read is unchanged.
    data = await gql(client, "list_pod_statuses", {"deploymentId": str(deleted_id)})
    assert {row["podName"] for row in data["podStatuses"]} == {"terminating-pod"}
