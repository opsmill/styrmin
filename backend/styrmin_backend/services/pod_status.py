"""Provides the pod status services."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from styrmin_backend.db.models import PodPhase, PodStatus
from styrmin_backend.services.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

# Valid pod phases for mapping unknown values
_VALID_PHASES = {phase.value for phase in PodPhase}


def _parse_phase(phase_str: str) -> PodPhase:
    """Parse a phase string into a PodPhase enum, falling back to UNKNOWN."""
    if phase_str in _VALID_PHASES:
        return PodPhase(phase_str)
    logger.warning("Unknown pod phase '%s', mapping to UNKNOWN", phase_str)
    return PodPhase.UNKNOWN


async def report_pod_statuses(
    reports: list[dict],
    uow: UnitOfWork,
) -> tuple[int, int]:
    """Upsert pod statuses for multiple deployments in a single transaction.

    Args:
        reports: List of dicts with keys: deployment_id (UUID), pods (list[dict]).
            Each pod dict has: pod_name, namespace, phase, ready, restart_count,
            container_statuses, node_name, started_at.
        uow: Unit of work for database operations.

    Returns:
        Tuple of (total_updated, total_removed).
    """
    async with uow:
        now = datetime.now(tz=timezone.utc)
        total_updated = 0
        total_removed = 0

        for report in reports:
            deployment_id = report["deployment_id"]
            pods = report["pods"]

            for pod_data in pods:
                pod_status = PodStatus(
                    deployment_id=deployment_id,
                    pod_name=pod_data["pod_name"],
                    namespace=pod_data["namespace"],
                    phase=_parse_phase(pod_data["phase"]),
                    ready=pod_data["ready"],
                    restart_count=pod_data["restart_count"],
                    container_statuses=pod_data.get("container_statuses"),
                    node_name=pod_data.get("node_name"),
                    started_at=pod_data.get("started_at"),
                    last_polled_at=now,
                )
                await uow.pod_statuses.upsert(pod_status)
                total_updated += 1

            active_pod_names = {pod["pod_name"] for pod in pods}
            removed = await uow.pod_statuses.delete_stale(
                deployment_id, active_pod_names
            )
            total_removed += removed

        await uow.commit()
        return total_updated, total_removed


async def get_pod_statuses(
    uow: UnitOfWork,
    deployment_id: UUID | None = None,
    environment_id: UUID | None = None,
    cluster_id: UUID | None = None,
) -> list[PodStatus]:
    """Get pod statuses with optional filtering.

    When no filter is provided, returns all pod statuses.
    """
    async with uow:
        if deployment_id is not None:
            return await uow.pod_statuses.find_by_deployment(deployment_id)
        if environment_id is not None:
            return await uow.pod_statuses.find_by_environment(environment_id)
        if cluster_id is not None:
            return await uow.pod_statuses.find_by_cluster(cluster_id)
        return list(await uow.pod_statuses.get_all())
