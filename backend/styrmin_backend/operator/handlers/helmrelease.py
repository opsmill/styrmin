"""Kopf handlers for HelmRelease resources.

Watches HelmRelease create/update/delete events for operator-managed
deployments and triggers NetworkPolicy lifecycle management.
"""

from __future__ import annotations

from typing import Any

import kopf

from styrmin_backend import config
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_ID,
    ANNOTATION_DEPLOYMENT_IN_PROGRESS,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
    LABEL_OPERATOR_MANAGED,
    LABEL_OPERATOR_MANAGED_VALUE,
    LABEL_RELEASE_REFERENCE,
)
from styrmin_backend.operator.events import (
    emit_reconcile_failed,
    emit_reconcile_succeeded,
)
from styrmin_backend.operator.reconciler import (
    cleanup_operator_resources,
    compute_diff,
    list_managed_resources,
    reconcile_resources,
)
from styrmin_backend.operator.state import (
    add_operator_managed_label,
    build_desired_resources,
    fetch_context,
    filter_resources_by_kind,
)


async def on_helmrelease_create(
    body: dict[str, Any],
    meta: dict[str, Any],
    spec: dict[str, Any],
    namespace: str,
    logger: Any,
    **_: Any,
) -> None:
    """Handle HelmRelease creation for operator-managed deployments.

    Fetches GlobalContext from the Styrmin API, builds desired NetworkPolicy
    specs, and creates them in the cluster.
    """
    labels = meta.get("labels", {})
    annotations = meta.get("annotations", {})
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    deployment_id = annotations.get(ANNOTATION_DEPLOYMENT_ID, "")
    helmrelease_name = meta.get("name", "")

    if not deployment_id:
        logger.warning(
            "HelmRelease %s/%s has no deployment-id annotation, skipping",
            namespace,
            helmrelease_name,
        )
        return

    # Skip CRD-managed deployments — their NetworkPolicies are handled
    # by the StyrminDeployment pipeline (Phase 1), not this handler.
    if not release_reference:
        logger.info(
            "HelmRelease %s/%s has no release-reference label (CRD-managed), skipping",
            namespace,
            helmrelease_name,
        )
        return

    logger.info(
        "Operator-managed HelmRelease created: %s/%s (deployment=%s)",
        namespace,
        helmrelease_name,
        deployment_id,
    )

    try:
        context = await fetch_context(deployment_id)
    except Exception:
        logger.exception(
            "Failed to fetch context for deployment %s, will retry on next reconciliation",
            deployment_id,
        )
        raise kopf.TemporaryError(
            f"Failed to fetch context for deployment {deployment_id}",
            delay=config.SETTINGS.operator.retry_delay,
        )

    all_resources = build_desired_resources(
        context=context,
        release_reference=release_reference,
        namespace=namespace,
    )

    # Only create NetworkPolicies - other utilities are still Prefect-managed
    netpols = filter_resources_by_kind(all_resources, "NetworkPolicy")
    # Add operator-managed label to each NetworkPolicy
    for np in netpols:
        add_operator_managed_label(np)

    result = await reconcile_resources(
        namespace=namespace,
        to_create=netpols,
        to_update=[],
        to_delete=[],
    )

    # Emit status events
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    async with get_kubernetes_client() as api_client:
        if result.has_errors:
            for error in result.errors:
                await emit_reconcile_failed(
                    api_client=api_client,
                    namespace=namespace,
                    helmrelease_name=helmrelease_name,
                    resource_kind="NetworkPolicy",
                    resource_name="(batch)",
                    error_message=error,
                )

    if result.has_errors:
        logger.warning(
            "Partial reconciliation for %s/%s: created=%d errors=%d",
            namespace,
            helmrelease_name,
            result.created,
            len(result.errors),
        )
        raise kopf.TemporaryError(
            f"Failed to create some NetworkPolicies: {result.errors}",
            delay=config.SETTINGS.operator.retry_delay,
        )

    if result.created > 0:
        async with get_kubernetes_client() as api_client:
            await emit_reconcile_succeeded(
                api_client=api_client,
                namespace=namespace,
                helmrelease_name=helmrelease_name,
                release_reference=release_reference,
            )

    logger.info(
        "Created %d NetworkPolicies for %s/%s",
        result.created,
        namespace,
        helmrelease_name,
    )


async def on_helmrelease_delete(
    body: dict[str, Any],
    meta: dict[str, Any],
    spec: dict[str, Any],
    namespace: str,
    logger: Any,
    **_: Any,
) -> None:
    """Handle HelmRelease deletion - clean up operator-created resources."""
    labels = meta.get("labels", {})
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    helmrelease_name = meta.get("name", "")

    logger.info(
        "Operator-managed HelmRelease deleted: %s/%s, cleaning up resources",
        namespace,
        helmrelease_name,
    )

    await cleanup_operator_resources(
        namespace=namespace,
        release_reference=release_reference,
    )

    logger.info(
        "Cleanup complete for %s/%s",
        namespace,
        helmrelease_name,
    )


# --- Kopf handler registrations ---


