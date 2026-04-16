"""Periodic status reporter.

Collects pod statuses and StyrminDeployment CRD statuses from Kubernetes
and reports them to the Styrmin backend via GraphQL mutations.
"""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

import httpx

from styrmin_backend.agent.service.kubernetes.primitives import (
    get_custom_resource,
    list_pods,
)
from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.agent.status.queries import load_query

logger = logging.getLogger(__name__)

STATUS_POLL_INTERVAL = int(os.environ.get("STYRMIN_AGENT_STATUS_POLL_INTERVAL", "60"))

_QUERY_DEPLOYMENTS = load_query("list_deployments_for_status")
_MUTATION_REPORT_PODS = load_query("report_pod_statuses")
_MUTATION_REPORT_CRD = load_query("report_crd_statuses")

# StyrminDeployment CRD constants
_CRD_GROUP = "styrmin.io"
_CRD_VERSION = "v1alpha1"
_CRD_PLURAL = "styrmindeployments"


def _extract_pod_data(pod) -> dict:  # type: ignore[no-untyped-def]
    """Extract relevant status fields from a V1Pod object."""
    status = pod.status
    container_statuses_raw = status.container_statuses or []

    container_statuses = []
    total_restarts = 0
    all_ready = True

    for cs in container_statuses_raw:
        total_restarts += cs.restart_count or 0
        if not cs.ready:
            all_ready = False

        state = "unknown"
        if cs.state:
            if cs.state.running:
                state = "running"
            elif cs.state.waiting:
                state = f"waiting:{cs.state.waiting.reason or 'unknown'}"
            elif cs.state.terminated:
                state = f"terminated:{cs.state.terminated.reason or 'unknown'}"

        container_statuses.append(
            {
                "name": cs.name,
                "ready": cs.ready or False,
                "state": state,
                "restart_count": cs.restart_count or 0,
                "image": cs.image or "",
                "started_at": (
                    cs.state.running.started_at.isoformat()
                    if cs.state and cs.state.running and cs.state.running.started_at
                    else None
                ),
            }
        )

    # If no container statuses yet (pod is Pending), mark as not ready
    if not container_statuses_raw:
        all_ready = False

    phase = (status.phase or "Unknown").lower()

    started_at = None
    if status.start_time:
        started_at = status.start_time.isoformat()

    return {
        "podName": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": phase,
        "ready": all_ready,
        "restartCount": total_restarts,
        "containerStatuses": container_statuses,
        "nodeName": pod.spec.node_name if pod.spec else None,
        "startedAt": started_at,
    }


async def _collect_pod_statuses(namespace: str) -> list[dict] | None:
    """Collect pod statuses from a Kubernetes namespace.

    Returns None on failure (as opposed to empty list) so the caller can
    distinguish "no pods" from "failed to list pods" and skip the deployment.
    """
    try:
        pod_list = await list_pods(namespace=namespace)
        return [_extract_pod_data(pod) for pod in pod_list.items]
    except Exception:
        logger.exception("Failed to list pods in namespace %s", namespace)
        return None


async def _collect_crd_status(namespace: str, crd_name: str) -> dict | None:
    """Collect StyrminDeployment CRD status from Kubernetes.

    Returns None if the CRD is missing (404) or on failure.
    """
    try:
        crd = await get_custom_resource(
            plural=_CRD_PLURAL,
            name=crd_name,
            group=_CRD_GROUP,
            version=_CRD_VERSION,
            namespace=namespace,
        )
        status = crd.get("status", {}) if isinstance(crd, dict) else {}
        return {
            "phase": status.get("phase", "Pending"),
            "message": status.get("message"),
            "conditions": status.get("conditions"),
            "managedResourceCounts": status.get("managedResources"),
        }
    except CustomResourceNotFound:
        logger.debug(
            "StyrminDeployment CRD not found in namespace %s (name=%s), skipping",
            namespace,
            crd_name,
        )
        return None
    except Exception:
        logger.exception(
            "Failed to read StyrminDeployment CRD in namespace %s", namespace
        )
        return None


