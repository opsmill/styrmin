"""Core reconciliation logic for the operator.

Compares desired vs actual resource state and applies creates, updates,
and deletes to bring the cluster into the desired state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
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
from styrmin_backend.services.component_container.exceptions import (
    parse_guard_failure,
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


async def _get_helmrelease(
    namespace: str,
    release_reference: str,
) -> dict[str, Any] | None:
    """GET a HelmRelease, or ``None`` when it is missing or unreadable."""
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            custom_api = kubeclient.CustomObjectsApi(client)
            return await custom_api.get_namespaced_custom_object(
                group=HELMRELEASE_GROUP,
                version=HELMRELEASE_VERSION,
                namespace=namespace,
                plural=HELMRELEASE_PLURAL,
                name=release_reference,
            )
    except ApiException as exc:
        if exc.status == 404:
            logger.debug("HelmRelease %s not found in %s", release_reference, namespace)
        else:
            logger.exception("Failed to check HelmRelease %s status", release_reference)
    except Exception:
        logger.exception("Failed to check HelmRelease %s status", release_reference)
    return None


# FluxCD's Warning events for an install or upgrade that failed.
_RELEASE_FAILURE_REASONS = frozenset({"InstallFailed", "UpgradeFailed"})


async def _list_release_failure_events(
    namespace: str,
    release_reference: str,
) -> list[dict[str, Any]]:
    """LIST FluxCD's install and upgrade failure Events of a HelmRelease; empty when unreadable."""
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    selector = (
        "involvedObject.kind=HelmRelease,"
        f"involvedObject.name={release_reference},type=Warning"
    )
    try:
        async with get_kubernetes_client() as client:
            core_api = kubeclient.CoreV1Api(client)
            events = await core_api.list_namespaced_event(
                namespace=namespace, field_selector=selector
            )
            items = client.sanitize_for_serialization(events).get("items") or []
    except Exception:
        logger.exception("Failed to list Events of HelmRelease %s", release_reference)
        return []
    return [item for item in items if item.get("reason") in _RELEASE_FAILURE_REASONS]


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class FluxEvent:
    """A FluxCD Warning event of a failed install or upgrade."""

    reason: str
    message: str
    time: datetime

    @classmethod
    def from_dict(cls, event: dict[str, Any]) -> FluxEvent | None:
        time = next(
            (
                parsed
                for value in (
                    (event.get("series") or {}).get("lastObservedTime"),
                    event.get("lastTimestamp"),
                    event.get("eventTime"),
                    event.get("firstTimestamp"),
                    (event.get("metadata") or {}).get("creationTimestamp"),
                )
                if (parsed := _parse_time(value)) is not None
            ),
            None,
        )
        if time is None:
            return None
        # FluxCD appends the last Helm log lines after a blank line.
        message = str(event.get("message") or "").split("\n\n", 1)[0].strip()
        return cls(reason=str(event.get("reason") or ""), message=message, time=time)


@dataclass(frozen=True)
class FluxCondition:
    """One FluxCD condition of a HelmRelease."""

    status: str
    reason: str
    message: str
    last_transition_time: str

    @classmethod
    def from_dict(cls, condition: dict[str, Any]) -> FluxCondition:
        return cls(
            status=str(condition.get("status") or ""),
            reason=str(condition.get("reason") or ""),
            message=str(condition.get("message") or ""),
            last_transition_time=str(condition.get("lastTransitionTime") or ""),
        )

    @property
    def is_true(self) -> bool:
        return self.status == "True"


