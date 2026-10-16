"""Cross-namespace service discovery via ExternalName Service aliases.

When applications in the same environment are deployed into separate namespaces
(``styrmin-{deployment_id}``), short DNS names like ``intent`` do not resolve
across namespace boundaries.  This module creates Kubernetes ``ExternalName``
Service resources that act as DNS aliases, so each namespace can resolve
services owned by other deployments using their short names.

An alias is named after the service's resolved name, which a service-name
override sets, and carries the id of the deployment that owns the service.
A flow deletes that deployment's aliases whose name it no longer uses.

A flow never writes an alias for, or into the namespace of, a deployment whose
deletion was requested, and never creates a namespace. It reads that state
again after its writes and deletes the aliases whose owner's deletion was
requested in between (#503).

ClusterIP Services for each deployment's own services are handled by
``ServiceDiscoveryUtility`` (see ``resources/utilities/service_discovery.py``).
"""

import asyncio
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from kubernetes_asyncio.client import V1Service
from kubernetes_asyncio.client.api_client import ApiException
from prefect import flow, task
from prefect.logging import get_run_logger
from pydantic import BaseModel

from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_service,
    delete_service,
    get_custom_resource,
    get_namespace,
    is_namespace_gone_error,
    list_services_in_all_namespaces,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend import config
from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION

SERVICE_ALIAS_LABEL = "styrmin.io/service-alias"
DEPLOYMENT_ID_LABEL = "styrmin.io/deployment-id"


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
    resource_version: str | None = None


def owner_namespace(alias: dict) -> str:
    """The namespace of the deployment that owns the service *alias* points to."""
    labels = alias["metadata"].get("labels") or {}
    if DEPLOYMENT_ID_LABEL in labels:
        return get_kubernetes_reference(UUID(labels[DEPLOYMENT_ID_LABEL]))
    return alias["spec"]["externalName"].split(".")[1]


def build_external_name_service(
    resolved_name: str,
    target_namespace: str,
    owner_namespace: str,
    deployment_id: str,
    cluster_domain: str = "cluster.local",
) -> dict[str, Any]:
    """Build a Kubernetes ExternalName Service manifest.

    Creates a Service resource in *owner_namespace* that aliases *resolved_name*
    to its FQDN in *target_namespace*. *deployment_id* is the deployment that
    owns the service.
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": resolved_name,
            "namespace": owner_namespace,
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
                owner_namespace=this_namespace,
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
                    owner_namespace=other_ns,
                    deployment_id=this_deployment_id,
                    cluster_domain=cluster_domain,
                )
            )

    return aliases


def is_alias_of_deployment(
    alias: V1Service, deployment_id: str, namespace: str
) -> bool:
    """Whether *alias* is for a service of the deployment *deployment_id*.

    Aliases created before the id label point into the deployment's *namespace*.
    """
    labels = alias.metadata.labels or {}
    if DEPLOYMENT_ID_LABEL in labels:
        return labels[DEPLOYMENT_ID_LABEL] == deployment_id
    external_name = (alias.spec.external_name if alias.spec else None) or ""
    return external_name.split(".")[1:2] == [namespace]


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


async def _read_styrmin_deployment(namespace: str) -> dict | None:
    """The StyrminDeployment named after *namespace*, or None when there is none."""
    try:
        resource = await get_custom_resource(
            plural=CRD_PLURAL,
            name=namespace,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
        )
    except CustomResourceNotFound:
        return None
    assert isinstance(resource, dict)
    return resource


async def _is_departing(namespace: str) -> bool:
    found, resource = await asyncio.gather(
        get_namespace(name=namespace), _read_styrmin_deployment(namespace)
    )
    if found is None or (found.status and found.status.phase == "Terminating"):
        return True
    if resource is None:
        return False
    return bool(
        (resource.get("spec") or {}).get("deletionRequested")
        or (resource.get("metadata") or {}).get("deletionTimestamp")
    )


async def find_departing_namespaces(namespaces: Iterable[str]) -> set[str]:
    """The namespaces whose deployment is being deleted or that are gone or terminating.

    A namespace without a StyrminDeployment counts only when it is gone or terminating.
    """
    distinct = sorted(set(namespaces))
    departing = await asyncio.gather(*(_is_departing(ns) for ns in distinct))
    return {ns for ns, gone in zip(distinct, departing, strict=True) if gone}


@task(task_run_name="Apply service alias: {alias_namespace}/{alias_name}")
async def apply_single_alias(
    alias_namespace: str, alias_name: str, resource: dict
) -> WrittenAlias | None:
    """Write one alias; None when its namespace is gone or being deleted."""
    try:
        written = await apply_service(resource=resource, namespace=alias_namespace)
    except ApiException as exc:
        if not is_namespace_gone_error(exc):
            raise
        get_run_logger().info(
            "Skipping service alias %s/%s: the namespace is gone or being deleted",
            alias_namespace,
            alias_name,
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


@flow(flow_run_name="Apply service aliases")
async def apply_service_aliases(
    aliases: list[dict],
    stale_aliases: list[StaleAlias] | None = None,
) -> None:
    """Apply ExternalName Service aliases to the cluster and delete the stale ones.

    Skips the aliases and stale aliases that touch a departing namespace, writes
    into existing namespaces only, then deletes the written aliases whose owner
    started departing during the writes.
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
        if {alias_ns, owner_namespace(alias)} & departing:
            logger.info(
                "Skipping service alias %s in namespace %s: its deployment or the "
                "namespace is being deleted",
                alias_name,
                alias_ns,
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
                "Keeping service alias %s in namespace %s: the namespace is being "
                "deleted",
                stale.name,
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

    # A deletion requested between the first read and a write: remove that write (#503).
    departing_after = await find_departing_namespaces(
        {alias.owner_namespace for alias in written}
    )
    for alias in written:
        if (
            alias.owner_namespace not in departing_after
            or alias.namespace in departing_after
        ):
            continue
        logger.info(
            "Deleting service alias %s in namespace %s: the deletion of the "
            "deployment in %s was requested while the alias was written (#503)",
            alias.name,
            alias.namespace,
            alias.owner_namespace,
        )
        await delete_single_alias(
            alias_namespace=alias.namespace,
            alias_name=alias.name,
            resource_version=alias.resource_version,
        )
