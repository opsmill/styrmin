"""Unit tests for CRD schema models and status helpers."""

import pytest
from styrmin_backend.operator.crd.schema import (
    ConditionStatus,
    ConditionType,
    DeploymentPhase,
    StyrminDeploymentSpec,
    StyrminDeploymentStatus,
)
from styrmin_backend.operator.crd.status import (
    build_managed_resource_counts,
    get_condition,
    is_condition_true,
    set_condition,
    set_phase,
)


class TestStyrminDeploymentSpec:
    def test_parses_from_crd_body(self) -> None:
        raw = {
            "deploymentId": "550e8400-e29b-41d4-a716-446655440000",
            "releaseReference": "abc123",
            "appName": "infrahub",
            "appVersion": "1.7.2",
            "context": {"cluster": {"config": {}}},
            "helm": {
                "chart": {"name": "infrahub", "version": "4.16.3"},
                "repository": {"url": "oci://registry.example.com"},
            },
        }
        spec = StyrminDeploymentSpec.model_validate(raw)
        assert spec.deployment_id == "550e8400-e29b-41d4-a716-446655440000"
        assert spec.app_name == "infrahub"
        assert spec.helm.chart.name == "infrahub"

    def test_rejects_missing_required_fields(self) -> None:
        with pytest.raises(ValueError):
            StyrminDeploymentSpec.model_validate({"appName": "test"})


class TestStyrminDeploymentStatus:
    def test_defaults(self) -> None:
        status = StyrminDeploymentStatus()
        assert status.phase == DeploymentPhase.PENDING
        assert status.conditions == []
        assert status.managed_resources.network_policies == 0


class TestSetCondition:
    def test_adds_new_condition(self) -> None:
        conditions: list[dict[str, str]] = []
        set_condition(
            conditions,
            ConditionType.NETWORK_POLICIES_READY,
            ConditionStatus.TRUE,
            "AllApplied",
            "5 NetworkPolicies created",
        )
        assert len(conditions) == 1
        assert conditions[0]["type"] == "NetworkPoliciesReady"
        assert conditions[0]["status"] == "True"

    def test_replaces_existing_condition(self) -> None:
        conditions = [
            {
                "type": "NetworkPoliciesReady",
                "status": "False",
                "reason": "Pending",
                "message": "",
                "lastTransitionTime": "",
            },
        ]
        set_condition(
            conditions,
            ConditionType.NETWORK_POLICIES_READY,
            ConditionStatus.TRUE,
            "AllApplied",
            "Done",
        )
        assert len(conditions) == 1
        assert conditions[0]["status"] == "True"


class TestGetCondition:
    def test_returns_condition(self) -> None:
        conditions = [{"type": "Ready", "status": "True"}]
        assert get_condition(conditions, "Ready") is not None

    def test_returns_none_when_missing(self) -> None:
        assert get_condition([], "Ready") is None


class TestIsConditionTrue:
    def test_true_when_true(self) -> None:
        conditions = [{"type": "Ready", "status": "True"}]
        assert is_condition_true(conditions, "Ready") is True

    def test_false_when_false(self) -> None:
        conditions = [{"type": "Ready", "status": "False"}]
        assert is_condition_true(conditions, "Ready") is False

    def test_false_when_missing(self) -> None:
        assert is_condition_true([], "Ready") is False


class TestSetPhase:
    def test_sets_phase_and_message(self) -> None:
        patch: dict = {}
        set_phase(patch, DeploymentPhase.CREATING_PREREQUISITES, "Starting phase 1")
        assert patch["phase"] == "CreatingPrerequisites"
        assert patch["message"] == "Starting phase 1"


class TestBuildManagedResourceCounts:
    def test_builds_counts(self) -> None:
        counts = build_managed_resource_counts(
            network_policies=5,
            secrets=2,
            helm_releases=1,
            services=3,
            middlewares=1,
        )
        assert counts["networkPolicies"] == 5
        assert counts["services"] == 3
