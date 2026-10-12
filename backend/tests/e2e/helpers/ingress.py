"""Wait and read helpers for the dedicated ingress controller and the cluster config fan-out E2E."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import kr8s
import kr8s.asyncio
from kr8s.asyncio.objects import Namespace as AsyncNamespace
from kr8s.asyncio.objects import Pod as AsyncPod
from styrmin_sdk import StyrminClient

INGRESS_CONTROLLER_NAME_PREFIX = "styrmin-ingress-controller"

_ROLLOUT_STATUSES = frozenset({"pending", "deploying"})
_ENDED_TASK_STATUSES = frozenset({"success", "failed"})


async def wait_for_deployment_status(
    client: StyrminClient, deployment_id: str, expected: str, timeout: float = 300.0
) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = (await client.deployments.get(deployment_id)).status
        if last == expected:
            return
        await asyncio.sleep(2)
    raise AssertionError(
        f"Deployment {deployment_id} never reached {expected!r} within "
        f"{timeout}s. Last observed: {last!r}."
    )


async def ingress_controller_ids(
    client: StyrminClient, environment_id: str, *, include_deleted: bool = False
) -> dict[str, str]:
    """Map each ingress controller deployment's id to its status. Both the
    ``deployment`` query and the default environment list hide internal
    deployments, so the list has to ask for them."""
    deployments = await client.deployments.list(
        environment_id=environment_id,
        include_deleted=include_deleted,
        include_internal=True,
    )
    return {
        str(deployment.id): deployment.status
        for deployment in deployments
        if deployment.name.startswith(INGRESS_CONTROLLER_NAME_PREFIX)
    }


async def wait_for_traefik_pod(
    kr8s_api: kr8s.asyncio.Api, namespace: str, timeout: float = 300.0
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        async for pod in AsyncPod.list(
            namespace=namespace,
            label_selector={"app.kubernetes.io/name": "traefik"},
            api=kr8s_api,
        ):
            if isinstance(pod, AsyncPod) and pod.status.get("phase") == "Running":
                return
        await asyncio.sleep(5)
    raise AssertionError(f"No running Traefik pod in {namespace!r} after {timeout}s")


async def _namespace_exists(kr8s_api: kr8s.asyncio.Api, namespace: str) -> bool:
    try:
        await AsyncNamespace.get(namespace, api=kr8s_api)
    except kr8s.NotFoundError:
        return False
    return True


async def wait_for_namespace_gone(
    kr8s_api: kr8s.asyncio.Api, namespace: str, timeout: float = 300.0
) -> None:
    # The synthetic Deleted report fires once the CR is gone, which can be
    # before the namespace finishes terminating.
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not await _namespace_exists(kr8s_api, namespace):
            return
        await asyncio.sleep(5)
    raise AssertionError(
        f"Namespace {namespace!r} (Traefik release) still present after {timeout}s"
    )


@dataclass(frozen=True)
class TaskTimes:
    """One task of a deployment, with the timestamps that ordering assertions compare."""

    id: str
    type: str
    status: str
    created_on: datetime
    # The task's last update once it succeeded or failed; None while it runs.
    ended_on: datetime | None


async def deployment_tasks(
    client: StyrminClient, deployment_id: str | UUID
) -> list[TaskTimes]:
    """The tasks of a deployment, oldest first. Works for internal and deleted deployments."""
    entries = await client.deployments.get_timeline(deployment_id)
    tasks = []
    for entry in entries:
        task = entry.task
        assert task.created_on is not None, f"Task {task.id} has no creation time"
        status = task.status.lower()
        tasks.append(
            TaskTimes(
                id=str(task.id),
                type=task.type_.lower(),
                status=status,
                created_on=task.created_on,
                ended_on=task.updated_on if status in _ENDED_TASK_STATUSES else None,
            )
        )
    return sorted(tasks, key=lambda task: task.created_on)


async def _rolling_out_deployments(
    client: StyrminClient, cluster_id: str
) -> dict[str, str]:
    rolling_out: dict[str, str] = {}
    for environment in await client.environments.list():
        if str(environment.cluster.id) != cluster_id:
            continue
        for deployment in await client.deployments.list(
            environment_id=environment.id, include_internal=True
        ):
            if deployment.status in _ROLLOUT_STATUSES:
                rolling_out[f"{deployment.name} ({deployment.id})"] = deployment.status
    return rolling_out


async def wait_for_cluster_settled(
    client: StyrminClient,
    cluster_id: str | UUID,
    *,
    timeout: float = 600.0,
    interval: float = 5.0,
) -> None:
    """Wait until no deployment of the cluster, internal ones included, is pending or deploying.

    A controller reaching RUNNING and the redeploys it releases commit together,
    so a poll never sees the gap between them.
    """
    deadline = time.time() + timeout
    rolling_out: dict[str, str] = {}
    while time.time() < deadline:
        rolling_out = await _rolling_out_deployments(client, str(cluster_id))
        if not rolling_out:
            return
        await asyncio.sleep(interval)
    raise AssertionError(
        f"Cluster {cluster_id} did not settle within {timeout}s; still rolling out: "
        f"{rolling_out}"
    )
