"""Provides the deployment CRD status services."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from styrmin_backend.db.models import DeploymentCrdStatus, DeploymentStatus
from styrmin_backend.services.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

# CRD displayState to DeploymentStatus mapping.
# The displayState is the user-facing state set by the operator, distinct
# from the internal phase. It is the sole source of truth for Deployment.status.
_DISPLAY_STATE_TO_STATUS: dict[str, DeploymentStatus] = {
    "Deploying": DeploymentStatus.PENDING,
    "Running": DeploymentStatus.RUNNING,
    "Error": DeploymentStatus.FAILED,
}


async def report_crd_statuses(
    reports: list[dict],
    uow: UnitOfWork,
) -> tuple[int, int]:
    """Upsert CRD statuses and update Deployment status based on CRD phase.

    Args:
        reports: List of dicts with keys: deployment_id (UUID), phase (str),
            message (str|None), conditions (list|None),
            managed_resource_counts (dict|None).
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

            crd_status = DeploymentCrdStatus(
                deployment_id=deployment_id,
                phase=phase,
                message=report.get("message"),
                conditions=report.get("conditions"),
                managed_resource_counts=report.get("managed_resource_counts"),
                last_polled_at=now,
            )
            await uow.deployment_crd_statuses.upsert(crd_status)
            statuses_updated += 1

            # Update Deployment status based on CRD displayState.
            # While a task is still in flight (e.g., an UPGRADE_INSTANCE hook
            # is running stop/start_components sub-steps), the CRD can
            # briefly transition to Running between nested pipeline runs.
            # Suppress the RUNNING override until no active task remains so
            # callers don't see a premature "running" state.
            target_status = _DISPLAY_STATE_TO_STATUS.get(display_state)
            if target_status is not None:
                deployment = await uow.deployments.find(deployment_id)
                if deployment is not None and deployment.status != target_status.value:
                    if target_status == DeploymentStatus.RUNNING and (
                        await uow.tasks.has_active_for_deployment(deployment_id)
                    ):
                        continue
                    deployment.status = target_status
                    await uow.deployments.save(deployment)
                    deployments_updated += 1

        await uow.commit()
        return statuses_updated, deployments_updated


async def get_deployment_crd_status(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> DeploymentCrdStatus | None:
    """Get the latest CRD status for a deployment."""
    async with uow:
        return await uow.deployment_crd_statuses.find_by_deployment(deployment_id)
