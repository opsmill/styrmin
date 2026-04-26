"""Post-velero recovery actions for the styrmin restore lifecycle.

Velero recreates a deployment's resources (namespace, StyrminDeployment CRD,
HelmRelease, etc.) but does not restore status subresources, and kopf will
not fire ``on.create`` for the restored CRD because velero re-applies the
``kopf.zalando.org/last-handled-configuration`` annotation. The styrmin
restore workflow therefore drives the post-restore lifecycle explicitly:

1. Strip kopf state-tracking annotations from the restored CRD.
2. Mark the CRD ``phase=Restoring`` so the operator's timer skips its
   readiness timeout while we reapply.
3. Re-apply Phase 1 prerequisites (NetworkPolicies + Secrets).
4. Verify the HelmRelease reaches Ready.
5. Re-apply Phase 3 utility resources (Middlewares + Services).
6. Mark the CRD ``phase=Ready / displayState=Running``.

Each step is idempotent (server-side apply for resources, JSON patch for
the CRD status).
"""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import ApiClient
from loguru import logger

from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION
from styrmin_backend.operator.crd.schema import (
    ConditionStatus,
    ConditionType,
    DeploymentPhase,
    DisplayState,
)
from styrmin_backend.operator.pipeline import (
    execute_phase_prerequisites,
    execute_phase_services,
)


# Kopf state-tracking annotations that velero restores along with the rest
# of the CRD metadata. Keeping them defeats kopf's create/resume detection,
# so the restore flow strips them post-velero.
_KOPF_STATE_ANNOTATIONS = (
    "kopf.zalando.org/last-handled-configuration",
    "kopf.zalando.org/touch-dummy",
)


async def _read_crd(api_client: ApiClient, namespace: str, name: str) -> dict[str, Any]:
    custom_api = k8s_client.CustomObjectsApi(api_client)
    return await custom_api.get_namespaced_custom_object(
        group=CRD_GROUP,
        version=CRD_VERSION,
        namespace=namespace,
        plural=CRD_PLURAL,
        name=name,
    )


async def _patch_crd_status(
    api_client: ApiClient, namespace: str, name: str, status: dict[str, Any]
) -> None:
    # kubernetes_asyncio's autodetect picks JSON-Patch (RFC 6902) for
    # custom-object PATCH calls, so an object body is rejected with
    # "cannot unmarshal object into []handlers.jsonPatchOp". Force
    # merge-patch — same workaround as
    # ``agent/service/kubernetes/primitives.py:apply_or_patch``.
    custom_api = k8s_client.CustomObjectsApi(api_client)
    await custom_api.patch_namespaced_custom_object_status(
        group=CRD_GROUP,
        version=CRD_VERSION,
        namespace=namespace,
        plural=CRD_PLURAL,
        name=name,
        body={"status": status},
        _content_type="application/merge-patch+json",  # type: ignore[call-arg]
    )


async def _strip_kopf_annotations(
    api_client: ApiClient, namespace: str, name: str
) -> None:
    """Remove kopf state-tracking annotations from the CRD.

    Uses a merge patch with ``null`` values, which is how the K8s API
    removes annotations. See ``_patch_crd_status`` for the
    ``_content_type`` workaround.
    """
    custom_api = k8s_client.CustomObjectsApi(api_client)
    body = {"metadata": {"annotations": {key: None for key in _KOPF_STATE_ANNOTATIONS}}}
    await custom_api.patch_namespaced_custom_object(
        group=CRD_GROUP,
        version=CRD_VERSION,
        namespace=namespace,
        plural=CRD_PLURAL,
        name=name,
        body=body,
        _content_type="application/merge-patch+json",  # type: ignore[call-arg]
    )


async def mark_restoring(api_client: ApiClient, namespace: str, name: str) -> None:
    """Patch the CRD to indicate the styrmin restore flow is in control.

    The operator's timer reads ``phase`` and skips both the 300 s readiness
    timeout and phase advancement when it sees ``Restoring``. Setting this
    immediately after velero finishes prevents the timer from racing the
    reapply step and tripping displayState=Error.
    """
    await _patch_crd_status(
        api_client,
        namespace,
        name,
        {
            "phase": DeploymentPhase.RESTORING.value,
            "displayState": DisplayState.RESTORING.value,
            "message": "Restoring from backup",
        },
    )


async def reapply_and_finalize(
    api_client: ApiClient, namespace: str, name: str
) -> None:
    """Re-apply prerequisites + utility resources, then transition to Ready.

    Caller is responsible for catching exceptions and translating to the
    failure path (``mark_failed``) — this function lets exceptions
    propagate so the workflow can record the precise failure point.
    """
    crd = await _read_crd(api_client, namespace, name)
    crd_spec = crd.get("spec", {})

    await _strip_kopf_annotations(api_client, namespace, name)

    prerequisites = await execute_phase_prerequisites(
        crd_spec=crd_spec, namespace=namespace
    )
    if not prerequisites.success:
        raise RuntimeError(
            f"Failed to re-apply prerequisites after restore: {prerequisites.errors}"
        )

    services = await execute_phase_services(crd_spec=crd_spec, namespace=namespace)
    if not services.success:
        raise RuntimeError(
            f"Failed to re-apply utility resources after restore: {services.errors}"
        )

    conditions = [
        {
            "type": ConditionType.NETWORK_POLICIES_READY.value,
            "status": ConditionStatus.TRUE.value,
            "reason": "RestoreReapplied",
            "message": "Prerequisites re-applied after restore",
        },
        {
            "type": ConditionType.SECRETS_READY.value,
            "status": ConditionStatus.TRUE.value,
            "reason": "RestoreReapplied",
            "message": "Prerequisites re-applied after restore",
        },
        {
            "type": ConditionType.SERVICES_READY.value,
            "status": ConditionStatus.TRUE.value,
            "reason": "RestoreReapplied",
            "message": "Utility resources re-applied after restore",
        },
        {
            "type": ConditionType.MIDDLEWARES_READY.value,
            "status": ConditionStatus.TRUE.value,
            "reason": "RestoreReapplied",
            "message": "Utility resources re-applied after restore",
        },
        {
            "type": ConditionType.READY.value,
            "status": ConditionStatus.TRUE.value,
            "reason": "RestoreCompleted",
            "message": "Deployment restored from backup",
        },
    ]
    await _patch_crd_status(
        api_client,
        namespace,
        name,
        {
            "phase": DeploymentPhase.READY.value,
            "displayState": DisplayState.RUNNING.value,
            "message": "Restored from backup",
            "conditions": conditions,
        },
    )
    logger.info("Restore lifecycle complete for %s/%s", namespace, name)


async def mark_failed(
    api_client: ApiClient, namespace: str, name: str, message: str
) -> None:
    """Mark the CRD as failed after a restore error.

    Used both for velero failures and for failures during the post-restore
    reapply step. The message should distinguish the two so the operator
    can diagnose without diffing the workflow log.
    """
    try:
        await _patch_crd_status(
            api_client,
            namespace,
            name,
            {
                "phase": DeploymentPhase.FAILED.value,
                "displayState": DisplayState.ERROR.value,
                "message": message,
            },
        )
    except Exception as exc:
        # The CRD itself may not exist if velero never recreated it. Log
        # and let the workflow's DB-side failure handling take over — the
        # restore record + deployment.status carry the failure signal.
        logger.warning(
            "Could not patch CRD %s/%s after restore failure: %s",
            namespace,
            name,
            exc,
        )
