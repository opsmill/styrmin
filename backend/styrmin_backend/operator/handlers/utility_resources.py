"""Kopf handlers for utility resource drift detection.

Watches for modifications and deletions of Styrmin-managed utility resources
(NetworkPolicies, Services, Ingresses, Secrets, Middlewares). A handler reconciles the drifted
resource only when it finds the parent HelmRelease by the label ``styrmin.io/release-reference``.
A HelmRelease that the StyrminDeployment pipeline creates has no such label
(``ApplicationHelmReleaseBuilder.build`` sets only ``managed-by`` and ``operator-managed``), so for
those deployments a handler logs a warning and does nothing. The periodic timers of
``helmrelease.py`` and ``styrmin_deployment.py`` then reconcile the resources.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf

from styrmin_backend import config
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_ID,
    ANNOTATION_DEPLOYMENT_IN_PROGRESS,
    HELMRELEASE_GROUP,
    HELMRELEASE_PLURAL,
    HELMRELEASE_VERSION,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
    LABEL_OPERATOR_MANAGED,
    LABEL_OPERATOR_MANAGED_VALUE,
    LABEL_RELEASE_REFERENCE,
)
from styrmin_backend.operator.events import (
    emit_drift_detected,
    emit_reconcile_failed,
    emit_reconcile_succeeded,
)
from styrmin_backend.operator.reconciler import (
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

_logger = logging.getLogger(__name__)


async def _find_helmrelease_for_resource(
    namespace: str, release_reference: str
) -> dict[str, Any] | None:
    """Look up the parent HelmRelease for a utility resource by release-reference label."""
    from kubernetes_asyncio import client as kubeclient

    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            custom_api = kubeclient.CustomObjectsApi(client)
            result = await custom_api.list_namespaced_custom_object(
                group=HELMRELEASE_GROUP,
                version=HELMRELEASE_VERSION,
                namespace=namespace,
                plural=HELMRELEASE_PLURAL,
                label_selector=f"{LABEL_RELEASE_REFERENCE}={release_reference}",
            )
            items = result.get("items", [])
            if items:
                return items[0]
    except Exception:
        _logger.exception(
            "Failed to find HelmRelease for release-reference %s in %s",
            release_reference,
            namespace,
        )
    return None


async def _reconcile_resource_drift(
    *,
    namespace: str,
    resource_kind: str,
    resource_name: str,
    release_reference: str,
    change_type: str,
    logger: Any,
) -> None:
    """Common drift reconciliation logic for utility resources.

    Looks up the parent HelmRelease, checks for in-progress deployments,
    fetches desired state, and reconciles the drifted resource.
    """
    helmrelease = await _find_helmrelease_for_resource(namespace, release_reference)
    if helmrelease is None:
        logger.warning(
            "No HelmRelease found for %s/%s (ref=%s), skipping reconciliation",
            resource_kind,
            resource_name,
            release_reference,
        )
        return

    hr_meta = helmrelease.get("metadata", {})
    hr_name = hr_meta.get("name", "")
    hr_labels = hr_meta.get("labels", {})
    hr_annotations = hr_meta.get("annotations", {})

    # Check if deployment is in progress
    if hr_annotations.get(ANNOTATION_DEPLOYMENT_IN_PROGRESS) == "true":
        logger.info(
            "Deployment in progress for %s/%s, deferring reconciliation of %s/%s",
            namespace,
            hr_name,
            resource_kind,
            resource_name,
        )
        return

    deployment_id = hr_annotations.get(ANNOTATION_DEPLOYMENT_ID, "")
    if not deployment_id:
        logger.warning(
            "HelmRelease %s/%s has no deployment-id, cannot reconcile",
            namespace,
            hr_name,
        )
        return

    logger.info(
        "Drift detected on %s/%s (%s) in %s, reconciling",
        resource_kind,
        resource_name,
        change_type,
        namespace,
    )

    try:
        context = await fetch_context(deployment_id)
    except Exception:
        logger.exception(
            "Failed to fetch context for deployment %s during drift reconciliation",
            deployment_id,
        )
        raise kopf.TemporaryError(
            f"Failed to fetch context for deployment {deployment_id}",
            delay=config.SETTINGS.operator.retry_delay,
        )

    desired_all = build_desired_resources(
        context=context,
        release_reference=release_reference,
        namespace=namespace,
    )
    desired_for_kind = filter_resources_by_kind(desired_all, resource_kind)

    # For operator-managed NetworkPolicies, add the label
    is_operator_managed = (
        hr_labels.get(LABEL_OPERATOR_MANAGED) == LABEL_OPERATOR_MANAGED_VALUE
    )
    if resource_kind == "NetworkPolicy" and is_operator_managed:
        for r in desired_for_kind:
            add_operator_managed_label(r)

    actual = await list_managed_resources(
        namespace=namespace,
        release_reference=release_reference,
        kind=resource_kind,
        operator_managed_only=(
            resource_kind == "NetworkPolicy" and is_operator_managed
        ),
    )

    to_create, to_update, to_delete = compute_diff(desired_for_kind, actual)

    result = await reconcile_resources(
        namespace=namespace,
        to_create=to_create,
        to_update=to_update,
        to_delete=to_delete,
    )

    # Emit Kubernetes Events for status reporting
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    async with get_kubernetes_client() as api_client:
        if result.has_errors:
            for error in result.errors:
                await emit_reconcile_failed(
                    api_client=api_client,
                    namespace=namespace,
                    helmrelease_name=hr_name,
                    resource_kind=resource_kind,
                    resource_name=resource_name,
                    error_message=error,
                )
        elif result.total_actions > 0:
            await emit_drift_detected(
                api_client=api_client,
                namespace=namespace,
                helmrelease_name=hr_name,
                resource_kind=resource_kind,
                resource_name=resource_name,
                change_type=change_type,
            )
            await emit_reconcile_succeeded(
                api_client=api_client,
                namespace=namespace,
                helmrelease_name=hr_name,
                release_reference=release_reference,
            )

    if result.total_actions > 0 or result.has_errors:
        logger.info(
            "Reconciled %s/%s: created=%d updated=%d deleted=%d errors=%d",
            resource_kind,
            resource_name,
            result.created,
            result.updated,
            result.deleted,
            len(result.errors),
        )


# --- Kopf handler registrations for NetworkPolicy drift (US1) ---


@kopf.on.update(
    version="v1",
    plural="networkpolicies",
    labels={
        LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
        LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
    },
)
async def kopf_on_networkpolicy_update(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="NetworkPolicy",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="modified",
        logger=logger,
    )


@kopf.on.delete(
    version="v1",
    plural="networkpolicies",
    labels={
        LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
        LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
    },
)
async def kopf_on_networkpolicy_delete(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="NetworkPolicy",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="deleted",
        logger=logger,
    )


# --- Kopf handler registrations for Service drift (US2) ---


@kopf.on.update(
    version="v1",
    plural="services",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_service_update(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Service",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="modified",
        logger=logger,
    )


@kopf.on.delete(
    version="v1",
    plural="services",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_service_delete(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Service",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="deleted",
        logger=logger,
    )


# --- Kopf handler registrations for Ingress drift (#598) ---
#
# The label filter keeps these handlers to the Ingress objects that Styrmin builds
# (``UtilityResourceBuilder`` sets ``app.kubernetes.io/managed-by: styrmin`` and the
# release reference on them). An Ingress that a chart renders carries neither label,
# so Helm keeps ownership of it. ``list_managed_resources`` uses the same two labels
# as its selector, so the reconcile never deletes a chart's Ingress.


@kopf.on.update(
    group="networking.k8s.io",
    version="v1",
    plural="ingresses",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_ingress_update(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Ingress",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="modified",
        logger=logger,
    )


@kopf.on.delete(
    group="networking.k8s.io",
    version="v1",
    plural="ingresses",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_ingress_delete(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Ingress",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="deleted",
        logger=logger,
    )


# --- Kopf handler registrations for Secret drift (US2) ---


@kopf.on.update(
    version="v1",
    plural="secrets",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_secret_update(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Secret",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="modified",
        logger=logger,
    )


@kopf.on.delete(
    version="v1",
    plural="secrets",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_secret_delete(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Secret",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="deleted",
        logger=logger,
    )


# --- Kopf handler registrations for Middleware CRD drift (US2) ---


@kopf.on.update(
    group="traefik.io",
    version="v1alpha1",
    plural="middlewares",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_middleware_update(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Middleware",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="modified",
        logger=logger,
    )


@kopf.on.delete(
    group="traefik.io",
    version="v1alpha1",
    plural="middlewares",
    labels={LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE},
)
async def kopf_on_middleware_delete(
    body: dict[str, Any],
    meta: kopf.Meta,
    namespace: str | None,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    labels = dict(meta.get("labels", {}))
    release_reference = labels.get(LABEL_RELEASE_REFERENCE, "")
    if not release_reference:
        return

    await _reconcile_resource_drift(
        namespace=namespace or "",
        resource_kind="Middleware",
        resource_name=meta.get("name", ""),
        release_reference=release_reference,
        change_type="deleted",
        logger=logger,
    )
