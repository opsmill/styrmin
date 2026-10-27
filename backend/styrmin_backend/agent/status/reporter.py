"""Periodic status reporter.

Collects pod statuses and StyrminDeployment CRD statuses from Kubernetes
and reports them to the Styrmin backend via GraphQL mutations.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import httpx

from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.agent.service.kubernetes.primitives import (
    get_custom_resource,
    get_namespace,
    list_pods,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.agent.status.models import (
    CONTAINER_KIND,
    INIT_CONTAINER_KIND,
    POD_KIND,
    SIDECAR_KIND,
    DeploymentStatusReport,
    DeploymentPodStatusReport,
    EnvironmentForStatus,
    GraphQLResponse,
    PodPhase,
    PodStatusData,
    ReportDeploymentStatusesResponse,
    ReportPodStatusesResponse,
)
from styrmin_backend.agent.status.queries import load_query

logger = logging.getLogger(__name__)

_QUERY_DEPLOYMENTS = load_query("list_deployments_for_status")
_MUTATION_REPORT_PODS = load_query("report_pod_statuses")
_MUTATION_REPORT_CRD = load_query("report_deployment_statuses")

# StyrminDeployment CRD constants
_CRD_GROUP = "styrmin.io"
_CRD_VERSION = "v1alpha1"
_CRD_PLURAL = "styrmindeployments"

# Pod label key the platform's application builder writes onto every workload it
# owns (see ``build_target_for_component_labels``). Pods without this label are
# either system pods, sidecars, or in-flight rollouts — they're reported with
# ``component_name = None`` rather than dropped or coerced.
_COMPONENT_LABEL_KEY = "styrmin/component"

_POD_SCHEDULED = "PodScheduled"
#: Waiting reasons whose kubelet message holds what a command in the container printed:
#: the message of ``PostStartHookError`` quotes the output of the ``postStart`` hook.
_REASONS_WITH_CONTAINER_OUTPUT = frozenset({"PostStartHookError"})


def _entry(
    name: str,
    kind: str,
    state: str,
    *,
    message: str | None = None,
    ready: bool = False,
    restart_count: int = 0,
    image: str = "",
    started_at: str | None = None,
) -> dict:
    """One ``containerStatuses`` entry; every kind has the same keys (ADR-088)."""
    return {
        "name": name,
        "kind": kind,
        "ready": ready,
        "state": state,
        "message": message,
        "restart_count": restart_count,
        "image": image,
        "started_at": started_at,
    }


def _container_entry(cs, kind: str) -> dict:  # type: ignore[no-untyped-def]
    """One ``containerStatuses`` entry from a V1ContainerStatus.

    ``message`` is the kubelet's message of a waiting container, such as the
    registry error of ``ErrImagePull``. The message of a terminated container,
    and the message of a waiting reason that quotes the container's output, are
    left out: the container writes them.
    """
    state = "unknown"
    message = None
    if cs.state:
        if cs.state.running:
            state = "running"
        elif cs.state.waiting:
            reason = cs.state.waiting.reason
            state = f"waiting:{reason or 'unknown'}"
            if reason not in _REASONS_WITH_CONTAINER_OUTPUT:
                message = cs.state.waiting.message or None
        elif cs.state.terminated:
            state = f"terminated:{cs.state.terminated.reason or 'unknown'}"
    return _entry(
        cs.name,
        kind,
        state,
        message=message,
        ready=cs.ready or False,
        restart_count=cs.restart_count or 0,
        image=cs.image or "",
        started_at=(
            cs.state.running.started_at.isoformat()
            if cs.state and cs.state.running and cs.state.running.started_at
            else None
        ),
    )


def _scheduling_entry(status) -> dict | None:  # type: ignore[no-untyped-def]
    """The ``pod`` entry of a pod that is not scheduled, with the scheduler's reason and message."""
    for condition in status.conditions or ():
        if condition.type == _POD_SCHEDULED and condition.status == "False":
            return _entry(
                _POD_SCHEDULED,
                POD_KIND,
                f"waiting:{condition.reason or 'unknown'}",
                message=condition.message or None,
            )
    return None


def _is_initialized(status) -> bool:  # type: ignore[no-untyped-def]
    return any(
        condition.type == "Initialized" and condition.status == "True"
        for condition in status.conditions or ()
    )


def _sidecar_names(pod) -> frozenset[str]:  # type: ignore[no-untyped-def]
    """The init containers with ``restartPolicy: Always``: they run for the pod's whole life."""
    return frozenset(
        container.name
        for container in ((pod.spec.init_containers if pod.spec else None) or ())
        if container.restart_policy == "Always"
    )


def _restart_count(pod, sidecars: frozenset[str]) -> int:  # type: ignore[no-untyped-def]
    """The pod's restarts as ``kubectl get pods`` counts them.

    While an init container has not finished, the restarts of the init containers and
    sidecars; after that, the restarts of the containers and of the sidecars.
    """
    status = pod.status
    init_statuses = status.init_container_statuses or []
    if init_statuses and not _is_initialized(status):
        return sum(cs.restart_count or 0 for cs in init_statuses)
    return sum(cs.restart_count or 0 for cs in status.container_statuses or ()) + sum(
        cs.restart_count or 0 for cs in init_statuses if cs.name in sidecars
    )


