"""Unit tests for CRD-based drift detection."""

from unittest.mock import AsyncMock, patch

import pytest
from styrmin_backend.operator.reconciler import observe_helmrelease


def _helmrelease(ready_status: str) -> dict:
    return {
        "metadata": {"generation": 1},
        "status": {
            "conditions": [
                {"type": "Ready", "status": ready_status, "observedGeneration": 1},
            ],
        },
    }


class TestObserveHelmRelease:
    @pytest.mark.anyio
    async def test_ready_when_current_generation_is_ready(self) -> None:
        with patch(
            "styrmin_backend.operator.reconciler._get_helmrelease",
            new_callable=AsyncMock,
            return_value=_helmrelease("True"),
        ):
            observation = await observe_helmrelease("ns", "ref-123")
        assert observation is not None
        assert observation.is_ready is True

    @pytest.mark.anyio
    async def test_not_ready_when_current_generation_is_not_ready(self) -> None:
        with patch(
            "styrmin_backend.operator.reconciler._get_helmrelease",
            new_callable=AsyncMock,
            return_value=_helmrelease("False"),
        ):
            observation = await observe_helmrelease("ns", "ref-123")
        assert observation is not None
        assert observation.is_ready is False

    @pytest.mark.anyio
    async def test_none_when_not_found(self) -> None:
        with patch(
            "styrmin_backend.operator.reconciler._get_helmrelease",
            new_callable=AsyncMock,
            return_value=None,
        ):
            assert await observe_helmrelease("ns", "ref-123") is None
