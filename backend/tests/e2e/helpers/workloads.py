from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from kubernetes_asyncio import client as kubeclient

RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0


async def _wait_for_pod_template(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    predicate: Callable[[Any], bool],
    description: str,
    timeout: float = RECONCILE_TIMEOUT_SECONDS,
) -> Any:
    """Poll workloads in ``namespace`` matching ``label_selector`` until one
    satisfies ``predicate``.

    Scans Deployments, StatefulSets, and DaemonSets — bitnami subcharts
    (e.g. postgresql) render the database as a StatefulSet, so a
    Deployment-only scan would never resolve component-scope env-var
    assertions for those workloads.
    """
    apps = kubeclient.AppsV1Api(vcluster["api"])
    deadline = time.time() + timeout
    last_seen: str = "(no matching workloads)"
    while time.time() < deadline:
        deployments = (
            await apps.list_namespaced_deployment(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        statefulsets = (
            await apps.list_namespaced_stateful_set(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        daemonsets = (
            await apps.list_namespaced_daemon_set(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        workloads = list(deployments) + list(statefulsets) + list(daemonsets)
        for workload in workloads:
            try:
                if predicate(workload):
                    return workload
            except Exception:
                continue
        if workloads:
            last_seen = f"{len(workloads)} workload(s) did not satisfy predicate"
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for {description} in namespace {namespace} "
        f"(selector={label_selector!r}): {last_seen}"
    )