@kopf.on.create(
    group="helm.toolkit.fluxcd.io",
    version="v2",
    plural="helmreleases",
    labels={
        LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
        LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
    },
)
async def kopf_on_helmrelease_create(
    body: dict[str, Any],
    meta: kopf.Meta,
    spec: kopf.Spec,
    namespace: str | None,
    logger: kopf.Logger,
    **kwargs: Any,
) -> None:
    await on_helmrelease_create(
        body=body,
        meta=dict(meta),
        spec=dict(spec),
        namespace=namespace or "",
        logger=logger,
        **kwargs,
    )


@kopf.on.delete(
    group="helm.toolkit.fluxcd.io",
    version="v2",
    plural="helmreleases",
    labels={
        LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
        LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
    },
)
async def kopf_on_helmrelease_delete(
    body: dict[str, Any],
    meta: kopf.Meta,
    spec: kopf.Spec,
    namespace: str | None,
    logger: kopf.Logger,
    **kwargs: Any,
) -> None:
    await on_helmrelease_delete(
        body=body,
        meta=dict(meta),
        spec=dict(spec),
        namespace=namespace or "",
        logger=logger,
        **kwargs,
    )


# --- Periodic full reconciliation timer (US2) ---


@kopf.timer(
    group="helm.toolkit.fluxcd.io",
    version="v2",
    plural="helmreleases",
    labels={
        LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
        LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
    },
    interval=config.SETTINGS.operator.reconcile_interval,
    initial_delay=config.SETTINGS.operator.reconcile_interval,
)
async def kopf_helmrelease_timer(  # noqa: ARG001
    *,
    body: kopf.Body,
    meta: kopf.Meta,
    spec: kopf.Spec,
    namespace: str | None,
    logger: kopf.Logger,
    **kwargs: Any,
) -> None:
    """Periodic full reconciliation of all utility resources for a deployment.

    Runs every ``SETTINGS.operator.reconcile_interval`` seconds to catch any missed events
    and ensure convergence.
    """
    ns = namespace or ""
    labels = dict(meta.get("labels", {}))
    annotations = dict(meta.get("annotations", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    deployment_id = annotations.get(ANNOTATION_DEPLOYMENT_ID, "")
    helmrelease_name = meta.get("name", "")

    if not deployment_id:
        return

    # Skip if a deployment is in progress
    if annotations.get(ANNOTATION_DEPLOYMENT_IN_PROGRESS) == "true":
        logger.debug(
            "Deployment in progress for %s/%s, skipping periodic reconciliation",
            ns,
            helmrelease_name,
        )
        return

    try:
        context = await fetch_context(deployment_id)
    except Exception:
        logger.warning(
            "Failed to fetch context for %s during periodic reconciliation, will retry next cycle",
            deployment_id,
        )
        return

    # The StyrminDeployment pipeline creates the HelmRelease with no release-reference label
    # (``ApplicationHelmReleaseBuilder.build``), so the label read above is empty. The release
    # reference of the instance is the value that the StyrminDeployment timer and the Prefect
    # flows give the builder and select by. With an empty value, this timer would list no object
    # that they wrote, create each one again and replace its label with an empty one, and they
    # would do the same to the objects of this timer.
    release_reference = release_reference or context.instance.release_reference

    desired_all = build_desired_resources(
        context=context,
        release_reference=release_reference,
        namespace=ns,
    )

    # Reconcile NetworkPolicies (operator-managed)
    desired_netpols = filter_resources_by_kind(desired_all, "NetworkPolicy")
    for np in desired_netpols:
        add_operator_managed_label(np)

    actual_netpols = await list_managed_resources(
        namespace=ns,
        release_reference=release_reference,
        kind="NetworkPolicy",
        operator_managed_only=True,
    )

    to_create, to_update, to_delete = compute_diff(desired_netpols, actual_netpols)
    if to_create or to_update or to_delete:
        result = await reconcile_resources(
            namespace=ns,
            to_create=to_create,
            to_update=to_update,
            to_delete=to_delete,
        )
        logger.info(
            "Periodic reconciliation for %s/%s (NetworkPolicy): created=%d updated=%d deleted=%d errors=%d",
            ns,
            helmrelease_name,
            result.created,
            result.updated,
            result.deleted,
            len(result.errors),
        )
        if result.has_errors:
            logger.warning(
                "Periodic reconciliation of NetworkPolicy in %s/%s had %d error(s): %s",
                ns,
                helmrelease_name,
                len(result.errors),
                "; ".join(result.errors),
            )

    # Reconcile other utility resources (Prefect-created, operator-reconciled)
    for kind in ("Service", "Secret", "Ingress"):
        desired_kind = filter_resources_by_kind(desired_all, kind)
        actual_kind = await list_managed_resources(
            namespace=ns,
            release_reference=release_reference,
            kind=kind,
        )
        kc, ku, kd = compute_diff(desired_kind, actual_kind)
        if kc or ku or kd:
            result = await reconcile_resources(
                namespace=ns, to_create=kc, to_update=ku, to_delete=kd
            )
            logger.info(
                "Periodic reconciliation for %s/%s (%s): created=%d updated=%d deleted=%d errors=%d",
                ns,
                helmrelease_name,
                kind,
                result.created,
                result.updated,
                result.deleted,
                len(result.errors),
            )
            if result.has_errors:
                logger.warning(
                    "Periodic reconciliation of %s in %s/%s had %d error(s): %s",
                    kind,
                    ns,
                    helmrelease_name,
                    len(result.errors),
                    "; ".join(result.errors),
                )
