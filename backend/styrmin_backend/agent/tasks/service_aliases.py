"""Cross-namespace service discovery via ExternalName Service aliases.

When applications in the same environment are deployed into separate namespaces
(``styrmin-{deployment_id}``), short DNS names like ``intent`` do not resolve
across namespace boundaries.  This module creates Kubernetes ``ExternalName``
Service resources that act as DNS aliases, so each namespace can resolve
services owned by other deployments using their short names.

An alias is named after the service's resolved name, which a service-name
override sets, and carries the id of the deployment that owns the service.
A flow deletes that deployment's aliases whose name it no longer uses.

The alias step reads the other deployments' services from the server, because the
context does not list a deployment requested after it. Before its writes, a flow
skips the aliases of, and in the namespace of, a deployment that is being deleted
or whose namespace is gone or terminating, and it never creates a namespace. The
flow of a deployment whose namespace was missing writes those aliases later. A
write can still race with a deletion request. The flow then deletes the alias
when its second read finds the request, and the operator's teardown deletes it
when the request comes after that read (#503).

ClusterIP Services for each deployment's own services are handled by
``ServiceDiscoveryUtility`` (see ``resources/utilities/service_discovery.py``).
"""

import asyncio
from collections.abc import Callable, Iterable
from http import HTTPStatus
from typing import Any
from uuid import UUID

