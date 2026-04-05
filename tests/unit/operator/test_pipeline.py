"""Unit tests for the ordered deployment pipeline."""

from unittest.mock import AsyncMock, patch

import pytest


class TestPipelinePhaseOrdering:
    @pytest.mark.anyio
    async def test_phase1_creates_netpols_and_secrets(self) -> None:
        from styrmin_backend.operator.pipeline import execute_phase_prerequisites

        mock_resources = [
            {"kind": "NetworkPolicy", "metadata": {"name": "np-1"}, "spec": {}},
            {"kind": "Secret", "metadata": {"name": "sec-1"}, "spec": {}},
            {"kind": "Service", "metadata": {"name": "svc-1"}, "spec": {}},
        ]

        with (
            patch(
                "styrmin_backend.operator.pipeline.build_desired_resources_from_crd",
                return_value=mock_resources,
            ),
            patch(
                "styrmin_backend.operator.pipeline.apply_kubernetes_resource",
                new_callable=AsyncMock,
            ) as mock_apply,
        ):
            result = await execute_phase_prerequisites(
                crd_spec={"context": {}, "releaseReference": "ref-1", "deploymentId": "dep-1"},
                namespace="ns",
            )

        # Should only apply NetworkPolicies and Secrets, not Services
        applied_kinds = [call.kwargs["resource"]["kind"] for call in mock_apply.call_args_list]
        assert "NetworkPolicy" in applied_kinds
        assert "Secret" in applied_kinds
        assert "Service" not in applied_kinds
        assert result.success is True

    @pytest.mark.anyio
    async def test_phase2_blocked_when_phase1_incomplete(self) -> None:
        from styrmin_backend.operator.pipeline import should_proceed_to_helmrelease

        conditions: list[dict[str, str]] = []
        assert should_proceed_to_helmrelease(conditions) is False

    @pytest.mark.anyio
    async def test_phase2_proceeds_when_phase1_complete(self) -> None:
        from styrmin_backend.operator.pipeline import should_proceed_to_helmrelease

        conditions = [
            {"type": "NetworkPoliciesReady", "status": "True"},
            {"type": "SecretsReady", "status": "True"},
        ]
        assert should_proceed_to_helmrelease(conditions) is True

    @pytest.mark.anyio
    async def test_phase3_blocked_when_helmrelease_not_ready(self) -> None:
        from styrmin_backend.operator.pipeline import should_proceed_to_services

        conditions = [
            {"type": "NetworkPoliciesReady", "status": "True"},
            {"type": "SecretsReady", "status": "True"},
            {"type": "HelmReleaseReady", "status": "False"},
        ]
        assert should_proceed_to_services(conditions) is False

    @pytest.mark.anyio
    async def test_phase1_failure_reports_error(self) -> None:
        from styrmin_backend.operator.pipeline import execute_phase_prerequisites

        with (
            patch(
                "styrmin_backend.operator.pipeline.build_desired_resources_from_crd",
                return_value=[{"kind": "NetworkPolicy", "metadata": {"name": "np-1"}, "spec": {}}],
            ),
            patch(
                "styrmin_backend.operator.pipeline.apply_kubernetes_resource",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
        ):
            result = await execute_phase_prerequisites(
                crd_spec={"context": {}, "releaseReference": "ref-1", "deploymentId": "dep-1"},
                namespace="ns",
            )

        assert result.success is False
        assert len(result.errors) > 0
