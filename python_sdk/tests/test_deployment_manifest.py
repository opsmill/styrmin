"""Pydantic validation tests for the deployment manifest models.

Hygiene tests added alongside T015-T017 to ensure the models behave per
`specs/009-deployments-apply/contracts/manifest-schema.md` before downstream
chunks build on them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from styrmin_sdk.models.deployment_manifest import (
    ApplyOutcome,
    ApplyOverrides,
    DeploymentManifest,
    ResolvedManifest,
)


def _full_manifest_dict() -> dict[str, Any]:
    return {
        "apiVersion": "styrmin/v1",
        "kind": "Deployment",
        "metadata": {"name": "my-app"},
        "spec": {
            "driver": "acme/my-driver",
            "version": "1.2.3",
            "environment": "production",
            "cluster": "us-east",
            "config": {"log_level": "info"},
            "parameters": {"replicas": 2},
        },
    }


def test_full_manifest_validates() -> None:
    manifest = DeploymentManifest.model_validate(_full_manifest_dict())
    assert manifest.metadata.name == "my-app"
    assert manifest.spec.driver == "acme/my-driver"
    assert manifest.spec.config == {"log_level": "info"}


def test_minimum_manifest_defaults_cleanly() -> None:
    manifest = DeploymentManifest.model_validate(
        {
            "apiVersion": "styrmin/v1",
            "kind": "Deployment",
            "spec": {"driver": "acme/my-driver"},
        },
    )
    assert manifest.metadata.name is None
    assert manifest.spec.version is None
    assert manifest.spec.environment is None
    assert manifest.spec.cluster is None
    assert manifest.spec.config == {}
    assert manifest.spec.parameters == {}


def test_missing_api_version_fails() -> None:
    data = _full_manifest_dict()
    del data["apiVersion"]
    with pytest.raises(ValidationError):
        DeploymentManifest.model_validate(data)


def test_wrong_api_version_fails() -> None:
    data = _full_manifest_dict()
    data["apiVersion"] = "styrmin/v2"
    with pytest.raises(ValidationError):
        DeploymentManifest.model_validate(data)


def test_wrong_kind_fails() -> None:
    data = _full_manifest_dict()
    data["kind"] = "Pod"
    with pytest.raises(ValidationError):
        DeploymentManifest.model_validate(data)


def test_unknown_top_level_key_fails() -> None:
    data = _full_manifest_dict()
    data["status"] = {"phase": "running"}
    with pytest.raises(ValidationError):
        DeploymentManifest.model_validate(data)


def test_unknown_spec_key_fails() -> None:
    data = _full_manifest_dict()
    spec = data["spec"]
    assert isinstance(spec, dict)
    spec["replicas"] = 3
    with pytest.raises(ValidationError):
        DeploymentManifest.model_validate(data)


def test_empty_driver_fails() -> None:
    data = _full_manifest_dict()
    spec = data["spec"]
    assert isinstance(spec, dict)
    spec["driver"] = ""
    with pytest.raises(ValidationError):
        DeploymentManifest.model_validate(data)


def test_resolved_manifest_requires_all_identity_fields() -> None:
    resolved = ResolvedManifest(
        name="my-app",
        driver="acme/my-driver",
        version="1.2.3",
        environment="prod",
        source_path=Path("manifest.yaml"),
    )
    assert resolved.cluster is None
    assert resolved.config == {}
    assert resolved.parameters == {}


def test_resolved_manifest_missing_required_fails() -> None:
    # Use model_validate so missing required fields surface as ValidationError
    # rather than a constructor type error.
    with pytest.raises(ValidationError):
        ResolvedManifest.model_validate(
            {
                "name": "my-app",
                "driver": "acme/my-driver",
                # version missing
                "environment": "prod",
                "source_path": Path("manifest.yaml"),
            },
        )


def test_apply_overrides_all_optional() -> None:
    overrides = ApplyOverrides()
    assert overrides.name is None
    assert overrides.version is None
    assert overrides.environment is None
    assert overrides.cluster is None


def test_apply_outcome_valid_actions() -> None:
    outcome = ApplyOutcome(
        name="my-app",
        action="created",
        deployment_id=uuid4(),
        task_id=uuid4(),
    )
    assert outcome.action == "created"
    assert outcome.failure_reason is None


def test_apply_outcome_invalid_action_fails() -> None:
    with pytest.raises(ValidationError):
        ApplyOutcome.model_validate({"name": "my-app", "action": "frobnicated"})