from kubernetes_asyncio.client import V1Namespace, V1Service
from kubernetes_asyncio.client.api_client import ApiException
from prefect import flow, task
from prefect.logging import get_run_logger
from pydantic import BaseModel

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_service,
    delete_service,
    get_namespace,
    is_namespace_gone_error,
    list_services_in_all_namespaces,
)
from styrmin_backend.agent.service.kubernetes.service_alias_rules import (
    DEPLOYMENT_ID_LABEL,
    SERVICE_ALIAS_LABEL,
    is_alias_of_deployment,
    is_gone_or_terminating,
    teardown_deletes_aliases,
)
from styrmin_backend.agent.service.kubernetes.styrmin_deployment import (
    read_styrmin_deployment,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.agent.tasks.environment_services import (
    EnvironmentServicesReadError,
    read_environment_services,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend import config

#: Bounds how many namespaces a flow reads at the same time.
MAX_CONCURRENT_NAMESPACE_READS = 10


class StaleAlias(BaseModel):
    """An alias to delete, with the version it had when it was listed."""

    namespace: str
    name: str
    resource_version: str | None = None


class WrittenAlias(BaseModel):
    """An alias that a flow wrote, with the version that its write returned."""

    namespace: str
    name: str
    owner_namespace: str
    resource_version: str | None


def owner_namespace(alias: dict) -> str:
    """The namespace of the deployment that owns the service *alias* points to."""
    labels = alias["metadata"].get("labels") or {}
    if DEPLOYMENT_ID_LABEL in labels:
        return get_kubernetes_reference(UUID(labels[DEPLOYMENT_ID_LABEL]))
    return alias["spec"]["externalName"].split(".")[1]


def build_external_name_service(
    resolved_name: str,
    target_namespace: str,
    holder_namespace: str,
    deployment_id: str,
    cluster_domain: str = "cluster.local",
) -> dict[str, Any]:
    """Build a Kubernetes ExternalName Service manifest.

    Creates a Service resource in *holder_namespace* that aliases *resolved_name*
    to its FQDN in *target_namespace*. *deployment_id* is the deployment that
    owns the service.
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": resolved_name,
            "namespace": holder_namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "styrmin",
                SERVICE_ALIAS_LABEL: "true",
                DEPLOYMENT_ID_LABEL: deployment_id,
            },
        },
        "spec": {
            "type": "ExternalName",
            "externalName": f"{resolved_name}.{target_namespace}.svc.{cluster_domain}",
        },
    }


def compute_service_aliases(context: GlobalContext) -> list[dict[str, Any]]:
    """Compute ExternalName Service manifests for cross-namespace discovery.

    For each deployed service in the environment owned by another deployment,
    an ExternalName alias is created in this deployment's namespace pointing
    to the service's actual namespace.  Conversely, for each service owned
    by *this* deployment, aliases are created in every other deployment's
    namespace so that peers can reach our services by short name.
    """
    this_deployment_id = str(context.instance.deployment_id)
    this_namespace = context.instance.namespace
    cluster_domain = config.SETTINGS.kubernetes.cluster_domain

    aliases: list[dict[str, Any]] = []

    # Group services by their owning deployment namespace
    other_namespaces: set[str] = set()
    for svc in context.deployed_services:
        svc_deployment_id = svc.get("deployment_id")
        if svc_deployment_id is None:
            continue
        svc_namespace = get_kubernetes_reference(UUID(str(svc_deployment_id)))
        if str(svc_deployment_id) == this_deployment_id:
            continue
        other_namespaces.add(svc_namespace)
        # Alias in OUR namespace for this other service
        aliases.append(
            build_external_name_service(
                resolved_name=svc["resolved_name"],
                target_namespace=svc_namespace,
                holder_namespace=this_namespace,
                deployment_id=str(svc_deployment_id),
                cluster_domain=cluster_domain,
            )
        )

    # For THIS deployment's services, create aliases in OTHER namespaces
    for svc in context.deployed_services:
        svc_deployment_id = svc.get("deployment_id")
        if svc_deployment_id is None:
            continue
        if str(svc_deployment_id) != this_deployment_id:
            continue
        for other_ns in other_namespaces:
            aliases.append(
                build_external_name_service(
                    resolved_name=svc["resolved_name"],
                    target_namespace=this_namespace,
                    holder_namespace=other_ns,
                    deployment_id=this_deployment_id,
                    cluster_domain=cluster_domain,
                )
            )

    return aliases


def select_stale_aliases(
    context: GlobalContext, live_aliases: list[V1Service]
) -> list[StaleAlias]:
    """The aliases of this deployment's services whose name it no longer uses.

    Selected by name only: another deployment's flow also writes this
    deployment's aliases, into namespaces that this flow does not write to.
    """
    deployment_id = str(context.instance.deployment_id)
    names = {
        svc["resolved_name"]
        for svc in context.deployed_services
        if str(svc.get("deployment_id")) == deployment_id
    }
    return [
        StaleAlias(
            namespace=alias.metadata.namespace,
            name=alias.metadata.name,
            resource_version=alias.metadata.resource_version,
        )
        for alias in live_aliases
        if alias.metadata.name not in names
        and is_alias_of_deployment(alias, deployment_id, context.instance.namespace)
    ]


async def find_stale_service_aliases(context: GlobalContext) -> list[StaleAlias]:
    """List the aliases in the cluster and select the stale ones of this deployment."""
    listed = await list_services_in_all_namespaces(
        label_selector=f"{SERVICE_ALIAS_LABEL}=true"
    )
    return select_stale_aliases(context, listed.items)


async def with_current_peer_services(context: GlobalContext) -> GlobalContext:
    """*context* with the other deployments' services that the server lists now (#503).

    The server builds the context when the change is requested, so the context does not list
    a deployment requested after that. The deployment's own services stay as the context lists
    them. When the server cannot be read, the context stays as it is.
    """
    logger = get_run_logger()
    environment_id = context.labels.get("environment_id")
    if environment_id is None:
        logger.warning(
            "The context names no environment; the aliases use the services listed "
            "when the change was requested"
        )
        return context
    try:
        current = await read_environment_services(str(environment_id))
    except EnvironmentServicesReadError as exc:
        logger.warning(
            "Could not read the services of environment %s (%s); the aliases use the "
            "services listed when the change was requested",
            environment_id,
            exc,
        )
        return context
    own_id = str(context.instance.deployment_id)
    own = [
        svc
        for svc in context.deployed_services
        if str(svc.get("deployment_id")) == own_id
    ]
    peers = [svc for svc in current if svc["deployment_id"] != own_id]
    listed = {str(svc.get("deployment_id")) for svc in context.deployed_services}
    if added := sorted({svc["deployment_id"] for svc in peers} - listed):
        logger.info(
            "The server lists services of deployments that the context does not list: %s",
            ", ".join(added),
        )
    return context.model_copy(update={"deployed_services": own + peers})


async def _read_namespace_state(
    namespace: str,
) -> tuple[V1Namespace | None, dict | None]:
    """The Namespace *namespace* and the StyrminDeployment in it; None for each one missing."""
    found, resource = await asyncio.gather(
        get_namespace(name=namespace),
        read_styrmin_deployment(name=namespace, namespace=namespace),
    )
    return found, resource


def _deletion_requested(resource: dict) -> bool:
    return bool((resource.get("spec") or {}).get("deletionRequested"))


def _has_deletion_timestamp(resource: dict) -> bool:
    return bool((resource.get("metadata") or {}).get("deletionTimestamp"))


def _is_departing(found: V1Namespace | None, resource: dict | None) -> bool:
    if is_gone_or_terminating(found):
        return True
    if resource is None:
        return False
    return _deletion_requested(resource) or _has_deletion_timestamp(resource)


def _is_deployment_deleted(found: V1Namespace | None, resource: dict | None) -> bool:
    """Whether the operator's teardown deletes the aliases of the deployment in *found*."""
    if resource is None:
        return False
    requested = _deletion_requested(resource)
    if not (requested or _has_deletion_timestamp(resource)):
        return False
    return teardown_deletes_aliases(deletion_requested=requested, namespace=found)


async def _read_namespace_states(
    namespaces: Iterable[str],
) -> dict[str, tuple[V1Namespace | None, dict | None]]:
    distinct = sorted(set(namespaces))
    limit = asyncio.Semaphore(MAX_CONCURRENT_NAMESPACE_READS)

    async def read(namespace: str) -> tuple[V1Namespace | None, dict | None]:
        async with limit:
            return await _read_namespace_state(namespace)

    states = await asyncio.gather(*(read(ns) for ns in distinct))
    return dict(zip(distinct, states, strict=True))


async def _select_namespaces(
    namespaces: Iterable[str],
    predicate: Callable[[V1Namespace | None, dict | None], bool],
) -> set[str]:
    states = await _read_namespace_states(namespaces)
    return {
        ns for ns, (found, resource) in states.items() if predicate(found, resource)
    }


async def find_departing_namespaces(namespaces: Iterable[str]) -> set[str]:
    """The namespaces whose deployment is being deleted or that are gone or terminating.

    A namespace without a StyrminDeployment counts only when it is gone or terminating. A
    namespace that does not exist yet also counts: its deployment's own flow writes the
    aliases later, because it reads the current services (``with_current_peer_services``).
    """
    return await _select_namespaces(namespaces, _is_departing)


async def find_deleted_deployment_namespaces(namespaces: Iterable[str]) -> set[str]:
    """The namespaces whose StyrminDeployment has a deletion request, or is deleted while
    the namespace exists and is not terminating."""
    return await _select_namespaces(namespaces, _is_deployment_deleted)


@task(task_run_name="Apply service alias: {alias_namespace}/{alias_name}")
async def apply_single_alias(
    alias_namespace: str, alias_name: str, resource: dict
) -> WrittenAlias | None:
    """Write one alias; None on a 404 (the namespace or the Service is gone) or when the
    namespace is terminating."""
    try:
        written = await apply_service(resource=resource, namespace=alias_namespace)
    except ApiException as exc:
        if not is_namespace_gone_error(exc):
            raise
        get_run_logger().info(
            "Skipping service alias %s/%s: the write returned %s (%s)",
            alias_namespace,
            alias_name,
            exc.status,
            "the namespace or the Service is gone"
            if exc.status == HTTPStatus.NOT_FOUND
            else "the namespace is terminating",
        )
        return None
    return WrittenAlias(
        namespace=alias_namespace,
        name=alias_name,
        owner_namespace=owner_namespace(resource),
        resource_version=written.metadata.resource_version
        if written.metadata
        else None,
    )


@task(task_run_name="Delete service alias: {alias_namespace}/{alias_name}")
async def delete_single_alias(
    alias_namespace: str, alias_name: str, resource_version: str | None
) -> bool:
    return await delete_service(
        name=alias_name, namespace=alias_namespace, resource_version=resource_version
    )


async def _delete_writes_of_deleted_deployments(written: list[WrittenAlias]) -> None:
    """Delete each written alias whose owner's deletion the second read finds (#503)."""
    logger = get_run_logger()
    deleted_owners = await find_deleted_deployment_namespaces(
        {alias.owner_namespace for alias in written}
    )
    for alias in written:
        if alias.owner_namespace not in deleted_owners:
            continue
        deleted = await delete_single_alias(
            alias_namespace=alias.namespace,
            alias_name=alias.name,
            resource_version=alias.resource_version,
        )
        if deleted:
            logger.info(
                "Deleted service alias %s in namespace %s: the deletion of the "
                "deployment in %s started after the flow's first read (#503)",
                alias.name,
                alias.namespace,
                alias.owner_namespace,
            )
        else:
            logger.info(
                "Did not delete service alias %s in namespace %s of the deleted "
                "deployment in %s: the alias is gone, or another flow wrote it again (#503)",
                alias.name,
                alias.namespace,
                alias.owner_namespace,
            )


@flow(flow_run_name="Apply service aliases")
async def apply_service_aliases(
    aliases: list[dict],
    stale_aliases: list[StaleAlias] | None = None,
) -> None:
    """Apply ExternalName Service aliases to the cluster and delete the stale ones.

    Skips the aliases and stale aliases that touch a departing namespace, writes into
    existing namespaces only, then deletes the written aliases whose owner's deletion
    started during the writes.
    """
    logger = get_run_logger()
    stale_aliases = stale_aliases or []

    departing = await find_departing_namespaces(
        {alias["metadata"]["namespace"] for alias in aliases}
        | {owner_namespace(alias) for alias in aliases}
        | {stale.namespace for stale in stale_aliases}
    )

    written: list[WrittenAlias] = []
    for alias in aliases:
        alias_ns = alias["metadata"]["namespace"]
        alias_name = alias["metadata"]["name"]
        owner_ns = owner_namespace(alias)
        if {alias_ns, owner_ns} & departing:
            logger.info(
                "Skipping service alias %s in namespace %s: namespace %s does not exist or "
                "is terminating, or the deletion of its deployment was requested",
                alias_name,
                alias_ns,
                owner_ns if owner_ns in departing else alias_ns,
            )
            continue
        logger.info(
            "Applying service alias: %s in namespace %s",
            alias_name,
            alias_ns,
        )
        result = await apply_single_alias(
            alias_namespace=alias_ns,
            alias_name=alias_name,
            resource=alias,
        )
        if result is not None:
            written.append(result)

    for stale in stale_aliases:
        if stale.namespace in departing:
            logger.info(
                "Keeping service alias %s in namespace %s: namespace %s does not exist or "
                "is terminating, or the deletion of its deployment was requested",
                stale.name,
                stale.namespace,
                stale.namespace,
            )
            continue
        logger.info(
            "Deleting service alias: %s in namespace %s",
            stale.name,
            stale.namespace,
        )
        await delete_single_alias(
            alias_namespace=stale.namespace,
            alias_name=stale.name,
            resource_version=stale.resource_version,
        )

    await _delete_writes_of_deleted_deployments(written)