def _extract_pod_data(pod) -> PodStatusData:  # type: ignore[no-untyped-def]
    """Extract relevant status fields from a V1Pod object.

    ``containerStatuses`` lists, in this order, a ``pod`` entry when the pod is not
    scheduled, the init containers and sidecars in the pod's order, and the
    containers (ADR-088).
    """
    status = pod.status
    container_statuses_raw = status.container_statuses or []
    sidecars = _sidecar_names(pod)

    container_statuses = []
    scheduling = _scheduling_entry(status)
    if scheduling is not None:
        container_statuses.append(scheduling)
    container_statuses.extend(
        _container_entry(
            cs, SIDECAR_KIND if cs.name in sidecars else INIT_CONTAINER_KIND
        )
        for cs in status.init_container_statuses or ()
    )
    container_statuses.extend(
        _container_entry(cs, CONTAINER_KIND) for cs in container_statuses_raw
    )

    # A pod without container statuses (not scheduled or not started) is not ready.
    all_ready = bool(container_statuses_raw) and all(
        cs.ready for cs in container_statuses_raw
    )

    phase = PodPhase((status.phase or "Unknown").upper())

    started_at = None
    if status.start_time:
        started_at = status.start_time.isoformat()

    labels = (pod.metadata.labels or {}) if pod.metadata else {}
    raw_component = labels.get(_COMPONENT_LABEL_KEY)
    component_name = (
        raw_component.strip() if raw_component and raw_component.strip() else None
    )

    return PodStatusData(
        podName=pod.metadata.name,
        namespace=pod.metadata.namespace,
        phase=phase,
        ready=all_ready,
        restartCount=_restart_count(pod, sidecars),
        containerStatuses=container_statuses or None,
        nodeName=pod.spec.node_name if pod.spec else None,
        componentName=component_name,
        startedAt=started_at,
    )


