"""``Deployment.crdStatus`` returns the conditions of the agent's last status report (#548).

``reportDeploymentStatuses`` stores each condition's ``lastTransitionTime``;
``Deployment.crdStatus.conditions`` returns it, and ``null`` for a condition
reported without one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import DeploymentStatus

from .conftest import gql
from .seeds import seed_deployment

READY_AT = datetime(2026, 10, 22, 10, 0, 5, tzinfo=UTC)


@pytest.mark.asyncio
async def test_reported_condition_transition_time_reaches_crd_status(
    client: AsyncClient, session: AsyncSession
) -> None:
    deployment_id = (await seed_deployment(session)).id

    reported = await gql(
        client,
        "report_deployment_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(deployment_id),
                    "phase": "Ready",
                    "conditions": [
                        {
                            "type": "Ready",
                            "status": "True",
                            "lastTransitionTime": READY_AT.isoformat(),
                        },
                        {"type": "HelmReleaseRemediated", "status": "False"},
                    ],
                }
            ]
        },
    )
    assert reported["reportDeploymentStatuses"]["statusesUpdated"] == 1

    session.expire_all()
    row = (
        await session.exec(
            select(DeploymentStatus).where(
                DeploymentStatus.deployment_id == deployment_id
            )
        )
    ).one()
    assert row.conditions is not None
    assert [c["lastTransitionTime"] for c in row.conditions] == [
        READY_AT.isoformat(),
        None,
    ]

    data = await gql(
        client, "get_deployment_crd_status", {"deploymentId": str(deployment_id)}
    )
    crd_status = data["deployment"]["crdStatus"]
    assert crd_status["phase"] == "Ready"
    ready, remediated = crd_status["conditions"]
    assert (ready["type"], ready["status"]) == ("Ready", "True")
    assert datetime.fromisoformat(ready["lastTransitionTime"]) == READY_AT
    assert remediated["type"] == "HelmReleaseRemediated"
    assert remediated["lastTransitionTime"] is None
