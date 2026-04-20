"""Unit tests for CRD status condition updates in the pipeline."""

from styrmin_backend.operator.crd.schema import ConditionStatus, ConditionType, DeploymentPhase
from styrmin_backend.operator.crd.status import (
    build_managed_resource_counts,
    is_condition_true,
    set_condition,
    set_phase,
)


class TestStatusConditionUpdates:
    def test_all_conditions_set_after_full_deployment(self) -> None:
        """Simulate the full pipeline setting all conditions."""
        conditions: list[dict[str, str]] = []

        # Phase 1
        set_condition(conditions, ConditionType.NETWORK_POLICIES_READY, ConditionStatus.TRUE, "AllApplied", "5 created")
        set_condition(conditions, ConditionType.SECRETS_READY, ConditionStatus.TRUE, "AllApplied", "2 created")

        # Phase 2
        set_condition(conditions, ConditionType.HELM_RELEASE_READY, ConditionStatus.TRUE, "FluxReady", "Ready")

        # Phase 3
        set_condition(conditions, ConditionType.SERVICES_READY, ConditionStatus.TRUE, "AllApplied", "3 created")
        set_condition(conditions, ConditionType.MIDDLEWARES_READY, ConditionStatus.TRUE, "AllApplied", "1 created")

        # Overall
        set_condition(conditions, ConditionType.READY, ConditionStatus.TRUE, "AllPhasesComplete", "Healthy")

        assert len(conditions) == 6
        assert is_condition_true(conditions, ConditionType.READY)
        assert is_condition_true(conditions, ConditionType.NETWORK_POLICIES_READY)
        assert is_condition_true(conditions, ConditionType.HELM_RELEASE_READY)

    def test_failure_condition_prevents_ready(self) -> None:
        conditions: list[dict[str, str]] = []

        set_condition(conditions, ConditionType.NETWORK_POLICIES_READY, ConditionStatus.FALSE, "ApplyFailed", "Error")
        set_condition(conditions, ConditionType.SECRETS_READY, ConditionStatus.TRUE, "AllApplied", "OK")

        assert not is_condition_true(conditions, ConditionType.NETWORK_POLICIES_READY)
        # Phase 2 should not proceed
        from styrmin_backend.operator.pipeline import should_proceed_to_helmrelease

        assert should_proceed_to_helmrelease(conditions) is False

    def test_managed_resource_counts_structure(self) -> None:
        counts = build_managed_resource_counts(
            network_policies=5,
            secrets=2,
            helm_releases=1,
            services=3,
            middlewares=1,
        )
        assert counts["networkPolicies"] == 5
        assert counts["helmReleases"] == 1
        assert sum(counts.values()) == 12

    def test_phase_transitions(self) -> None:
        patch: dict = {}
        set_phase(patch, DeploymentPhase.PENDING)
        assert patch["phase"] == "Pending"

        set_phase(patch, DeploymentPhase.CREATING_PREREQUISITES, "Starting")
        assert patch["phase"] == "CreatingPrerequisites"
        assert patch["message"] == "Starting"

        set_phase(patch, DeploymentPhase.READY, "All done")
        assert patch["phase"] == "Ready"