async def _get_active_deployment_ids(graphql_url: str) -> list[UUID]:
    """Query the backend for all active non-internal deployment IDs."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={"query": _QUERY_DEPLOYMENTS},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            deployment_ids = []
            for env in data.get("data", {}).get("environments", []):
                for deployment in env.get("deployments", []):
                    if not deployment.get("internal", False):
                        deployment_ids.append(UUID(deployment["id"]))
            return deployment_ids
    except Exception:
        logger.exception("Failed to fetch deployments from backend")
        return []


async def _report_pod_statuses_to_backend(
    graphql_url: str, reports: list[dict]
) -> None:
    """Send pod status reports to the backend via GraphQL mutation."""
    if not reports:
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={
                    "query": _MUTATION_REPORT_PODS,
                    "variables": {"reports": reports},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()
            data = result.get("data", {}).get("reportPodStatuses", {})
            if data.get("success"):
                logger.debug("Pod status report: %s", data.get("message", ""))
            else:
                logger.warning("Pod status report failed: %s", data.get("message", ""))
    except Exception:
        logger.exception("Failed to report pod statuses to backend")


async def _report_crd_statuses_to_backend(
    graphql_url: str, reports: list[dict]
) -> None:
    """Send CRD status reports to the backend via GraphQL mutation."""
    if not reports:
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={
                    "query": _MUTATION_REPORT_CRD,
                    "variables": {"reports": reports},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()
            data = result.get("data", {}).get("reportCrdStatuses", {})
            if data.get("success"):
                logger.debug("CRD status report: %s", data.get("message", ""))
            else:
                logger.warning("CRD status report failed: %s", data.get("message", ""))
    except Exception:
        logger.exception("Failed to report CRD statuses to backend")


async def _poll_once(graphql_url: str) -> None:
    """Run a single poll cycle: fetch deployments, collect pods and CRD status, report."""
    deployment_ids = await _get_active_deployment_ids(graphql_url)
    if not deployment_ids:
        logger.debug("No active deployments found, skipping poll cycle")
        return

    pod_reports = []
    crd_reports = []

    for deployment_id in deployment_ids:
        namespace = get_kubernetes_reference(deployment_id)
        crd_name = namespace  # CRD name matches namespace (styrmin-{deployment_id})

        # Collect pod statuses
        pods = await _collect_pod_statuses(namespace)
        if pods is not None:
            pod_reports.append(
                {
                    "deploymentId": str(deployment_id),
                    "pods": pods,
                }
            )

        # Collect CRD status
        crd_status = await _collect_crd_status(namespace, crd_name)
        if crd_status is not None:
            crd_reports.append(
                {
                    "deploymentId": str(deployment_id),
                    "phase": crd_status["phase"],
                    "message": crd_status.get("message"),
                    "conditions": crd_status.get("conditions"),
                    "managedResourceCounts": crd_status.get("managedResourceCounts"),
                }
            )

    await _report_pod_statuses_to_backend(graphql_url, pod_reports)
    await _report_crd_statuses_to_backend(graphql_url, crd_reports)


async def run_status_reporter(
    shutdown_event: asyncio.Event,
    graphql_url: str | None = None,
    interval: int | None = None,
) -> None:
    """Run the periodic pod status reporter until shutdown.

    Args:
        shutdown_event: Event that signals graceful shutdown.
        graphql_url: Backend GraphQL endpoint URL.
        interval: Polling interval in seconds.
    """
    if graphql_url is None:
        graphql_url = os.environ.get(
            "STYRMIN_URL_GRAPHQL", "http://localhost:8000/graphql"
        )
    if interval is None:
        interval = STATUS_POLL_INTERVAL

    logger.info(
        "Status reporter starting (interval=%ds, url=%s)",
        interval,
        graphql_url,
    )

    while not shutdown_event.is_set():
        try:
            await _poll_once(graphql_url)
        except Exception:
            logger.exception("Unexpected error in status reporter poll cycle")

        # Wait for the interval or shutdown, whichever comes first
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            # If we get here, shutdown was signaled
            break
        except asyncio.TimeoutError:
            # Normal: interval elapsed, loop again
            pass

    logger.info("Status reporter stopped")
