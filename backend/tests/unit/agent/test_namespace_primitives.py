"""Unit tests for ``get_namespace`` and ``is_namespace_gone_error`` (#503)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import (
    get_namespace,
    is_namespace_gone_error,
)

# Undecorated function: inject a dummy client without fast_depends' type validation.
_get = get_namespace.__wrapped__

CORE_V1_API = "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CoreV1Api"


def _api_error(status: int, body: str | bytes | None = None) -> ApiException:
    exc = ApiException(status=status)
    exc.body = body
    return exc


async def _get_with(side_effect: Exception | None) -> tuple[object, AsyncMock]:
    api = MagicMock()
    api.read_namespace = AsyncMock(side_effect=side_effect, return_value="namespace")
    with patch(CORE_V1_API, return_value=api):
        result = await _get(name="styrmin-peer", client=None)
    return result, api.read_namespace


@pytest.mark.asyncio
async def test_get_namespace_returns_the_namespace() -> None:
    result, call = await _get_with(None)

    assert result == "namespace"
    call.assert_awaited_once_with(name="styrmin-peer")


@pytest.mark.asyncio
async def test_get_namespace_returns_none_when_missing() -> None:
    result, _ = await _get_with(ApiException(status=404))

    assert result is None


@pytest.mark.asyncio
async def test_get_namespace_raises_other_errors() -> None:
    with pytest.raises(ApiException) as raised:
        await _get_with(ApiException(status=500))

    assert raised.value.status == 500


_TERMINATING_STATUS = json.dumps(
    {"details": {"causes": [{"type": "NamespaceTerminating"}]}}
)
_TERMINATING_MESSAGE = (
    'services "intent" is forbidden: unable to create new content in namespace '
    "styrmin-peer because it is being terminated"
)
_RBAC_MESSAGE = (
    'services is forbidden: User "system:serviceaccount:styrmin:agent" cannot create '
    'resource "services" in API group "" in the namespace "styrmin-peer"'
)


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_api_error(404), id="namespace-not-found"),
        pytest.param(_api_error(403, _TERMINATING_STATUS), id="terminating-cause"),
        pytest.param(
            _api_error(403, _TERMINATING_STATUS.encode()), id="terminating-cause-bytes"
        ),
        pytest.param(_api_error(403, _TERMINATING_MESSAGE), id="terminating-message"),
    ],
)
def test_namespace_gone_errors(exc: ApiException) -> None:
    assert is_namespace_gone_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_api_error(403, _RBAC_MESSAGE), id="rbac-forbidden"),
        pytest.param(_api_error(403), id="forbidden-without-body"),
        pytest.param(_api_error(409), id="conflict"),
        pytest.param(_api_error(500), id="server-error"),
    ],
)
def test_other_errors_are_not_namespace_gone(exc: ApiException) -> None:
    assert is_namespace_gone_error(exc) is False
