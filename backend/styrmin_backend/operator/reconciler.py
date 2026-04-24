"""Core reconciliation logic for the operator.

Compares desired vs actual resource state and applies creates, updates,
and deletes to bring the cluster into the desired state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_resource,
)
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_IN_PROGRESS,
    BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS,
    HELMRELEASE_GROUP,
    HELMRELEASE_PLURAL,
    HELMRELEASE_VERSION,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
    LABEL_OPERATOR_MANAGED,
    LABEL_OPERATOR_MANAGED_VALUE,
    LABEL_RELEASE_REFERENCE,
)

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    """Result of a reconciliation operation."""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def total_actions(self) -> int:
        return self.created + self.updated + self.deleted


def compute_backoff_delay(attempt: int) -> float:
    """Compute exponential backoff delay with a cap.

    Args:
        attempt: The retry attempt number (0-indexed).

    Returns:
        Delay in seconds, capped at BACKOFF_MAX_SECONDS.
    """
    delay = min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_MAX_SECONDS)
    return float(delay)


def _resource_key(resource: dict[str, Any]) -> str:
    """Build a unique key for a resource: kind/name."""
    return f"{resource.get('kind', '')}/{resource.get('metadata', {}).get('name', '')}"


def _normalize_for_comparison(resource: dict[str, Any]) -> dict[str, Any]:
    """Normalize a resource dict for comparison by extracting key fields.

    Strips metadata fields that Kubernetes adds (uid, resourceVersion, etc.)
    and focuses on the spec and kind/name.
    """
    return {
        "kind": resource.get("kind"),
        "metadata": {
            "name": resource.get("metadata", {}).get("name"),
            "namespace": resource.get("metadata", {}).get("namespace"),
        },
        "spec": resource.get("spec"),
    }


def _ensure_resource_type_metadata(
    resource: dict[str, Any],
    *,
    kind: str,
    api_version: str,
) -> dict[str, Any]:
    """Ensure serialized resources retain kind and apiVersion metadata."""
    payload = dict(resource)
    if not payload.get("kind"):
        payload["kind"] = kind
    if not payload.get("apiVersion"):
        payload["apiVersion"] = api_version
    return payload


def compute_diff(
    desired: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute the diff between desired and actual resource sets.

    Args:
        desired: The desired resource specifications.
        actual: The actual resources currently in the cluster.

    Returns:
        Tuple of (to_create, to_update, to_delete) resource lists.
    """
    desired_by_key = {_resource_key(r): r for r in desired}
    actual_by_key = {_resource_key(r): r for r in actual}

    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    to_delete: list[dict[str, Any]] = []

    # Resources in desired but not in actual -> create
    # Resources in both -> compare, update if different
    for key, desired_resource in desired_by_key.items():
        if key not in actual_by_key:
            to_create.append(desired_resource)
        else:
            actual_resource = actual_by_key[key]
            if _normalize_for_comparison(desired_resource) != _normalize_for_comparison(
                actual_resource
            ):
                to_update.append(desired_resource)

    # Resources in actual but not in desired -> delete
    for key, actual_resource in actual_by_key.items():
        if key not in desired_by_key:
            to_delete.append(actual_resource)

    return to_create, to_update, to_delete


async def delete_kubernetes_resource(
    resource: dict[str, Any],
    namespace: str,
) -> None:
    """Delete a Kubernetes resource by kind and name.

    Uses kubernetes_asyncio directly since the primitives module doesn't
    have a generic delete function.
    """
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    kind = resource.get("kind", "")
    name = resource.get("metadata", {}).get("name", "")
    api_version = resource.get("apiVersion", "")

    async with get_kubernetes_client() as client:
        try:
            if kind == "NetworkPolicy":
                networking_api = kubeclient.NetworkingV1Api(client)
                await networking_api.delete_namespaced_network_policy(
                    name=name, namespace=namespace
                )
            elif kind == "Service":
                core_api = kubeclient.CoreV1Api(client)
                await core_api.delete_namespaced_service(name=name, namespace=namespace)
            elif kind == "Secret":
                core_api = kubeclient.CoreV1Api(client)
                await core_api.delete_namespaced_secret(name=name, namespace=namespace)
            elif "/" in api_version:
                # CRD resource (e.g., Middleware)
                group, version = api_version.rsplit("/", 1)
                custom_api = kubeclient.CustomObjectsApi(client)
                await custom_api.delete_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=kind.lower() + "s",
                    name=name,
                )
            else:
                logger.warning("Cannot delete unsupported resource kind: %s", kind)
        except ApiException as exc:
            if exc.status == 404:
                logger.debug("Resource %s/%s already deleted", kind, name)
            else:
                raise


