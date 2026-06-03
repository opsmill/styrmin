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


async def test_create_deployment_with_driver_version_pin(client: StyrminClient, mock_transport: AsyncMock) -> None:
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

    await client.deployments.create(
        driver="my-app",
        version="1.0.0",
        environment_id="22222222-3333-4444-5555-666666666666",
        driver_version_id="77777777-8888-9999-aaaa-bbbbbbbbbbbb",
    )

    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables["driverVersionId"] == "77777777-8888-9999-aaaa-bbbbbbbbbbbb"


async def test_create_deployment_omits_driver_version_id_when_unset(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
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

    await client.deployments.create(
        driver="my-app",
        version="1.0.0",
        environment_id="22222222-3333-4444-5555-666666666666",
    )

    sent_variables = mock_transport.execute.await_args.args[1]
    assert "driverVersionId" not in sent_variables


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
                "applicationDriverVersion": {
                    "version": "1.0.0",
                    "contentHash": None,
                    "sourceCommitSha": None,
                },
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
# update_version (driver-version reselection / pinning)
# ---------------------------------------------------------------------------


_UPDATE_VERSION_RESPONSE = {
    "data": {
        "updateDeploymentVersion": {
            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "status": "pending",
            "type": "update_version",
            "message": None,
            "deploymentId": "11111111-2222-3333-4444-555555555555",
        },
    }
}


async def test_update_version_defaults_to_latest_wins(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """Without a pin, only deploymentId/version are sent — the backend's
    latest-wins resolution decides the driver-version binding."""
    mock_transport.execute.return_value = _UPDATE_VERSION_RESPONSE

    task = await client.deployments.update_version("11111111-2222-3333-4444-555555555555", "2.0.0")

    assert task.status == "pending"
    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables == {
        "deploymentId": "11111111-2222-3333-4444-555555555555",
        "version": "2.0.0",
    }


async def test_update_version_with_driver_version_pin(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = _UPDATE_VERSION_RESPONSE

    await client.deployments.update_version(
        "11111111-2222-3333-4444-555555555555",
        "2.0.0",
        driver_version_id="77777777-8888-9999-aaaa-bbbbbbbbbbbb",
    )

    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables["driverVersionId"] == "77777777-8888-9999-aaaa-bbbbbbbbbbbb"


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


# ---------------------------------------------------------------------------
# list (deployments-by-environment; backs the styrminctl deployment lookup)
# ---------------------------------------------------------------------------


async def test_list_deployments_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {
            "environment": {
                "deployments": [
                    {
                        "id": "11111111-2222-3333-4444-555555555555",
                        "name": "demo",
                        "status": "deployed",
                        "applicationInstance": {
                            "id": "33333333-4444-5555-6666-777777777777",
                            "status": "running",
                        },
                    },
                    {
                        "id": "99999999-8888-7777-6666-555555555555",
                        "name": "idle",
                        "status": "pending",
                        "applicationInstance": None,
                    },
                ]
            }
        }
    }

    deployments = await client.deployments.list("22222222-3333-4444-5555-666666666666")

    assert [d.name for d in deployments] == ["demo", "idle"]
    assert deployments[0].application_instance is not None
    assert str(deployments[0].application_instance.id) == "33333333-4444-5555-6666-777777777777"
    assert deployments[1].application_instance is None

    # Active instance excluded deleted deployments by default.
    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables == {
        "environmentId": "22222222-3333-4444-5555-666666666666",
        "includeDeleted": False,
    }


async def test_list_deployments_unknown_environment_returns_empty(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = {"data": {"environment": None}}

    deployments = await client.deployments.list("22222222-3333-4444-5555-666666666666")

    assert deployments == []
