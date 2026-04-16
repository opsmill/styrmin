"""Provides the deployment CRD status services."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from styrmin_backend.db.models import DeploymentCrdStatus, DeploymentStatus
from styrmin_backend.services.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

# CRD phase to DeploymentStatus mapping per FR-004
_PHASE_TO_STATUS: dict[str, DeploymentStatus] = {
    "Pending": DeploymentStatus.PENDING,
    "CreatingPrerequisites": DeploymentStatus.PENDING,
    "CreatingHelmRelease": DeploymentStatus.PENDING,
    "CreatingServices": DeploymentStatus.PENDING,
    "Ready": DeploymentStatus.RUNNING,
    "Failed": DeploymentStatus.FAILED,
}

# "Deleting" intentionally excluded — no status change


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

            # Update Deployment status based on CRD phase mapping
            target_status = _PHASE_TO_STATUS.get(phase)
            if target_status is not None:
                deployment = await uow.deployments.find(deployment_id)
                if deployment is not None and deployment.status != target_status.value:
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
