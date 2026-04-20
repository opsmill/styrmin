"""Provides the deployment status services."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from styrmin_backend.db.models import DeploymentState, DeploymentStatus
from styrmin_backend.services.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

# CRD displayState to DeploymentState mapping.
# The displayState is the user-facing state set by the operator, distinct
# from the internal phase. It is the sole source of truth for Deployment.status.
_DISPLAY_STATE_TO_STATUS: dict[str, DeploymentState] = {
    "Deploying": DeploymentState.DEPLOYING,
    "Running": DeploymentState.RUNNING,
    "Error": DeploymentState.FAILED,
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
                    "Skipping status update for deployment %s: reported instance %s "
                    "does not match active instance %s",
                    deployment_id,
                    reported_instance_id,
                    active_instance_id,
                )
                continue

            if deployment.status != target_state.value:
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
