"""Unit tests for the combined operator + Prefect worker entrypoint."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestShutdownPropagation:
    @pytest.mark.anyio
    async def test_shutdown_event_propagates_to_prefect(self) -> None:
        """Verify that setting the shutdown event stops the Prefect worker."""
        from styrmin_backend.entrypoint import combined

        # Reset the module-level event
        combined._shutdown = asyncio.Event()

        with patch.object(
            combined,
            "ProcessWorker",
        ) as mock_worker_cls:
            mock_worker = AsyncMock()
            mock_worker.name = "test-worker"
            mock_worker.heartbeat_interval_seconds = 30
            mock_worker.get_and_submit_flow_runs = AsyncMock()
            mock_worker.sync_with_backend = AsyncMock()
            mock_worker.__aenter__ = AsyncMock(return_value=mock_worker)
            mock_worker.__aexit__ = AsyncMock(return_value=False)
            mock_worker_cls.return_value = mock_worker

            # Signal shutdown after a brief delay
            async def signal_shutdown() -> None:
                await asyncio.sleep(0.1)
                combined._shutdown.set()

            shutdown_task = asyncio.create_task(signal_shutdown())
            await combined.run_prefect_worker("test-pool")
            await shutdown_task

        # Worker context manager should have been entered and exited
        mock_worker.__aenter__.assert_called_once()
        mock_worker.__aexit__.assert_called_once()


class TestOnStartup:
    @pytest.mark.anyio
    async def test_configures_peering(self) -> None:
        from styrmin_backend.entrypoint.combined import on_startup

        settings = MagicMock()
        settings.peering = MagicMock()

        await on_startup(settings=settings)

        assert settings.peering.name == "styrmin-operator"
        assert settings.peering.mandatory is True
        assert settings.peering.priority == 100


class TestOnCleanup:
    @pytest.mark.anyio
    async def test_sets_shutdown_event(self) -> None:
        from styrmin_backend.entrypoint import combined

        combined._shutdown = asyncio.Event()
        assert not combined._shutdown.is_set()

        await combined.on_cleanup()

        assert combined._shutdown.is_set()
