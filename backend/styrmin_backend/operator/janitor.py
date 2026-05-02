"""Forensic-retention janitor for StyrminDeployment CRs.

After a CR reaches ``phase: Deleted`` the operator leaves it in place so
operators can inspect cluster-side state (final conditions, events) for
the configured ``DELETED_CR_TTL_HOURS`` window. Once the window elapses,
this kopf timer reaps the CR.

Deliberately scoped:

* Only acts on CRs whose ``status.phase == "Deleted"``.
* CRs stuck in ``Deleting`` are NEVER auto-reaped — they remain visible
  until human action resolves them (per spec 008 §FR-015).
* The reap is a regular ``kubectl delete styrmindeployment`` — the
  existing ``@kopf.on.delete`` safety-net handler short-circuits because
  every owned resource has already been removed by the platform-driven
  teardown.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import kopf

from styrmin_backend.operator.config import (
    CRD_GROUP,
    CRD_PLURAL,
    CRD_VERSION,
    DELETED_CR_TTL_HOURS,
    JANITOR_INTERVAL_SECONDS,
)
from styrmin_backend.operator.crd.schema import ConditionType, DeploymentPhase


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an RFC3339/ISO-8601 timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        # Handle both "Z" suffix and explicit offsets.
        normalised = value.replace("Z", "+00:00") if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_eligible_for_reap(
    status: dict[str, Any],
    *,
    now: datetime,
    ttl_hours: int = DELETED_CR_TTL_HOURS,
) -> bool:
    """Decide whether a CR is eligible for janitor reaping.

    Pure function so the decision logic can be tested without spinning
    up kopf or a real Kubernetes API. The two requirements are:

    1. ``status.phase == "Deleted"`` (CRs in ``Deleting`` are protected
       so failed teardowns remain visible).
    2. The ``Deleted`` condition's ``lastTransitionTime`` is older than
       ``ttl_hours``.
    """
    if status.get("phase") != DeploymentPhase.DELETED.value:
        return False

    deleted_condition: dict[str, Any] | None = None
    for cond in status.get("conditions", []):
        if cond.get("type") == ConditionType.DELETED.value:
            deleted_condition = cond
            break
    if deleted_condition is None:
        # Defensive: no condition recorded means we cannot date the
        # transition — leave the CR in place rather than reap something
        # we cannot prove is past TTL.
        return False

    transition = _parse_iso(deleted_condition.get("lastTransitionTime"))
    if transition is None:
        return False

    return now - transition >= timedelta(hours=ttl_hours)


@kopf.timer(
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL,
    interval=JANITOR_INTERVAL_SECONDS,
    initial_delay=JANITOR_INTERVAL_SECONDS,
)
async def kopf_styrmin_deployment_janitor(
    *,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Reap StyrminDeployment CRs in ``phase: Deleted`` past the TTL."""
    ns = namespace or ""
    if not is_eligible_for_reap(dict(status), now=datetime.now(tz=timezone.utc)):
        return

    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio.client.api_client import ApiException
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    logger.info(
        "Janitor reaping StyrminDeployment %s/%s (TTL %sh elapsed)",
        ns,
        name,
        DELETED_CR_TTL_HOURS,
    )
    try:
        async with get_kubernetes_client() as client:
            custom_api = kubeclient.CustomObjectsApi(client)
            await custom_api.delete_namespaced_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=ns,
                plural=CRD_PLURAL,
                name=name,
            )
    except ApiException as exc:
        if exc.status == 404:
            return
        logger.exception("Janitor failed to reap %s/%s", ns, name)
