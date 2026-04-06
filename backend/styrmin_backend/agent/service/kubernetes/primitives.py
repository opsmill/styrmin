import asyncio
from typing import Any

from fast_depends import Depends, inject
from fastapi import status
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client import (
    V1DeploymentList,
    V1Job,
    V1PodTemplateSpec,
    V1StatefulSetList,
)
from kubernetes_asyncio.client.api_client import ApiClient, ApiException

from .dependency import get_api_client
from .exceptions import CustomResourceNotFound, JobFailedError


@inject
async def run_kubernetes_job(
    namespace: str,
    manifest: dict,
    client: ApiClient = Depends(get_api_client),
) -> V1Job:
    batch_api = kubeclient.BatchV1Api(client)

    body = V1Job(
        api_version=manifest["apiVersion"],
        kind=manifest["kind"],
        metadata=manifest["metadata"],
        spec=manifest["spec"],
    )
    # Create the job
    try:
        job = await batch_api.create_namespaced_job(
            body=body, namespace=namespace, pretty="pretty"
        )
    except ApiException:
        raise

    # Wait for the job to complete
    while True:
        read_job = await batch_api.read_namespaced_job_status(
            name=job.metadata.name, namespace=namespace
        )
        for condition in read_job.status.conditions or []:
            if condition.type in ["Complete", "Failed"] and condition.status == "True":
                if condition.type == "Complete":
                    return read_job
                else:
                    raise JobFailedError(
                        f"Job {manifest['metadata']['name']} failed in namespace {namespace}"
                    )

        await asyncio.sleep(5)


@inject
async def apply_kubernetes_namespace(
    namespace: str,
    labels: dict[str, str] | None = None,
    client: ApiClient = Depends(get_api_client),
) -> None:
    core_api = kubeclient.CoreV1Api(client)
    try:
        await core_api.create_namespace(
            body=kubeclient.V1Namespace(
                metadata=kubeclient.V1ObjectMeta(name=namespace, labels=labels)
            )
        )
    except ApiException as exc:
        if exc.status != status.HTTP_409_CONFLICT:  # Namespace already exists
            pass


@inject
async def upsert_custom_resource(
    plurals: str,
    body: Any,
    group: str,
    version: str,
    namespace: str,
    update: bool = True,
    client: ApiClient = Depends(get_api_client),
) -> None:
    # Declare the kubernetes client object
    custom_obj_api = kubeclient.CustomObjectsApi(client)

    try:
        await custom_obj_api.create_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plurals,
            body=body,
        )
    except ApiException as exc:
        if update:
            if exc.status == status.HTTP_409_CONFLICT:
                await custom_obj_api.patch_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plurals,
                    body=body,
                    name=body["metadata"]["name"],
                    _content_type="application/merge-patch+json",  # type: ignore[call-arg]  # Workaround for patch type autodetect for custom objects
                )
            else:
                raise
        else:
            raise


@inject
async def get_custom_resource(
    plural: str,
    name: str,
    group: str,
    version: str,
    namespace: str,
    client: ApiClient = Depends(get_api_client),
) -> object:
    custom_obj_api = kubeclient.CustomObjectsApi(client)
    try:
        return await custom_obj_api.get_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            name=name,
        )
    except ApiException as exc:
        if exc.status == status.HTTP_404_NOT_FOUND:
            raise CustomResourceNotFound(
                f"Custom resource {plural}/{name} not found in namespace {namespace}"
            )
        raise


@inject
async def patch_custom_resource(
    plural: str,
    reference: str,
    group: str,
    version: str,
    namespace: str,
    patch: list,
    client: ApiClient = Depends(get_api_client),
) -> None:
    custom_obj_api = kubeclient.CustomObjectsApi(client)
    try:
        await custom_obj_api.patch_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            body=patch,
            name=reference,
        )
    except ApiException as exc:
        if exc.status == status.HTTP_404_NOT_FOUND:
            raise CustomResourceNotFound(
                f"Custom resource {plural}/{reference} not found in namespace {namespace}"
            )
        raise


