"""Tests for the transport layer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from styrmin_sdk import StyrminClient, Transport
from styrmin_sdk.exceptions import StyrminTransportError


async def test_execute_success() -> None:
    transport = Transport(server_address="http://test-server:8000")
    mock_response = httpx.Response(
        200,
        json={"data": {"clusters": [{"id": "abc", "name": "test"}]}},
        request=httpx.Request("POST", "http://test-server:8000/graphql"),
    )
    transport._client.post = AsyncMock(return_value=mock_response)

    try:
        result = await transport.execute("query { clusters { id name } }")
        assert result == {"data": {"clusters": [{"id": "abc", "name": "test"}]}}
    finally:
        await transport.close()


async def test_execute_returns_errors_without_raising() -> None:
    """Transport returns the full response including errors for resource-level handling."""
    transport = Transport(server_address="http://test-server:8000")
    mock_response = httpx.Response(
        200,
        json={
            "data": {"cluster": None},
            "errors": [{"message": "Cluster not found", "extensions": {"code": "NOT_FOUND"}}],
        },
        request=httpx.Request("POST", "http://test-server:8000/graphql"),
    )
    transport._client.post = AsyncMock(return_value=mock_response)

    try:
        result = await transport.execute('query { cluster(clusterId: "abc") { id } }')
        assert result["data"]["cluster"] is None
        assert result["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    finally:
        await transport.close()


async def test_execute_http_error() -> None:
    transport = Transport(server_address="http://test-server:8000")
    mock_response = httpx.Response(
        500,
        request=httpx.Request("POST", "http://test-server:8000/graphql"),
    )
    transport._client.post = AsyncMock(return_value=mock_response)

    try:
        with pytest.raises(StyrminTransportError):
            await transport.execute("query { clusters { id } }")
    finally:
        await transport.close()


async def test_execute_connection_error() -> None:
    transport = Transport(server_address="http://test-server:8000")
    transport._client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    try:
        with pytest.raises(StyrminTransportError, match="Connection refused"):
            await transport.execute("query { clusters { id } }")
    finally:
        await transport.close()


async def test_client_context_manager() -> None:
    async with StyrminClient(server_address="http://localhost:9999") as client:
        assert client.clusters is not None
        assert client.deployments is not None
