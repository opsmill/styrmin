from kubernetes_asyncio.client.api_client import ApiException
from loguru import logger
from prefect import flow

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_resource,
)
from styrmin_backend.agent.tasks.shared import (
    apply_helm_charts,
    apply_helm_release,
    apply_helm_repositories,
    apply_namespace,
    poll_helm_release_status,
    poll_kubernetes_deployments_status,
    poll_kubernetes_stateful_sets_status,
)
from styrmin_backend.agent.tasks.shared import (
    apply_helm_release as update_helm_release_task,
)


@flow(flow_run_name="Update Helm release: {namespace} {reference}")
async def update_helm_release(
    namespace: str,
    release_spec: dict,
    reference: str,
    namespace_labels: dict[str, str] | None = None,
) -> None:
    """Update an instance in the Kubernetes cluster.

    To keep modularity here, the agent verb should get everything variables from its arguments.
    """

    await apply_namespace(namespace=namespace, labels=namespace_labels)

    await update_helm_release_task(namespace=namespace, release_spec=release_spec)

    await poll_helm_release_status(namespace=namespace, reference=reference)
    await poll_kubernetes_deployments_status(namespace=namespace)
    await poll_kubernetes_stateful_sets_status(namespace=namespace)


@flow(flow_run_name="Apply utility resources: {namespace}")
async def apply_utility_resources(
    namespace: str,
    resources: list[dict],
    namespace_labels: dict[str, str] | None = None,
) -> None:
    """Apply native Kubernetes resources for a utility to the cluster.

    This flow runs on the k8s-agent (user-work-pool) which has Kubernetes access.
    """

    await apply_namespace(namespace=namespace, labels=namespace_labels)

    # Apply core API resources first, then CRDs (which may not be installed yet)
    core_resources = [r for r in resources if "/" not in r.get("apiVersion", "")]
    crd_resources = [r for r in resources if "/" in r.get("apiVersion", "")]

    for resource in core_resources:
        await apply_kubernetes_resource(resource=resource, namespace=namespace)

    for resource in crd_resources:
        try:
            await apply_kubernetes_resource(resource=resource, namespace=namespace)
        except ApiException:
            logger.warning(
                "Failed to apply CRD resource {}/{} — the CRD type may not be installed yet",
                resource.get("kind"),
                resource.get("metadata", {}).get("name"),
            )


@flow(flow_run_name="Create Helm release: {namespace} {reference}")
async def create_helm_release(
    namespace: str,
    reference: str,
    release_spec: dict,
    helm_repositories: list[dict],
    charts: list[dict],
    namespace_labels: dict[str, str] | None = None,
) -> None:
    """Create an instance in the Kubernetes cluster.

    To keep modularity here, the agent verb should get everything variables from its arguments.
    """

    await apply_namespace(namespace=namespace, labels=namespace_labels)

    await apply_helm_repositories(helm_repositories=helm_repositories)
    await apply_helm_charts(charts=charts)
    await apply_helm_release(namespace=namespace, release_spec=release_spec)

    await poll_helm_release_status(namespace=namespace, reference=reference)
    await poll_kubernetes_deployments_status(namespace=namespace)
    await poll_kubernetes_stateful_sets_status(namespace=namespace)
