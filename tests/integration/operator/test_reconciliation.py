"""Integration tests for operator reconciliation.

These tests require a running Kubernetes cluster with FluxCD installed.
Run with: uv run pytest tests/integration/operator/ -v

NOTE: Skipped by default. Set STYRMIN_RUN_INTEGRATION_TESTS=1 to enable.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("STYRMIN_RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require STYRMIN_RUN_INTEGRATION_TESTS=1",
)


class TestNetworkPolicyReconciliation:
    """Test that the operator creates and reconciles NetworkPolicies."""

    @pytest.mark.anyio
    async def test_helmrelease_create_triggers_networkpolicy_creation(self) -> None:
        """Verify that creating a HelmRelease with operator-managed label
        triggers the operator to create NetworkPolicies."""
        # TODO: Implement with Kind cluster and kopf.testing
        pytest.skip("Requires Kind cluster infrastructure")

    @pytest.mark.anyio
    async def test_networkpolicy_deletion_triggers_recreation(self) -> None:
        """Verify that deleting an operator-managed NetworkPolicy
        triggers the operator to recreate it."""
        pytest.skip("Requires Kind cluster infrastructure")

    @pytest.mark.anyio
    async def test_networkpolicy_modification_triggers_correction(self) -> None:
        """Verify that modifying an operator-managed NetworkPolicy
        triggers the operator to restore the desired state."""
        pytest.skip("Requires Kind cluster infrastructure")

    @pytest.mark.anyio
    async def test_operator_ignores_unmanaged_resources(self) -> None:
        """Verify that the operator does not touch resources without
        Styrmin ownership labels."""
        pytest.skip("Requires Kind cluster infrastructure")
