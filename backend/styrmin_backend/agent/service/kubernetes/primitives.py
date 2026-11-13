import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fast_depends import Depends, inject
from fastapi import status
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client import (
    V1DeleteOptions,
    V1DeploymentList,
    V1Job,
    V1Namespace,
    V1PodList,
    V1PodTemplateSpec,
    V1Preconditions,
    V1Service,
    V1ServiceList,
    V1StatefulSetList,
)
from kubernetes_asyncio.client.api_client import ApiClient, ApiException

from .dependency import get_api_client
from .exceptions import (
    CustomResourceNotFound,
    JobAlreadyExistsError,
    JobDeletedError,
    JobFailedError,
    JobNotDeletedError,
    JobNotFromActionError,
    JobOutputUnreadableError,
    JobStillRunningError,
)
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
async def get_namespace(
    name: str, client: ApiClient = Depends(get_api_client)
) -> V1Namespace | None:
    """Read a Namespace; None when it does not exist."""
    core_api = kubeclient.CoreV1Api(client)
    try:
        return await core_api.read_namespace(name=name)
    except ApiException as exc:
        if exc.status == status.HTTP_404_NOT_FOUND:
            return None
        raise


_NAMESPACE_TERMINATING_CAUSE = "NamespaceTerminating"
_NAMESPACE_TERMINATING_MESSAGE = "because it is being terminated"


def _status_cause_types(body: str) -> set[str]:
    """The ``details.causes[*].type`` values of a Kubernetes Status body; empty if not one."""
    try:
        details = json.loads(body).get("details") or {}
        return {cause.get("type") for cause in details.get("causes") or []}
    except ValueError, AttributeError, TypeError:
        return set()


def is_namespace_gone_error(exc: ApiException) -> bool:
    """True for a 404 (the namespace or the Service is gone) and when the namespace is terminating.

    A 403 counts only with the NamespaceLifecycle plugin's cause or message, never an RBAC 403.
    """
    if exc.status == status.HTTP_404_NOT_FOUND:
        return True
    if exc.status != status.HTTP_403_FORBIDDEN:
        return False
    body = exc.body or ""
    if isinstance(body, bytes):
        body = body.decode(errors="replace")
    return (
        _NAMESPACE_TERMINATING_CAUSE in _status_cause_types(body)
        or _NAMESPACE_TERMINATING_MESSAGE in body
    )


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

    Handles built-in resources (Secret, NetworkPolicy, Ingress, Service) and custom
    resources (Middleware).
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
    elif kind == "Ingress":
        # A built-in kind of networking.k8s.io/v1, not a custom resource: the custom
        # resource path below would build the plural "ingresss" and be refused.
        networking_api = kubeclient.NetworkingV1Api(client)
        try:
            await networking_api.create_namespaced_ingress(
                namespace=namespace,
                body=resource,  # type: ignore[arg-type]
            )
        except ApiException as exc:
            if exc.status == status.HTTP_409_CONFLICT:
                await networking_api.replace_namespaced_ingress(
                    name=name,
                    namespace=namespace,
                    body=resource,  # type: ignore[arg-type]
                )
            else:
                raise
    elif kind == "Service":
        await apply_service(resource=resource, namespace=namespace, client=client)
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
async def apply_service(
    resource: dict,
    namespace: str,
    client: ApiClient = Depends(get_api_client),
) -> V1Service:
    """Create a Service, or replace the one with the same name; return the stored object."""
    core_api = kubeclient.CoreV1Api(client)
    try:
        return await core_api.create_namespaced_service(
            namespace=namespace,
            body=resource,  # type: ignore[arg-type]
        )
    except ApiException as exc:
        if exc.status != status.HTTP_409_CONFLICT:
            raise
    return await core_api.replace_namespaced_service(
        name=resource["metadata"]["name"],
        namespace=namespace,
        body=resource,  # type: ignore[arg-type]
    )


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


