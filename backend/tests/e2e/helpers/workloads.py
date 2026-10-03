from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from kubernetes_asyncio import client as kubeclient

RECONCILE_TIMEOUT_SECONDS = 480.0
RECONCILE_POLL_INTERVAL = 3.0


def container_command_args(
    workload: Any, *, container_name: str | None = None
) -> tuple[list[str] | None, list[str] | None]:
    """Return ``(command, args)`` for a container in the rendered pod template.

    Reads ``spec.template.spec.containers[*].{command,args}`` off a rendered
    workload (the desired-state pod template). Returns the first container's
    pair when ``container_name`` is ``None``, else the named container's.
    Each element is ``None`` when the container does not set that field (the
    image ENTRYPOINT/CMD applies) — used by the 014 container-override E2E to
    assert overrides land on (or fall back from) the container spec.
    """
    containers = workload.spec.template.spec.containers or []
    for container in containers:
        if container_name is None or container.name == container_name:
            command = list(container.command) if container.command else None
            args = list(container.args) if container.args else None
            return command, args
    return None, None


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


def container_spec(workload: Any, container_name: str) -> Any | None:
    """The named container of a rendered pod template, or ``None``."""
    for container in workload.spec.template.spec.containers or []:
        if container.name == container_name:
            return container
    return None


async def wait_for_ready_container_image(
    vcluster: dict,
    *,
    namespace: str,
    label_selector: str,
    container_name: str,
    image: str,
    timeout: float = RECONCILE_TIMEOUT_SECONDS,
) -> Any:
    """Poll pods matching ``label_selector`` until one runs ``container_name``
    with spec image ``image`` and reports it ready; returns that pod."""
    core = kubeclient.CoreV1Api(vcluster["api"])
    deadline = time.time() + timeout
    last_seen = "(no matching pods)"
    while time.time() < deadline:
        pods = (
            await core.list_namespaced_pod(
                namespace=namespace, label_selector=label_selector
            )
        ).items
        seen: list[str] = []
        for pod in pods:
            spec = next(
                (c for c in pod.spec.containers or [] if c.name == container_name),
                None,
            )
            status = next(
                (
                    s
                    for s in (pod.status.container_statuses or [])
                    if s.name == container_name
                ),
                None,
            )
            waiting = status.state.waiting if status and status.state else None
            seen.append(
                f"{pod.metadata.name}: image={spec.image if spec else None} "
                f"ready={status.ready if status else None} "
                f"waiting={waiting.reason if waiting else None}"
            )
            if spec is not None and spec.image == image and status and status.ready:
                return pod
        if seen:
            last_seen = "; ".join(seen)
        await asyncio.sleep(RECONCILE_POLL_INTERVAL)
    raise TimeoutError(
        f"Timed out waiting for a ready {container_name!r} container running "
        f"{image} in namespace {namespace} (selector={label_selector!r}): {last_seen}"
    )
