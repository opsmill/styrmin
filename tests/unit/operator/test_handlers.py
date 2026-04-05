"""Unit tests for kopf HelmRelease handlers."""

from unittest.mock import AsyncMock, patch

import pytest
from styrmin_backend.operator.handlers.helmrelease import (
    on_helmrelease_create,
    on_helmrelease_delete,
)


@pytest.fixture
def mock_helmrelease_body() -> dict:
    return {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "metadata": {
            "name": "test-release",
            "namespace": "test-ns",
            "labels": {
                "app.kubernetes.io/managed-by": "styrmin",
                "styrmin.io/operator-managed": "true",
                "styrmin.io/release-reference": "ref-123",
            },
            "annotations": {
                "styrmin.io/deployment-id": "550e8400-e29b-41d4-a716-446655440000",
            },
        },
    }


class TestOnHelmReleaseCreate:
    @pytest.mark.anyio
    async def test_creates_network_policies(self, mock_helmrelease_body: dict) -> None:
        mock_context = AsyncMock()
        mock_netpols = [
            {"kind": "NetworkPolicy", "metadata": {"name": "ref-123-deny"}, "spec": {}},
        ]

        with (
            patch(
                "styrmin_backend.operator.handlers.helmrelease.fetch_context",
                new_callable=AsyncMock,
                return_value=mock_context,
            ),
            patch(
                "styrmin_backend.operator.handlers.helmrelease.build_desired_resources",
                return_value=[*mock_netpols, {"kind": "Service", "metadata": {"name": "svc"}, "spec": {}}],
            ),
            patch(
                "styrmin_backend.operator.handlers.helmrelease.reconcile_resources",
                new_callable=AsyncMock,
            ) as mock_reconcile,
        ):
            await on_helmrelease_create(
                body=mock_helmrelease_body,
                meta=mock_helmrelease_body["metadata"],
                spec=mock_helmrelease_body.get("spec", {}),
                namespace="test-ns",
                logger=AsyncMock(),
            )

        mock_reconcile.assert_called_once()
        call_kwargs = mock_reconcile.call_args
        # Should only reconcile NetworkPolicies, not Services
        created = call_kwargs.kwargs.get("to_create") or call_kwargs[1].get("to_create") or call_kwargs[0][1]
        assert all(r["kind"] == "NetworkPolicy" for r in created)


class TestOnHelmReleaseDelete:
    @pytest.mark.anyio
    async def test_calls_cleanup(self, mock_helmrelease_body: dict) -> None:
        with patch(
            "styrmin_backend.operator.handlers.helmrelease.cleanup_operator_resources",
            new_callable=AsyncMock,
        ) as mock_cleanup:
            await on_helmrelease_delete(
                body=mock_helmrelease_body,
                meta=mock_helmrelease_body["metadata"],
                spec=mock_helmrelease_body.get("spec", {}),
                namespace="test-ns",
                logger=AsyncMock(),
            )

        mock_cleanup.assert_called_once_with(
            namespace="test-ns",
            release_reference="ref-123",
        )
