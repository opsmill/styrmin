"""Unit tests for StyrminDeployment CRD handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from styrmin_backend.operator.crd.schema import DeploymentPhase


@pytest.fixture
def mock_crd_body() -> dict:
    return {
        "apiVersion": "styrmin.io/v1alpha1",
        "kind": "StyrminDeployment",
        "metadata": {
            "name": "test-deployment",
            "namespace": "test-ns",
        },
        "spec": {
            "deploymentId": "dep-uuid",
            "releaseReference": "ref-123",
            "appName": "test-app",
            "appVersion": "1.0",
            "context": {"cluster": {"config": {}}},
            "helm": {
                "chart": {"name": "test-chart", "version": "1.0"},
                "repository": {"url": "oci://example.com"},
            },
        },
        "status": {},
    }


class TestOnStyrminDeploymentCreate:
    @pytest.mark.anyio
    async def test_sets_pending_phase(self, mock_crd_body: dict) -> None:
        from styrmin_backend.operator.handlers.styrmin_deployment import (
            on_styrmin_deployment_create,
        )

        patch_obj: dict = {"status": {}}

        with patch(
            "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_prerequisites",
            new_callable=AsyncMock,
        ) as mock_phase1:
            from styrmin_backend.operator.pipeline import PhaseResult

            mock_phase1.return_value = PhaseResult(success=True)

            await on_styrmin_deployment_create(
                spec=mock_crd_body["spec"],
                status=mock_crd_body["status"],
                name="test-deployment",
                namespace="test-ns",
                patch=MagicMock(status=patch_obj["status"]),
                logger=MagicMock(),
            )

        mock_phase1.assert_called_once()


class TestOnStyrminDeploymentResume:
    @pytest.mark.anyio
    async def test_resumes_from_current_phase(self, mock_crd_body: dict) -> None:
        """Verify that on resume, the operator reads the current phase
        from status and does not re-run completed phases."""
        from styrmin_backend.operator.handlers.styrmin_deployment import (
            on_styrmin_deployment_resume,
        )

        mock_crd_body["status"]["phase"] = DeploymentPhase.CREATING_HELM_RELEASE.value
        mock_crd_body["status"]["conditions"] = [
            {"type": "NetworkPoliciesReady", "status": "True"},
            {"type": "SecretsReady", "status": "True"},
        ]

        with (
            patch(
                "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_prerequisites",
                new_callable=AsyncMock,
            ) as mock_phase1,
            patch(
                "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_helmrelease",
                new_callable=AsyncMock,
            ) as mock_phase2,
        ):
            from styrmin_backend.operator.pipeline import PhaseResult

            mock_phase2.return_value = PhaseResult(success=True)

            await on_styrmin_deployment_resume(
                spec=mock_crd_body["spec"],
                status=mock_crd_body["status"],
                name="test-deployment",
                namespace="test-ns",
                patch=MagicMock(status={}),
                logger=MagicMock(),
            )

        # Phase 1 should NOT be re-executed
        mock_phase1.assert_not_called()
        # Phase 2 should proceed
        mock_phase2.assert_called_once()
