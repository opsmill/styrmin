"""Create and delete a demo's environments and deployments on the demo stack through the Styrmin SDK (research R-014)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import kr8s
import kr8s.asyncio
from kr8s.asyncio.objects import Namespace
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError
from styrmin_sdk.graphql._generated.input_types import ParameterValueInput

from tests.e2e.demos.progress import report, waiting

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from styrmin_sdk.graphql._generated.get_deployment import GetDeploymentDeployment

# Created by `uv run invoke start` (tasks/dev.py bootstrap).
CLUSTER_NAME = "local"
BACKUP_STORAGE_LOCATION_NAME = "local"
ENTERPRISE_DRIVER_PATH = "/styrmin/drivers/infrahub-enterprise"
# The context `vcluster connect styrmin --driver=docker` writes; selected without changing the current context.
KUBE_CONTEXT = "vcluster-docker_styrmin"
POLL_INTERVAL = 5.0
DELETE_TIMEOUT = 600.0


class StackError(RuntimeError):
    """The demo stack is missing something a demo needs, or a deployment or deletion did not finish."""


def namespace_name(deployment_id: object) -> str:
    return f"styrmin-{deployment_id}"


async def connect(
    api_url: str, username: str, password: str, *, timeout: float = 60.0
) -> StyrminClient:
    """Return a client logged in to the Styrmin server at ``api_url`` (without ``/graphql``)."""
    client = StyrminClient(server_address=api_url, timeout=timeout)
    try:
        await client.auth.login(username, password)
    except BaseException:
        await client.close()
        raise
    return client


@dataclass(frozen=True)
class EnvironmentRecord:
    """An environment on the ``local`` cluster: its name and its Styrmin id."""

    name: str
    id: str


async def find_environments(
    client: StyrminClient, names: Sequence[str]
) -> list[EnvironmentRecord]:
    """Return the environments of ``names`` that exist on the ``local`` cluster, in the given order."""
    found: list[EnvironmentRecord] = []
    for name in names:
        try:
            environment = await client.environments.get(
                environment_name=name, cluster_name=CLUSTER_NAME
            )
        except ResourceNotFoundError:
            continue
        found.append(EnvironmentRecord(name=name, id=str(environment.id)))
    return found


async def delete_environments(
    client: StyrminClient,
    environments: Sequence[EnvironmentRecord],
    *,
    timeout: float = DELETE_TIMEOUT,
    kube_context: str = KUBE_CONTEXT,
) -> None:
    """Delete ``environments`` by id, in order, then wait until the namespaces of their deployments are gone."""
    namespaces: list[str] = []
    for environment in environments:
        deployments = await client.deployments.list(
            environment.id, include_deleted=True, include_internal=True
        )
        namespaces += [namespace_name(deployment.id) for deployment in deployments]
        report(f"Deleting environment {environment.name}")
        await client.environments.delete(environment_id=environment.id)
    await wait_for_namespaces_gone(
        namespaces, timeout=timeout, kube_context=kube_context
    )


async def check_kube_context(kube_context: str = KUBE_CONTEXT) -> str | None:
    """Return why the cluster of ``kube_context`` cannot be reached, or ``None`` when it answers."""
    try:
        api = await kr8s.asyncio.api(context=kube_context)
        await api.version()
    except Exception as error:  # noqa: BLE001 - every failure means the same thing to the caller
        return f"{type(error).__name__}: {error}"
    return None


async def wait_for_namespaces_gone(
    namespaces: Sequence[str], *, timeout: float, kube_context: str = KUBE_CONTEXT
) -> None:
    if not namespaces:
        return
    api = await kr8s.asyncio.api(context=kube_context)
    deadline = time.monotonic() + timeout
    remaining = list(namespaces)
    count = len(namespaces)
    what = f"the {count} namespace{'' if count == 1 else 's'} of the deleted deployments {'is' if count == 1 else 'are'} gone"
    async with waiting(what, limit=timeout):
        while True:
            remaining = [
                namespace
                for namespace in remaining
                if await _namespace_exists(api, namespace)
            ]
            if not remaining:
                return
            if time.monotonic() >= deadline:
                raise StackError(
                    f"These namespaces still exist after {timeout:.0f} s: {', '.join(remaining)}"
                )
            await asyncio.sleep(POLL_INTERVAL)


async def _namespace_exists(api: kr8s.asyncio.Api, namespace: str) -> bool:
    try:
        await Namespace.get(namespace, api=api)
    except kr8s.NotFoundError:
        return False
    return True


async def create_environment(client: StyrminClient, name: str) -> str:
    """Create environment ``name`` on the ``local`` cluster with the stack's backup storage location; return its id."""
    locations = await client.backup_storage_locations.list()
    location = next(
        (item for item in locations if item.name == BACKUP_STORAGE_LOCATION_NAME), None
    )
    if location is None:
        raise StackError(
            f"The demo stack has no backup storage location named {BACKUP_STORAGE_LOCATION_NAME!r}. "
            "Run 'uv run invoke start' first."
        )
    report(f"Creating environment {name}")
    environment = await client.environments.create(
        name=name, cluster_name=CLUSTER_NAME, config={}
    )
    await client.backup_storage_locations.assign(environment.id, location.id)
    return str(environment.id)


async def load_enterprise_driver(client: StyrminClient) -> None:
    # Loading a version that is already loaded returns that version without an error (spike-notes.md).
    report(f"Loading the driver at {ENTERPRISE_DRIVER_PATH}")
    await client.drivers.load_local_version(ENTERPRISE_DRIVER_PATH)


async def deploy(
    client: StyrminClient,
    *,
    environment_id: str,
    driver: str,
    version: str,
    name: str,
    parameters: Mapping[str, object] | None = None,
    timeout: float = 900.0,
) -> GetDeploymentDeployment:
    """Create a deployment, wait until it is Running, and return it with its deployed services."""
    task = await client.deployments.create(
        driver=driver,
        version=version,
        environment_id=environment_id,
        name=name,
        parameters=[
            ParameterValueInput(name=key, value=value)
            for key, value in parameters.items()
        ]
        if parameters
        else None,
    )
    if task.deployment_id is None:
        raise StackError(
            f"Styrmin created no deployment for {name!r}: {task.message or task.status}"
        )
    described = f"Deployment {name!r} ({driver} {version})"
    deadline = time.monotonic() + timeout
    status = "unknown"
    async with waiting(f"{described} runs", limit=timeout):
        while time.monotonic() < deadline:
            deployment = await client.deployments.get(task.deployment_id)
            status = deployment.status
            if status == "running":
                return deployment
            if status == "failed":
                step = await client.tasks.failed_step(task.id)
                reason = (
                    f'step "{step.name}" failed: {step.error}'
                    if step is not None
                    else "no step failed"
                )
                raise StackError(f"{described} failed: {reason}")
            await asyncio.sleep(POLL_INTERVAL)
    raise StackError(
        f"{described} is not Running after {timeout:.0f} s (status: {status})"
    )


def service_url(deployment: GetDeploymentDeployment, service_name: str) -> str:
    """Return the human-readable URL of the deployed service that the driver names ``service_name``."""
    names = [service.driver_service_name for service in deployment.deployed_services]
    service = next(
        (
            service
            for service in deployment.deployed_services
            if service.driver_service_name == service_name
        ),
        None,
    )
    if service is None:
        raise StackError(
            f"Deployment {deployment.name!r} has no service {service_name!r}; it has: {', '.join(names)}"
        )
    if not service.human_readable_url:
        raise StackError(
            f"Service {service_name!r} of deployment {deployment.name!r} has no human-readable URL"
        )
    return service.human_readable_url
