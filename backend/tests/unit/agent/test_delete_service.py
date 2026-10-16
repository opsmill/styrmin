"""Unit tests for ``delete_service``, which deletes a stale service alias (#491)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import delete_service

# Undecorated function: inject a dummy client without fast_depends' type validation.
_delete = delete_service.__wrapped__

CORE_V1_API = "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CoreV1Api"


async def _delete_with(side_effect: Exception | None) -> tuple[bool, AsyncMock]:
    api = MagicMock()
    api.delete_namespaced_service = AsyncMock(side_effect=side_effect)
    with patch(CORE_V1_API, return_value=api):
        deleted = await _delete(
            name="old-name", namespace="styrmin-peer", resource_version="7", client=None
        )
    return deleted, api.delete_namespaced_service


@pytest.mark.asyncio
async def test_deletes_only_the_listed_version() -> None:
    deleted, call = await _delete_with(None)

    assert deleted is True
    kwargs = call.await_args.kwargs
    assert (kwargs["name"], kwargs["namespace"]) == ("old-name", "styrmin-peer")
    assert kwargs["body"].preconditions.resource_version == "7"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [404, 409])
async def test_gone_or_changed_service_is_not_an_error(code: int) -> None:
    """404: already deleted. 409: another deployment's flow rewrote the alias since the list."""
    deleted, _ = await _delete_with(ApiException(status=code))

    assert deleted is False


@pytest.mark.asyncio
async def test_other_api_errors_are_raised() -> None:
    with pytest.raises(ApiException):
        await _delete_with(ApiException(status=403))
