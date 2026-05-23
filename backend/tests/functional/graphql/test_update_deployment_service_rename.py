"""GraphQL-level repro for #237 — instance context reflects the renamed service.

See backend/tests/unit/services/test_update_deployment_service_rename.py
for the service-layer counterpart. This test pins the invariant at the
GraphQL boundary against a real DB session.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import ApplicationInstance, Deployment

from ._queries import load_query
from .seeds import seed_application_driver_version, seed_deployment


@pytest.mark.asyncio
async def test_service_rename_propagates_to_active_instance_context(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,
) -> None:
    """updateDeployment(serviceNameOverrides=…) must regenerate the active
    instance with the renamed service in its context.deployed_services.

    Without #237's two-UoW fix, the instance is generated BEFORE the
    DeployedService row is updated, so context.deployed_services carries
    the old name — this test would fail.
    """
    flow_info = type("FlowInfo", (), {"id": uuid4()})()
    prefect_manager_mock.run_action = AsyncMock(return_value=flow_info)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    adv = await seed_application_driver_version(session)
    adv.services = [
        {
            "name": "simple-app",
            "kind": "http",
            "scope": "internal",
            "port": 8080,
            "component": "web",
        }
    ]
    session.add(adv)
    await session.commit()

    deployment = await seed_deployment(session, adv=adv)
    deployment_id = deployment.id

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("update_deployment"),
            "variables": {
                "deploymentId": str(deployment_id),
                "input": {
                    "serviceNameOverrides": [
                        {
                            "driverServiceName": "simple-app",
                            "overrideName": "simple-app-v2",
                        }
                    ]
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload

    # Verify the active instance reflects the renamed service in its context.
    session.expire_all()
    result = await session.exec(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    dep = result.one()
    assert dep.active_application_instance_id is not None, (
        "Deployment must have an active instance after updateDeployment"
    )

    inst_result = await session.exec(
        select(ApplicationInstance).where(
            ApplicationInstance.id == dep.active_application_instance_id
        )
    )
    instance = inst_result.one()

    context = instance.context  # JSON-serialized dict
    deployed_services = context.get("deployed_services") or []
    resolved_names = {svc["resolved_name"] for svc in deployed_services}
    assert resolved_names == {"simple-app-v2"}, (
        f"Active instance context did not reflect the rename. "
        f"Expected {{'simple-app-v2'}}, got {resolved_names}. This is #237."
    )
