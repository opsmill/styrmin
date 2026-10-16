import asyncio
from datetime import UTC, datetime
from typing import Any

from fast_depends import Depends, inject
from fastapi import status
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client import (
    V1DeleteOptions,
    V1DeploymentList,
    V1Job,
    V1PodList,
    V1PodTemplateSpec,
    V1Preconditions,
    V1ServiceList,
    V1StatefulSetList,
)
from kubernetes_asyncio.client.api_client import ApiClient, ApiException

from .dependency import get_api_client
from .exceptions import CustomResourceNotFound, JobFailedError, JobOutputUnreadableError
from .job_logs import read_job_output_tail


def _prune_none(value: Any) -> Any:
    """Recursively drop dict keys whose value is ``None``; list elements are kept.

    A values template may render ``key: null``; pruning the create body makes it read as absent,
    as ``replace_spec_keys_on_update`` does on update.
    """
    if isinstance(value, dict):
        return {k: _prune_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune_none(v) for v in value]
    return value


def json_pointer_token(key: str) -> str:
    """Escape *key* as one RFC 6901 reference token (``~`` first, then ``/``)."""
    return key.replace("~", "~0").replace("/", "~1")


def replace_spec_keys_json_patch(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the JSON Patch that replaces each spec key the body sets.

    Each top-level ``spec`` key the body sets is replaced (nested ``None``
    pruned), so nested keys the new body omits are removed. A top-level key set
    to ``None`` is removed by ``add {}`` then ``remove``, which succeeds whether
    or not the key exists live. Spec keys the body does not set
    (``spec.suspend``, ``spec.deletionRequested``) are left alone, as with
    merge-patch. ``metadata.labels`` / ``metadata.annotations`` keys are added
    one by one, leaving keys other actors wrote (kopf annotations, Flux's
    finalizer) untouched. Per-key ``add`` needs the live maps to exist.
    """
    ops: list[dict[str, Any]] = []
    for key, value in (body.get("spec") or {}).items():
        path = f"/spec/{json_pointer_token(key)}"
        if value is None:
            ops.append({"op": "add", "path": path, "value": {}})
            ops.append({"op": "remove", "path": path})
        else:
            ops.append({"op": "add", "path": path, "value": _prune_none(value)})
    metadata = _prune_none(body.get("metadata") or {})
    for map_key in ("labels", "annotations"):
        for key, value in metadata.get(map_key, {}).items():
            ops.append(
                {
                    "op": "add",
                    "path": f"/metadata/{map_key}/{json_pointer_token(key)}",
                    "value": value,
                }
            )
    return ops


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

    # The manifest may only set generateName, so use the created Job's name.
    job_name = job.metadata.name
    while True:
        read_job = await batch_api.read_namespaced_job_status(
            name=job_name, namespace=namespace
        )
        for condition in read_job.status.conditions or []:
            if condition.type in ["Complete", "Failed"] and condition.status == "True":
                if condition.type == "Complete":
                    return read_job
                raise await _job_failed_error(
                    namespace, job_name, _first_container(manifest), client
                )

        await asyncio.sleep(5)


def _first_container(manifest: dict) -> str:
    return manifest["spec"]["template"]["spec"]["containers"][0]["name"]


async def _job_failed_error(
    namespace: str, job_name: str, container: str, client: ApiClient
) -> JobFailedError:
    """The Job's failure with the end of its output, read before the Job can be removed."""
    message = f"Job {job_name} failed in namespace {namespace}"
    try:
        output = await read_job_output_tail(
            namespace=namespace, job_name=job_name, container=container, client=client
        )
    except JobOutputUnreadableError as exc:
        return JobFailedError(f"{message}. The output could not be read: {exc}")
    return JobFailedError(message, output=output.text, truncated=output.truncated)


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
    prune_none_on_create: bool = False,
    replace_spec_keys_on_update: bool = False,
    client: ApiClient = Depends(get_api_client),
) -> None:
    # Declare the kubernetes client object
    custom_obj_api = kubeclient.CustomObjectsApi(client)

    # A create stores a rendered ``null`` verbatim, so prune it; the update's JSON Patch
    # (``replace_spec_keys_on_update``) prunes it too, so ``null`` reads as absent on both paths.
    create_body = _prune_none(body) if prune_none_on_create else body

    try:
        await custom_obj_api.create_namespaced_custom_object(
            group=group,
            version=version,
            namespace=namespace,
            plural=plurals,
            body=create_body,
        )
    except ApiException as exc:
        if update:
            if exc.status == status.HTTP_409_CONFLICT and replace_spec_keys_on_update:
                # Replace each spec key the body sets rather than merge it, so
                # nested keys the new body omits do not linger (FR-011).
                await custom_obj_api.patch_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plurals,
                    body=replace_spec_keys_json_patch(body),
                    name=body["metadata"]["name"],
                    _content_type="application/json-patch+json",  # type: ignore[call-arg]
                )
            elif exc.status == status.HTTP_409_CONFLICT:
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
async def create_event(
    *,
    involved_object: kubeclient.V1ObjectReference,
    reason: str,
    message: str,
    component: str,
    event_type: str = "Normal",
    client: ApiClient = Depends(get_api_client),
) -> None:
    """Record a Kubernetes Event on ``involved_object``, in that object's namespace."""
    now = datetime.now(tz=UTC)
    await kubeclient.CoreV1Api(client).create_namespaced_event(
        namespace=involved_object.namespace,
        body=kubeclient.CoreV1Event(
            metadata=kubeclient.V1ObjectMeta(
                generate_name=f"{involved_object.name}.",
                namespace=involved_object.namespace,
            ),
            involved_object=involved_object,
            reason=reason,
            message=message,
            type=event_type,
            first_timestamp=now,
            last_timestamp=now,
            source=kubeclient.V1EventSource(component=component),
            reporting_component=component,
            action=reason,
        ),
    )


