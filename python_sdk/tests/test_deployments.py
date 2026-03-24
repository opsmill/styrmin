"""Tests for deployment resource operations."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import Deployment, OperationFailedError, ResourceNotFoundError, StyrminClient, Task


async def test_create_deployment_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "deploy": {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "type": "deploy",
                "status": "pending",
                "message": None,
                "deploymentId": "11111111-2222-3333-4444-555555555555",
            },
        }
    }

    task = await client.deployments.create(
        driver="my-app",
        version="1.0.0",
        environment_id="22222222-3333-4444-5555-666666666666",
    )

    assert isinstance(task, Task)
    assert str(task.deployment_id) == "11111111-2222-3333-4444-555555555555"
    assert task.status == "pending"


async def test_create_deployment_failed(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"deploy": None},
        "errors": [{"message": "No matching driver version", "extensions": {"code": "OPERATION_FAILED"}}],
    }

    with pytest.raises(OperationFailedError, match="No matching driver version"):
        await client.deployments.create(driver="my-app", version="1.0.0", environment_id="some-id")


async def test_get_deployment_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "deployment": {
                "id": "11111111-2222-3333-4444-555555555555",
                "name": "my-app",
                "status": "deployed",
                "config": {},
                "applicationVersion": "1.0.0",
                "applicationDriverVersionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "environmentId": "22222222-3333-4444-5555-666666666666",
                "applicationInstance": {"id": "33333333-4444-5555-6666-777777777777", "status": "running"},
                "components": [
                    {"id": "44444444-5555-6666-7777-888888888888", "name": "web", "enabled": True},
                ],
            }
        }
    }

    deployment = await client.deployments.get("11111111-2222-3333-4444-555555555555")

    assert isinstance(deployment, Deployment)
    assert deployment.status == "deployed"
    assert deployment.application_version == "1.0.0"
    assert deployment.application_instance is not None
    assert deployment.application_instance.status == "running"
    assert len(deployment.components) == 1
    assert deployment.components[0].name == "web"


async def test_get_deployment_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"deployment": None},
        "errors": [{"message": "Deployment not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Deployment not found"):
        await client.deployments.get("11111111-2222-3333-4444-555555555555")


async def test_update_deployment_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "updateDeployment": {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "status": "pending",
                "type": "update",
                "message": None,
                "deploymentId": "11111111-2222-3333-4444-555555555555",
            },
        }
    }

    task = await client.deployments.update("11111111-2222-3333-4444-555555555555", config={"replicas": 3})
    assert isinstance(task, Task)
