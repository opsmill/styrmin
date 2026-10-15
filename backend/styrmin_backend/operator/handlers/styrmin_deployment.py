"""Kopf handlers for StyrminDeployment CRD lifecycle.

Watches StyrminDeployment create/update/delete/resume events and
orchestrates the ordered deployment pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import kopf

from styrmin_backend import config
from styrmin_backend.operator.config import (
    ANNOTATION_SKIP_TEARDOWN,
    CRD_GROUP,
    CRD_PLURAL,
    CRD_VERSION,
)
from styrmin_backend.operator.crd.schema import (
    ConditionStatus,
    ConditionType,
    DeploymentPhase,
    DisplayState,
)
from styrmin_backend.operator.crd.status import (
    get_condition,
    is_condition_true,
    remove_condition,
    replace_condition,
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

if TYPE_CHECKING:
    from styrmin_backend.operator.reconciler import FluxEvent, HelmReleaseObservation

#: Phases of a rollout in progress, which the readiness timeout watches.
_ROLLOUT_PHASES = frozenset(
    {
        DeploymentPhase.PENDING.value,
        DeploymentPhase.CREATING_PREREQUISITES.value,
        DeploymentPhase.CREATING_HELM_RELEASE.value,
        DeploymentPhase.CREATING_SERVICES.value,
    }
)


def _is_internal(spec: dict[str, Any]) -> bool:
    """Check if a StyrminDeployment is an internal deployment (e.g., ingress controller)."""
    return spec.get("internal", False)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _start_rollout(conditions: list[dict[str, str]], patch: Any) -> None:
    """Forget the previous rollout's HelmRelease state and record when this one started (research D5)."""
    set_condition(
        conditions,
        ConditionType.HELM_RELEASE_READY,
        ConditionStatus.UNKNOWN,
        "Progressing",
        "Waiting for FluxCD to apply the HelmRelease",
    )
    remove_condition(conditions, ConditionType.HELM_RELEASE_REMEDIATED)
    patch.status["conditions"] = conditions
    patch.status["rolloutStartedAt"] = _now()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _rollout_started_at(status: Any, body: Any) -> datetime | None:
    """``status.rolloutStartedAt``, else the CR's creation time for a CR from an older operator."""
    return _parse_time(status.get("rolloutStartedAt")) or _parse_time(
        body.get("metadata", {}).get("creationTimestamp")
    )


def _seconds_to_ready_timeout(status: Any, body: Any) -> float | None:
    """Seconds left before the rollout's readiness timeout (negative once passed)."""
    started_at = _rollout_started_at(status, body)
    if started_at is None:
        return None
    elapsed = (datetime.now(tz=UTC) - started_at).total_seconds()
    return config.SETTINGS.operator.deployment_ready_timeout - elapsed


#: Wait this long past the readiness timeout, so the check after the wait sees it passed.
_READY_TIMEOUT_MARGIN_SECONDS = 1.0


async def _wait_for_ready_timeout(
    spec: Any, status: Any, body: Any, stopped: kopf.DaemonStopped
) -> None:
    """Wait past the readiness timeout when the next timer run would come after it."""
    phase = status.get("phase", DeploymentPhase.PENDING.value)
    if phase not in _ROLLOUT_PHASES or spec.get("deletionRequested", False):
        return
    remaining = _seconds_to_ready_timeout(status, body)
    if remaining is None or remaining <= 0:
        return
    delay = remaining + _READY_TIMEOUT_MARGIN_SECONDS
    if delay < config.SETTINGS.operator.reconcile_interval:
        await stopped.wait(delay)


@contextmanager
def _recording_instance(spec: dict[str, Any], patch: Any) -> Iterator[None]:
    """Write the handled ``spec.instanceId`` to ``status.instanceId``, also when the handler raises.

    The status reporter sends it, so a report names the instance the operator acted on.
    """
    try:
        yield
    finally:
        instance_id = spec.get("instanceId")
        if instance_id:
            patch.status["instanceId"] = instance_id


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
    _fail_on_guard(
        failure,
        conditions=conditions,
        namespace=namespace,
        name=name,
        patch=patch,
        logger=logger,
    )
    return True


