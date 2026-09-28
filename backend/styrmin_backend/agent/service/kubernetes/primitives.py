import asyncio
from typing import Any

from fast_depends import Depends, inject
from fastapi import status
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client import (
    V1DeploymentList,
    V1Job,
    V1PodList,
    V1PodTemplateSpec,
    V1StatefulSetList,
)
from kubernetes_asyncio.client.api_client import ApiClient, ApiException

from .dependency import get_api_client
from .exceptions import CustomResourceNotFound, JobAlreadyExistsError, JobFailedError


def _prune_none(value: Any) -> Any:
    """Recursively drop dict keys whose value is ``None`` (lists are recursed
    but their elements are kept).

    Used on the **create** path of :func:`upsert_custom_resource`. The two
    apply paths treat a ``null`` differently:

    - **create** (``POST``) stores the body verbatim, so a ``key: null`` lands
      in the object as a literal null;
    - **update** (``application/merge-patch+json``) interprets ``key: null`` as
      "delete this member" (RFC 7386).

    Driver value templates exploit the merge-patch semantics to *clear* an
    override: they emit ``args: null`` when the operator has no override set, so
    the update path removes the key and the chart's own default flows through.
    But on the first reconcile (create) that same ``null`` would persist
    literally — and an upstream chart that consumes the value unconditionally
    (e.g. infrahub's server ``args``, which the chart ``toYaml``s with no
    ``with`` guard) would render ``null`` and blank the field. Stripping ``None``
    on create makes a rendered ``null`` behave as "absent" (chart default
    applies), while the merge-patch path keeps the ``null`` so clearing still
    deletes the key. See ADR-045 §5.

    The ``replace_spec_keys_on_update`` path also prunes nested ``None``, since
    replacing a spec key removes its omitted nested keys without a ``null``.
    """
    if isinstance(value, dict):
        return {k: _prune_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_prune_none(v) for v in value]
    return value


def _json_pointer_token(key: str) -> str:
    """Escape *key* as one RFC 6901 reference token (``~`` first, then ``/``)."""
    return key.replace("~", "~0").replace("/", "~1")


def _replace_spec_keys_json_patch(body: dict[str, Any]) -> list[dict[str, Any]]:
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
        path = f"/spec/{_json_pointer_token(key)}"
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
                    "path": f"/metadata/{map_key}/{_json_pointer_token(key)}",
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
    prune_none_on_create: bool = False,
    replace_spec_keys_on_update: bool = False,
    client: ApiClient = Depends(get_api_client),
) -> None:
    # Declare the kubernetes client object
    custom_obj_api = kubeclient.CustomObjectsApi(client)

    # On create, a ``null`` would be stored verbatim; on the merge-patch update
    # below it deletes the key. Drivers emit ``null`` to clear an override, so
    # callers that carry such values prune ``None`` from the *create* body. The
    # HelmRelease apply also sets ``replace_spec_keys_on_update``, whose JSON
    # Patch prunes nested ``None`` and removes a top-level spec key set to
    # ``None``, so a null marker reads as absent on both paths.
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
                    body=_replace_spec_keys_json_patch(body),
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
    """Create the Job described by ``body`` and wait until it finishes.

    ``body["metadata"]`` may carry either a fixed ``name`` or a ``generateName``
    prefix. The name is read back from the API server's create response, so
    callers can let Kubernetes make every Job unique instead of reusing one
    deterministic name that collides with a finished Job (#374).

    Raises:
        JobAlreadyExistsError: A Job with the requested name already exists.
        JobFailedError: The Job reached its failure state.
    """
    batch_api = kubeclient.BatchV1Api(client)
    metadata = body["metadata"]
    requested_name = metadata.get("name") or metadata.get("generateName")

    try:
        # Create the job
        created: V1Job = await batch_api.create_namespaced_job(
            body=body, namespace=namespace, pretty="pretty"
        )
    except ApiException as exc:
        if exc.status == status.HTTP_409_CONFLICT:
            raise JobAlreadyExistsError(
                f"Job {requested_name} already exists in namespace {namespace}"
            ) from exc
        raise

    job_name = created.metadata.name

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
            raise JobFailedError(f"Job {job_name} failed in namespace {namespace}")
        await asyncio.sleep(5)  # Poll every 5 seconds