async def reconcile_resources(
    *,
    namespace: str,
    to_create: list[dict[str, Any]],
    to_update: list[dict[str, Any]],
    to_delete: list[dict[str, Any]],
) -> ReconcileResult:
    """Apply reconciliation actions to bring cluster state to desired state.

    Creates, updates, and deletes resources as needed. Collects errors
    without raising so partial reconciliation can succeed.

    Args:
        namespace: Target namespace.
        to_create: Resources to create.
        to_update: Resources to update (replace).
        to_delete: Resources to delete.

    Returns:
        ReconcileResult with counts and any errors.
    """
    result = ReconcileResult()

    for resource in to_create:
        key = _resource_key(resource)
        try:
            await apply_kubernetes_resource(resource=resource, namespace=namespace)
            result.created += 1
            logger.info("Created %s in %s", key, namespace)
        except Exception as exc:
            error_msg = f"Failed to create {key}: {exc}"
            result.errors.append(error_msg)
            logger.error(error_msg)

    for resource in to_update:
        key = _resource_key(resource)
        try:
            await apply_kubernetes_resource(resource=resource, namespace=namespace)
            result.updated += 1
            logger.info("Updated %s in %s", key, namespace)
        except Exception as exc:
            error_msg = f"Failed to update {key}: {exc}"
            result.errors.append(error_msg)
            logger.error(error_msg)

    for resource in to_delete:
        key = _resource_key(resource)
        try:
            await delete_kubernetes_resource(resource=resource, namespace=namespace)
            result.deleted += 1
            logger.info("Deleted %s from %s", key, namespace)
        except Exception as exc:
            error_msg = f"Failed to delete {key}: {exc}"
            result.errors.append(error_msg)
            logger.error(error_msg)

    return result


async def is_deployment_in_progress(namespace: str, helmrelease_name: str) -> bool:
    """Check if a deployment operation is in progress on a HelmRelease.

    Reads the deployment-in-progress annotation to determine if the
    operator should defer reconciliation.
    """
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            custom_api = kubeclient.CustomObjectsApi(client)
            hr = await custom_api.get_namespaced_custom_object(
                group=HELMRELEASE_GROUP,
                version=HELMRELEASE_VERSION,
                namespace=namespace,
                plural=HELMRELEASE_PLURAL,
                name=helmrelease_name,
            )
            annotations = hr.get("metadata", {}).get("annotations", {})
            return annotations.get(ANNOTATION_DEPLOYMENT_IN_PROGRESS) == "true"
    except Exception:
        return False


