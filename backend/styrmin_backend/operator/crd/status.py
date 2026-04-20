"""Status condition helpers for StyrminDeployment CRD.

Functions for building and updating status conditions on the CRD,
used by the pipeline and handlers via kopf's patch.status mechanism.
"""

from __future__ import annotations

import datetime
from typing import Any

from styrmin_backend.operator.crd.schema import (
    ConditionStatus,
    DeploymentPhase,
)


def build_condition(
    condition_type: str,
    status: ConditionStatus,
    reason: str,
    message: str,
) -> dict[str, str]:
    """Build a condition dict suitable for CRD status patch."""
    return {
        "type": condition_type,
        "status": status.value,
        "reason": reason,
        "message": message,
        "lastTransitionTime": datetime.datetime.now(tz=datetime.UTC).isoformat(),
    }


def set_condition(
    conditions: list[dict[str, str]],
    condition_type: str,
    status: ConditionStatus,
    reason: str,
    message: str,
) -> list[dict[str, str]]:
    """Set or update a condition in a conditions list.

    If a condition with the given type already exists, it is replaced.
    Otherwise, a new condition is appended.

    Returns the updated conditions list (mutated in place).
    """
    new_condition = build_condition(condition_type, status, reason, message)

    for i, cond in enumerate(conditions):
        if cond.get("type") == condition_type:
            conditions[i] = new_condition
            return conditions

    conditions.append(new_condition)
    return conditions


def get_condition(
    conditions: list[dict[str, str]],
    condition_type: str,
) -> dict[str, str] | None:
    """Get a condition by type from a conditions list."""
    for cond in conditions:
        if cond.get("type") == condition_type:
            return cond
    return None


def is_condition_true(
    conditions: list[dict[str, str]],
    condition_type: str,
) -> bool:
    """Check if a specific condition is True."""
    cond = get_condition(conditions, condition_type)
    return cond is not None and cond.get("status") == ConditionStatus.TRUE.value


def set_phase(
    patch_status: dict[str, Any],
    phase: DeploymentPhase,
    message: str = "",
) -> None:
    """Set the phase and optional message on a patch.status dict."""
    patch_status["phase"] = phase.value
    if message:
        patch_status["message"] = message


def build_managed_resource_counts(
    network_policies: int = 0,
    secrets: int = 0,
    helm_releases: int = 0,
    services: int = 0,
    middlewares: int = 0,
) -> dict[str, int]:
    """Build a managedResources dict for CRD status."""
    return {
        "networkPolicies": network_policies,
        "secrets": secrets,
        "helmReleases": helm_releases,
        "services": services,
        "middlewares": middlewares,
    }