def _fail_on_guard(
    failure: tuple[str, str],
    *,
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> None:
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
    # A guard failure after Ready must not leave Ready=True next to phase Failed.
    set_condition(
        conditions,
        ConditionType.READY,
        ConditionStatus.FALSE,
        "ComponentContainerNotFound",
        message,
    )
    patch.status["conditions"] = conditions
    set_phase(patch.status, DeploymentPhase.FAILED, message)
    patch.status["displayState"] = DisplayState.ERROR.value
    logger.warning("Deployment %s/%s failed: %s", namespace, name, message)


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

    conditions: list[dict[str, str]] = list(status.get("conditions", []))
    _start_rollout(conditions, patch)

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
                f"HelmRelease creation failed: {result.errors}",
                delay=config.SETTINGS.operator.retry_delay,
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
                f"HelmRelease creation failed: {hr_result.errors}",
                delay=config.SETTINGS.operator.retry_delay,
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
            delay=config.SETTINGS.operator.retry_delay,
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

    # Continues the rollout: keep its start so a restart does not extend the readiness timeout.
    if phase in _ROLLOUT_PHASES and not status.get("rolloutStartedAt"):
        patch.status["rolloutStartedAt"] = _now()

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
                    f"HelmRelease resume failed: {result.errors}",
                    delay=config.SETTINGS.operator.retry_delay,
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
                    f"Phase 1 resume failed: {result.errors}",
                    delay=config.SETTINGS.operator.retry_delay,
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
                    f"Phase 2 resume failed: {result.errors}",
                    delay=config.SETTINGS.operator.retry_delay,
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
    with _recording_instance(dict(spec), patch):
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
    with _recording_instance(dict(spec), patch):
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

    with _recording_instance(crd_spec, patch):
        await _roll_out_spec_update(
            crd_spec=crd_spec,
            status=status,
            name=name,
            ns=ns,
            patch=patch,
            logger=logger,
        )


async def _roll_out_spec_update(
    *,
    crd_spec: dict[str, Any],
    status: Any,
    name: str,
    ns: str,
    patch: Any,
    logger: Any,
) -> None:
    """Re-run the ordered pipeline for a changed spec."""
    logger.info("StyrminDeployment spec updated: %s/%s, re-reconciling", ns, name)

    patch.status["displayState"] = DisplayState.DEPLOYING.value

    conditions: list[dict[str, str]] = list(status.get("conditions", []))
    _start_rollout(conditions, patch)

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
                f"HelmRelease update failed: {result.errors}",
                delay=config.SETTINGS.operator.retry_delay,
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
                f"HelmRelease update failed: {hr_result.errors}",
                delay=config.SETTINGS.operator.retry_delay,
            )
    else:
        set_phase(
            patch.status, DeploymentPhase.FAILED, f"Update failed: {result.errors}"
        )
        patch.status["displayState"] = DisplayState.ERROR.value
        raise kopf.TemporaryError(
            f"Phase 1 update failed: {result.errors}",
            delay=config.SETTINGS.operator.retry_delay,
        )


# --- The HelmRelease's current generation (spec 019, research D5) ---


