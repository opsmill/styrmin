"""Kopf handlers for StyrminDeployment CRD lifecycle.

Watches StyrminDeployment create/update/delete/resume events and
orchestrates the ordered deployment pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import kopf

from styrmin_backend.operator.config import (
    CRD_GROUP,
    CRD_PLURAL,
    CRD_VERSION,
    DEPLOYMENT_READY_TIMEOUT_SECONDS,
    RECONCILIATION_INTERVAL_SECONDS,
)
from styrmin_backend.operator.crd.schema import (
    ConditionStatus,
    ConditionType,
    DeploymentPhase,
    DisplayState,
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
from styrmin_backend.services.component_container.exceptions import (
    ComponentContainerNotFoundError,
)


def _is_internal(spec: dict[str, Any]) -> bool:
    """Check if a StyrminDeployment is an internal deployment (e.g., ingress controller)."""
    return spec.get("internal", False)


async def _fail_on_component_container_guard(
    *,
    crd_spec: dict[str, Any],
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> bool:
    """Fail the CR when its HelmRelease failed on the component-container guard (018, FR-007).

    Returns True when the CR was failed, so the timer stops for this tick.
    """
    from styrmin_backend.operator.reconciler import read_helmrelease_guard_failure

    failure = await read_helmrelease_guard_failure(
        namespace=namespace,
        release_reference=crd_spec.get("releaseReference", ""),
    )
    if failure is None:
        return False

    component_name, container = failure
    message = str(
        ComponentContainerNotFoundError(
            component_name=component_name, container=container
        )
    )
    set_condition(
        conditions,
        ConditionType.HELM_RELEASE_READY,
        ConditionStatus.FALSE,
        "ComponentContainerNotFound",
        message,
    )
    patch.status["conditions"] = conditions
    set_phase(patch.status, DeploymentPhase.FAILED, message)
    patch.status["displayState"] = DisplayState.ERROR.value
    logger.warning("Deployment %s/%s failed: %s", namespace, name, message)
    return True


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

    patch.status["displayState"] = DisplayState.DEPLOYING.value

    conditions: list[dict[str, str]] = status.get("conditions", [])

    # Internal deployments (e.g., ingress controller) skip prerequisites
    # and go straight to HelmRelease creation.
    if _is_internal(spec):
        logger.info(
            "Internal deployment %s/%s — skipping prerequisites", namespace, name
        )
        set_condition(
            conditions,
            ConditionType.NETWORK_POLICIES_READY,
            ConditionStatus.TRUE,
            "Skipped",
            "Internal deployment — no prerequisites needed",
        )
        set_condition(
            conditions,
            ConditionType.SECRETS_READY,
            ConditionStatus.TRUE,
            "Skipped",
            "Internal deployment — no prerequisites needed",
        )
        patch.status["conditions"] = conditions

        # Immediately create HelmRelease
        result = await execute_phase_helmrelease(crd_spec=spec, namespace=namespace)
        if result.success:
            set_phase(
                patch.status,
                DeploymentPhase.CREATING_HELM_RELEASE,
                "HelmRelease created, waiting for Ready",
            )
        else:
            set_phase(
                patch.status,
                DeploymentPhase.FAILED,
                f"HelmRelease creation failed: {result.errors}",
            )
            patch.status["displayState"] = DisplayState.ERROR.value
            raise kopf.TemporaryError(
                f"HelmRelease creation failed: {result.errors}", delay=30
            )
        return

    set_phase(
        patch.status, DeploymentPhase.CREATING_PREREQUISITES, "Starting deployment"
    )

    # Phase 1: NetworkPolicies + Secrets
    result = await execute_phase_prerequisites(crd_spec=spec, namespace=namespace)

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
        logger.info(
            "Phase 1 complete for %s/%s, proceeding to HelmRelease", namespace, name
        )

        # Phase 2: Create HelmRelease
        hr_result = await execute_phase_helmrelease(crd_spec=spec, namespace=namespace)
        if hr_result.success:
            set_phase(
                patch.status,
                DeploymentPhase.CREATING_HELM_RELEASE,
                "HelmRelease created, waiting for Ready",
            )
        else:
            set_phase(
                patch.status,
                DeploymentPhase.FAILED,
                f"HelmRelease creation failed: {hr_result.errors}",
            )
            patch.status["displayState"] = DisplayState.ERROR.value
            raise kopf.TemporaryError(
                f"HelmRelease creation failed: {hr_result.errors}", delay=30
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
        patch.status["displayState"] = DisplayState.ERROR.value
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

    # Internal deployments skip prerequisites — resume straight to HelmRelease
    if _is_internal(spec):
        if not is_condition_true(conditions, ConditionType.HELM_RELEASE_READY):
            result = await execute_phase_helmrelease(crd_spec=spec, namespace=namespace)
            if result.success:
                set_phase(
                    patch.status,
                    DeploymentPhase.CREATING_HELM_RELEASE,
                    "HelmRelease created, waiting for Ready",
                )
            else:
                raise kopf.TemporaryError(
                    f"HelmRelease resume failed: {result.errors}", delay=30
                )
        return

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
async def kopf_on_styrmin_deployment_create(
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
async def kopf_on_styrmin_deployment_resume(
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
async def kopf_on_styrmin_deployment_update(
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
    crd_spec = dict(spec)

    # Spec 008: when the spec change *is* the deletion request, the
    # deletion-observer handler (kopf_on_styrmin_deployment_deletion_requested)
    # owns this update — it tears resources down. Re-running the full
    # deploy pipeline here would be wasted work and would briefly flip
    # displayState to Deploying mid-teardown (confusing for the UI).
    if crd_spec.get("deletionRequested", False):
        logger.info(
            "StyrminDeployment spec updated for %s/%s with deletionRequested=true — "
            "deferring to deletion handler",
            ns,
            name,
        )
        return

    logger.info("StyrminDeployment spec updated: %s/%s, re-reconciling", ns, name)

    patch.status["displayState"] = DisplayState.DEPLOYING.value

    conditions: list[dict[str, str]] = list(status.get("conditions", []))

    # Internal deployments skip prerequisites — go straight to HelmRelease
    if _is_internal(crd_spec):
        result = await execute_phase_helmrelease(crd_spec=crd_spec, namespace=ns)
        if result.success:
            set_phase(
                patch.status,
                DeploymentPhase.CREATING_HELM_RELEASE,
                "HelmRelease updated, waiting for Ready",
            )
            patch.status["conditions"] = conditions
        else:
            set_phase(
                patch.status,
                DeploymentPhase.FAILED,
                f"Update failed: {result.errors}",
            )
            patch.status["displayState"] = DisplayState.ERROR.value
            raise kopf.TemporaryError(
                f"HelmRelease update failed: {result.errors}", delay=30
            )
        return

    # Reset to CreatingPrerequisites to re-run the full pipeline
    set_phase(
        patch.status,
        DeploymentPhase.CREATING_PREREQUISITES,
        "Spec updated, re-reconciling",
    )

    result = await execute_phase_prerequisites(crd_spec=crd_spec, namespace=ns)

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
        logger.info(
            "Prerequisites updated for %s/%s, proceeding to HelmRelease update",
            ns,
            name,
        )

        # Phase 2: Update HelmRelease with new spec
        hr_result = await execute_phase_helmrelease(crd_spec=crd_spec, namespace=ns)
        if hr_result.success:
            set_phase(
                patch.status,
                DeploymentPhase.CREATING_HELM_RELEASE,
                "HelmRelease updated, waiting for Ready",
            )
        else:
            set_phase(
                patch.status,
                DeploymentPhase.FAILED,
                f"HelmRelease update failed: {hr_result.errors}",
            )
            patch.status["displayState"] = DisplayState.ERROR.value
            raise kopf.TemporaryError(
                f"HelmRelease update failed: {hr_result.errors}", delay=30
            )
    else:
        set_phase(
            patch.status, DeploymentPhase.FAILED, f"Update failed: {result.errors}"
        )
        patch.status["displayState"] = DisplayState.ERROR.value
        raise kopf.TemporaryError(f"Phase 1 update failed: {result.errors}", delay=30)


# --- Timer for drift detection and phase advancement (US3) ---


@kopf.timer(
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL,
    interval=RECONCILIATION_INTERVAL_SECONDS,
    initial_delay=RECONCILIATION_INTERVAL_SECONDS,
)
async def kopf_styrmin_deployment_timer(
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

    # While the styrmin restore flow drives the lifecycle, the operator
    # must not advance phases or trip the readiness timeout — let the
    # workflow finish, strip the kopf annotations, and transition out.
    if phase == DeploymentPhase.RESTORING.value:
        return

    # If teardown was requested (spec.deletionRequested == True), advance
    # to phase: Deleted as soon as the namespace is gone. The timer is
    # the only path that can set the terminal phase — the field-update
    # handler kicks teardown off but does not block on namespace
    # finalisers (which can take minutes).
    if phase == DeploymentPhase.DELETING.value or crd_spec.get(
        "deletionRequested", False
    ):
        if await _advance_to_phase_deleted(
            status=dict(status), patch=patch, namespace=ns, name=name, logger=logger
        ):
            return
        # Still tearing down — don't run the rest of the phase advancement.
        if phase == DeploymentPhase.DELETING.value:
            return

    # Once terminal, the timer has nothing more to do for this CR — the
    # janitor (kopf_styrmin_deployment_janitor) is responsible for the
    # eventual TTL-based cleanup.
    if phase == DeploymentPhase.DELETED.value:
        return

    # --- displayState timeout check ---
    # If deployment hasn't reached Ready or Failed within the timeout, mark as Error.
    if phase not in (
        DeploymentPhase.READY.value,
        DeploymentPhase.FAILED.value,
        DeploymentPhase.DELETING.value,
    ):
        creation_ts = body.get("metadata", {}).get("creationTimestamp")
        if creation_ts:
            created_at = datetime.fromisoformat(creation_ts)
            elapsed = (datetime.now(tz=timezone.utc) - created_at).total_seconds()
            if elapsed > DEPLOYMENT_READY_TIMEOUT_SECONDS:
                current_display = status.get(
                    "displayState", DisplayState.DEPLOYING.value
                )
                if current_display != DisplayState.ERROR.value:
                    patch.status["displayState"] = DisplayState.ERROR.value
                    patch.status["message"] = (
                        f"Deployment did not reach Ready within"
                        f" {DEPLOYMENT_READY_TIMEOUT_SECONDS}s (phase: {phase})"
                    )
                    logger.warning(
                        "Deployment %s/%s timed out in phase %s", ns, name, phase
                    )

    # Phase advancement for in-progress deployments
    if phase == DeploymentPhase.CREATING_HELM_RELEASE.value:
        # Checked first: on an update, HelmReleaseReady is still True from the previous rollout.
        if await _fail_on_component_container_guard(
            crd_spec=crd_spec,
            conditions=conditions,
            namespace=ns,
            name=name,
            patch=patch,
            logger=logger,
        ):
            return

        hr_already_ready = is_condition_true(
            conditions, ConditionType.HELM_RELEASE_READY
        )

        if not hr_already_ready:
            # Check if HelmRelease is Ready via FluxCD
            from styrmin_backend.operator.reconciler import (
                _check_helmrelease_ready,
                _check_any_pod_ready,
            )

            hr_ready = await _check_helmrelease_ready(
                namespace=ns,
                release_reference=crd_spec.get("releaseReference", ""),
            )

            # For internal deployments (e.g., ingress controller), also accept
            # running pods as "ready" — the HelmRelease may stay in
            # Unknown/Progressing if a LoadBalancer can't get an external IP.
            if not hr_ready and _is_internal(crd_spec):
                hr_ready = await _check_any_pod_ready(namespace=ns)

            if not hr_ready:
                return

            hr_already_ready = True
            set_condition(
                conditions,
                ConditionType.HELM_RELEASE_READY,
                ConditionStatus.TRUE,
                "FluxReady",
                "HelmRelease is Ready",
            )
            patch.status["conditions"] = conditions

        if hr_already_ready:
            # Internal deployments skip Phase 3 — go straight to Ready
            if _is_internal(crd_spec):
                set_condition(
                    conditions,
                    ConditionType.SERVICES_READY,
                    ConditionStatus.TRUE,
                    "Skipped",
                    "Internal deployment — no services needed",
                )
                set_condition(
                    conditions,
                    ConditionType.MIDDLEWARES_READY,
                    ConditionStatus.TRUE,
                    "Skipped",
                    "Internal deployment — no middlewares needed",
                )
                set_condition(
                    conditions,
                    ConditionType.READY,
                    ConditionStatus.TRUE,
                    "AllPhasesComplete",
                    "Internal deployment is healthy",
                )
                patch.status["conditions"] = conditions
                set_phase(patch.status, DeploymentPhase.READY, "All resources deployed")
                patch.status["displayState"] = DisplayState.RUNNING.value
                logger.info("Internal deployment %s/%s reached Ready state", ns, name)
                return

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
                set_phase(patch.status, DeploymentPhase.READY, "All resources deployed")
                patch.status["displayState"] = DisplayState.RUNNING.value
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
        # Internal deployments have no utility resources to reconcile
        if _is_internal(crd_spec):
            return

        if await _fail_on_component_container_guard(
            crd_spec=crd_spec,
            conditions=conditions,
            namespace=ns,
            name=name,
            patch=patch,
            logger=logger,
        ):
            return

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


# --- Ordered deletion (US3 + spec 008) ---


async def _teardown_owned_resources(
    *,
    namespace: str,
    release_reference: str,
    name: str,
    logger: Any,
) -> None:
    """Reverse-order teardown of resources owned by a StyrminDeployment.

    Order: Services/Middlewares -> HelmRelease -> NetworkPolicies/Secrets.
    Errors are logged and swallowed — teardown is best-effort and
    finalisers / 404s should not block the lifecycle.

    Reused by both the platform-driven path (``spec.deletionRequested``
    flip, observed by ``kopf_on_styrmin_deployment_deletion_requested``)
    and the manual safety-net path (``kubectl delete styrmindeployment``,
    handled by ``kopf_on_styrmin_deployment_delete``).
    """
    from styrmin_backend.operator.reconciler import (
        delete_kubernetes_resource,
        list_managed_resources,
    )

    # Step 1: Services and Middlewares.
    logger.info("Teardown step 1: Services / Middlewares for %s/%s", namespace, name)
    for kind in ("Service",):
        resources = await list_managed_resources(
            namespace=namespace, release_reference=release_reference, kind=kind
        )
        for resource in resources:
            try:
                await delete_kubernetes_resource(resource=resource, namespace=namespace)
            except Exception:
                logger.exception(
                    "Failed to delete %s/%s",
                    kind,
                    resource.get("metadata", {}).get("name"),
                )

    # Step 2: HelmRelease.
    logger.info("Teardown step 2: HelmRelease for %s/%s", namespace, name)
    from kubernetes_asyncio import client as kubeclient
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            custom_api = kubeclient.CustomObjectsApi(client)
            await custom_api.delete_namespaced_custom_object(
                group="helm.toolkit.fluxcd.io",
                version="v2",
                namespace=namespace,
                plural="helmreleases",
                name=release_reference,
            )
            logger.info("HelmRelease %s deleted", release_reference)
    except Exception:
        logger.warning("HelmRelease %s not found or already deleted", release_reference)

    # Step 3: NetworkPolicies and Secrets.
    logger.info("Teardown step 3: NetworkPolicies / Secrets for %s/%s", namespace, name)
    for kind in ("NetworkPolicy", "Secret"):
        resources = await list_managed_resources(
            namespace=namespace, release_reference=release_reference, kind=kind
        )
        for resource in resources:
            try:
                await delete_kubernetes_resource(resource=resource, namespace=namespace)
            except Exception:
                logger.exception(
                    "Failed to delete %s/%s",
                    kind,
                    resource.get("metadata", {}).get("name"),
                )


async def _request_namespace_deletion(*, namespace: str, logger: Any) -> None:
    """Issue a delete on the deployment's own namespace.

    Idempotent — a 404 from the API server is treated as already-gone.
    The actual finalisers may take time; ``_namespace_is_gone`` polls
    for the eventual disappearance.
    """
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio.client.api_client import ApiException
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            core_api = kubeclient.CoreV1Api(client)
            await core_api.delete_namespace(name=namespace)
            logger.info("Namespace %s delete requested", namespace)
    except ApiException as exc:
        if exc.status == 404:
            logger.info("Namespace %s already gone", namespace)
            return
        raise


async def _namespace_is_gone(*, namespace: str) -> bool:
    """Return True iff the namespace no longer exists (API server 404)."""
    from kubernetes_asyncio import client as kubeclient
    from kubernetes_asyncio.client.api_client import ApiException
    from styrmin_backend.operator.kubernetes import get_kubernetes_client

    try:
        async with get_kubernetes_client() as client:
            core_api = kubeclient.CoreV1Api(client)
            await core_api.read_namespace(name=namespace)
            return False
    except ApiException as exc:
        if exc.status == 404:
            return True
        raise


async def _advance_to_phase_deleted(
    *,
    status: dict[str, Any],
    patch: kopf.Patch,
    namespace: str,
    name: str,
    logger: Any,
) -> bool:
    """If the namespace is gone, advance the CR to phase: Deleted.

    Returns True if the advancement was applied (caller should not run
    the timer's other phase logic for this tick), False otherwise.
    """
    if not await _namespace_is_gone(namespace=namespace):
        return False

    set_phase(patch.status, DeploymentPhase.DELETED, "Namespace removed")
    patch.status["displayState"] = DisplayState.DELETED.value

    conditions = list(status.get("conditions", []))
    set_condition(
        conditions,
        ConditionType.DELETED,
        ConditionStatus.TRUE,
        "NamespaceGone",
        f"All owned resources removed; namespace {namespace} no longer exists",
    )
    patch.status["conditions"] = conditions
    logger.info("StyrminDeployment %s/%s reached phase: Deleted", namespace, name)
    return True


@kopf.on.update(
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL,
    field="spec.deletionRequested",
    new=True,
)
async def kopf_on_styrmin_deployment_deletion_requested(
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Observe ``spec.deletionRequested`` flip true and run the teardown
    pipeline platform-side (no CR delete — the CR lingers until the
    janitor reaps it after ``DELETED_CR_TTL_HOURS``)."""

    ns = namespace or ""
    release_ref = spec.get("releaseReference", "")

    current_phase = status.get("phase")
    if current_phase == DeploymentPhase.DELETED.value:
        # Already terminal — nothing to do (defensive; CEL rule prevents
        # un-setting the flag, so we should not see updates after Deleted).
        return

    logger.info("Deletion requested via spec for %s/%s — running teardown", ns, name)

    set_phase(patch.status, DeploymentPhase.DELETING, "Cleaning up resources")
    patch.status["displayState"] = DisplayState.DELETING.value

    await _teardown_owned_resources(
        namespace=ns, release_reference=release_ref, name=name, logger=logger
    )
    await _request_namespace_deletion(namespace=ns, logger=logger)

    # The namespace finaliser may take time; the periodic timer
    # (kopf_styrmin_deployment_timer) advances to phase: Deleted once
    # the API server reports 404 for the namespace.


@kopf.on.delete(CRD_GROUP, CRD_VERSION, CRD_PLURAL)
async def kopf_on_styrmin_deployment_delete(
    spec: kopf.Spec,
    status: kopf.Status,
    name: str,
    namespace: str | None,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Manual ``kubectl delete styrmindeployment`` safety-net.

    Runs the teardown pipeline; does NOT produce a backend tombstone
    (out of scope per spec 008). The platform-driven path is handled by
    ``kopf_on_styrmin_deployment_deletion_requested`` instead.
    """
    ns = namespace or ""
    release_ref = spec.get("releaseReference", "")
    logger.info(
        "Deleting StyrminDeployment %s/%s (safety-net path), cleaning up resources",
        ns,
        name,
    )
    set_phase(patch.status, DeploymentPhase.DELETING, "Cleaning up resources")

    await _teardown_owned_resources(
        namespace=ns, release_reference=release_ref, name=name, logger=logger
    )

    logger.info("Cleanup complete for StyrminDeployment %s/%s", ns, name)