@dataclass(frozen=True)
class HelmReleaseObservation:
    """FluxCD's conditions for the HelmRelease's current generation (spec 019, research D5).

    A field is ``None`` when FluxCD has no such condition for ``metadata.generation``.
    ``rolled_back_version`` is the failed release that the newest release rolled back.
    """

    ready: FluxCondition | None = None
    released: FluxCondition | None = None
    remediated: FluxCondition | None = None
    stalled: FluxCondition | None = None
    guard_failure: tuple[str, str] | None = None
    rolled_back_version: int | None = None
    skipped_failure: FluxEvent | None = None

    @property
    def is_ready(self) -> bool:
        return self.ready is not None and self.ready.is_true

    @property
    def is_ready_after_rollback(self) -> bool:
        """FluxCD reports Ready, but the release that runs is its rollback of this generation's failure.

        After a rollback, FluxCD compares only the chart and the values with the current
        generation, so it reports a change of post-renderers alone Ready although it was never
        applied.
        """
        return self.is_ready and self.rolled_back_version is not None

    @property
    def failure(self) -> FluxCondition | None:
        """Why the current generation is not Ready: the failed install or upgrade, else ``Ready=False``.

        After a rollback ``Ready`` repeats the remediation, so ``Released=False`` names the cause.
        """
        if self.ready is None or self.ready.status != "False":
            return None
        if self.released is not None and self.released.status == "False":
            return self.released
        return self.ready


def _is_current_generation(
    condition: dict[str, Any], generation: object, status: dict[str, Any]
) -> bool:
    """True when ``condition``'s ``observedGeneration``, else ``status.lastAttemptedGeneration``, is ``generation``."""
    observed = condition.get("observedGeneration")
    if observed is None:
        observed = status.get("lastAttemptedGeneration")
    return generation is not None and observed == generation


def _current_generation_conditions(helmrelease: dict[str, Any]) -> list[dict[str, Any]]:
    generation = (helmrelease.get("metadata") or {}).get("generation")
    status = helmrelease.get("status") or {}
    return [
        condition
        for condition in status.get("conditions") or []
        if _is_current_generation(condition, generation, status)
    ]


def _helmrelease_guard_failure(
    helmrelease: dict[str, Any], skipped_failure: FluxEvent | None = None
) -> tuple[str, str] | None:
    """Return ``(component, container)`` when the HelmRelease's current generation failed on the guard.

    Ready must not be True, and the guard key must be in the message of a condition observed for
    ``metadata.generation`` (its ``observedGeneration``, else ``status.lastAttemptedGeneration``).
    When FluxCD reports Ready after it skipped the failure, the guard key is read from the
    failure's event.
    """
    if skipped_failure is not None:
        return parse_guard_failure(skipped_failure.message)
    conditions = (helmrelease.get("status") or {}).get("conditions") or []
    if any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in conditions
    ):
        return None
    for condition in _current_generation_conditions(helmrelease):
        failure = parse_guard_failure(condition.get("message") or "")
        if failure is not None:
            return failure
    return None


def _snapshot_version(snapshot: dict[str, Any]) -> int:
    version = snapshot.get("version")
    return version if isinstance(version, int) else -1


def _rolled_back_version(helmrelease: dict[str, Any]) -> int | None:
    """The version of the failed release that FluxCD's newest release rolled back, if it is one.

    With failures counted for the current generation, FluxCD remediates a failed release before
    it tries again, so a ``deployed`` release that directly follows a ``failed`` one is the
    rollback. FluxCD resets the failure counters for each new generation.
    """
    status = helmrelease.get("status") or {}
    if not (status.get("installFailures") or status.get("upgradeFailures")):
        return None
    history = sorted(status.get("history") or [], key=_snapshot_version, reverse=True)
    if len(history) < 2:
        return None
    newest, previous = history[0], history[1]
    failed = _snapshot_version(previous)
    if (
        newest.get("status") != "deployed"
        or previous.get("status") != "failed"
        or failed < 0
        or _snapshot_version(newest) != failed + 1
    ):
        return None
    return failed


def _may_have_skipped_failure(helmrelease: dict[str, Any]) -> bool:
    """FluxCD reports Ready for the current generation although it counted a failure for it.

    FluxCD resets ``status.failures`` for each new generation, and keeps it after a release that
    succeeds, so the failure events decide (see ``_skipped_failure``).
    """
    generation = (helmrelease.get("metadata") or {}).get("generation")
    status = helmrelease.get("status") or {}
    ready = next(
        (
            c
            for c in _current_generation_conditions(helmrelease)
            if c.get("type") == "Ready"
        ),
        None,
    )
    return (
        ready is not None
        and ready.get("status") == "True"
        and bool(status.get("failures"))
        and status.get("lastAttemptedGeneration") == generation
    )