async def _wait_for_helm_release(
    *,
    crd_spec: dict[str, Any],
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> bool:
    """Return True once FluxCD reports the HelmRelease's current generation Ready.

    An internal deployment is also ready when one of its pods is. Until then, copy FluxCD's
    readiness and remediation into the CR conditions, writing them only when they change, and
    fail the CR when FluxCD stalled, or reports Ready for its rollback of this generation.
    """
    from styrmin_backend.operator.reconciler import (
        _check_any_pod_ready,
        observe_helmrelease,
    )

    observation = await observe_helmrelease(
        namespace=namespace, release_reference=crd_spec.get("releaseReference", "")
    )
    if observation is not None and observation.guard_failure is not None:
        _fail_on_guard(
            observation.guard_failure,
            conditions=conditions,
            namespace=namespace,
            name=name,
            patch=patch,
            logger=logger,
        )
        return False
    if observation is not None and observation.skipped_failure is not None:
        _fail_on_skipped_failure(
            observation.skipped_failure,
            conditions=conditions,
            namespace=namespace,
            name=name,
            patch=patch,
            logger=logger,
        )
        return False

    changed = observation is not None and _copy_remediation(conditions, observation)
    rolled_back = observation is not None and observation.is_ready_after_rollback
    ready = observation is not None and observation.is_ready and not rolled_back
    # For internal deployments (e.g., ingress controller), also accept running pods as "ready" — the
    # HelmRelease may stay in Unknown/Progressing if a LoadBalancer can't get an external IP.
    if not ready and _is_internal(crd_spec):
        ready = await _check_any_pod_ready(namespace=namespace)

    if not ready and rolled_back and observation is not None:
        _fail_on_rollback(
            observation,
            conditions=conditions,
            namespace=namespace,
            name=name,
            patch=patch,
            logger=logger,
        )
        return False
    if ready:
        if not is_condition_true(conditions, ConditionType.HELM_RELEASE_READY):
            set_condition(
                conditions,
                ConditionType.HELM_RELEASE_READY,
                ConditionStatus.TRUE,
                "FluxReady",
                "HelmRelease is Ready",
            )
            changed = True
    elif observation is not None:
        changed = _copy_readiness(conditions, observation) or changed
        if observation.stalled is not None:
            _fail_on_stalled(
                observation,
                conditions=conditions,
                namespace=namespace,
                name=name,
                patch=patch,
                logger=logger,
            )
            return False
    if changed:
        patch.status["conditions"] = conditions
    return ready


def _copy_readiness(
    conditions: list[dict[str, str]], observation: HelmReleaseObservation
) -> bool:
    """Copy FluxCD's ``Ready`` of the current generation into ``HelmReleaseReady``.

    The reason and message name the failure when there is one. Nothing is copied before
    FluxCD has observed the generation.
    """
    ready = observation.ready
    if ready is None:
        return False
    source = observation.failure or ready
    return replace_condition(
        conditions,
        {
            "type": ConditionType.HELM_RELEASE_READY.value,
            "status": ready.status,
            "reason": source.reason,
            "message": source.message,
            "lastTransitionTime": ready.last_transition_time,
        },
    )


def _copy_remediation(
    conditions: list[dict[str, str]], observation: HelmReleaseObservation
) -> bool:
    """Copy FluxCD's ``Remediated=True`` of the current generation into ``HelmReleaseRemediated``."""
    remediated = observation.remediated
    if remediated is None:
        return False
    return replace_condition(
        conditions,
        {
            "type": ConditionType.HELM_RELEASE_REMEDIATED.value,
            "status": remediated.status,
            "reason": remediated.reason,
            "message": remediated.message,
            "lastTransitionTime": remediated.last_transition_time,
        },
    )


def _fail_on_stalled(
    observation: HelmReleaseObservation,
    *,
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> None:
    """FluxCD used all its retries on the current generation, so the rollout failed."""
    stalled = observation.stalled
    if stalled is None:
        return
    message = stalled.message
    failure = observation.failure
    if failure is not None and failure.message and failure.message != stalled.message:
        message = f"{stalled.message}: {failure.message}"
    # Phase Failed must not sit next to Ready=True of the previous rollout.
    set_condition(
        conditions,
        ConditionType.READY,
        ConditionStatus.FALSE,
        stalled.reason or "Stalled",
        message,
    )
    patch.status["conditions"] = conditions
    set_phase(patch.status, DeploymentPhase.FAILED, message)
    patch.status["displayState"] = DisplayState.ERROR.value
    logger.warning("Deployment %s/%s failed: %s", namespace, name, message)


def _fail_on_rollback(
    observation: HelmReleaseObservation,
    *,
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> None:
    """FluxCD rolled back this generation's failed release and stopped, so the rollout failed.

    ``HelmReleaseReady`` keeps FluxCD's failure when the timer copied one; it names the cause.
    """
    message = (
        f"FluxCD rolled the release back after release"
        f" v{observation.rolled_back_version} failed"
    )
    hr_ready = get_condition(conditions, ConditionType.HELM_RELEASE_READY.value)
    if (
        hr_ready is not None
        and hr_ready.get("status") == ConditionStatus.FALSE.value
        and str(hr_ready.get("reason") or "").endswith("Failed")
        and hr_ready.get("message")
    ):
        message = f"{message}: {hr_ready['message']}"
    else:
        set_condition(
            conditions,
            ConditionType.HELM_RELEASE_READY,
            ConditionStatus.FALSE,
            "RolledBack",
            message,
        )
    # Phase Failed must not sit next to Ready=True of the previous rollout.
    set_condition(
        conditions, ConditionType.READY, ConditionStatus.FALSE, "RolledBack", message
    )
    patch.status["conditions"] = conditions
    set_phase(patch.status, DeploymentPhase.FAILED, message)
    patch.status["displayState"] = DisplayState.ERROR.value
    logger.warning("Deployment %s/%s failed: %s", namespace, name, message)


def _fail_on_skipped_failure(
    failure: FluxEvent,
    *,
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> None:
    """FluxCD reported Ready after an install or upgrade of this generation failed without a release.

    FluxCD does not retry, so the change never reaches the cluster.
    """
    message = f"FluxCD reported the release in sync after the change failed: {failure.message}"
    set_condition(
        conditions,
        ConditionType.HELM_RELEASE_READY,
        ConditionStatus.FALSE,
        failure.reason,
        failure.message,
    )
    # Phase Failed must not sit next to Ready=True of the previous rollout.
    set_condition(
        conditions, ConditionType.READY, ConditionStatus.FALSE, failure.reason, message
    )
    patch.status["conditions"] = conditions
    set_phase(patch.status, DeploymentPhase.FAILED, message)
    patch.status["displayState"] = DisplayState.ERROR.value
    logger.warning("Deployment %s/%s failed: %s", namespace, name, message)


async def _advance_past_helm_release(
    *,
    crd_spec: dict[str, Any],
    conditions: list[dict[str, str]],
    namespace: str,
    name: str,
    patch: Any,
    logger: Any,
) -> None:
    """Create the services once the HelmRelease is Ready; an internal deployment is then Ready."""
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
        logger.info("Internal deployment %s/%s reached Ready state", namespace, name)
        return

    set_phase(
        patch.status,
        DeploymentPhase.CREATING_SERVICES,
        "HelmRelease ready, creating Services",
    )

    result = await execute_phase_services(crd_spec=crd_spec, namespace=namespace)
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
        logger.info("Deployment %s/%s reached Ready state", namespace, name)


# --- Timer for drift detection and phase advancement (US3) ---


@kopf.timer(
    CRD_GROUP,
    CRD_VERSION,
    CRD_PLURAL,
    interval=config.SETTINGS.operator.reconcile_interval,
    initial_delay=config.SETTINGS.operator.reconcile_interval,
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
    stopped: kopf.DaemonStopped,
    **_: Any,
) -> None:
    """Periodic reconciliation: advance phases and detect drift."""
    # kopf keeps a timer's body, spec and status up to date, so after the wait the tick reads the
    # CR as it is at the readiness timeout.
    await _wait_for_ready_timeout(spec, status, body, stopped)
    if stopped:
        return
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
        remaining = _seconds_to_ready_timeout(status, body)
        if remaining is not None and remaining < 0:
            ready_timeout = config.SETTINGS.operator.deployment_ready_timeout
            current_display = status.get("displayState", DisplayState.DEPLOYING.value)
            if current_display != DisplayState.ERROR.value:
                patch.status["displayState"] = DisplayState.ERROR.value
                patch.status["message"] = (
                    f"Deployment did not reach Ready within"
                    f" {ready_timeout}s (phase: {phase})"
                )
                logger.warning(
                    "Deployment %s/%s timed out in phase %s", ns, name, phase
                )

    # Phase advancement for in-progress deployments
    if phase == DeploymentPhase.CREATING_HELM_RELEASE.value:
        if await _wait_for_helm_release(
            crd_spec=crd_spec,
            conditions=conditions,
            namespace=ns,
            name=name,
            patch=patch,
            logger=logger,
        ):
            await _advance_past_helm_release(
                crd_spec=crd_spec,
                conditions=conditions,
                namespace=ns,
                name=name,
                patch=patch,
                logger=logger,
            )
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
    annotations: kopf.Annotations,
    patch: kopf.Patch,
    logger: kopf.Logger,
    **_: Any,
) -> None:
    """Manual ``kubectl delete styrmindeployment`` safety-net.

    Runs the teardown pipeline; does NOT produce a backend tombstone
    (out of scope per spec 008). The platform-driven path is handled by
    ``kopf_on_styrmin_deployment_deletion_requested`` instead.

    A CR annotated with ``ANNOTATION_SKIP_TEARDOWN`` is deleted without
    teardown: a cross-target restore discards its restored copy of the
    source's CR, whose resources now belong to the counterpart CR.
    """
    ns = namespace or ""
    # A new value on every run, so the patch always makes an event: kopf then checks again
    # for a timer run that has not ended, instead of keeping the finalizer (#446, #461).
    patch.status["deletionHandledAt"] = _now()
    if annotations.get(ANNOTATION_SKIP_TEARDOWN) == "true":
        logger.info(
            "Deleting StyrminDeployment %s/%s without teardown (%s)",
            ns,
            name,
            ANNOTATION_SKIP_TEARDOWN,
        )
        return

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
