"""Unit tests for ``apply_kubernetes_resource`` on the Ingress kind (#598).

An Ingress belongs to ``networking.k8s.io/v1``, a built-in API group. The first
version of the function sent it down the custom-resource path, which built the
plural ``ingresss`` and was refused with 403 by the Kubernetes API server.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_resource,
)

_apply_resource = apply_kubernetes_resource.__wrapped__

PRIMITIVES = "styrmin_backend.agent.service.kubernetes.primitives"
NETWORKING_V1_API = f"{PRIMITIVES}.kubeclient.NetworkingV1Api"

_INGRESS: dict[str, Any] = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "Ingress",
    "metadata": {"name": "styrmin-svc-task-manager", "namespace": "styrmin-abc"},
    "spec": {"rules": [{"host": "task-manager-env.example.com"}]},
}


def _mock_api(create_error: Exception | None) -> MagicMock:
    api = MagicMock()
    api.create_namespaced_ingress = AsyncMock(side_effect=create_error)
    api.replace_namespaced_ingress = AsyncMock()
    return api


@pytest.mark.asyncio
async def test_an_ingress_is_created_with_the_networking_api() -> None:
    api = _mock_api(None)
    with (
        patch(NETWORKING_V1_API, return_value=api),
        patch(f"{PRIMITIVES}.upsert_custom_resource", new=AsyncMock()) as custom,
    ):
        await _apply_resource(resource=_INGRESS, namespace="styrmin-abc", client=None)

    api.create_namespaced_ingress.assert_awaited_once_with(
        namespace="styrmin-abc", body=_INGRESS
    )
    api.replace_namespaced_ingress.assert_not_awaited()
    custom.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_existing_ingress_is_replaced() -> None:
    api = _mock_api(ApiException(status=409))
    with patch(NETWORKING_V1_API, return_value=api):
        await _apply_resource(resource=_INGRESS, namespace="styrmin-abc", client=None)

    api.replace_namespaced_ingress.assert_awaited_once_with(
        name="styrmin-svc-task-manager", namespace="styrmin-abc", body=_INGRESS
    )


@pytest.mark.asyncio
async def test_other_ingress_create_errors_are_raised_without_replace() -> None:
    api = _mock_api(ApiException(status=403))
    with patch(NETWORKING_V1_API, return_value=api), pytest.raises(ApiException):
        await _apply_resource(resource=_INGRESS, namespace="styrmin-abc", client=None)

    api.replace_namespaced_ingress.assert_not_awaited()