def _newest_release_time(helmrelease: dict[str, Any]) -> datetime | None:
    times = [
        parsed
        for snapshot in (helmrelease.get("status") or {}).get("history") or []
        for value in (snapshot.get("lastDeployed"), snapshot.get("firstDeployed"))
        if (parsed := _parse_time(value)) is not None
    ]
    return max(times, default=None)


def _skipped_failure(
    helmrelease: dict[str, Any], events: list[dict[str, Any]]
) -> FluxEvent | None:
    """The failed install or upgrade of this generation that FluxCD then reported in sync.

    helm-controller v1.5.0 and later record the post-renderers digest after a failed attempt
    too. When the attempt stored no release (a post-render error, for example), the next
    reconcile compares only the chart and the values, finds the release in sync and reports
    ``Ready=True`` without retrying. The newest failure event is then newer than FluxCD's
    newest release.
    """
    if not _may_have_skipped_failure(helmrelease):
        return None
    failures = [e for e in map(FluxEvent.from_dict, events) if e is not None]
    if not failures:
        return None
    newest = max(failures, key=lambda event: event.time)
    released = _newest_release_time(helmrelease)
    if released is not None and newest.time <= released:
        return None
    return newest


def observe_helmrelease_conditions(
    helmrelease: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
) -> HelmReleaseObservation:
    """Read FluxCD's ``Ready``, ``Released``, ``Remediated=True`` and ``Stalled=True`` of the current generation.

    Also reads whether FluxCD's newest release is the rollback of a failed release, and, from
    FluxCD's failure ``events``, whether FluxCD reports Ready after it skipped a failure.
    """
    skipped_failure = _skipped_failure(helmrelease, events or [])
    current = {
        str(condition.get("type")): FluxCondition.from_dict(condition)
        for condition in _current_generation_conditions(helmrelease)
    }
    remediated = current.get("Remediated")
    stalled = current.get("Stalled")
    return HelmReleaseObservation(
        ready=current.get("Ready"),
        released=current.get("Released"),
        remediated=remediated
        if remediated is not None and remediated.is_true
        else None,
        stalled=stalled if stalled is not None and stalled.is_true else None,
        guard_failure=_helmrelease_guard_failure(helmrelease, skipped_failure),
        rolled_back_version=_rolled_back_version(helmrelease),
        skipped_failure=skipped_failure,
    )


async def _read_failure_events(
    namespace: str, release_reference: str, helmrelease: dict[str, Any]
) -> list[dict[str, Any]]:
    """FluxCD's failure events, read only when FluxCD may have skipped a failure."""
    if not _may_have_skipped_failure(helmrelease):
        return []
    return await _list_release_failure_events(
        namespace=namespace, release_reference=release_reference
    )


async def observe_helmrelease(
    namespace: str,
    release_reference: str,
) -> HelmReleaseObservation | None:
    """Read the HelmRelease once; ``None`` when it is missing or unreadable."""
    helmrelease = await _get_helmrelease(
        namespace=namespace, release_reference=release_reference
    )
    if helmrelease is None:
        return None
    events = await _read_failure_events(namespace, release_reference, helmrelease)
    return observe_helmrelease_conditions(helmrelease, events)


async def read_helmrelease_guard_failure(
    namespace: str,
    release_reference: str,
) -> tuple[str, str] | None:
    """Read the HelmRelease once and return its component-container guard failure, if any."""
    helmrelease = await _get_helmrelease(
        namespace=namespace, release_reference=release_reference
    )
    if helmrelease is None:
        return None
    events = await _read_failure_events(namespace, release_reference, helmrelease)
    return _helmrelease_guard_failure(
        helmrelease, _skipped_failure(helmrelease, events)
    )


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