async def list_managed_resources(
    namespace: str,
    release_reference: str,
    kind: str | None = None,
    operator_managed_only: bool = False,
) -> list[dict[str, Any]]:
    """List Kubernetes resources managed by Styrmin for a given deployment.

    Args:
        namespace: Target namespace.
        release_reference: The release reference label value.
        kind: Optional filter by resource kind (e.g., "NetworkPolicy").
        operator_managed_only: If True, only return resources with the
            operator-managed label.

    Returns:
        List of resource dicts from the cluster.
    """
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    label_parts = [
        f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        f"{LABEL_RELEASE_REFERENCE}={release_reference}",
    ]
    if operator_managed_only:
        label_parts.append(f"{LABEL_OPERATOR_MANAGED}={LABEL_OPERATOR_MANAGED_VALUE}")
    label_selector = ",".join(label_parts)

    resources: list[dict[str, Any]] = []

    async with get_kubernetes_client() as client:
        if kind is None or kind == "NetworkPolicy":
            try:
                networking_api = kubeclient.NetworkingV1Api(client)
                result = await networking_api.list_namespaced_network_policy(
                    namespace=namespace, label_selector=label_selector
                )
                for item in result.items:
                    resources.append(
                        _ensure_resource_type_metadata(
                            client.sanitize_for_serialization(item),
                            kind="NetworkPolicy",
                            api_version="networking.k8s.io/v1",
                        )
                    )
            except Exception:
                logger.exception("Failed to list NetworkPolicies in %s", namespace)

        if kind is None or kind == "Service":
            try:
                core_api = kubeclient.CoreV1Api(client)
                result = await core_api.list_namespaced_service(
                    namespace=namespace, label_selector=label_selector
                )
                for item in result.items:
                    resources.append(
                        _ensure_resource_type_metadata(
                            client.sanitize_for_serialization(item),
                            kind="Service",
                            api_version="v1",
                        )
                    )
            except Exception:
                logger.exception("Failed to list Services in %s", namespace)

        if kind is None or kind == "Secret":
            try:
                core_api = kubeclient.CoreV1Api(client)
                result = await core_api.list_namespaced_secret(
                    namespace=namespace, label_selector=label_selector
                )
                for item in result.items:
                    resources.append(
                        _ensure_resource_type_metadata(
                            client.sanitize_for_serialization(item),
                            kind="Secret",
                            api_version="v1",
                        )
                    )
            except Exception:
                logger.exception("Failed to list Secrets in %s", namespace)

    return resources


async def _check_helmrelease_ready(
    namespace: str,
    release_reference: str,
) -> bool:
    """Check if a HelmRelease has reached Ready state via FluxCD.

    Returns True if the HelmRelease has a Ready=True condition.
    """
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            custom_api = kubeclient.CustomObjectsApi(client)
            hr = await custom_api.get_namespaced_custom_object(
                group=HELMRELEASE_GROUP,
                version=HELMRELEASE_VERSION,
                namespace=namespace,
                plural=HELMRELEASE_PLURAL,
                name=release_reference,
            )
            status = hr.get("status", {})
            conditions = status.get("conditions", [])
            for condition in conditions:
                if (
                    condition.get("type") == "Ready"
                    and condition.get("status") == "True"
                ):
                    return True
    except ApiException as exc:
        if exc.status == 404:
            logger.debug("HelmRelease %s not found in %s", release_reference, namespace)
        else:
            logger.exception("Failed to check HelmRelease %s status", release_reference)
    except Exception:
        logger.exception("Failed to check HelmRelease %s status", release_reference)
    return False


async def _check_any_pod_ready(namespace: str) -> bool:
    """Check if at least one pod in the namespace is Running and Ready.

    Returns True as soon as any single pod has all containers ready.
    Used as a fallback readiness check for internal deployments (typically
    single-replica) where the HelmRelease may not reach Ready=True
    (e.g., LoadBalancer pending in vCluster).
    """
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            core_api = kubeclient.CoreV1Api(client)
            pods = await core_api.list_namespaced_pod(namespace=namespace)
            for pod in pods.items:
                if pod.status and pod.status.phase == "Running":
                    container_statuses = pod.status.container_statuses or []
                    if container_statuses and all(
                        cs.ready for cs in container_statuses
                    ):
                        return True
    except Exception:
        logger.exception("Failed to check pod readiness in %s", namespace)
    return False


async def cleanup_operator_resources(
    namespace: str,
    release_reference: str,
) -> None:
    """Delete all operator-created resources for a deployment.

    Called when a HelmRelease is deleted to clean up associated
    NetworkPolicies created by the operator.
    """
    resources = await list_managed_resources(
        namespace=namespace,
        release_reference=release_reference,
        operator_managed_only=True,
    )
    for resource in resources:
        key = _resource_key(resource)
        try:
            await delete_kubernetes_resource(resource=resource, namespace=namespace)
            logger.info("Cleaned up %s from %s", key, namespace)
        except Exception:
            logger.exception("Failed to clean up %s from %s", key, namespace)
