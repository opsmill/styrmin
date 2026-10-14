"""Tests for deployment resource operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from styrmin_sdk import (
    DeploymentRestoringError,
    OperationFailedError,
    ResourceNotFoundError,
    StyrminClient,
)
from styrmin_sdk.exceptions import (
    ApplyError,
    BatchNameConflictError,
    DriverMismatchError,
    EnvironmentAmbiguityError,
    EnvironmentNotFoundError,
    ResourceAlreadyExistsError,
)
from styrmin_sdk.models.deployment_manifest import ApplyOutcome, ApplyOverrides, ResolvedManifest


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
                "componentImageOverrides": [
                    {
                        "component": "web",
                        "reference": "registry.example/acme/web:{{ app.version }}",
                        "resolvedReference": "registry.example/acme/web:1.0.0",
                        "isOrphaned": False,
                        "isApplicable": True,
                    }
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
    [override] = deployment.component_image_overrides
    assert override.component == "web"
    assert override.resolved_reference == "registry.example/acme/web:1.0.0"
    assert override.is_applicable is True


async def test_get_deployment_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"deployment": None},
        "errors": [{"message": "Deployment not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError, match="Deployment not found"):
        await client.deployments.get("11111111-2222-3333-4444-555555555555")


async def test_get_by_name_success(client: StyrminClient, mock_transport: AsyncMock) -> None:
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
                    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "applicationDriver": {
                        "id": "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb",
                        "name": "my-app",
                    },
                },
                "environmentId": "22222222-3333-4444-5555-666666666666",
                "applicationInstance": {"id": "33333333-4444-5555-6666-777777777777", "status": "running"},
                "components": [
                    {"id": "44444444-5555-6666-7777-888888888888", "name": "web", "enabled": True},
                ],
                "deployedServices": [],
            }
        }
    }

    deployment = await client.deployments.get_by_name("my-app", environment_id="22222222-3333-4444-5555-666666666666")

    assert deployment is not None
    assert deployment.name == "my-app"
    assert deployment.status == "deployed"
    assert deployment.application_version == "1.0.0"
    assert str(deployment.environment_id) == "22222222-3333-4444-5555-666666666666"

    call_args = mock_transport.execute.call_args
    assert call_args.args[1] == {
        "name": "my-app",
        "environmentId": "22222222-3333-4444-5555-666666666666",
    }


async def test_get_by_name_returns_none_on_miss(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"deployment": None}}

    deployment = await client.deployments.get_by_name(
        "missing-app", environment_id="22222222-3333-4444-5555-666666666666"
    )

    assert deployment is None


async def test_get_by_name_returns_none_on_internal_hidden(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """The backend collapses internal-hidden rows to a null payload (the
    internal-vs-truly-missing distinction is verified at the GraphQL layer
    in chunk 2). Here we just confirm the SDK passes that null straight
    through as ``None`` without raising."""
    mock_transport.execute.return_value = {"data": {"deployment": None}}

    deployment = await client.deployments.get_by_name(
        "internal-app", environment_id="22222222-3333-4444-5555-666666666666"
    )

    assert deployment is None


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
    assert task is not None
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

    assert task is not None
    assert task.status == "pending"
    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables == {
        "deploymentId": "11111111-2222-3333-4444-555555555555",
        "version": "2.0.0",
    }
    # Without input, the operation leaves out the argument older servers do not know.
    assert mock_transport.execute.await_args.args[0].lstrip().startswith("mutation UpdateDeploymentVersion(")


async def test_update_version_with_input_uses_its_own_operation(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    from styrmin_sdk.models import UpdateDeploymentInput

    mock_transport.execute.return_value = _UPDATE_VERSION_RESPONSE

    task = await client.deployments.update_version(
        "11111111-2222-3333-4444-555555555555",
        "2.0.0",
        input=UpdateDeploymentInput.model_validate({"ipWhitelist": ["10.0.0.0/8"]}),
    )

    assert task is not None
    query, variables = mock_transport.execute.await_args.args
    assert query.lstrip().startswith("mutation UpdateDeploymentVersionWithInput(")
    assert variables["input"] == {"ipWhitelist": ["10.0.0.0/8"]}


async def test_update_version_with_input_against_an_older_server_says_to_upgrade_it(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    from styrmin_sdk import IncompatibleServerError
    from styrmin_sdk.models import UpdateDeploymentInput

    mock_transport.execute.return_value = {
        "data": None,
        "errors": [
            {
                "message": "Unknown argument 'input' on field 'Mutation.updateDeploymentVersion'.",
                "locations": [{"line": 2, "column": 5}],
            }
        ],
    }

    with pytest.raises(IncompatibleServerError, match="Upgrade the Styrmin server"):
        await client.deployments.update_version(
            "11111111-2222-3333-4444-555555555555",
            "2.0.0",
            input=UpdateDeploymentInput.model_validate({"ipWhitelist": ["10.0.0.0/8"]}),
        )


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
# apply() (spec 009 — Phase 3b)
# ---------------------------------------------------------------------------

ENV_ID = "22222222-3333-4444-5555-666666666666"
CLUSTER_ID = "99999999-aaaa-bbbb-cccc-dddddddddddd"
DEPLOYMENT_ID = "11111111-2222-3333-4444-555555555555"
TASK_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _resolved_manifest(
    *,
    name: str = "my-app",
    driver: str = "my-app",
    version: str = "1.0.0",
    environment: str = "prod",
    cluster: str | None = None,
    config: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
) -> ResolvedManifest:
    return ResolvedManifest(
        name=name,
        driver=driver,
        version=version,
        environment=environment,
        cluster=cluster,
        config=config or {},
        parameters=parameters or {},
        source_path=Path("test.yaml"),
    )


def _list_environments_response(*, ambiguous: bool = False) -> dict[str, Any]:
    envs: list[dict[str, Any]] = [
        {
            "id": ENV_ID,
            "name": "prod",
            "config": {},
            "cluster": {"id": CLUSTER_ID, "name": "cluster-a"},
        },
    ]
    if ambiguous:
        envs.append(
            {
                "id": "33333333-4444-5555-6666-777777777777",
                "name": "prod",
                "config": {},
                "cluster": {"id": "88888888-7777-6666-5555-444444444444", "name": "cluster-b"},
            }
        )
    return {"data": {"environments": envs}}


def _existing_deployment_response(
    *,
    version: str = "1.0.0",
    config: dict[str, Any] | None = None,
    driver: str = "my-app",
    status: str = "deployed",
) -> dict[str, Any]:
    return {
        "data": {
            "deployment": {
                "id": DEPLOYMENT_ID,
                "name": "my-app",
                "status": status,
                "deletedAt": None,
                "config": config or {},
                "parameters": {},
                "applicationVersion": version,
                "applicationDriverVersionId": "cccccccc-dddd-eeee-ffff-000000000000",
                "applicationDriverVersion": {
                    "id": "cccccccc-dddd-eeee-ffff-000000000000",
                    "applicationDriver": {
                        "id": "dddddddd-eeee-ffff-0000-111111111111",
                        "name": driver,
                    },
                },
                "environmentId": ENV_ID,
                "applicationInstance": {
                    "id": "33333333-4444-5555-6666-777777777777",
                    "status": "running",
                },
                "components": [],
                "deployedServices": [],
            }
        }
    }


def _missing_deployment_response() -> dict[str, Any]:
    return {"data": {"deployment": None}}


def _deploy_response() -> dict[str, Any]:
    return {
        "data": {
            "deploy": {
                "id": TASK_ID,
                "type": "deploy",
                "status": "pending",
                "message": None,
                "deploymentId": DEPLOYMENT_ID,
            }
        }
    }


def _update_version_response() -> dict[str, Any]:
    return {
        "data": {
            "updateDeploymentVersion": {
                "id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                "type": "update_version",
                "status": "pending",
                "message": None,
                "deploymentId": DEPLOYMENT_ID,
            }
        }
    }


def _update_noop_response() -> dict[str, Any]:
    """Backend no-op: ``updateDeployment`` returns ``null`` (no task)."""
    return {"data": {"updateDeployment": None}}


def _update_version_noop_response() -> dict[str, Any]:
    """Backend no-op: ``updateDeploymentVersion`` returns ``null`` (no task)."""
    return {"data": {"updateDeploymentVersion": None}}


def _applicability_response(
    *,
    env_vars: dict[str, bool],
    images: dict[str, bool] | None = None,
    containers: dict[str, bool] | None = None,
) -> dict[str, Any]:
    def rows(blocks: dict[str, bool] | None) -> list[dict[str, Any]]:
        return [{"component": name, "isApplicable": applicable} for name, applicable in (blocks or {}).items()]

    return {
        "data": {
            "deployment": {
                "id": DEPLOYMENT_ID,
                "componentEnvVars": rows(env_vars),
                "componentImageOverrides": rows(images),
                "componentContainerOverrides": rows(containers),
            }
        }
    }


def _rejected_response(code: str, message: str) -> dict[str, Any]:
    return {"data": None, "errors": [{"message": message, "extensions": {"code": code}}]}


def _operation_names(mock: AsyncMock) -> list[str]:
    """Return the leading line of each GraphQL document executed, e.g. 'query GetDeploymentByName(...)'."""
    return [call.args[0].splitlines()[0].strip() for call in mock.execute.call_args_list]


async def test_apply_creates_when_lookup_returns_none(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _missing_deployment_response(),
        _deploy_response(),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(
            config={"envVars": [{"name": "MY_ENV", "value": "value01"}]},
            parameters={"replicas": 2},
        )
    )

    assert outcome.action == "created"
    assert outcome.name == "my-app"
    assert str(outcome.deployment_id) == DEPLOYMENT_ID
    assert str(outcome.task_id) == TASK_ID

    ops = _operation_names(mock_transport)
    assert len(ops) == 3
    assert ops[0].startswith("query ListEnvironments")
    assert ops[1].startswith("query GetDeploymentByName")
    assert ops[2].startswith("mutation Deploy(")
    deploy_vars = mock_transport.execute.call_args_list[2].args[1]
    assert deploy_vars["driver"] == "my-app"
    assert deploy_vars["version"] == "1.0.0"
    assert deploy_vars["environmentId"] == ENV_ID
    assert deploy_vars["name"] == "my-app"
    # The create path now sends the SAME typed shapes as updateDeployment:
    # env_vars as a [{name, value}] list (camelCase aliases) and parameters
    # as a [ParameterValueInput!] list — no freeform JSON map.
    assert deploy_vars["config"] == {"envVars": [{"name": "MY_ENV", "value": "value01"}]}
    assert deploy_vars["parameters"] == [{"name": "replicas", "value": 2}]


async def test_apply_sends_config_and_version_in_one_mutation(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """Config, parameters and version travel in one ``UpdateDeploymentVersion``,
    so the backend validates the config against the target driver version (#388)."""
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        _applicability_response(env_vars={"server": True}),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(
            version="2.0.0",
            config={"components": [{"name": "server", "envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}]},
            parameters={"replicas": 2},
        )
    )

    assert outcome.action == "updated"
    assert str(outcome.task_id) == "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    assert outcome.target_version == "2.0.0"
    assert outcome.inapplicable_components == []
    ops = _operation_names(mock_transport)
    assert len(ops) == 4
    assert ops[0].startswith("query ListEnvironments")
    assert ops[1].startswith("query GetDeploymentByName")
    assert ops[2].startswith("mutation UpdateDeploymentVersionWithInput(")
    assert ops[3].startswith("query GetDeploymentOverrideApplicability(")
    version_vars = mock_transport.execute.call_args_list[2].args[1]
    assert version_vars["version"] == "2.0.0"
    assert version_vars["input"] == {
        "components": [{"name": "server", "envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}],
        "parameters": [{"name": "replicas", "value": 2}],
    }


async def test_apply_updates_config_when_version_unchanged(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """The client does not guess what changed: it dispatches ``UpdateDeploymentVersion``
    with the unchanged version, and the backend's task drives the ``updated`` outcome."""
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="1.0.0", config={"ip_whitelist": ["10.0.0.0/8"]})
    )

    assert outcome.action == "updated"
    assert outcome.target_version is None
    ops = _operation_names(mock_transport)
    # No component overrides in the manifest, so no applicability read.
    assert len(ops) == 3
    assert ops[2].startswith("mutation UpdateDeploymentVersionWithInput(")
    version_vars = mock_transport.execute.call_args_list[2].args[1]
    assert version_vars["version"] == "1.0.0"
    assert version_vars["input"] == {"ipWhitelist": ["10.0.0.0/8"]}


async def test_update_maps_null_payload_to_none(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A ``null`` ``data.updateDeployment`` payload (backend no-op) maps to
    ``None`` rather than raising a parse error."""
    from styrmin_sdk.models import UpdateDeploymentInput

    mock_transport.execute.side_effect = [_update_noop_response()]

    result = await client.deployments.update(
        DEPLOYMENT_ID, input=UpdateDeploymentInput.model_validate({"ipWhitelist": ["10.0.0.0/8"]})
    )

    assert result is None


async def test_update_version_maps_null_payload_to_none(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A ``null`` ``data.updateDeploymentVersion`` payload maps to ``None``."""
    mock_transport.execute.side_effect = [_update_version_noop_response()]

    result = await client.deployments.update_version(DEPLOYMENT_ID, "1.0.0")

    assert result is None


async def test_apply_unchanged_when_the_mutation_is_a_noop(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """When the backend reports a no-op (``null``) the apply is idempotent and
    returns ``action="unchanged"`` with ``task_id=None``."""
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_noop_response(),
    ]

    outcome = await client.deployments.apply(_resolved_manifest(version="1.0.0"))

    assert outcome.action == "unchanged"
    assert str(outcome.deployment_id) == DEPLOYMENT_ID
    assert outcome.task_id is None
    assert outcome.failure_reason is None

    ops = _operation_names(mock_transport)
    assert len(ops) == 3
    assert ops[2].startswith("mutation UpdateDeploymentVersionWithInput(")


async def test_apply_returns_a_failed_outcome_when_the_server_rejects_the_manifest(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """A rejected update is a ``failed`` outcome with the server's code, not an
    exception, so a loop over manifests goes on; nothing was written."""
    message = "Environment variables target component 'server', which declares no component container"
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _rejected_response("COMPONENT_CONTAINER_NOT_DECLARED", message),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(
            version="2.0.0",
            config={"components": [{"name": "server", "envVars": [{"name": "LOG_LEVEL", "value": "debug"}]}]},
        )
    )

    assert outcome.action == "failed"
    assert str(outcome.deployment_id) == DEPLOYMENT_ID
    assert outcome.task_id is None
    assert outcome.failure_reason == message
    assert outcome.error_code == "COMPONENT_CONTAINER_NOT_DECLARED"


async def test_apply_lists_components_whose_overrides_the_driver_version_cannot_apply(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """Unchanged env vars on a component that loses its container pass validation;
    the outcome names the component so the CLI can warn."""
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        _applicability_response(env_vars={"server": True, "worker": False}, images={"cron": False}),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(
            version="2.0.0",
            config={
                "components": [
                    {"name": "server", "envVars": [{"name": "A", "value": "1"}]},
                    {"name": "worker", "envVars": [{"name": "B", "value": "2"}]},
                ]
            },
        )
    )

    assert outcome.action == "updated"
    # ``cron`` keeps a stored override the manifest does not set, so it is not listed.
    assert outcome.inapplicable_components == ["worker"]


async def test_apply_lists_components_whose_command_or_args_the_driver_version_cannot_apply(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """A re-sent ``command`` or ``args`` on a component without a component container
    passes validation and is stored; the outcome names the component so the CLI can warn."""
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        _applicability_response(env_vars={}, containers={"server": True, "worker": False, "migrate": False}),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(
            version="2.0.0",
            config={
                "components": [
                    {"name": "server", "command": ["/bin/server"]},
                    {"name": "worker", "args": ["--queue", "low"]},
                    {"name": "migrate"},
                ]
            },
        )
    )

    assert outcome.action == "updated"
    # ``migrate`` sets neither ``command`` nor ``args``, so it is not listed.
    assert outcome.inapplicable_components == ["worker"]
    assert _operation_names(mock_transport)[3].startswith("query GetDeploymentOverrideApplicability(")


async def test_apply_skips_the_applicability_read_when_no_block_sets_an_override(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="2.0.0", config={"components": [{"name": "worker"}]})
    )

    assert outcome.action == "updated"
    assert outcome.inapplicable_components == []
    assert len(_operation_names(mock_transport)) == 3


async def test_apply_ignores_a_failed_applicability_read(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        _rejected_response("FORBIDDEN", "nope"),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(
            version="2.0.0",
            config={"components": [{"name": "worker", "envVars": [{"name": "B", "value": "2"}]}]},
        )
    )

    assert outcome.action == "updated"
    assert outcome.inapplicable_components == []


async def test_apply_unchanged_against_failed_deployment(client: StyrminClient, mock_transport: AsyncMock) -> None:
    """A no-op re-apply against a FAILED deployment still resolves to
    ``unchanged`` — the action is driven by the backend's null result,
    not by the deployment's current status."""
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0", status="failed"),
        _update_version_noop_response(),
    ]

    outcome = await client.deployments.apply(_resolved_manifest(version="1.0.0"))

    assert outcome.action == "unchanged"
    assert outcome.task_id is None


async def test_apply_raises_driver_mismatch_when_existing_driver_differs(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(driver="other-driver"),
    ]

    with pytest.raises(DriverMismatchError, match="driver mismatch"):
        await client.deployments.apply(_resolved_manifest(driver="my-app"))

    # Lookup happened, but no update mutation should have fired.
    ops = _operation_names(mock_transport)
    assert any(op.startswith("mutation UpdateDeployment") for op in ops) is False


async def test_apply_raises_environment_ambiguity_when_no_cluster_disambiguates(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.side_effect = [_list_environments_response(ambiguous=True)]

    with pytest.raises(EnvironmentAmbiguityError, match="multiple clusters"):
        await client.deployments.apply(_resolved_manifest(cluster=None))

    # Only the env lookup should have happened — nothing else.
    assert mock_transport.execute.await_count == 1


async def test_apply_raises_environment_not_found_when_no_match(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """Distinct from ambiguity: when no env matches the resolved
    ``(environment, cluster)`` pair, ``apply()`` raises
    :class:`EnvironmentNotFoundError` so callers can branch on the difference
    between "specify a cluster" and "the env doesn't exist"."""
    mock_transport.execute.side_effect = [{"data": {"environments": []}}]

    with pytest.raises(EnvironmentNotFoundError, match="not found"):
        await client.deployments.apply(_resolved_manifest())

    assert mock_transport.execute.await_count == 1


async def test_apply_environment_not_found_includes_cluster_in_message(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """When ``cluster`` is supplied, the error message names it so the user
    can spot a typo in their cluster argument quickly."""
    mock_transport.execute.side_effect = [{"data": {"environments": []}}]

    with pytest.raises(EnvironmentNotFoundError, match="in cluster 'cluster-z'"):
        await client.deployments.apply(_resolved_manifest(cluster="cluster-z"))


async def test_apply_handles_duplicate_name_race_by_pivoting_to_update(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """Per research.md D2: a concurrent apply may race past the "not found"
    branch. On the resulting :class:`ResourceAlreadyExistsError` from the
    backend's unique constraint, ``apply`` re-runs the lookup once and pivots
    to the update path — exactly one retry, no loop."""

    duplicate_error = ResourceAlreadyExistsError("duplicate name", "ALREADY_EXISTS")
    lookup_calls = [0]

    def execute_side_effect(query: str, _vars: dict[str, Any] | None = None) -> dict[str, Any]:
        first_line = query.splitlines()[0].strip()
        if first_line.startswith("query ListEnvironments"):
            return _list_environments_response()
        if first_line.startswith("query GetDeploymentByName"):
            # First call: deployment not found. Second call (after the
            # duplicate-name race): deployment now exists.
            lookup_calls[0] += 1
            if lookup_calls[0] == 1:
                return _missing_deployment_response()
            return _existing_deployment_response(version="1.0.0")
        if first_line.startswith("mutation Deploy("):
            raise duplicate_error
        if first_line.startswith("mutation UpdateDeploymentVersionWithInput("):
            return _update_version_response()
        raise AssertionError(f"unexpected query: {first_line}")

    mock_transport.execute.side_effect = execute_side_effect

    outcome = await client.deployments.apply(
        _resolved_manifest(version="1.0.0", config={"ip_whitelist": ["10.0.0.0/8"]})
    )

    assert outcome.action == "updated"
    assert str(outcome.deployment_id) == DEPLOYMENT_ID
    # Two lookups (initial + post-race) and one update.
    assert lookup_calls[0] == 2
    ops = _operation_names(mock_transport)
    assert sum(1 for op in ops if op.startswith("query GetDeploymentByName")) == 2
    assert sum(1 for op in ops if op.startswith("mutation UpdateDeploymentVersionWithInput(")) == 1


# ---------------------------------------------------------------------------
# apply_files() (spec 009 — Phase 4a / Chunk 8)
# ---------------------------------------------------------------------------


_MANIFEST_BODY = """\
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: {name}
spec:
  driver: my-app
  version: "1.0.0"
  environment: prod
"""


def _write_manifest(path: Path, *, name: str = "my-app", body: str | None = None) -> Path:
    """Write a single-doc manifest to ``path`` and return the path."""
    path.write_text(
        body if body is not None else _MANIFEST_BODY.format(name=name),
        encoding="utf-8",
    )
    return path


def _stub_apply_outcome(name: str = "my-app", action: str = "created") -> ApplyOutcome:
    """Build an ``ApplyOutcome`` stub for monkeypatched ``apply()`` returns."""
    return ApplyOutcome(
        name=name,
        action=action,  # type: ignore[arg-type]
        deployment_id=UUID(DEPLOYMENT_ID),
        task_id=UUID(TASK_ID),
    )


async def test_apply_files_single_file_with_one_doc(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single-file → one outcome dispatched via apply()."""
    manifest_path = _write_manifest(tmp_path / "app.yaml", name="my-app")
    apply_mock = AsyncMock(return_value=_stub_apply_outcome("my-app", "created"))
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    outcomes = await client.deployments.apply_files([manifest_path])

    assert [o.action for o in outcomes] == ["created"]
    assert apply_mock.await_count == 1
    resolved_arg = apply_mock.await_args_list[0].args[0]
    assert resolved_arg.name == "my-app"
    assert resolved_arg.source_path == manifest_path


async def test_apply_files_multidoc_yaml(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One file with multiple ----separated docs → one apply() per doc."""
    body = _MANIFEST_BODY.format(name="frontend") + "---\n" + _MANIFEST_BODY.format(name="backend")
    manifest_path = _write_manifest(tmp_path / "stack.yaml", body=body)
    apply_mock = AsyncMock(
        side_effect=[
            _stub_apply_outcome("frontend", "created"),
            _stub_apply_outcome("backend", "created"),
        ]
    )
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    outcomes = await client.deployments.apply_files([manifest_path])

    assert [o.name for o in outcomes] == ["frontend", "backend"]
    assert apply_mock.await_count == 2


async def test_apply_files_multiple_paths_combined(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple `-f` paths combine in user-supplied order."""
    a = _write_manifest(tmp_path / "a.yaml", name="a")
    b = _write_manifest(tmp_path / "b.yaml", name="b")

    def fake_apply(resolved: ResolvedManifest) -> ApplyOutcome:
        return _stub_apply_outcome(resolved.name, "created")

    apply_mock = AsyncMock(side_effect=fake_apply)
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    outcomes = await client.deployments.apply_files([b, a])  # user-order matters

    assert [o.name for o in outcomes] == ["b", "a"]


async def test_apply_files_directory_sorts_immediate_yaml_files(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory expansion uses sorted `.yaml`/`.yml` immediate children only.

    Files in subdirectories are NOT picked up (research.md D10), and the
    output order is alphabetical regardless of filesystem order.
    """
    _write_manifest(tmp_path / "c.yaml", name="c")
    _write_manifest(tmp_path / "a.yml", name="a")
    _write_manifest(tmp_path / "b.yaml", name="b")
    # Subdirectory file MUST be ignored (non-recursive).
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_manifest(sub / "z.yaml", name="z")
    # Non-yaml extension MUST be ignored.
    (tmp_path / "notes.txt").write_text("ignored")

    apply_mock = AsyncMock(
        side_effect=[
            _stub_apply_outcome("a", "created"),
            _stub_apply_outcome("b", "created"),
            _stub_apply_outcome("c", "created"),
        ]
    )
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    outcomes = await client.deployments.apply_files([tmp_path])

    assert [o.name for o in outcomes] == ["a", "b", "c"]


async def test_apply_files_continues_past_invalid_manifest(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad manifest in the middle is reported as failed; siblings still apply."""
    _write_manifest(tmp_path / "a.yaml", name="a")
    # Invalid: missing required `spec.driver`.
    (tmp_path / "b.yaml").write_text("apiVersion: styrmin/v1\nkind: Deployment\nmetadata: {name: b}\nspec: {}\n")
    _write_manifest(tmp_path / "c.yaml", name="c")

    apply_mock = AsyncMock(
        side_effect=[
            _stub_apply_outcome("a", "created"),
            _stub_apply_outcome("c", "created"),
        ]
    )
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    outcomes = await client.deployments.apply_files([tmp_path])

    actions = [o.action for o in outcomes]
    assert actions.count("created") == 2
    assert actions.count("failed") == 1
    failed = next(o for o in outcomes if o.action == "failed")
    assert failed.failure_reason is not None
    assert "b.yaml" in failed.failure_reason
    # apply() must NOT have been called for the invalid one.
    assert apply_mock.await_count == 2


async def test_apply_files_per_apply_exception_becomes_failed_outcome(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exceptions raised by apply() itself (e.g. driver mismatch) are
    converted to failed outcomes with the source-path prefix, and the
    batch continues."""
    a = _write_manifest(tmp_path / "a.yaml", name="a")
    b = _write_manifest(tmp_path / "b.yaml", name="b")
    apply_mock = AsyncMock(
        side_effect=[
            _stub_apply_outcome("a", "created"),
            DriverMismatchError("driver mismatch boom"),
        ]
    )
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    outcomes = await client.deployments.apply_files([a, b])

    assert outcomes[0].action == "created"
    assert outcomes[1].action == "failed"
    assert outcomes[1].failure_reason is not None
    assert outcomes[1].failure_reason.startswith(f"manifest {b}: ")
    assert "driver mismatch boom" in outcomes[1].failure_reason


async def test_apply_files_empty_directory_raises_apply_error(client: StyrminClient, tmp_path: Path) -> None:
    """A directory with no `.yaml`/`.yml` immediate children is fatal."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(ApplyError, match="no manifests found"):
        await client.deployments.apply_files([empty_dir])


async def test_apply_files_missing_path_raises_file_not_found(client: StyrminClient, tmp_path: Path) -> None:
    """A path that doesn't exist fails fast with FileNotFoundError."""
    bogus = tmp_path / "does-not-exist.yaml"

    with pytest.raises(FileNotFoundError):
        await client.deployments.apply_files([bogus])


async def test_apply_files_name_override_with_multidoc_raises_before_dispatch(
    client: StyrminClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`overrides.name` + >1 manifest is a whole-batch error, raised BEFORE
    any per-manifest dispatch (so apply() is never called)."""
    body = _MANIFEST_BODY.format(name="frontend") + "---\n" + _MANIFEST_BODY.format(name="backend")
    manifest_path = _write_manifest(tmp_path / "stack.yaml", body=body)
    apply_mock = AsyncMock()
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    with pytest.raises(BatchNameConflictError, match="multiple manifests"):
        await client.deployments.apply_files(
            [manifest_path],
            overrides=ApplyOverrides(name="forced"),
        )

    assert apply_mock.await_count == 0


# ---------------------------------------------------------------------------
# apply(wait=True) and apply_files(wait=True, on_event=...) (spec 009 — Phase 6)
# ---------------------------------------------------------------------------


def _get_deployment_response(*, deployment_status: str = "running") -> dict[str, Any]:
    """Build a ``deployment(deploymentId)`` payload for ``wait`` polling tests.

    The SDK ``--wait`` helpers poll ``Deployment.status`` (see
    ``python_sdk/src/styrmin_sdk/_wait.py``), so all wait-loop fixtures
    stub the ``GetDeployment`` query with the desired top-level status.
    The rest of the payload mirrors a realistic projection so the
    generated Pydantic validators don't reject the stub.
    """
    return {
        "data": {
            "deployment": {
                "id": DEPLOYMENT_ID,
                "name": "my-app",
                "status": deployment_status,
                "deletedAt": None,
                "config": {},
                "parameters": {},
                "applicationVersion": "1.0.0",
                "applicationDriverVersionId": "cccccccc-dddd-eeee-ffff-000000000000",
                "applicationDriverVersion": {
                    "version": "1.0.0",
                    "contentHash": None,
                    "sourceCommitSha": None,
                },
                "environmentId": ENV_ID,
                "createdBy": {
                    "id": "55555555-6666-7777-8888-999999999999",
                    "username": "alice",
                    "displayName": "Alice",
                },
                "applicationInstance": {
                    "id": "33333333-4444-5555-6666-777777777777",
                    "status": "running",
                },
                "components": [],
                "componentImageOverrides": [],
                "deployedServices": [],
            }
        }
    }


async def test_apply_wait_returns_outcome_when_deployment_running(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apply(wait=True)`` polls the deployment until ``Deployment.status``
    flips to ``"running"`` and returns the original ``updated`` outcome
    unchanged."""
    # Avoid real sleeps in the poll loop.
    from styrmin_sdk.resources import deployments as deployments_module

    async def _no_sleep(_seconds: float) -> None:  # noqa: RUF029 — must mirror asyncio.sleep signature
        return None

    monkeypatch.setattr(deployments_module.asyncio, "sleep", _no_sleep)

    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        _get_deployment_response(deployment_status="deploying"),
        _get_deployment_response(deployment_status="running"),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="1.0.0", config={"ip_whitelist": ["10.0.0.0/8"]}),
        wait=True,
    )

    assert outcome.action == "updated"
    assert outcome.failure_reason is None
    # Two polls (one deploying, one running) — confirms the loop actually
    # iterated rather than short-circuiting on the first call.
    ops = _operation_names(mock_transport)
    poll_count = sum(1 for op in ops if op.startswith("query GetDeployment("))
    assert poll_count == 2


async def test_apply_wait_marks_outcome_failed_on_terminal_failure(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the deployment reaches a terminal failure status the outcome
    flips to ``action="failed"`` with a ``failure_reason`` that names the
    status."""
    from styrmin_sdk.resources import deployments as deployments_module

    async def _no_sleep(_seconds: float) -> None:  # noqa: RUF029 — must mirror asyncio.sleep signature
        return None

    monkeypatch.setattr(deployments_module.asyncio, "sleep", _no_sleep)

    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _missing_deployment_response(),
        _deploy_response(),
        _get_deployment_response(deployment_status="failed"),
        # No step of the task failed, so the status reason stays.
        _get_task_response(TASK_ID, [_task_step("Plan the changes", "SUCCEEDED")]),
    ]

    outcome = await client.deployments.apply(_resolved_manifest(), wait=True)

    assert outcome.action == "failed"
    assert outcome.failure_reason == "deployment reconciliation failed (status: failed)"
    # ``deployment_id`` must survive the flip so callers can re-apply.
    assert outcome.deployment_id is not None


HELMRELEASE_STEP = "Install or upgrade the HelmRelease"
HELMRELEASE_ERROR = "UpgradeFailed: Helm upgrade failed. Pods not ready: my-app-6d9 (app: ImagePullBackOff)"
STARTED_TASK_ID = "cccccccc-dddd-eeee-ffff-000000000000"


def _task_step(name: str, status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid5(NAMESPACE_URL, name)),
        "key": name.lower().replace(" ", "-"),
        "name": name,
        "kind": "OPERATOR_PHASE",
        "status": status,
        "startedAt": "2026-10-06T10:00:00+00:00",
        "endedAt": "2026-10-06T10:04:30+00:00",
        "durationSeconds": 270.0,
        "attemptCount": 1,
        "errors": []
        if error is None
        else [{"attempt": 1, "message": error, "occurredAt": "2026-10-06T10:04:30+00:00"}],
        "error": error,
        "detail": None,
        "rolledBackAt": None,
        "rollbackMessage": None,
        "hasOutput": False,
        "supersededBy": None,
        "startedTasks": [],
        "noReportSince": None,
    }


def _get_task_response(
    task_id: str, steps: list[dict[str, Any]], started_task_ids: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "data": {
            "task": {
                "id": task_id,
                "type": "deploy",
                "status": "completed",
                "message": None,
                "deploymentId": DEPLOYMENT_ID,
                "createdOn": "2026-10-06T10:00:00+00:00",
                "result": "FAILED",
                "startedByStepId": None,
                "startedBy": None,
                "startedTasks": [
                    {"id": started, "type": "deploy", "status": "completed", "result": "FAILED"}
                    for started in started_task_ids
                ],
                "steps": steps,
            }
        }
    }


async def _apply_until_failed(
    client: StyrminClient, mock_transport: AsyncMock, monkeypatch: pytest.MonkeyPatch, *task_reads: dict[str, Any]
) -> ApplyOutcome:
    from styrmin_sdk.resources import deployments as deployments_module

    async def _no_sleep(_seconds: float) -> None:  # noqa: RUF029 — must mirror asyncio.sleep signature
        return None

    monkeypatch.setattr(deployments_module.asyncio, "sleep", _no_sleep)
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _missing_deployment_response(),
        _deploy_response(),
        _get_deployment_response(deployment_status="deploying"),
        _get_deployment_response(deployment_status="failed"),
        *task_reads,
    ]
    return await client.deployments.apply(_resolved_manifest(), wait=True)


async def test_apply_wait_failure_reason_names_the_failed_step(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal failure names the task's failed step and its newest error (FR-012)."""
    outcome = await _apply_until_failed(
        client,
        mock_transport,
        monkeypatch,
        _get_task_response(
            TASK_ID,
            [
                _task_step("Create network policies and secrets", "SUCCEEDED"),
                _task_step(HELMRELEASE_STEP, "FAILED", HELMRELEASE_ERROR),
            ],
        ),
    )

    assert outcome.action == "failed"
    assert outcome.failure_reason == f'step "{HELMRELEASE_STEP}" failed: {HELMRELEASE_ERROR}'
    # The task is read right after the poll that saw the failure.
    ops = _operation_names(mock_transport)
    assert ops[-2:] == ["query GetDeployment($deploymentId: UUID!) {", "query GetTask($taskId: UUID!) {"]


async def test_apply_wait_failure_reason_names_a_failed_step_of_a_started_task(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = await _apply_until_failed(
        client,
        mock_transport,
        monkeypatch,
        _get_task_response(TASK_ID, [_task_step("Run the upgrade hook", "SUCCEEDED")], (STARTED_TASK_ID,)),
        _get_task_response(STARTED_TASK_ID, [_task_step(HELMRELEASE_STEP, "FAILED", HELMRELEASE_ERROR)]),
    )

    assert outcome.failure_reason == f'step "{HELMRELEASE_STEP}" failed: {HELMRELEASE_ERROR}'


async def test_apply_wait_failure_reason_without_an_error_message(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = await _apply_until_failed(
        client,
        mock_transport,
        monkeypatch,
        _get_task_response(TASK_ID, [_task_step(HELMRELEASE_STEP, "FAILED")]),
    )

    assert outcome.failure_reason == f'step "{HELMRELEASE_STEP}" failed'


async def test_apply_wait_failure_reason_falls_back_when_the_task_cannot_be_read(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server without ``Task.steps`` rejects the read; the status reason stays."""
    outcome = await _apply_until_failed(
        client,
        mock_transport,
        monkeypatch,
        {"data": None, "errors": [{"message": "Cannot query field 'steps' on type 'Task'."}]},
    )

    assert outcome.action == "failed"
    assert outcome.failure_reason == "deployment reconciliation failed (status: failed)"


async def test_apply_wait_marks_outcome_failed_on_timeout(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the wait budget elapses without a terminal status, ``apply`` returns
    ``action="failed"`` with the contracted ``failure_reason="wait timeout"``."""
    from styrmin_sdk import _wait as wait_module  # noqa: PLC2701 — internal constant under test
    from styrmin_sdk.resources import deployments as deployments_module

    # Drive monotonic time past the deadline on the second call so the loop
    # exits via the timeout branch deterministically. Cycle past the deadline
    # for any further calls so a defensive fixture teardown does not blow up.
    call_count = {"n": 0}

    def fake_monotonic() -> float:
        n = call_count["n"]
        call_count["n"] += 1
        if n == 0:
            return 0.0
        return wait_module.WAIT_TIMEOUT_SECONDS + 1.0

    monkeypatch.setattr(deployments_module.time, "monotonic", fake_monotonic)

    async def _no_sleep(_seconds: float) -> None:  # noqa: RUF029 — must mirror asyncio.sleep signature
        return None

    monkeypatch.setattr(deployments_module.asyncio, "sleep", _no_sleep)

    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        _get_deployment_response(deployment_status="deploying"),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="1.0.0", config={"ip_whitelist": ["10.0.0.0/8"]}),
        wait=True,
    )

    assert outcome.action == "failed"
    assert outcome.failure_reason == "wait timeout"


async def test_apply_wait_stops_at_max_wait(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``max_wait`` replaces the default limit: 101 s after the submission, a 100 s wait ends unpolled."""
    from styrmin_sdk.resources import deployments as deployments_module

    times = iter([0.0, 101.0])
    monkeypatch.setattr(deployments_module.time, "monotonic", lambda: next(times, 101.0))
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="1.0.0", config={"ip_whitelist": ["10.0.0.0/8"]}),
        wait=True,
        max_wait=100,
    )

    assert outcome.action == "failed"
    assert outcome.failure_reason == "wait timeout"
    assert mock_transport.execute.await_count == 3


@pytest.mark.parametrize(
    ("max_wait", "expected_sleeps"),
    [(3, [3.0]), (25, [10.0, 10.0, 5.0])],
    ids=["shorter-than-the-poll-interval", "not-a-multiple-of-the-poll-interval"],
)
async def test_apply_wait_never_sleeps_past_max_wait(
    client: StyrminClient,
    mock_transport: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    max_wait: float,
    expected_sleeps: list[float],
) -> None:
    """The last sleep ends at the deadline instead of a full poll interval after it."""
    from styrmin_sdk.resources import deployments as deployments_module

    clock = {"now": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:  # noqa: RUF029 — must mirror asyncio.sleep signature
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(deployments_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(deployments_module.asyncio, "sleep", fake_sleep)
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _existing_deployment_response(version="1.0.0"),
        _update_version_response(),
        *[_get_deployment_response(deployment_status="deploying") for _ in expected_sleeps],
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="1.0.0", config={"ip_whitelist": ["10.0.0.0/8"]}),
        wait=True,
        max_wait=max_wait,
    )

    assert outcome.failure_reason == "wait timeout"
    assert sleeps == expected_sleeps
    assert clock["now"] == max_wait


@pytest.mark.parametrize("max_wait", [0, -1])
async def test_apply_rejects_non_positive_max_wait_before_submitting(
    client: StyrminClient,
    mock_transport: AsyncMock,
    max_wait: float,
) -> None:
    """A ``max_wait`` that is not positive raises before any request."""
    with pytest.raises(ValueError, match="max_wait must be positive"):
        await client.deployments.apply(_resolved_manifest(version="1.0.0"), wait=True, max_wait=max_wait)
    with pytest.raises(ValueError, match="max_wait must be positive"):
        await client.deployments.apply_files([], wait=True, max_wait=max_wait)

    mock_transport.execute.assert_not_awaited()


async def test_apply_files_wait_emits_submitted_then_terminal_events_in_order(
    client: StyrminClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The callback receives one ``submitted`` event followed by one
    ``terminal`` event per dispatched manifest, in that order."""
    from styrmin_sdk.models.deployment_manifest import ApplyEvent

    manifest_path = _write_manifest(tmp_path / "app.yaml", name="my-app")

    async def fake_apply(_resolved: ResolvedManifest, *, wait: bool = False) -> ApplyOutcome:  # noqa: RUF029 — mirrors apply() signature
        # ``apply_files`` controls waiting itself via ``_wait_for_terminal``,
        # so it should call apply() WITHOUT ``wait=True``.
        assert wait is False
        return _stub_apply_outcome("my-app", "updated")

    async def fake_wait(outcome: ApplyOutcome, _max_wait: float | None = None) -> ApplyOutcome:  # noqa: RUF029 — mirrors _wait_for_terminal signature
        return outcome  # terminal RUNNING — no change

    monkeypatch.setattr(client.deployments, "apply", fake_apply)
    monkeypatch.setattr(client.deployments, "_wait_for_terminal", fake_wait)

    events: list[ApplyEvent] = []
    outcomes = await client.deployments.apply_files(
        [manifest_path],
        wait=True,
        on_event=events.append,
    )

    assert [o.action for o in outcomes] == ["updated"]
    assert [(e.type, e.outcome.action) for e in events] == [
        ("submitted", "updated"),
        ("terminal", "updated"),
    ]
    assert all(e.name == "my-app" for e in events)


async def test_apply_files_no_wait_does_not_emit_events(
    client: StyrminClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``wait=True`` the streaming callback is never invoked — the
    return-list path stays the only signal (research D7)."""
    manifest_path = _write_manifest(tmp_path / "app.yaml", name="my-app")
    apply_mock = AsyncMock(return_value=_stub_apply_outcome("my-app", "created"))
    monkeypatch.setattr(client.deployments, "apply", apply_mock)

    events: list[Any] = []
    outcomes = await client.deployments.apply_files(
        [manifest_path],
        on_event=events.append,
    )

    assert [o.action for o in outcomes] == ["created"]
    assert events == []


async def test_apply_files_wait_terminal_failure_keeps_failed_outcome_in_list(
    client: StyrminClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal-failure during wait flips the outcome and the callback's
    ``terminal`` event reflects the post-wait state."""
    from styrmin_sdk.models.deployment_manifest import ApplyEvent

    manifest_path = _write_manifest(tmp_path / "app.yaml", name="my-app")

    async def fake_apply(_resolved: ResolvedManifest, *, wait: bool = False) -> ApplyOutcome:  # noqa: RUF029 — mirrors apply() signature
        assert wait is False
        return _stub_apply_outcome("my-app", "created")

    async def fake_wait(outcome: ApplyOutcome, _max_wait: float | None = None) -> ApplyOutcome:  # noqa: RUF029 — mirrors _wait_for_terminal signature
        return outcome.model_copy(
            update={"action": "failed", "failure_reason": "deployment reconciliation failed (status: failed)"}
        )

    monkeypatch.setattr(client.deployments, "apply", fake_apply)
    monkeypatch.setattr(client.deployments, "_wait_for_terminal", fake_wait)

    events: list[ApplyEvent] = []
    outcomes = await client.deployments.apply_files(
        [manifest_path],
        wait=True,
        on_event=events.append,
    )

    assert outcomes[0].action == "failed"
    assert "deployment reconciliation failed" in (outcomes[0].failure_reason or "")
    # submitted reflects the pre-wait (created) state; terminal reflects the
    # post-wait (failed) state.
    assert events[0].type == "submitted"
    assert events[0].outcome.action == "created"
    assert events[1].type == "terminal"
    assert events[1].outcome.action == "failed"


async def test_apply_files_wait_skips_terminal_event_for_submission_failures(
    client: StyrminClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If submission itself fails, no ``terminal`` event fires — the contract
    has the failure reported by the ``submitted`` event so a duplicate
    terminal-failed line would just be noise."""
    from styrmin_sdk.models.deployment_manifest import ApplyEvent

    manifest_path = _write_manifest(tmp_path / "app.yaml", name="my-app")

    async def fake_apply(_resolved: ResolvedManifest, *, wait: bool = False) -> ApplyOutcome:  # noqa: RUF029 — mirrors apply() signature
        assert wait is False
        raise DriverMismatchError("driver mismatch boom")

    monkeypatch.setattr(client.deployments, "apply", fake_apply)

    events: list[ApplyEvent] = []
    outcomes = await client.deployments.apply_files(
        [manifest_path],
        wait=True,
        on_event=events.append,
    )

    assert outcomes[0].action == "failed"
    # Only one event; no ``terminal`` follows because we never polled.
    assert len(events) == 1
    assert events[0].type == "submitted"
    assert events[0].outcome.action == "failed"


async def test_apply_rejected_update_writes_nothing_else(
    client: StyrminClient,
    mock_transport: AsyncMock,
) -> None:
    """A rejected ``UpdateDeploymentVersion`` propagates and no other mutation ran,
    so the config is never written without the version (#388)."""

    def execute_side_effect(query: str, _vars: dict[str, Any] | None = None) -> dict[str, Any]:
        first_line = query.splitlines()[0].strip()
        if first_line.startswith("query ListEnvironments"):
            return _list_environments_response()
        if first_line.startswith("query GetDeploymentByName"):
            return _existing_deployment_response(version="1.0.0")
        if first_line.startswith("mutation UpdateDeploymentVersionWithInput("):
            raise RuntimeError("COMPONENT_CONTAINER_NOT_DECLARED")
        raise AssertionError(f"unexpected query: {first_line}")

    mock_transport.execute.side_effect = execute_side_effect

    with pytest.raises(RuntimeError, match="COMPONENT_CONTAINER_NOT_DECLARED"):
        await client.deployments.apply(_resolved_manifest(version="2.0.0", config={"ip_whitelist": ["10.0.0.0/8"]}))

    mutations = [op for op in _operation_names(mock_transport) if op.startswith("mutation")]
    assert len(mutations) == 1


# ---------------------------------------------------------------------------
# apply: pinned image overrides on a version change (018, FR-008)
# ---------------------------------------------------------------------------

PINNED_IMAGE = "registry.example/acme/app-patched:1.0.0"
TOKEN_IMAGE = "registry.example/acme/app-patched:{{ app.version }}"
STORED_IMAGE_CONFIG: dict[str, Any] = {
    "components": {
        "server": {"image": PINNED_IMAGE},
        "worker": {"image": TOKEN_IMAGE},
        "migrate": {"env_vars": {"MODE": "fast"}},
    }
}


def _apply_update_side_effect(*, existing_version: str, stored_config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _list_environments_response(),
        _existing_deployment_response(version=existing_version, config=stored_config),
        _update_version_response(),
        _applicability_response(env_vars={}),
    ]


async def test_apply_version_change_reports_pinned_components_from_manifest(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """Manifest ``components`` replace the stored ones, so they alone decide what is pinned."""
    mock_transport.execute.side_effect = _apply_update_side_effect(
        existing_version="1.0.0", stored_config={"components": {"api": {"image": "registry.example/api:1"}}}
    )

    outcome = await client.deployments.apply(
        _resolved_manifest(
            version="2.0.0",
            config={
                "components": [
                    {"name": "worker", "image": TOKEN_IMAGE},
                    {"name": "server", "image": PINNED_IMAGE},
                    {"name": "migrate", "envVars": [{"name": "MODE", "value": "fast"}]},
                ]
            },
        )
    )

    assert outcome.action == "updated"
    assert outcome.pinned_image_components == ["server"]
    assert outcome.target_version == "2.0.0"


async def test_apply_version_change_reports_pinned_components_from_stored_config(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.side_effect = _apply_update_side_effect(
        existing_version="1.0.0", stored_config=STORED_IMAGE_CONFIG
    )

    outcome = await client.deployments.apply(
        _resolved_manifest(version="2.0.0", config={"ip_whitelist": ["10.0.0.0/8"]})
    )

    assert outcome.action == "updated"
    assert outcome.pinned_image_components == ["server"]
    assert outcome.target_version == "2.0.0"


async def test_apply_version_change_with_empty_manifest_components_reports_none(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    """An empty ``components`` list clears every stored block, so nothing stays pinned."""
    mock_transport.execute.side_effect = _apply_update_side_effect(
        existing_version="1.0.0", stored_config=STORED_IMAGE_CONFIG
    )

    outcome = await client.deployments.apply(_resolved_manifest(version="2.0.0", config={"components": []}))

    assert outcome.action == "updated"
    assert outcome.pinned_image_components == []


async def test_apply_without_version_change_reports_no_pinned_components(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.side_effect = _apply_update_side_effect(
        existing_version="2.0.0", stored_config=STORED_IMAGE_CONFIG
    )

    outcome = await client.deployments.apply(
        _resolved_manifest(version="2.0.0", config={"ip_whitelist": ["10.0.0.0/8"]})
    )

    assert outcome.action == "updated"
    assert outcome.pinned_image_components == []
    assert outcome.target_version is None


async def test_apply_create_reports_no_pinned_components(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _list_environments_response(),
        _missing_deployment_response(),
        _deploy_response(),
    ]

    outcome = await client.deployments.apply(
        _resolved_manifest(version="2.0.0", config={"components": [{"name": "server", "image": PINNED_IMAGE}]})
    )

    assert outcome.action == "created"
    assert outcome.pinned_image_components == []
    assert outcome.target_version is None


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

    # Deleted and internal deployments are excluded by default.
    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables == {
        "environmentId": "22222222-3333-4444-5555-666666666666",
        "includeDeleted": False,
        "includeInternal": False,
    }


async def test_list_deployments_forwards_include_internal(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {"data": {"environment": {"deployments": []}}}

    await client.deployments.list("22222222-3333-4444-5555-666666666666", include_internal=True)

    sent_variables = mock_transport.execute.await_args.args[1]
    assert sent_variables["includeInternal"] is True


async def test_list_deployments_unknown_environment_returns_empty(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = {"data": {"environment": None}}

    deployments = await client.deployments.list("22222222-3333-4444-5555-666666666666")

    assert deployments == []
