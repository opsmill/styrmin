"""Tests for environment resource operations."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from styrmin_sdk import OperationFailedError, ResourceNotFoundError, StyrminClient
from styrmin_sdk.models import DeployedService, PodPhase, PodStatus

ENVIRONMENT_ID = "22222222-3333-4444-5555-666666666666"
CLUSTER_ID = "33333333-4444-5555-6666-777777777777"

_ENVIRONMENT_RESPONSE = {
    "data": {
        "environment": {
            "id": ENVIRONMENT_ID,
            "name": "demo",
            "config": {},
            "capabilities": {},
            "cluster": {"id": CLUSTER_ID, "name": "local"},
        }
    }
}
_ENVIRONMENT_NOT_FOUND = {
    "data": {"environment": None},
    "errors": [{"message": "Environment not found: demo", "extensions": {"code": "NOT_FOUND"}}],
}


def _pod_status(pod_name: str, deployment_id: str) -> dict[str, Any]:
    return {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "deploymentId": deployment_id,
        "podName": pod_name,
        "namespace": f"styrmin-{deployment_id}",
        "phase": "RUNNING",
        "ready": True,
        "restartCount": 0,
        "containerStatuses": [],
        "nodeName": "node-1",
        "componentName": "server",
        "startedAt": "2026-10-22T10:00:00Z",
        "lastPolledAt": "2026-10-22T10:05:00Z",
    }


def _service(resolved_name: str, deployment_id: str) -> dict[str, Any]:
    return {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "driverServiceName": "simple-app",
        "resolvedName": resolved_name,
        "kind": "http",
        "scope": "internal",
        "port": 8000,
        "component": "server",
        "deploymentId": deployment_id,
    }


def _sent(mock_transport: AsyncMock) -> list[tuple[str, dict[str, Any]]]:
    """The operation name and the variables of each request, in order."""
    return [(call.args[0].lstrip().split("(", 1)[0], call.args[1]) for call in mock_transport.execute.await_args_list]


async def test_get_pod_statuses_of_environment(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _ENVIRONMENT_RESPONSE,
        {
            "data": {
                "podStatuses": [
                    _pod_status("app-a-0", "11111111-2222-3333-4444-555555555555"),
                    _pod_status("app-b-0", "77777777-8888-9999-aaaa-bbbbbbbbbbbb"),
                ]
            }
        },
    ]

    pods = await client.environments.get_pod_statuses(UUID(ENVIRONMENT_ID))

    assert _sent(mock_transport) == [
        ("query GetEnvironment", {"environmentId": ENVIRONMENT_ID}),
        ("query GetPodStatuses", {"environmentId": ENVIRONMENT_ID}),
    ]
    assert [(pod.pod_name, str(pod.deployment_id)) for pod in pods] == [
        ("app-a-0", "11111111-2222-3333-4444-555555555555"),
        ("app-b-0", "77777777-8888-9999-aaaa-bbbbbbbbbbbb"),
    ]
    assert all(isinstance(pod, PodStatus) for pod in pods)
    assert pods[0].phase is PodPhase.RUNNING
    assert pods[0].ready is True


async def test_get_pod_statuses_of_environment_by_name(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [_ENVIRONMENT_RESPONSE, {"data": {"podStatuses": []}}]

    assert await client.environments.get_pod_statuses(environment_name="demo", cluster_name="local") == []
    assert _sent(mock_transport) == [
        ("query GetEnvironment", {"environmentName": "demo", "clusterName": "local"}),
        ("query GetPodStatuses", {"environmentId": ENVIRONMENT_ID}),
    ]


async def test_get_pod_statuses_of_unknown_environment(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = _ENVIRONMENT_NOT_FOUND

    with pytest.raises(ResourceNotFoundError, match="Environment not found"):
        await client.environments.get_pod_statuses(ENVIRONMENT_ID)
    assert [name for name, _ in _sent(mock_transport)] == ["query GetEnvironment"]


async def test_get_pod_statuses_of_environment_graphql_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [_ENVIRONMENT_RESPONSE, {"errors": [{"message": "boom"}]}]

    with pytest.raises(OperationFailedError, match="boom"):
        await client.environments.get_pod_statuses(ENVIRONMENT_ID)


async def test_get_services_of_environment(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _ENVIRONMENT_RESPONSE,
        {
            "data": {
                "environmentServices": [
                    _service("simple-app", "11111111-2222-3333-4444-555555555555"),
                    _service("simple-app-2", "77777777-8888-9999-aaaa-bbbbbbbbbbbb"),
                ]
            }
        },
    ]

    services = await client.environments.get_services(ENVIRONMENT_ID)

    assert _sent(mock_transport) == [
        ("query GetEnvironment", {"environmentId": ENVIRONMENT_ID}),
        ("query GetEnvironmentServices", {"environmentId": ENVIRONMENT_ID}),
    ]
    assert [(service.resolved_name, str(service.deployment_id)) for service in services] == [
        ("simple-app", "11111111-2222-3333-4444-555555555555"),
        ("simple-app-2", "77777777-8888-9999-aaaa-bbbbbbbbbbbb"),
    ]
    assert all(isinstance(service, DeployedService) for service in services)
    assert services[1].driver_service_name == "simple-app"
    assert services[1].port == 8000


async def test_get_services_of_environment_by_name(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [_ENVIRONMENT_RESPONSE, {"data": {"environmentServices": []}}]

    assert await client.environments.get_services(environment_name="demo", cluster_id=CLUSTER_ID) == []
    assert _sent(mock_transport) == [
        ("query GetEnvironment", {"environmentName": "demo", "clusterId": CLUSTER_ID}),
        ("query GetEnvironmentServices", {"environmentId": ENVIRONMENT_ID}),
    ]


async def test_get_services_of_unknown_environment(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = _ENVIRONMENT_NOT_FOUND

    with pytest.raises(ResourceNotFoundError, match="Environment not found"):
        await client.environments.get_services(environment_name="demo", cluster_name="local")
    assert [name for name, _ in _sent(mock_transport)] == ["query GetEnvironment"]


async def test_get_services_of_environment_graphql_error(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [_ENVIRONMENT_RESPONSE, {"errors": [{"message": "boom"}]}]

    with pytest.raises(OperationFailedError, match="boom"):
        await client.environments.get_services(ENVIRONMENT_ID)