#: The label that marks a Job that ``execute_commands`` created for a driver action.
ACTION_JOB_LABEL = "styrmin.io/action-job"
#: The container of the Job that ``execute_commands`` creates. A Job that an
#: earlier Styrmin version created for an action has no ``ACTION_JOB_LABEL``
#: and is known by this single container.
ACTION_JOB_CONTAINER = "user-job"
#: How long ``run_job`` waits for the earlier Job of the same name and its pods to be deleted.
JOB_DELETION_TIMEOUT_SECONDS = 120.0
#: How often ``run_job`` reads the earlier Job while it waits for its deletion.
JOB_DELETION_POLL_SECONDS = 1.0


def _is_action_job(job: V1Job) -> bool:
    """Whether a driver action created ``job`` through ``execute_commands``.

    True when the Job has ``ACTION_JOB_LABEL``, or, for a Job that an earlier
    Styrmin version created without the label, when its only container is
    ``ACTION_JOB_CONTAINER``.
    """
    labels = job.metadata.labels or {}
    if labels.get(ACTION_JOB_LABEL) == "true":
        return True
    template = job.spec.template if job.spec else None
    containers = template.spec.containers if template and template.spec else []
    return [container.name for container in containers] == [ACTION_JOB_CONTAINER]


def _end_of_job(job: V1Job) -> str | None:
    """``"completed"`` or ``"failed"`` when ``job`` has ended, None while it can still run a pod.

    A Job has ended when it has the ``Complete`` or the ``Failed`` condition.
    A Job with a failed pod and no ``Failed`` condition can still start
    another pod (``backoffLimit``), so it has not ended.
    """
    conditions = job.status.conditions if job.status else None
    for condition in conditions or []:
        if condition.status != "True":
            continue
        if condition.type == "Complete":
            return "completed"
        if condition.type == "Failed":
            return "failed"
    return None


async def _delete_earlier_job(
    batch_api: kubeclient.BatchV1Api,
    namespace: str,
    job_name: str,
    on_delete: Callable[[str], Awaitable[None]] | None,
) -> None:
    """Delete the Job ``job_name`` that an earlier action left, then wait until it and its pods are gone.

    Only a Job that a driver action created (:func:`_is_action_job`) and that
    has ended (:func:`_end_of_job`) is deleted. Before the delete,
    ``on_delete`` receives a line that names the Job and how it ended.

    The delete uses the ``Foreground`` propagation policy, so Kubernetes
    removes the Job only after its pods; a Job that is gone therefore has no
    pod left that the output reader of the next Job could read. The delete
    has a ``uid`` precondition, so it never removes a Job that another writer
    created after the read. Returns when the read answers 404, or finds a Job
    with another ``uid``, which the create then reports as a conflict.

    Raises:
        JobNotFromActionError: the Job was not created by a driver action.
        JobStillRunningError: the Job has not ended.
        JobNotDeletedError: the earlier Job still exists after
            ``JOB_DELETION_TIMEOUT_SECONDS``.
    """
    try:
        earlier = await batch_api.read_namespaced_job(
            name=job_name, namespace=namespace
        )
    except ApiException as exc:
        if exc.status == status.HTTP_404_NOT_FOUND:
            return
        raise
    if not _is_action_job(earlier):
        raise JobNotFromActionError(
            f"Job {job_name} in namespace {namespace} was not created by a driver "
            f"action: it has no label {ACTION_JOB_LABEL}=true. Styrmin does not delete "
            "it, so the action cannot create its own Job of that name. If nothing "
            "needs that Job, delete it, then request the change again: "
            f"kubectl delete job -n {namespace} {job_name}"
        )
    end = _end_of_job(earlier)
    if end is None:
        raise JobStillRunningError(
            f"Job {job_name} of an earlier action is still running in namespace "
            f"{namespace}, so Styrmin does not delete it: another change of this "
            "deployment may still be running its action. Wait until the Job ends, "
            "then request the change again. To read its state: "
            f"kubectl get job -n {namespace} {job_name}"
        )
    if on_delete is not None:
        await on_delete(
            f"Deleting Job {job_name}, which an earlier action left ({end}), and its "
            "pods before the new Job is created. This waits up to "
            f"{JOB_DELETION_TIMEOUT_SECONDS:.0f} seconds."
        )
    uid = earlier.metadata.uid
    try:
        await batch_api.delete_namespaced_job(
            name=job_name,
            namespace=namespace,
            body=V1DeleteOptions(
                propagation_policy="Foreground",
                preconditions=V1Preconditions(uid=uid),
            ),
        )
    except ApiException as exc:
        # 404: already gone. 409: another Job replaced it; the create reports it.
        if exc.status not in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
            raise

    deadline = time.monotonic() + JOB_DELETION_TIMEOUT_SECONDS
    while True:
        try:
            job = await batch_api.read_namespaced_job(
                name=job_name, namespace=namespace
            )
        except ApiException as exc:
            if exc.status == status.HTTP_404_NOT_FOUND:
                return
            raise
        if job.metadata.uid != uid:
            return
        if time.monotonic() >= deadline:
            raise JobNotDeletedError(
                f"Job {job_name} of an earlier run still exists in namespace {namespace} "
                f"{JOB_DELETION_TIMEOUT_SECONDS:.0f} seconds after Styrmin deleted it, so "
                "the new Job cannot be created. Check why its pods are not removed: "
                f"kubectl get pods -n {namespace} -l batch.kubernetes.io/job-name={job_name}"
            )
        await asyncio.sleep(JOB_DELETION_POLL_SECONDS)


