"""Unit tests for ``apply_service``, the one create-then-replace for Services (#503)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_resource,
    apply_service,
)

# Undecorated functions: inject a dummy client without fast_depends' type validation.
_apply = apply_service.__wrapped__
_apply_resource = apply_kubernetes_resource.__wrapped__

PRIMITIVES = "styrmin_backend.agent.service.kubernetes.primitives"
CORE_V1_API = f"{PRIMITIVES}.kubeclient.CoreV1Api"

_CLUSTER_IP_SERVICE: dict[str, Any] = {
    "apiVersion": "v1",
    "kind": "Service",
    "metadata": {"name": "intent", "namespace": "styrmin-executor"},
    "spec": {
        "type": "ClusterIP",
        "ports": [{"port": 80}],
        "selector": {"app": "intent"},
    },
}


def _mock_api(create_error: Exception | None) -> MagicMock:
    api = MagicMock()
    api.create_namespaced_service = AsyncMock(
        side_effect=create_error, return_value="created"
    )
    api.replace_namespaced_service = AsyncMock(return_value="replaced")
    return api


@pytest.mark.asyncio
async def test_create_returns_the_created_service() -> None:
    api = _mock_api(None)
    with patch(CORE_V1_API, return_value=api):
        result = await _apply(
            resource=_CLUSTER_IP_SERVICE, namespace="styrmin-executor", client=None
        )

    assert result == "created"
    api.create_namespaced_service.assert_awaited_once_with(
        namespace="styrmin-executor", body=_CLUSTER_IP_SERVICE
    )
    api.replace_namespaced_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_cluster_ip_service_replaces_alias_a_failed_teardown_left() -> None:
    """A failed teardown left an ExternalName alias with the Service's name: create gets 409."""
    api = _mock_api(ApiException(status=409))
    with patch(CORE_V1_API, return_value=api):
        result = await _apply(
            resource=_CLUSTER_IP_SERVICE, namespace="styrmin-executor", client=None
        )

    assert result == "replaced"
    api.replace_namespaced_service.assert_awaited_once_with(
        name="intent", namespace="styrmin-executor", body=_CLUSTER_IP_SERVICE
    )


@pytest.mark.asyncio
async def test_other_create_errors_are_raised_without_replace() -> None:
    api = _mock_api(ApiException(status=500))
    with patch(CORE_V1_API, return_value=api), pytest.raises(ApiException) as raised:
        await _apply(
            resource=_CLUSTER_IP_SERVICE, namespace="styrmin-executor", client=None
        )

    assert raised.value.status == 500
    api.replace_namespaced_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_kubernetes_resource_writes_services_with_apply_service() -> None:
    with (
        patch(f"{PRIMITIVES}.apply_service", new=AsyncMock()) as apply,
        patch(CORE_V1_API) as core_api,
    ):
        await _apply_resource(
            resource=_CLUSTER_IP_SERVICE, namespace="styrmin-executor", client=None
        )

    apply.assert_awaited_once_with(
        resource=_CLUSTER_IP_SERVICE, namespace="styrmin-executor", client=None
    )
    core_api.assert_not_called()