@inject
async def apply_kubernetes_resource(
    resource: dict,
    namespace: str,
    client: ApiClient = Depends(get_api_client),
) -> None:
    """Apply a Kubernetes resource using server-side-like upsert logic.

    Handles both core API resources (Secret, NetworkPolicy) and custom resources (Middleware).
    Creates the resource if it doesn't exist, patches it if it does.
    """
    api_version = resource["apiVersion"]
    kind = resource["kind"]
    name = resource["metadata"]["name"]

    # Core API resources — check kind first since some core resources
    # use grouped apiVersions (e.g., networking.k8s.io/v1 for NetworkPolicy)
    if kind == "Secret":
        core_api = kubeclient.CoreV1Api(client)
        try:
            await core_api.create_namespaced_secret(namespace=namespace, body=resource)  # type: ignore[arg-type]
        except ApiException as exc:
            if exc.status == status.HTTP_409_CONFLICT:
                await core_api.replace_namespaced_secret(
                    name=name,
                    namespace=namespace,
                    body=resource,  # type: ignore[arg-type]
                )
            else:
                raise
    elif kind == "NetworkPolicy":
        networking_api = kubeclient.NetworkingV1Api(client)
        try:
            await networking_api.create_namespaced_network_policy(
                namespace=namespace,
                body=resource,  # type: ignore[arg-type]
            )
        except ApiException as exc:
            if exc.status == status.HTTP_409_CONFLICT:
                await networking_api.replace_namespaced_network_policy(
                    name=name,
                    namespace=namespace,
                    body=resource,  # type: ignore[arg-type]
                )
            else:
                raise
    elif kind == "Service":
        core_api = kubeclient.CoreV1Api(client)
        try:
            await core_api.create_namespaced_service(
                namespace=namespace,
                body=resource,  # type: ignore[arg-type]
            )
        except ApiException as exc:
            if exc.status == status.HTTP_409_CONFLICT:
                await core_api.replace_namespaced_service(
                    name=name,
                    namespace=namespace,
                    body=resource,  # type: ignore[arg-type]
                )
            else:
                raise
    elif "/" in api_version:
        # Custom resources (e.g., Traefik Middleware)
        group, version = api_version.rsplit("/", 1)
        plural = _kind_to_plural(kind)
        await upsert_custom_resource(
            plurals=plural,
            body=resource,
            group=group,
            version=version,
            namespace=namespace,
        )
    else:
        raise ValueError(f"Unsupported resource kind: {kind}")


_CRD_KIND_PLURALS: dict[str, str] = {
    "Middleware": "middlewares",
    "IngressRoute": "ingressroutes",
    "TLSOption": "tlsoptions",
}


def _kind_to_plural(kind: str) -> str:
    """Convert a Kubernetes CRD kind to its plural form.

    Uses an explicit mapping for known kinds. Falls back to lowercase + 's'
    for unknown kinds, which works for most simple cases.
    """
    if kind in _CRD_KIND_PLURALS:
        return _CRD_KIND_PLURALS[kind]
    return kind.lower() + "s"


@inject
async def get_deployments(
    namespace: str, client: ApiClient = Depends(get_api_client)
) -> V1DeploymentList:
    apps_api = kubeclient.AppsV1Api(client)
    return await apps_api.list_namespaced_deployment(namespace=namespace)


@inject
async def get_stateful_sets(
    namespace: str, client: ApiClient = Depends(get_api_client)
) -> V1StatefulSetList:
    apps_api = kubeclient.AppsV1Api(client)
    return await apps_api.list_namespaced_stateful_set(namespace=namespace)