async def _collect_pod_statuses(namespace: str) -> list[PodStatusData] | None:
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
        crd_dict: dict = crd if isinstance(crd, dict) else {}
        spec: dict = crd_dict.get("spec") or {}
        status: dict = crd_dict.get("status") or {}
        return {
            # The instance the operator acted on; a CR it has not handled since its upgrade has none.
            "instanceId": status.get("instanceId") or spec.get("instanceId"),
            "phase": status.get("phase", "Pending"),
            "displayState": status.get("displayState", "Deploying"),
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


async def _namespace_is_terminating(namespace: str) -> bool:
    """True while Kubernetes removes the namespace, and when the namespace cannot be read.

    A namespace that is gone, or that has no deletion timestamp, is not terminating.
    """
    try:
        found = await get_namespace(name=namespace)
    except Exception:
        logger.exception("Failed to read namespace %s", namespace)
        return True
    return found is not None and found.metadata.deletion_timestamp is not None


async def _get_active_deployments(graphql_url: str) -> list[tuple[UUID, str]]:
    """Query the backend for every live deployment, internal ones included.

    Internal deployments (the ingress controller of a dedicated ingress) need
    their status reported like any other, including the terminal ``DELETED``
    transition when the controller is torn down with the last app (#252).

    Returns tuples of ``(deployment_id, status)`` so the caller can decide
    how to handle each based on its current lifecycle state — in
    particular, a deployment in the ``DELETING`` state with no live CR
    on the cluster gets a synthetic ``displayState=Deleted`` report so
    the DB-side terminal transition is not lost when the namespace
    deletion takes the StyrminDeployment CR with it.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={"query": _QUERY_DEPLOYMENTS},
                timeout=30.0,
            )
            response.raise_for_status()
            gql = GraphQLResponse.model_validate(response.json())

            if gql.errors:
                logger.warning("Deployment list GraphQL errors: %s", gql.errors)
                return []

            results: list[tuple[UUID, str]] = []
            for env_data in (gql.data or {}).get("environments", []):
                env = EnvironmentForStatus.model_validate(env_data)
                for dep in env.deployments:
                    results.append((UUID(dep.id), dep.status))
            return results
    except httpx.ConnectError, httpx.ConnectTimeout:
        logger.debug("Backend unreachable at %s, will retry next cycle", graphql_url)
        return []
    except Exception:
        logger.exception("Failed to fetch deployments from backend")
        return []


async def _report_pod_statuses_to_backend(
    graphql_url: str, reports: list[DeploymentPodStatusReport]
) -> None:
    """Send pod status reports to the backend via GraphQL mutation."""
    if not reports:
        return

    try:
        payload = [r.model_dump(by_alias=True) for r in reports]
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={
                    "query": _MUTATION_REPORT_PODS,
                    "variables": {"reports": payload},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            gql = GraphQLResponse.model_validate(response.json())

            if gql.errors:
                logger.warning("Pod status GraphQL errors: %s", gql.errors)
                return

            raw = (gql.data or {}).get("reportPodStatuses", {})
            data = ReportPodStatusesResponse.model_validate(raw)
            if data.success:
                logger.debug("Pod status report: %s", data.message)
            else:
                logger.warning("Pod status report failed: %s", data.message)
    except httpx.ConnectError, httpx.ConnectTimeout:
        logger.debug("Backend unreachable, pod status report deferred")
    except Exception:
        logger.exception("Failed to report pod statuses to backend")


async def _report_deployment_statuses_to_backend(
    graphql_url: str, reports: list[DeploymentStatusReport]
) -> None:
    """Send CRD status reports to the backend via GraphQL mutation."""
    if not reports:
        return

    try:
        payload = [r.model_dump(by_alias=True) for r in reports]
        async with httpx.AsyncClient() as client:
            response = await client.post(
                graphql_url,
                json={
                    "query": _MUTATION_REPORT_CRD,
                    "variables": {"reports": payload},
                },
                timeout=30.0,
            )
            response.raise_for_status()
            gql = GraphQLResponse.model_validate(response.json())

            if gql.errors:
                logger.warning("CRD status GraphQL errors: %s", gql.errors)
                return

            raw = (gql.data or {}).get("reportDeploymentStatuses", {})
            data = ReportDeploymentStatusesResponse.model_validate(raw)
            if data.success:
                logger.debug("CRD status report: %s", data.message)
            else:
                logger.warning("CRD status report failed: %s", data.message)
    except httpx.ConnectError, httpx.ConnectTimeout:
        logger.debug("Backend unreachable, CRD status report deferred")
    except Exception:
        logger.exception("Failed to report CRD statuses to backend")


async def _poll_once(graphql_url: str) -> None:
    """Run a single poll cycle: fetch deployments, collect pods and CRD status, report."""
    deployments = await _get_active_deployments(graphql_url)
    if not deployments:
        logger.debug("No active deployments found, skipping poll cycle")
        return

    pod_reports: list[DeploymentPodStatusReport] = []
    crd_reports: list[DeploymentStatusReport] = []

    for deployment_id, db_status in deployments:
        namespace = get_kubernetes_reference(deployment_id)
        crd_name = namespace  # CRD name matches namespace (styrmin-{deployment_id})

        # Collect pod statuses
        pods = await _collect_pod_statuses(namespace)
        if pods is not None:
            pod_reports.append(
                DeploymentPodStatusReport(
                    deploymentId=str(deployment_id),
                    pods=pods,
                )
            )

        # Collect CRD status
        crd_status = await _collect_crd_status(namespace, crd_name)
        if crd_status is not None:
            crd_reports.append(
                DeploymentStatusReport(
                    deploymentId=str(deployment_id),
                    instanceId=crd_status.get("instanceId"),
                    phase=crd_status["phase"],
                    displayState=crd_status.get("displayState", "Deploying"),
                    message=crd_status.get("message"),
                    conditions=crd_status.get("conditions"),
                    managedResourceCounts=crd_status.get("managedResourceCounts"),
                )
            )
        elif db_status == "deleting":
            # Spec 008: the StyrminDeployment CRD is namespaced and lives in
            # the deployment's own namespace, so the platform-driven delete
            # path takes the CR out with the namespace before the operator
            # timer can advance it to phase: Deleted. When the DB still
            # thinks the deployment is DELETING but the CR is gone, we
            # synthesise a final ``displayState: Deleted`` report so the
            # backend's status reporter flips the row to DELETED and
            # atomically stamps deleted_at. Kubernetes deletes the CR with
            # the rest of the namespace's contents, before it removes the
            # namespace itself, so the report waits while the namespace is
            # terminating (FR-003). A namespace that nothing deletes, such as
            # the one of a create that failed before its CR write, does not
            # hold the report back.
            if await _namespace_is_terminating(namespace):
                continue
            logger.info(
                "Deployment %s is DELETING and its CR is gone — emitting "
                "synthetic Deleted status report",
                deployment_id,
            )
            crd_reports.append(
                DeploymentStatusReport(
                    deploymentId=str(deployment_id),
                    instanceId=None,
                    phase="Deleted",
                    displayState="Deleted",
                    message="Namespace removed; CR garbage-collected with it",
                    conditions=None,
                    managedResourceCounts=None,
                )
            )

    # Report independently — a failure in one must not block the other
    try:
        await _report_pod_statuses_to_backend(graphql_url, pod_reports)
    except Exception:
        logger.exception("Unexpected error reporting pod statuses")

    try:
        await _report_deployment_statuses_to_backend(graphql_url, crd_reports)
    except Exception:
        logger.exception("Unexpected error reporting CRD statuses")

    total_pods = sum(len(r.pods) for r in pod_reports)
    logger.info(
        "Status poll: %d deployments, %d pods, %d CRD statuses reported",
        len(deployments),
        total_pods,
        len(crd_reports),
    )


async def run_status_reporter(
    shutdown_event: asyncio.Event,
    graphql_url: str,
    interval: int,
) -> None:
    """Run the periodic pod status reporter until shutdown.

    Args:
        shutdown_event: Event that signals graceful shutdown.
        graphql_url: Backend GraphQL endpoint URL.
        interval: Polling interval in seconds.
    """
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
