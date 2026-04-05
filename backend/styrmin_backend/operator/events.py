"""Kubernetes Event emission for operator status reporting.

Emits Events on HelmRelease resources to report reconciliation status,
visible via `kubectl describe helmrelease/<name>`.
"""

from __future__ import annotations

import datetime
import logging

from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client.api_client import ApiClient

from styrmin_backend.operator.config import (
    EVENT_DRIFT_DETECTED,
    EVENT_RECONCILE_FAILED,
    EVENT_RECONCILE_SUCCEEDED,
)

logger = logging.getLogger(__name__)

_EVENT_SOURCE_COMPONENT = "styrmin-operator"


async def _emit_event(
    *,
    api_client: ApiClient,
    namespace: str,
    helmrelease_name: str,
    reason: str,
    message: str,
    event_type: str,
) -> None:
    """Emit a Kubernetes Event on a HelmRelease resource.

    Args:
        api_client: Kubernetes API client.
        namespace: Namespace of the HelmRelease.
        helmrelease_name: Name of the HelmRelease resource.
        reason: Event reason (e.g., ReconcileSucceeded).
        message: Human-readable event message.
        event_type: "Normal" or "Warning".
    """
    core_api = kubeclient.CoreV1Api(api_client)
    now = datetime.datetime.now(tz=datetime.UTC)

    event = kubeclient.CoreV1Event(
        metadata=kubeclient.V1ObjectMeta(
            generate_name=f"{helmrelease_name}.",
            namespace=namespace,
        ),
        involved_object=kubeclient.V1ObjectReference(
            api_version="helm.toolkit.fluxcd.io/v2",
            kind="HelmRelease",
            name=helmrelease_name,
            namespace=namespace,
        ),
        reason=reason,
        message=message,
        type=event_type,
        first_timestamp=now,
        last_timestamp=now,
        source=kubeclient.V1EventSource(component=_EVENT_SOURCE_COMPONENT),
        reporting_component=_EVENT_SOURCE_COMPONENT,
        action=reason,
    )

    try:
        await core_api.create_namespaced_event(namespace=namespace, body=event)
    except Exception:
        logger.exception(
            "Failed to emit %s event for HelmRelease %s/%s",
            reason,
            namespace,
            helmrelease_name,
        )


async def emit_reconcile_succeeded(
    api_client: ApiClient,
    namespace: str,
    helmrelease_name: str,
    release_reference: str,
) -> None:
    """Emit a ReconcileSucceeded event."""
    await _emit_event(
        api_client=api_client,
        namespace=namespace,
        helmrelease_name=helmrelease_name,
        reason=EVENT_RECONCILE_SUCCEEDED,
        message=f"All utility resources in sync for deployment {release_reference}",
        event_type="Normal",
    )


async def emit_drift_detected(
    api_client: ApiClient,
    namespace: str,
    helmrelease_name: str,
    resource_kind: str,
    resource_name: str,
    change_type: str,
) -> None:
    """Emit a DriftDetected event."""
    await _emit_event(
        api_client=api_client,
        namespace=namespace,
        helmrelease_name=helmrelease_name,
        reason=EVENT_DRIFT_DETECTED,
        message=f"Drift detected on {resource_kind}/{resource_name}: {change_type}",
        event_type="Normal",
    )


async def emit_reconcile_failed(
    api_client: ApiClient,
    namespace: str,
    helmrelease_name: str,
    resource_kind: str,
    resource_name: str,
    error_message: str,
) -> None:
    """Emit a ReconcileFailed event."""
    await _emit_event(
        api_client=api_client,
        namespace=namespace,
        helmrelease_name=helmrelease_name,
        reason=EVENT_RECONCILE_FAILED,
        message=f"Failed to reconcile {resource_kind}/{resource_name}: {error_message}",
        event_type="Warning",
    )
