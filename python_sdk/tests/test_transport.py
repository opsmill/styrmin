"""Tests for the transport layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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

    try:
        with patch.object(transport._client, "post", new=AsyncMock(return_value=mock_response)):
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

    try:
        with patch.object(transport._client, "post", new=AsyncMock(return_value=mock_response)):
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

    try:
        with (
            patch.object(transport._client, "post", new=AsyncMock(return_value=mock_response)),
            pytest.raises(StyrminTransportError),
        ):
            await transport.execute("query { clusters { id } }")
    finally:
        await transport.close()


async def test_execute_connection_error() -> None:
    transport = Transport(server_address="http://test-server:8000")

    try:
        with (
            patch.object(
                transport._client, "post", new=AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            ),
            pytest.raises(StyrminTransportError, match="Connection refused"),
        ):
            await transport.execute("query { clusters { id } }")
    finally:
        await transport.close()


async def test_execute_read_timeout_has_actionable_message() -> None:
    """A ``ReadTimeout`` stringifies to empty in httpx; the transport must
    still surface a non-empty, actionable message (kind + target URL +
    timeout + reachability hint) rather than wrapping an empty string.

    Regression: ``deployments apply`` printed ``failed <name>: manifest
    <path>:`` with no reason when the server was unreachable.
    """
    transport = Transport(server_address="http://test-server:8000", timeout=30.0)

    try:
        with (
            patch.object(transport._client, "post", new=AsyncMock(side_effect=httpx.ReadTimeout(""))),
            pytest.raises(StyrminTransportError) as exc_info,
        ):
            await transport.execute("query { clusters { id } }")
    finally:
        await transport.close()

    message = str(exc_info.value)
    assert message.strip()  # never blank
    assert "ReadTimeout" in message
    assert "http://test-server:8000/graphql" in message
    assert "30.0" in message


async def test_describe_http_error_preserves_detail_for_connect_error() -> None:
    """ConnectError keeps the underlying httpx detail AND adds a hint."""
    transport = Transport(server_address="http://test-server:8000")
    try:
        message = transport._describe_http_error(httpx.ConnectError("Connection refused"), "POST", "/graphql")
    finally:
        await transport.close()

    assert "ConnectError" in message
    assert "Connection refused" in message
    assert "http://test-server:8000" in message


async def test_client_context_manager() -> None:
    async with StyrminClient(server_address="http://localhost:9999") as client:
        assert client.clusters is not None
        assert client.deployments is not None
