"""Cross-namespace service discovery via ExternalName Service aliases.

When applications in the same environment are deployed into separate namespaces
(``styrmin-{deployment_id}``), short DNS names like ``intent`` do not resolve
across namespace boundaries.  This module creates Kubernetes ``ExternalName``
Service resources that act as DNS aliases, so each namespace can resolve
services owned by other deployments using their short names.

ClusterIP Services for each deployment's own services are handled by
``ServiceDiscoveryUtility`` (see ``resources/utilities/service_discovery.py``).
"""

from typing import Any
from uuid import UUID

from prefect import flow, task
from prefect.logging import get_run_logger

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_resource,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.agent.tasks.shared import apply_namespace
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend import config


def build_external_name_service(
    resolved_name: str,
    target_namespace: str,
    owner_namespace: str,
    cluster_domain: str = "cluster.local",
) -> dict[str, Any]:
    """Build a Kubernetes ExternalName Service manifest.

    Creates a Service resource in *owner_namespace* that aliases *resolved_name*
    to its FQDN in *target_namespace*.
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": resolved_name,
            "namespace": owner_namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "styrmin",
                "styrmin.io/service-alias": "true",
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
                    cluster_domain=cluster_domain,
                )
            )

    return aliases


@task(task_run_name="Apply service alias: {alias_namespace}/{alias_name}")
async def apply_single_alias(
    alias_namespace: str, alias_name: str, resource: dict
) -> None:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    await apply_kubernetes_resource(resource=resource, namespace=alias_namespace)


@flow(flow_run_name="Apply service aliases")
async def apply_service_aliases(
    aliases: list[dict],
    namespace_labels: dict[str, str] | None = None,
) -> None:
    """Apply ExternalName Service aliases to the cluster.

    Ensures target namespaces exist, then creates/updates each alias.
    """
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()

    # Collect unique namespaces that need to exist
    namespaces_needed: set[str] = set()
    for alias in aliases:
        namespaces_needed.add(alias["metadata"]["namespace"])

    for ns in namespaces_needed:
        await apply_namespace(namespace=ns, labels=namespace_labels)

    # Apply each alias
    for alias in aliases:
        alias_ns = alias["metadata"]["namespace"]
        alias_name = alias["metadata"]["name"]
        logger.info(
            "Applying service alias: %s in namespace %s",
            alias_name,
            alias_ns,
        )
        await apply_single_alias(
            alias_namespace=alias_ns,
            alias_name=alias_name,
            resource=alias,
        )
