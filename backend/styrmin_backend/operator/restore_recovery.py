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

    Note: we deliberately do NOT strip kopf state-tracking annotations
    here. The restored CRD carries a ``last-handled-configuration``
    annotation from before the backup, which makes kopf treat it as
    already-handled — which is exactly what we want, because this
    function does the work ``on.create`` would have done. Stripping the
    annotation would trigger kopf to fire ``on.create`` after we set
    ``displayState=Running``, which then resets it back to ``Deploying``
    and the deployment ends up oscillating.
    """
    crd = await _read_crd(api_client, namespace, name)
    crd_spec = crd.get("spec", {})
    await _reapply_phases_and_finalize(api_client, namespace, name, crd_spec)


async def _reapply_phases_and_finalize(
    api_client: ApiClient, namespace: str, name: str, crd_spec: dict[str, Any]
) -> None:
    """Run the prerequisite + utility phases for ``crd_spec``, then mark Ready.

    Shared by the in-place recovery path (``reapply_and_finalize``, whose
    spec comes from the restored CR) and the cross-target one
    (``reapply_with_counterpart_identity``, whose spec comes from the
    counterpart's own CR body).
    """
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


async def _upsert_crd(
    api_client: ApiClient, namespace: str, body: dict[str, Any]
) -> None:
    """Create the CR, falling back to a merge patch when it already exists."""
    custom_api = k8s_client.CustomObjectsApi(api_client)
    try:
        await custom_api.create_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            body=body,
        )
    except k8s_client.ApiException as exc:
        if exc.status != 409:
            raise
        await custom_api.patch_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=body["metadata"]["name"],
            body=body,
            _content_type="application/merge-patch+json",  # type: ignore[call-arg]
        )


async def _delete_crd(api_client: ApiClient, namespace: str, name: str) -> None:
    """Delete a CR, tolerating a CR that is already gone."""
    custom_api = k8s_client.CustomObjectsApi(api_client)
    try:
        await custom_api.delete_namespaced_custom_object(
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
            plural=CRD_PLURAL,
            name=name,
        )
    except k8s_client.ApiException as exc:
        if exc.status != 404:
            raise


async def reapply_with_counterpart_identity(
    api_client: ApiClient,
    namespace: str,
    restored_crd_name: str,
    counterpart_crd_body: dict[str, Any],
) -> None:
    """Swap a cross-target restore's CR to the counterpart's identity, then finalize.

    A cross-target restore (environment clone) rides Velero's
    ``namespaceMapping``: the *data* lands in the counterpart's namespace, but
    every restored object keeps its source name — including the
    ``StyrminDeployment`` CR, whose spec still carries the source's
    ``deploymentId``, ``instanceId``, ``releaseReference`` and full resolved
    context (FQDNs embed the source deployment id and environment name). Left
    as-is, the counterpart's namespace would be reconciled forever under the
    source's identity (research D2.4).

    Steps, in order:

    1. Apply the counterpart's own CR body into the restored namespace,
       carrying over kopf's state-tracking annotations from the restored CR.
       Carrying them is deliberate and mirrors ``reapply_and_finalize``: a CR
       without ``last-handled-configuration`` makes kopf fire ``on.create``,
       which would race — and then undo — the finalize below.
    2. Delete the restored source-named CR, so exactly one
       ``StyrminDeployment`` owns the namespace. Data (PVC contents) survives;
       only identity objects are re-rendered.
    3. Re-apply prerequisites + utility resources from the **counterpart's**
       spec and mark the counterpart CR Ready — the same finalize the in-place
       path performs.

    Caller is responsible for catching exceptions and translating to
    ``mark_failed`` (same contract as ``reapply_and_finalize``).
    """
    counterpart_name = counterpart_crd_body.get("metadata", {}).get("name")
    if not counterpart_name:
        raise RuntimeError(
            "Cross-target restore recovery requires a named counterpart CR body"
        )

    restored_crd = await _read_crd(api_client, namespace, restored_crd_name)
    inherited_annotations = {
        key: value
        for key, value in (
            (restored_crd.get("metadata") or {}).get("annotations") or {}
        ).items()
        if key in _KOPF_STATE_ANNOTATIONS
    }

    body = {
        **counterpart_crd_body,
        "metadata": {
            **counterpart_crd_body.get("metadata", {}),
            "namespace": namespace,
            "annotations": {
                **(counterpart_crd_body.get("metadata", {}).get("annotations") or {}),
                **inherited_annotations,
            },
        },
    }
    await _upsert_crd(api_client, namespace, body)
    logger.info(
        "Applied counterpart StyrminDeployment %s/%s over restored CR %s",
        namespace,
        counterpart_name,
        restored_crd_name,
    )

    if counterpart_name != restored_crd_name:
        await _delete_crd(api_client, namespace, restored_crd_name)
        logger.info(
            "Deleted restored source-named StyrminDeployment %s/%s",
            namespace,
            restored_crd_name,
        )

    await _reapply_phases_and_finalize(
        api_client, namespace, counterpart_name, counterpart_crd_body.get("spec", {})
    )


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
