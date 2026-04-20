"""Unit tests for Kubernetes Event emission."""

from unittest.mock import AsyncMock, patch

import pytest
from styrmin_backend.operator.events import (
    emit_drift_detected,
    emit_reconcile_failed,
    emit_reconcile_succeeded,
)


@pytest.fixture
def mock_api_client() -> AsyncMock:
    return AsyncMock()


class TestEmitReconcileSucceeded:
    @pytest.mark.anyio
    async def test_creates_normal_event(self, mock_api_client: AsyncMock) -> None:
        with patch("styrmin_backend.operator.events.kubeclient.CoreV1Api") as mock_core:
            mock_core_instance = AsyncMock()
            mock_core.return_value = mock_core_instance

            await emit_reconcile_succeeded(
                api_client=mock_api_client,
                namespace="test-ns",
                helmrelease_name="test-hr",
                release_reference="ref-123",
            )

        mock_core_instance.create_namespaced_event.assert_called_once()
        call_kwargs = mock_core_instance.create_namespaced_event.call_args
        event = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert event.reason == "ReconcileSucceeded"
        assert event.type == "Normal"
        assert "ref-123" in event.message


class TestEmitDriftDetected:
    @pytest.mark.anyio
    async def test_creates_normal_event_with_change_type(self, mock_api_client: AsyncMock) -> None:
        with patch("styrmin_backend.operator.events.kubeclient.CoreV1Api") as mock_core:
            mock_core_instance = AsyncMock()
            mock_core.return_value = mock_core_instance

            await emit_drift_detected(
                api_client=mock_api_client,
                namespace="test-ns",
                helmrelease_name="test-hr",
                resource_kind="NetworkPolicy",
                resource_name="np-1",
                change_type="modified",
            )

        mock_core_instance.create_namespaced_event.assert_called_once()
        call_kwargs = mock_core_instance.create_namespaced_event.call_args
        event = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert event.reason == "DriftDetected"
        assert "NetworkPolicy/np-1" in event.message
        assert "modified" in event.message


class TestEmitReconcileFailed:
    @pytest.mark.anyio
    async def test_creates_warning_event(self, mock_api_client: AsyncMock) -> None:
        with patch("styrmin_backend.operator.events.kubeclient.CoreV1Api") as mock_core:
            mock_core_instance = AsyncMock()
            mock_core.return_value = mock_core_instance

            await emit_reconcile_failed(
                api_client=mock_api_client,
                namespace="test-ns",
                helmrelease_name="test-hr",
                resource_kind="Service",
                resource_name="svc-1",
                error_message="permission denied",
            )

        mock_core_instance.create_namespaced_event.assert_called_once()
        call_kwargs = mock_core_instance.create_namespaced_event.call_args
        event = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert event.reason == "ReconcileFailed"
        assert event.type == "Warning"
        assert "permission denied" in event.message

    @pytest.mark.anyio
    async def test_does_not_raise_on_api_failure(self, mock_api_client: AsyncMock) -> None:
        with patch("styrmin_backend.operator.events.kubeclient.CoreV1Api") as mock_core:
            mock_core_instance = AsyncMock()
            mock_core.return_value = mock_core_instance
            mock_core_instance.create_namespaced_event.side_effect = Exception("API down")

            # Should not raise
            await emit_reconcile_failed(
                api_client=mock_api_client,
                namespace="test-ns",
                helmrelease_name="test-hr",
                resource_kind="Service",
                resource_name="svc-1",
                error_message="some error",
            )
