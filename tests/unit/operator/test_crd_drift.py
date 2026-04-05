"""Unit tests for CRD-based drift detection."""

from unittest.mock import AsyncMock, patch

import pytest
from styrmin_backend.operator.reconciler import _check_helmrelease_ready  # noqa: PLC2701


class TestCheckHelmReleaseReady:
    @pytest.mark.anyio
    async def test_returns_true_when_ready(self) -> None:
        mock_hr = {
            "status": {
                "conditions": [
                    {"type": "Ready", "status": "True"},
                ],
            },
        }
        with patch(
            "styrmin_backend.operator.reconciler.get_custom_resource",
            new_callable=AsyncMock,
            return_value=mock_hr,
        ):
            assert await _check_helmrelease_ready("ns", "ref-123") is True

    @pytest.mark.anyio
    async def test_returns_false_when_not_ready(self) -> None:
        mock_hr = {
            "status": {
                "conditions": [
                    {"type": "Ready", "status": "False"},
                ],
            },
        }
        with patch(
            "styrmin_backend.operator.reconciler.get_custom_resource",
            new_callable=AsyncMock,
            return_value=mock_hr,
        ):
            assert await _check_helmrelease_ready("ns", "ref-123") is False

    @pytest.mark.anyio
    async def test_returns_false_when_not_found(self) -> None:
        from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound

        with patch(
            "styrmin_backend.operator.reconciler.get_custom_resource",
            new_callable=AsyncMock,
            side_effect=CustomResourceNotFound("not found"),
        ):
            assert await _check_helmrelease_ready("ns", "ref-123") is False
