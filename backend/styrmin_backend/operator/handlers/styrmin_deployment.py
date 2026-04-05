"""Kopf handlers for StyrminDeployment CRD lifecycle.

Watches StyrminDeployment create/update/delete/resume events and
orchestrates the ordered deployment pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf

from styrmin_backend.operator.config import (
    CRD_GROUP,
    CRD_PLURAL,
    CRD_VERSION,
    RECONCILIATION_INTERVAL_SECONDS,
)
from styrmin_backend.operator.crd.schema import (
    ConditionStatus,
    ConditionType,
    DeploymentPhase,
)
from styrmin_backend.operator.crd.status import (
    is_condition_true,
    set_condition,
    set_phase,
)
from styrmin_backend.operator.pipeline import (
    execute_phase_helmrelease,
    execute_phase_prerequisites,
    execute_phase_services,
    should_proceed_to_helmrelease,
)

_logger = logging.getLogger(__name__)


async def on_styrmin_deployment_create(
    spec: dict[str, Any],
    status: dict[str, Any],
    name: str,
    namespace: str,
    patch: Any,
    logger: Any,
    **_: Any,
) -> None:
    """Handle StyrminDeployment creation — start ordered deployment."""
    logger.info("StyrminDeployment created: %s/%s", namespace, name)
    set_phase(
        patch.status, DeploymentPhase.CREATING_PREREQUISITES, "Starting deployment"
    )

    # Phase 1: NetworkPolicies + Secrets
    result = await execute_phase_prerequisites(crd_spec=spec, namespace=namespace)

    conditions: list[dict[str, str]] = status.get("conditions", [])

    if result.success:
        set_condition(
            conditions,
            ConditionType.NETWORK_POLICIES_READY,
            ConditionStatus.TRUE,
            "AllApplied",
            f"{result.resource_details.get('networkPolicies', 0)} NetworkPolicies created",
        )
        set_condition(
            conditions,
            ConditionType.SECRETS_READY,
            ConditionStatus.TRUE,
            "AllApplied",
            f"{result.resource_details.get('secrets', 0)} Secrets created",
        )
        patch.status["conditions"] = conditions
        set_phase(
            patch.status,
            DeploymentPhase.CREATING_HELM_RELEASE,
            "Prerequisites ready, creating HelmRelease",
        )
        logger.info(
            "Phase 1 complete for %s/%s, proceeding to HelmRelease", namespace, name
        )
    else:
        set_condition(
            conditions,
            ConditionType.NETWORK_POLICIES_READY,
            ConditionStatus.FALSE,
            "ApplyFailed",
            "; ".join(result.errors),
        )
        patch.status["conditions"] = conditions
        set_phase(patch.status, DeploymentPhase.FAILED, "Prerequisites failed")
        raise kopf.TemporaryError(
            f"Phase 1 failed: {result.errors}",
            delay=30,
        )


async def on_styrmin_deployment_resume(
    spec: dict[str, Any],
    status: dict[str, Any],
    name: str,
    namespace: str,
    patch: Any,
    logger: Any,
    **_: Any,
) -> None:
    """Resume from current phase after operator restart.

    Reads the status to determine which phase to continue from,
    avoiding re-execution of completed phases.
    """
    phase = status.get("phase", DeploymentPhase.PENDING.value)
    conditions = status.get("conditions", [])

    logger.info("Resuming %s/%s from phase=%s", namespace, name, phase)

    if phase == DeploymentPhase.READY.value:
        return  # Already complete

    if phase in (
        DeploymentPhase.PENDING.value,
        DeploymentPhase.CREATING_PREREQUISITES.value,
    ):
        if not should_proceed_to_helmrelease(conditions):
            # Re-run phase 1
            result = await execute_phase_prerequisites(
                crd_spec=spec, namespace=namespace
            )
            if result.success:
                set_condition(
                    conditions,
                    ConditionType.NETWORK_POLICIES_READY,
                    ConditionStatus.TRUE,
                    "AllApplied",
                    "Resumed",
                )
                set_condition(
                    conditions,
                    ConditionType.SECRETS_READY,
                    ConditionStatus.TRUE,
                    "AllApplied",
                    "Resumed",
                )
                patch.status["conditions"] = conditions
                set_phase(patch.status, DeploymentPhase.CREATING_HELM_RELEASE)
            else:
                raise kopf.TemporaryError(
                    f"Phase 1 resume failed: {result.errors}", delay=30
                )

    if phase in (
        DeploymentPhase.CREATING_PREREQUISITES.value,
        DeploymentPhase.CREATING_HELM_RELEASE.value,
    ):
        if should_proceed_to_helmrelease(conditions) and not is_condition_true(
            conditions, ConditionType.HELM_RELEASE_READY
        ):
            result = await execute_phase_helmrelease(crd_spec=spec, namespace=namespace)
            if result.success:
                # HelmRelease created, but we need to wait for FluxCD Ready — timer will handle that
                set_phase(
                    patch.status,
                    DeploymentPhase.CREATING_HELM_RELEASE,
                    "HelmRelease created, waiting for Ready",
                )
                patch.status["conditions"] = conditions
            else:
                raise kopf.TemporaryError(
                    f"Phase 2 resume failed: {result.errors}", delay=30
                )


# --- Kopf handler registrations ---


@kopf.on.create(CRD_GROUP, CRD_VERSION, CRD_PLURAL)
async def _kopf_on_styrmin_deployment_create(
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **kwargs: Any,
) -> None:
    await on_styrmin_deployment_create(
        spec=dict(spec),
        status=dict(status),
        name=name,
        namespace=namespace or "",
        patch=patch,
        logger=logger,
        **kwargs,
    )


@kopf.on.resume(CRD_GROUP, CRD_VERSION, CRD_PLURAL)
async def _kopf_on_styrmin_deployment_resume(
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **kwargs: Any,
) -> None:
    await on_styrmin_deployment_resume(
        spec=dict(spec),
        status=dict(status),
        name=name,
        namespace=namespace or "",
        patch=patch,
        logger=logger,
        **kwargs,
    )


@kopf.on.update(CRD_GROUP, CRD_VERSION, CRD_PLURAL, field="spec")
async def _kopf_on_styrmin_deployment_update(
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    diff: kopf.Diff,
    **_: Any,
) -> None:
    """Handle StyrminDeployment spec changes — re-run ordered pipeline."""
    ns = namespace or ""
    logger.info("StyrminDeployment spec updated: %s/%s, re-reconciling", ns, name)

    # Reset to CreatingPrerequisites to re-run the full pipeline
    set_phase(
        patch.status,
        DeploymentPhase.CREATING_PREREQUISITES,
        "Spec updated, re-reconciling",
    )

    result = await execute_phase_prerequisites(crd_spec=dict(spec), namespace=ns)
    conditions: list[dict[str, str]] = list(status.get("conditions", []))

    if result.success:
        set_condition(
            conditions,
            ConditionType.NETWORK_POLICIES_READY,
            ConditionStatus.TRUE,
            "AllApplied",
            "Updated",
        )
        set_condition(
            conditions,
            ConditionType.SECRETS_READY,
            ConditionStatus.TRUE,
            "AllApplied",
            "Updated",
        )
        patch.status["conditions"] = conditions
        set_phase(
            patch.status, DeploymentPhase.CREATING_HELM_RELEASE, "Prerequisites updated"
        )
    else:
        set_phase(
            patch.status, DeploymentPhase.FAILED, f"Update failed: {result.errors}"
        )
        raise kopf.TemporaryError(f"Phase 1 update failed: {result.errors}", delay=30)


# --- Timer for drift detection and phase advancement (US3) ---


@kopf.timer(
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL,
    interval=RECONCILIATION_INTERVAL_SECONDS,
    initial_delay=RECONCILIATION_INTERVAL_SECONDS,
)
async def _kopf_styrmin_deployment_timer(
    *,
    body: kopf.Body,
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Periodic reconciliation: advance phases and detect drift."""
    ns = namespace or ""
    phase = status.get("phase", DeploymentPhase.PENDING.value)
    conditions = list(status.get("conditions", []))
    crd_spec = dict(spec)

    # Phase advancement for in-progress deployments
    if phase == DeploymentPhase.CREATING_HELM_RELEASE.value:
        if not is_condition_true(conditions, ConditionType.HELM_RELEASE_READY):
            # Check if HelmRelease is Ready via FluxCD
            from styrmin_backend.operator.reconciler import _check_helmrelease_ready

            hr_ready = await _check_helmrelease_ready(
                namespace=ns,
                release_reference=crd_spec.get("releaseReference", ""),
            )
            if hr_ready:
                set_condition(
                    conditions,
                    ConditionType.HELM_RELEASE_READY,
                    ConditionStatus.TRUE,
                    "FluxReady",
                    "HelmRelease is Ready",
                )
                patch.status["conditions"] = conditions
                set_phase(
                    patch.status,
                    DeploymentPhase.CREATING_SERVICES,
                    "HelmRelease ready, creating Services",
                )

                # Execute phase 3
                result = await execute_phase_services(crd_spec=crd_spec, namespace=ns)
                if result.success:
                    set_condition(
                        conditions,
                        ConditionType.SERVICES_READY,
                        ConditionStatus.TRUE,
                        "AllApplied",
                        f"{result.resource_details.get('services', 0)} Services",
                    )
                    set_condition(
                        conditions,
                        ConditionType.MIDDLEWARES_READY,
                        ConditionStatus.TRUE,
                        "AllApplied",
                        f"{result.resource_details.get('middlewares', 0)} Middlewares",
                    )
                    set_condition(
                        conditions,
                        ConditionType.READY,
                        ConditionStatus.TRUE,
                        "AllPhasesComplete",
                        "Deployment is healthy",
                    )
                    patch.status["conditions"] = conditions
                    set_phase(
                        patch.status, DeploymentPhase.READY, "All resources deployed"
                    )
                    logger.info("Deployment %s/%s reached Ready state", ns, name)
        return

    if phase == DeploymentPhase.CREATING_PREREQUISITES.value:
        # Phase 1 may still be in progress — check and advance
        if should_proceed_to_helmrelease(conditions):
            result = await execute_phase_helmrelease(crd_spec=crd_spec, namespace=ns)
            if result.success:
                set_phase(
                    patch.status,
                    DeploymentPhase.CREATING_HELM_RELEASE,
                    "HelmRelease created, waiting for Ready",
                )
                patch.status["conditions"] = conditions
        return

    if phase == DeploymentPhase.READY.value:
        # Drift detection: reconcile all resources
        from styrmin_backend.operator.pipeline import build_desired_resources_from_crd
        from styrmin_backend.operator.reconciler import (
            compute_diff,
            list_managed_resources,
            reconcile_resources,
        )

        try:
            desired_all = build_desired_resources_from_crd(crd_spec, ns)
        except Exception:
            logger.warning(
                "Failed to build desired resources for drift check on %s/%s", ns, name
            )
            return

        release_ref = crd_spec.get("releaseReference", "")

        for kind in ("NetworkPolicy", "Secret", "Service"):
            desired_kind = [r for r in desired_all if r.get("kind") == kind]
            actual_kind = await list_managed_resources(
                namespace=ns,
                release_reference=release_ref,
                kind=kind,
            )
            to_create, to_update, to_delete = compute_diff(desired_kind, actual_kind)
            if to_create or to_update or to_delete:
                result = await reconcile_resources(
                    namespace=ns,
                    to_create=to_create,
                    to_update=to_update,
                    to_delete=to_delete,
                )
                logger.info(
                    "Drift reconciled for %s in %s/%s: +%d ~%d -%d",
                    kind,
                    ns,
                    name,
                    result.created,
                    result.updated,
                    result.deleted,
                )