async def _find_workload_pod_template(
    namespace: str,
    label_selector: str,
    client: ApiClient,
) -> V1PodTemplateSpec:
    """Find a Deployment or StatefulSet by label selector and return its pod template.

    Queries for Deployments first, then falls back to StatefulSets. This works even
    when the component is scaled to 0 replicas, since the resource spec persists.

    Args:
        namespace: The Kubernetes namespace.
        label_selector: Label selector string (e.g., "service=infrahub-server").
        client: The Kubernetes API client.

    Returns:
        The pod template spec of the matching workload.

    Raises:
        ValueError: If no matching Deployment or StatefulSet is found.
    """
    apps_api = kubeclient.AppsV1Api(client)

    deployments = await apps_api.list_namespaced_deployment(
        namespace=namespace, label_selector=label_selector
    )
    if deployments.items:
        return deployments.items[0].spec.template

    stateful_sets = await apps_api.list_namespaced_stateful_set(
        namespace=namespace, label_selector=label_selector
    )
    if stateful_sets.items:
        return stateful_sets.items[0].spec.template

    raise ValueError(
        f"No Deployment or StatefulSet found with label selector '{label_selector}' "
        f"in namespace '{namespace}'"
    )


@inject
async def get_component_env(
    namespace: str,
    label_selector: str,
    client: ApiClient = Depends(get_api_client),
) -> tuple[list[dict], list[dict]]:
    """Extract env and envFrom from a component's pod template.

    Args:
        namespace: The Kubernetes namespace.
        label_selector: Label selector string (e.g., "service=infrahub-server").

    Returns:
        Tuple of (env, env_from) as lists of dicts in K8s API format.
    """
    pod_template = await _find_workload_pod_template(namespace, label_selector, client)
    container = pod_template.spec.containers[0]

    env = client.sanitize_for_serialization(container.env) if container.env else []
    env_from = (
        client.sanitize_for_serialization(container.env_from)
        if container.env_from
        else []
    )

    return env, env_from


@inject
async def get_component_labels(
    namespace: str,
    label_selector: str,
    client: ApiClient = Depends(get_api_client),
) -> dict[str, str]:
    """Extract pod template labels from a component's Deployment or StatefulSet.

    Args:
        namespace: The Kubernetes namespace.
        label_selector: Label selector string (e.g., "service=infrahub-server").

    Returns:
        Dict of label key-value pairs from the pod template metadata.
    """
    pod_template = await _find_workload_pod_template(namespace, label_selector, client)
    return dict(pod_template.metadata.labels or {})


@inject
async def get_component_images(
    namespace: str,
    label_selector: str,
    client: ApiClient = Depends(get_api_client),
) -> list[str]:
    """Extract container images from a component's Deployment or StatefulSet.

    Returns images from all containers in the pod template spec.

    Args:
        namespace: The Kubernetes namespace.
        label_selector: Label selector string (e.g., "service=infrahub-server").

    Returns:
        List of container image strings.
    """
    pod_template = await _find_workload_pod_template(namespace, label_selector, client)
    return [container.image for container in pod_template.spec.containers]


@inject
async def run_job(
    namespace: str,
    body: Any,
    client: ApiClient = Depends(get_api_client),
) -> None:
    batch_api = kubeclient.BatchV1Api(client)
    # core_api = kubeclient.CoreV1Api(client)
    job_name = body["metadata"]["name"]

    try:
        # Create the job
        await batch_api.create_namespaced_job(
            body=body, namespace=namespace, pretty="pretty"
        )
    except ApiException as exc:
        if exc.status == status.HTTP_409_CONFLICT:
            raise CustomResourceNotFound(
                f"Job {job_name} already exists in namespace {namespace}"
            )
        raise

    # Wait for the job to complete
    while True:
        job = await batch_api.read_namespaced_job_status(
            name=job_name, namespace=namespace
        )
        if job.status.succeeded:
            # Job completed successfully
            break
        if job.status.failed:
            # Job failed
            raise RuntimeError(f"Job {job_name} failed in namespace {namespace}")
        await asyncio.sleep(5)  # Poll every 5 seconds
