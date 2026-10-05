"""Provides the deployment status services."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from loguru import logger

from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.db.models import DeploymentState, DeploymentStatus
from styrmin_backend.services.backup.service import find_in_flight_restore
from styrmin_backend.services.unit_of_work import UnitOfWork

# CRD displayState to DeploymentState mapping.
# The displayState is the user-facing state set by the operator, distinct
# from the internal phase. It is the sole source of truth for Deployment.status.
_DISPLAY_STATE_TO_STATUS: dict[str, DeploymentState] = {
    "Deploying": DeploymentState.DEPLOYING,
    "Running": DeploymentState.RUNNING,
    "Restoring": DeploymentState.RESTORING,
    "Error": DeploymentState.FAILED,
    "Deleting": DeploymentState.DELETING,
    "Deleted": DeploymentState.DELETED,
}


async def report_deployment_statuses(
    reports: list[dict],
    uow: UnitOfWork,
) -> tuple[int, int]:
    """Upsert deployment status snapshots and update Deployment state based on CRD phase.

    A status report carries the ``instance_id`` that was on the CRD at poll
    time. The server updates ``deployment.status`` only when that id matches
    the current ``deployment.active_application_instance_id``; otherwise the
    report is for a superseded instance (e.g. the previous version during an
    in-progress upgrade) and must not be allowed to overwrite the status of
    the new instance still rolling out. Reports with ``instance_id=None``
    (legacy CRDs without the field) bypass the guard for backward compat.

    A deployment in ``RESTORING`` with a non-terminal restore keeps that state
    whatever the report says: the restore workflow sets the final state. The
    CR only reads ``Restoring`` once Velero has finished, so reports sent
    earlier carry the pre-restore ``Running``, the teardown's ``Deleting``, or
    the ``Deploying`` default of the status-less CR that Velero recreates.

    Args:
        reports: List of dicts with keys: deployment_id (UUID), phase (str),
            instance_id (UUID|None), display_state (str|None), message (str|None),
            conditions (list|None), managed_resource_counts (dict|None).
        uow: Unit of work for database operations.

    Returns:
        Tuple of (statuses_updated, deployments_updated).
    """
    async with uow:
        now = datetime.now(tz=timezone.utc)
        statuses_updated = 0
        deployments_updated = 0

        for report in reports:
            deployment_id = report["deployment_id"]
            phase = report["phase"]
            display_state = report.get("display_state", "Deploying")
            reported_instance_id: UUID | None = report.get("instance_id")

            snapshot = DeploymentStatus(
                deployment_id=deployment_id,
                phase=phase,
                message=report.get("message"),
                conditions=report.get("conditions"),
                managed_resource_counts=report.get("managed_resource_counts"),
                last_polled_at=now,
            )
            await uow.deployment_statuses.upsert(snapshot)
            statuses_updated += 1

            # Update Deployment state based on CRD displayState
            target_state = _DISPLAY_STATE_TO_STATUS.get(display_state)
            if target_state is None:
                continue

            deployment = await uow.deployments.find(deployment_id)
            if deployment is None:
                continue

            # Stale-instance guard: ignore reports for an instance that is no
            # longer the active one on the deployment.
            active_instance = deployment.active_instance
            active_instance_id = active_instance.id if active_instance else None
            if (
                reported_instance_id is not None
                and active_instance_id is not None
                and reported_instance_id != active_instance_id
            ):
                logger.info(
                    "Skipping status update for deployment {}: reported instance {} "
                    "does not match active instance {}",
                    deployment_id,
                    reported_instance_id,
                    active_instance_id,
                )
                continue

            if (
                deployment.status == DeploymentState.RESTORING
                and target_state != DeploymentState.RESTORING
                and await find_in_flight_restore(
                    uow,
                    deployment_id=deployment_id,
                    target_namespace=get_kubernetes_reference(deployment_id),
                )
                is not None
            ):
                logger.info(
                    "Skipping status update for deployment {}: a restore is in "
                    "progress, ignoring reported state {}",
                    deployment_id,
                    display_state,
                )
                continue

            if deployment.status != target_state.value:
                # On the transition into DELETED, atomically tombstone the
                # deployment by stamping deleted_at. This is the *only* code
                # path that writes deleted_at, ensuring readers cannot observe
                # status == DELETED with a NULL deleted_at.
                if (
                    target_state == DeploymentState.DELETED
                    and deployment.deleted_at is None
                ):
                    deployment.deleted_at = now
                    # A tombstoned deployment no longer participates in the
                    # environment, so its DeployedService rows must go too.
                    # They are operational discovery/uniqueness state (not
                    # audit data); leaving them orphaned would (a) block a
                    # later deployment from reclaiming the same service name
                    # and (b) leak ghost services into other deployments'
                    # service-discovery context. The deployment row itself is
                    # retained for history/backups. Inline import mirrors the
                    # upgrade path in deployment.py to avoid a circular import.
                    from styrmin_backend.services.services_discovery import (
                        delete_services_for_deployment,
                    )

                    await delete_services_for_deployment(
                        deployment_id=deployment.id, uow=uow
                    )
                deployment.status = target_state
                await uow.deployments.save(deployment)
                deployments_updated += 1

        await uow.commit()
        return statuses_updated, deployments_updated


async def get_deployment_status(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> DeploymentStatus | None:
    """Get the latest status snapshot for a deployment."""
    async with uow:
        return await uow.deployment_statuses.find_by_deployment(deployment_id)


#: Substrings that mark a Kubernetes pod condition / event message as
#: scheduling-related. Matched case-insensitively against condition messages
#: so the deployment status view can highlight unsatisfied affinity or
#: toleration rules (FR-018).
_SCHEDULING_MESSAGE_MARKERS: tuple[str, ...] = (
    "affinity",
    "anti-affinity",
    "antiaffinity",
    "taint",
    "toleration",
    "topology",
    "runtimeclass",
    "runtime class",
    "nodeaffinity",
    "node(s) didn't match",
)


def extract_scheduling_conditions(
    conditions: list[dict] | None,
) -> list[dict]:
    """Pull scheduling-related entries out of a status ``conditions`` list.

    Returns entries whose ``message`` matches any of the scheduling marker
    substrings (case-insensitive). Each returned entry carries the original
    condition payload unchanged plus a ``scheduling: True`` marker so the
    rendering surface can pick it out. Non-scheduling conditions are dropped.
    """
    if not conditions:
        return []
    out: list[dict] = []
    for cond in conditions:
        message = str(cond.get("message") or "").lower()
        reason = str(cond.get("reason") or "").lower()
        if any(
            marker in message or marker in reason
            for marker in _SCHEDULING_MESSAGE_MARKERS
        ):
            out.append({**cond, "scheduling": True})
    return out
