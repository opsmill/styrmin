"""Post-velero recovery actions for the styrmin restore lifecycle.

Velero recreates a deployment's resources (namespace, StyrminDeployment CRD,
HelmRelease, etc.) but does not restore status subresources, and kopf will
not fire ``on.create`` for the restored CRD because velero re-applies the
``kopf.zalando.org/last-handled-configuration`` annotation. The styrmin
restore workflow therefore drives the post-restore lifecycle explicitly:

1. Mark the CRD ``phase=Restoring`` so the operator's timer skips its
   readiness timeout while we reapply.
2. Re-apply Phase 1 prerequisites (NetworkPolicies + Secrets).
3. Re-apply Phase 3 utility resources (Middlewares + Services).
4. Mark the CRD ``phase=Ready / displayState=Running``.

The kopf state annotations are deliberately **kept** — see
``reapply_and_finalize`` for why stripping them makes the deployment
oscillate.

A cross-target restore (environment clone) takes the same route through
``reapply_with_counterpart_identity``, with two additions: the restored
source-named CR is replaced by the counterpart's own CR body, and Phase 2
(HelmRelease) is re-rendered from the counterpart's spec.

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
    execute_phase_helmrelease,
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
    api_client: ApiClient,
    namespace: str,
    name: str,
    crd_spec: dict[str, Any],
    include_helmrelease: bool = False,
) -> None:
    """Run the prerequisite + utility phases for ``crd_spec``, then mark Ready.

    Shared by the in-place recovery path (``reapply_and_finalize``, whose
    spec comes from the restored CR) and the cross-target one
    (``reapply_with_counterpart_identity``, whose spec comes from the
    counterpart's own CR body).

    ``include_helmrelease`` inserts pipeline phase 2 between the prerequisites
    and the utility resources, in the operator's own phase order. The in-place
    path leaves it off — the restored HelmRelease already carries the identity
    it should — while the cross-target path needs it: the restored HelmRelease
    was rendered from the **source's** context (source FQDNs, source ingress
    hosts), so without re-rendering it from the counterpart's spec the cloned
    namespace would keep serving the source's identity (010 research D2.4).
    """
    prerequisites = await execute_phase_prerequisites(
        crd_spec=crd_spec, namespace=namespace
    )
    if not prerequisites.success:
        raise RuntimeError(
            f"Failed to re-apply prerequisites after restore: {prerequisites.errors}"
        )

    if include_helmrelease:
        helmrelease = await execute_phase_helmrelease(
            crd_spec=crd_spec, namespace=namespace
        )
        if not helmrelease.success:
            raise RuntimeError(
                "Failed to re-render the HelmRelease with counterpart identity: "
                f"{helmrelease.errors}"
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


async def _clear_finalizers(api_client: ApiClient, namespace: str, name: str) -> None:
    """Drop every finalizer from a CR so deleting it runs no delete handler.

    This is what makes deleting the restored source-named CR safe. That CR
    arrives from Velero with kopf's finalizer intact, and kopf only runs
    ``@kopf.on.delete`` — which for a ``StyrminDeployment`` is
    ``_teardown_owned_resources``: it deletes the HelmRelease named by
    ``spec.releaseReference`` plus every resource labelled with it. In a
    cross-target restore that HelmRelease is the one Flux uses to keep the
    **counterpart's** chart alive, so letting the handler fire would have Flux
    uninstall the release and take the just-restored PersistentVolumeClaims
    with it. Without a finalizer the API server removes the object outright and
    the handler never gets the chance.
    """
    custom_api = k8s_client.CustomObjectsApi(api_client)
    await custom_api.patch_namespaced_custom_object(
        group=CRD_GROUP,
        version=CRD_VERSION,
        namespace=namespace,
        plural=CRD_PLURAL,
        name=name,
        body={"metadata": {"finalizers": []}},
        # See ``_patch_crd_status`` for why the content type is forced.
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


async def _delete_restored_crd_without_teardown(
    api_client: ApiClient, namespace: str, name: str
) -> None:
    """Remove the restored source-named CR without triggering kopf's teardown.

    Finalizers are cleared first and the result is **verified** before the
    delete: a delete that still had kopf's finalizer attached would run
    ``_teardown_owned_resources`` against the counterpart's live HelmRelease
    and destroy the restored data. Refusing to delete is the safe failure —
    the caller turns it into a failed restore, which is recoverable by
    discarding the cloned environment; data loss is not.
    """
    try:
        await _clear_finalizers(api_client, namespace, name)
    except k8s_client.ApiException as exc:
        if exc.status == 404:
            return
        raise

    try:
        remaining = (await _read_crd(api_client, namespace, name)).get(
            "metadata", {}
        ).get("finalizers") or []
    except k8s_client.ApiException as exc:
        if exc.status == 404:
            # Nothing left to delete: no finalizers means the clear itself
            # completed a deletion that was already pending.
            return
        raise

    if remaining:
        raise RuntimeError(
            f"Refusing to delete restored StyrminDeployment {namespace}/{name}: "
            f"finalizers are still attached ({remaining}), and deleting it would "
            "run the operator's teardown against the counterpart's Helm release"
        )

    await _delete_crd(api_client, namespace, name)


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
       which would race — and then undo — the finalize below. kopf **will**
       still see a spec diff against the inherited annotation and fire
       ``on.update``; that handler re-runs exactly the phases below against the
       same counterpart spec, so it is idempotent rather than harmful (its
       ``displayState`` bounce is settled by the operator's timer).
    2. Delete the restored source-named CR — finalizers first, so kopf's
       ``on.delete`` teardown never fires (see
       ``_delete_restored_crd_without_teardown``: that teardown would delete
       the counterpart's own HelmRelease and, through Flux, the restored
       volumes). Data survives; only identity objects are re-rendered.
    3. Re-apply prerequisites, **re-render the HelmRelease from the
       counterpart's spec** and re-apply utility resources, then mark the
       counterpart CR Ready.

    The HelmRelease is where the identity swap is subtle. The counterpart keeps
    the *source's* Helm release name (``spec.releaseReference``, pinned at
    counterpart creation — research D2), so this upsert **updates** the restored
    HelmRelease rather than installing a second release: Flux performs a Helm
    *upgrade*, which rewrites the ``meta.helm.sh/release-*`` ownership
    annotations the restored objects carry from the source. A counterpart-named
    release would instead be a fresh *install* over objects Helm already owns
    and would fail its ownership check outright.

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
        await _delete_restored_crd_without_teardown(
            api_client, namespace, restored_crd_name
        )
        logger.info(
            "Deleted restored source-named StyrminDeployment %s/%s",
            namespace,
            restored_crd_name,
        )

    await _reapply_phases_and_finalize(
        api_client,
        namespace,
        counterpart_name,
        counterpart_crd_body.get("spec", {}),
        include_helmrelease=True,
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
