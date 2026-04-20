"""Unit tests for the operator state resolution client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from styrmin_backend.operator.state import (
    add_operator_managed_label,
    fetch_context,
    filter_resources_by_kind,
)


class TestFetchContext:
    @pytest.mark.anyio
    async def test_returns_context_on_success(self) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "cluster": {"config": {}},
            "environment": {"config": {}, "name": "test"},
            "deployment": {"config": {}},
            "instance": {
                "config": {},
                "deployment_id": "550e8400-e29b-41d4-a716-446655440000",
                "namespace": "test-ns",
                "release_reference": "ref-123",
            },
            "app": {
                "name": "test-app",
                "version": "1.0",
                "helm": {
                    "chart": {"id": "chart-id", "name": "chart", "version": "1.0", "values_template": ""},
                    "repository": {"id": "repo-id", "url": "https://example.com"},
                },
            },
            "labels": {},
            "utilities": [],
            "parameters": {},
            "services": {},
            "deployed_services": [],
        }

        with patch("styrmin_backend.operator.state.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            context = await fetch_context("550e8400-e29b-41d4-a716-446655440000")

        assert context.app.name == "test-app"
        assert str(context.instance.deployment_id) == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.anyio
    async def test_raises_on_http_error(self) -> None:
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        with patch("styrmin_backend.operator.state.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await fetch_context("some-id")


class TestFilterResourcesByKind:
    def test_filters_correctly(self) -> None:
        resources = [
            {"kind": "NetworkPolicy", "metadata": {"name": "np"}},
            {"kind": "Service", "metadata": {"name": "svc"}},
            {"kind": "NetworkPolicy", "metadata": {"name": "np2"}},
        ]
        result = filter_resources_by_kind(resources, "NetworkPolicy")
        assert len(result) == 2
        assert all(r["kind"] == "NetworkPolicy" for r in result)

    def test_returns_empty_when_no_match(self) -> None:
        resources = [{"kind": "Service", "metadata": {"name": "svc"}}]
        assert filter_resources_by_kind(resources, "NetworkPolicy") == []


class TestAddOperatorManagedLabel:
    def test_adds_label(self) -> None:
        resource: dict = {"kind": "NetworkPolicy", "metadata": {"name": "np"}}
        result = add_operator_managed_label(resource)
        assert result["metadata"]["labels"]["styrmin.io/operator-managed"] == "true"

    def test_preserves_existing_labels(self) -> None:
        resource: dict = {
            "kind": "NetworkPolicy",
            "metadata": {"name": "np", "labels": {"existing": "label"}},
        }
        result = add_operator_managed_label(resource)
        assert result["metadata"]["labels"]["existing"] == "label"
        assert result["metadata"]["labels"]["styrmin.io/operator-managed"] == "true"
