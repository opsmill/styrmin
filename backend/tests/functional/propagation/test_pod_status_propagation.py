"""Propagation tests for the PodStatus GraphQL surface."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import PodPhase, PodStatus

from .seeds import seed_cluster, seed_deployment, seed_environment

report_pod_statuses_mutation = """
    mutation ReportPodStatuses($reports: [DeploymentPodStatusReport!]!) {
        reportPodStatuses(reports: $reports) {
            success
            podsUpdated
            podsRemoved
        }
    }
"""

list_pod_statuses_query = """
    query ListPodStatuses(
        $deploymentId: UUID,
        $environmentId: UUID,
        $clusterId: UUID
    ) {
        podStatuses(
            deploymentId: $deploymentId,
            environmentId: $environmentId,
            clusterId: $clusterId
        ) {
            id
            podName
            namespace
            phase
            ready
            restartCount
            nodeName
        }
    }
"""


@pytest.mark.asyncio
async def test_report_pod_statuses_upserts_and_removes_stale(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment = await seed_deployment(session)
    deployment_id = deployment.id

    # Seed a stale pod that should be removed by the upsert.
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

    response = await client.post(
        "/graphql",
        json={
            "query": report_pod_statuses_mutation,
            "variables": {
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
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    response_data = payload["data"]["reportPodStatuses"]
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

    response = await client.post(
        "/graphql",
        json={"query": list_pod_statuses_query, "variables": variables},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    rows = payload["data"]["podStatuses"]
    names = {row["podName"] for row in rows}
    assert names == {"pod-a"}, (
        f"filter_arg={filter_arg} should restrict to pod-a; got {names}"
    )