@inject
async def run_job(
    namespace: str,
    body: Any,
    client: ApiClient = Depends(get_api_client),
    *,
    on_delete: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """Run the Job ``body`` in ``namespace`` and wait until it succeeds.

    The Job's name is fixed by its caller (``execute_commands`` names it after
    the deployment's release). A Job of that name that an earlier action left
    and that has ended, completed or failed, is deleted first, with its pods,
    so each run of an action can create its Job again; ``on_delete`` receives
    a line that names it first. A Job of that name that is still running, or
    that no driver action created, is never deleted: the call raises instead.
    The last Job stays in the cluster until the next run, for inspection.

    Raises:
        JobStillRunningError: the earlier Job has not ended.
        JobNotFromActionError: the Job of that name was not created by a
            driver action.
        JobNotDeletedError: the earlier Job was not deleted in time.
        JobAlreadyExistsError: a Job of the same name was created after the
            earlier one was deleted.
        JobDeletedError: the Job was deleted before it ended.
        JobFailedError: the Job failed; carries the end of its output.
    """
    batch_api = kubeclient.BatchV1Api(client)
    job_name = body["metadata"]["name"]

    await _delete_earlier_job(batch_api, namespace, job_name, on_delete)
    try:
        await batch_api.create_namespaced_job(
            body=body, namespace=namespace, pretty="pretty"
        )
    except ApiException as exc:
        if exc.status == status.HTTP_409_CONFLICT:
            raise JobAlreadyExistsError(
                f"Job {job_name} already exists in namespace {namespace}: it was created "
                "after Styrmin deleted the Job of an earlier run. Another action may be "
                "running for this deployment."
            ) from exc
        raise

    # Wait for the job to complete
    while True:
        try:
            job = await batch_api.read_namespaced_job_status(
                name=job_name, namespace=namespace
            )
        except ApiException as exc:
            if exc.status == status.HTTP_404_NOT_FOUND:
                raise JobDeletedError(
                    f"Job {job_name} in namespace {namespace} was deleted before it "
                    "ended, so the result of its commands is not known. Something other "
                    "than this action deleted it, such as another change of this "
                    "deployment or a kubectl command. Request the change again."
                ) from exc
            raise
        if job.status.succeeded:
            # Job completed successfully
            break
        if job.status.failed:
            raise await _job_failed_error(
                namespace, job_name, _first_container(body), client
            )
        await asyncio.sleep(5)  # Poll every 5 seconds