@inject
async def patch_custom_resource_status(
    plural: str,
    reference: str,
    group: str,
    version: str,
    namespace: str,
    status_patch: dict,
    client: ApiClient = Depends(get_api_client),
) -> None:
    """Merge-patch the ``status`` subresource of a custom resource.

    Use this when writing fields that live under ``.status`` — the standard
    spec-level patch does not reach the status subresource.
    """
    custom_obj_api = kubeclient.CustomObjectsApi(client)
    try:
        await custom_obj_api.patch_namespaced_custom_object_status(
            group=group,
            version=version,
            namespace=namespace,
            plural=plural,
            name=reference,
            body={"status": status_patch},
            _content_type="application/merge-patch+json",  # type: ignore[call-arg]
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
async def list_pods(
    namespace: str, client: ApiClient = Depends(get_api_client)
) -> V1PodList:
    """List all pods in a namespace."""
    core_api = kubeclient.CoreV1Api(client)
    return await core_api.list_namespaced_pod(namespace=namespace)


@inject
async def list_services_in_all_namespaces(
    label_selector: str, client: ApiClient = Depends(get_api_client)
) -> V1ServiceList:
    """List the Services of every namespace that match ``label_selector``."""
    core_api = kubeclient.CoreV1Api(client)
    return await core_api.list_service_for_all_namespaces(label_selector=label_selector)


@inject
async def delete_service(
    name: str,
    namespace: str,
    resource_version: str | None = None,
    client: ApiClient = Depends(get_api_client),
) -> bool:
    """Delete a Service; False when it is gone or changed since ``resource_version``."""
    core_api = kubeclient.CoreV1Api(client)
    try:
        await core_api.delete_namespaced_service(
            name=name,
            namespace=namespace,
            body=V1DeleteOptions(
                preconditions=V1Preconditions(resource_version=resource_version)
            ),
        )
    except ApiException as exc:
        if exc.status in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
            return False
        raise
    return True


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
    *,
    container: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Extract env and envFrom from a component's pod template.

    Reads the ``container`` container when it is present, else the first container.

    Args:
        namespace: The Kubernetes namespace.
        label_selector: Label selector string (e.g., "service=infrahub-server").
        container: The component container's name, if the driver declares one.

    Returns:
        Tuple of (env, env_from) as lists of dicts in K8s API format.
    """
    pod_template = await _find_workload_pod_template(namespace, label_selector, client)
    containers = pod_template.spec.containers
    source = next((c for c in containers if c.name == container), containers[0])

    env = client.sanitize_for_serialization(source.env) if source.env else []
    env_from = (
        client.sanitize_for_serialization(source.env_from) if source.env_from else []
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
    *,
    container: str | None = None,
) -> list[str]:
    """Extract container images from a component's Deployment or StatefulSet.

    Returns images from all containers in the pod template spec, in pod-template
    order, except that the ``container`` image comes first when that container is
    present. Init containers are never included.

    Args:
        namespace: The Kubernetes namespace.
        label_selector: Label selector string (e.g., "service=infrahub-server").
        container: The component container's name, if the driver declares one.

    Returns:
        List of container image strings.
    """
    pod_template = await _find_workload_pod_template(namespace, label_selector, client)
    # Stable sort: only the component container moves; the others keep their order.
    containers = sorted(pod_template.spec.containers, key=lambda c: c.name != container)
    return [c.image for c in containers]


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
            raise await _job_failed_error(
                namespace, job_name, _first_container(body), client
            )
        await asyncio.sleep(5)  # Poll every 5 seconds
