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


# Kinds whose apply error was always skipped before the Ingress was added. Left as it was (review F2).
_SKIPPED_ON_ANY_ERROR = frozenset({"NetworkPolicy"})


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
        except ApiException as exc:
            kind = resource.get("kind")
            name = resource.get("metadata", {}).get("name")
            # An Ingress is the one object that makes a service reachable: a refusal (403, 422, an
            # admission webhook) must fail the flow, not end it as a success with no Ingress.
            if kind == "Ingress":
                raise
            # A NetworkPolicy has always been skipped here whatever the error: kept as it was.
            # Any other kind is a custom resource; only status 404 (the kind is not installed yet) is skipped.
            if kind not in _SKIPPED_ON_ANY_ERROR and exc.status != 404:
                raise
            logger.warning(
                "Failed to apply {}/{} (status {}, reason {}): skipped, the kind may not be installed yet",
                kind,
                name,
                exc.status,
                exc.reason,
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
