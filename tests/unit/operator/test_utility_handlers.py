"""Unit tests for utility resource drift handlers."""

from unittest.mock import AsyncMock, patch

import pytest
from styrmin_backend.operator.handlers.utility_resources import (
    _reconcile_resource_drift,  # noqa: PLC2701
)


@pytest.fixture
def mock_helmrelease() -> dict:
    return {
        "metadata": {
            "name": "test-hr",
            "labels": {
                "app.kubernetes.io/managed-by": "styrmin",
                "styrmin.io/operator-managed": "true",
                "styrmin.io/release-reference": "ref-123",
            },
            "annotations": {
                "styrmin.io/deployment-id": "deploy-uuid",
            },
        },
    }


class TestReconcileResourceDrift:
    @pytest.mark.anyio
    async def test_skips_when_deployment_in_progress(self, mock_helmrelease: dict) -> None:
        mock_helmrelease["metadata"]["annotations"]["styrmin.io/deployment-in-progress"] = "true"

        with (
            patch(
                "styrmin_backend.operator.handlers.utility_resources._find_helmrelease_for_resource",
                new_callable=AsyncMock,
                return_value=mock_helmrelease,
            ),
            patch(
                "styrmin_backend.operator.handlers.utility_resources.fetch_context",
                new_callable=AsyncMock,
            ) as mock_fetch,
        ):
            await _reconcile_resource_drift(
                namespace="ns",
                resource_kind="Service",
                resource_name="svc-1",
                release_reference="ref-123",
                change_type="modified",
                logger=AsyncMock(),
            )

        # Should not fetch context since deployment is in progress
        mock_fetch.assert_not_called()

    @pytest.mark.anyio
    async def test_reconciles_when_no_deployment_in_progress(self, mock_helmrelease: dict) -> None:
        mock_context = AsyncMock()

        with (
            patch(
                "styrmin_backend.operator.handlers.utility_resources._find_helmrelease_for_resource",
                new_callable=AsyncMock,
                return_value=mock_helmrelease,
            ),
            patch(
                "styrmin_backend.operator.handlers.utility_resources.fetch_context",
                new_callable=AsyncMock,
                return_value=mock_context,
            ),
            patch(
                "styrmin_backend.operator.handlers.utility_resources.build_desired_resources",
                return_value=[{"kind": "Service", "metadata": {"name": "svc-1", "namespace": "ns"}, "spec": {}}],
            ),
            patch(
                "styrmin_backend.operator.handlers.utility_resources.list_managed_resources",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "styrmin_backend.operator.handlers.utility_resources.reconcile_resources",
                new_callable=AsyncMock,
            ) as mock_reconcile,
        ):
            from styrmin_backend.operator.reconciler import ReconcileResult

            mock_reconcile.return_value = ReconcileResult(created=1)

            await _reconcile_resource_drift(
                namespace="ns",
                resource_kind="Service",
                resource_name="svc-1",
                release_reference="ref-123",
                change_type="modified",
                logger=AsyncMock(),
            )

        mock_reconcile.assert_called_once()

    @pytest.mark.anyio
    async def test_skips_when_no_helmrelease_found(self) -> None:
        with (
            patch(
                "styrmin_backend.operator.handlers.utility_resources._find_helmrelease_for_resource",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "styrmin_backend.operator.handlers.utility_resources.fetch_context",
                new_callable=AsyncMock,
            ) as mock_fetch,
        ):
            await _reconcile_resource_drift(
                namespace="ns",
                resource_kind="Secret",
                resource_name="sec-1",
                release_reference="ref-123",
                change_type="deleted",
                logger=AsyncMock(),
            )

        mock_fetch.assert_not_called()
