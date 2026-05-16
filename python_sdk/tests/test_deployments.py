"""Tests for deployment resource operations."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from styrmin_sdk import (
    DeploymentRestoringError,
    OperationFailedError,
    ResourceNotFoundError,
    StyrminClient,
)


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
                "deletedAt": None,
                "config": {},
                "parameters": {},
                "applicationVersion": "1.0.0",
                "applicationDriverVersionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "applicationDriverVersion": None,
                "environmentId": "22222222-3333-4444-5555-666666666666",
                "createdBy": {
                    "id": "55555555-6666-7777-8888-999999999999",
                    "username": "alice",
                    "displayName": "Alice",
                },
                "applicationInstance": {"id": "33333333-4444-5555-6666-777777777777", "status": "running"},
                "components": [
                    {"id": "44444444-5555-6666-7777-888888888888", "name": "web", "enabled": True},
                ],
                "deployedServices": [],
            }
        }
    }

    deployment = await client.deployments.get("11111111-2222-3333-4444-555555555555")

    assert deployment.status == "deployed"
    assert deployment.deleted_at is None
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
    # Imported locally — matches the precedent in
    from styrmin_sdk.models import (
        ComponentConfigInput,
        EnvVarInput,
        ParameterValueInput,
        UpdateDeploymentInput,
    )

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

    task = await client.deployments.update(
        "11111111-2222-3333-4444-555555555555",
        input=UpdateDeploymentInput(
            name="renamed-app",
            env_vars=[EnvVarInput(name="LOG_LEVEL", value="debug")],
            parameters=[ParameterValueInput(name="replicas", value=3)],
            components=[
                ComponentConfigInput(
                    name="web",
                    env_vars=[EnvVarInput(name="WEB_FLAG", value="on")],
                ),
            ],
        ),
    )
    assert task.status == "pending"

    # Verify the transport received the typed input serialised under the
    # ``input`` variable with camelCase aliases and no None-valued fields.
    mock_transport.execute.assert_awaited_once()
    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables["deploymentId"] == "11111111-2222-3333-4444-555555555555"
    assert sent_variables["input"] == {
        "name": "renamed-app",
        "parameters": [{"name": "replicas", "value": 3}],
        "components": [
            {
                "name": "web",
                "envVars": [{"name": "WEB_FLAG", "value": "on"}],
            },
        ],
        "envVars": [{"name": "LOG_LEVEL", "value": "debug"}],
    }


# ---------------------------------------------------------------------------
# delete_deployment (spec 008)
# ---------------------------------------------------------------------------


async def test_delete_deployment_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "deleteDeployment": {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "type": "delete_deployment",
                "status": "success",
                "message": None,
                "deploymentId": "11111111-2222-3333-4444-555555555555",
            },
        }
    }

    task = await client.deployments.delete("11111111-2222-3333-4444-555555555555")

    assert task.type_ == "delete_deployment"
    assert task.status == "success"
    assert str(task.deployment_id) == "11111111-2222-3333-4444-555555555555"


async def test_delete_deployment_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """Conflated with already-deleted; both surface NOT_FOUND. Scripts
    treat this as the natural success outcome for a no-op cleanup."""
    mock_transport.execute.return_value = {
        "data": {"deleteDeployment": None},
        "errors": [{"message": "Deployment not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Deployment not found"):
        await client.deployments.delete("11111111-2222-3333-4444-555555555555")


async def test_delete_deployment_restoring_raises_typed_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A restore-in-progress deployment refuses delete with a code that
    automation can specifically catch (rather than swallowing all errors)."""
    mock_transport.execute.return_value = {
        "data": {"deleteDeployment": None},
        "errors": [
            {
                "message": "Cannot delete a deployment while a restore is in progress",
                "extensions": {"code": "DEPLOYMENT_RESTORING"},
            }
        ],
    }

    with pytest.raises(DeploymentRestoringError, match="restore is in progress"):
        await client.deployments.delete("11111111-2222-3333-4444-555555555555")
