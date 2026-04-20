"""Unit tests for CRD-based Prefect orchestration flows."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCreateInstanceCrd:
    @pytest.mark.anyio
    async def test_creates_styrmin_deployment_crd(self) -> None:
        from styrmin_backend.agent.tasks.orchestration import create_instance_crd

        mock_instance = MagicMock()
        mock_context = MagicMock()
        mock_context.instance.release_reference = "ref-123"
        mock_context.instance.namespace = "test-ns"
        mock_context.instance.deployment_id = "dep-uuid"
        mock_context.app.name = "test-app"
        mock_context.app.version = "1.0"
        mock_context.labels = {}
        mock_instance.context = mock_context

        with (
            patch("styrmin_backend.agent.tasks.orchestration.config") as mock_config,
            patch("styrmin_backend.agent.tasks.orchestration.get_run_logger") as mock_logger_fn,
            patch("styrmin_backend.agent.tasks.orchestration.build_styrmin_deployment_body") as mock_builder,
            patch(
                "styrmin_backend.agent.tasks.orchestration.apply_kubernetes_namespace",
                new_callable=AsyncMock,
            ),
            patch(
                "styrmin_backend.agent.tasks.orchestration.upsert_custom_resource",
                new_callable=AsyncMock,
            ) as mock_upsert,
        ):
            mock_config.SETTINGS.initialized = True
            mock_logger_fn.return_value = MagicMock()
            mock_builder.return_value = {"apiVersion": "styrmin.io/v1alpha1", "kind": "StyrminDeployment"}

            await create_instance_crd(
                instance=mock_instance,
                prehook=None,
                posthook=None,
            )

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["plurals"] == "styrmindeployments"
        assert call_kwargs.kwargs["group"] == "styrmin.io"