# --- Ordered deletion (US3) ---


@kopf.on.delete(CRD_GROUP, CRD_VERSION, CRD_PLURAL)
async def _kopf_on_styrmin_deployment_delete(
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Reverse-order cleanup: Services/Middlewares -> HelmRelease -> NetworkPolicies/Secrets."""
    ns = namespace or ""
    release_ref = spec.get("releaseReference", "")
    logger.info(
        "Deleting StyrminDeployment %s/%s, cleaning up resources in reverse order",
        ns,
        name,
    )
    set_phase(patch.status, DeploymentPhase.DELETING, "Cleaning up resources")

    from styrmin_backend.operator.reconciler import (
        delete_kubernetes_resource,
        list_managed_resources,
    )

    # Step 1: Delete Services and Middlewares
    logger.info("Step 1: Deleting Services and Middlewares for %s/%s", ns, name)
    for kind in ("Service",):
        resources = await list_managed_resources(
            namespace=ns, release_reference=release_ref, kind=kind
        )
        for resource in resources:
            try:
                await delete_kubernetes_resource(resource=resource, namespace=ns)
            except Exception:
                logger.exception(
                    "Failed to delete %s/%s",
                    kind,
                    resource.get("metadata", {}).get("name"),
                )

    # Step 2: Delete HelmRelease
    logger.info("Step 2: Deleting HelmRelease for %s/%s", ns, name)
    from kubernetes_asyncio import client as kubeclient
    from styrmin_backend.agent.service.kubernetes.dependency import get_api_client

    try:
        client = await anext(get_api_client())
        custom_api = kubeclient.CustomObjectsApi(client)
        await custom_api.delete_namespaced_custom_object(
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace=ns,
            plural="helmreleases",
            name=release_ref,
        )
        logger.info("HelmRelease %s deleted", release_ref)
    except Exception:
        logger.warning("HelmRelease %s not found or already deleted", release_ref)

    # Step 3: Delete NetworkPolicies and Secrets
    logger.info("Step 3: Deleting NetworkPolicies and Secrets for %s/%s", ns, name)
    for kind in ("NetworkPolicy", "Secret"):
        resources = await list_managed_resources(
            namespace=ns, release_reference=release_ref, kind=kind
        )
        for resource in resources:
            try:
                await delete_kubernetes_resource(resource=resource, namespace=ns)
            except Exception:
                logger.exception(
                    "Failed to delete %s/%s",
                    kind,
                    resource.get("metadata", {}).get("name"),
                )

    logger.info("Cleanup complete for StyrminDeployment %s/%s", ns, name)
