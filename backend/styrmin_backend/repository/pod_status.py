from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import select

from styrmin_backend.db.models import PodStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class PodStatusRepository(BaseRepository[PodStatus], ABC):
    """Repository specific to pod statuses."""

    @abstractmethod
    async def find_by_deployment(self, deployment_id: UUID) -> list[PodStatus]:
        """Get all pod statuses for a deployment."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def upsert(self, pod_status: PodStatus) -> PodStatus:
        """Upsert a pod status by (deployment_id, pod_name)."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def delete_stale(
        self, deployment_id: UUID, active_pod_names: set[str]
    ) -> int:
        """Delete pod statuses for pods no longer present. Returns count of deleted."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def find_by_environment(self, environment_id: UUID) -> list[PodStatus]:
        """Get all pod statuses for an environment."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def find_by_cluster(self, cluster_id: UUID) -> list[PodStatus]:
        """Get all pod statuses for a cluster."""
        raise NotImplementedError("Method not implemented yet.")


class SQLModelPodStatusRepository(
    BaseSQLModelRepository[PodStatus], PodStatusRepository
):
    """The async SQLModel pod status repository."""

    model_class = PodStatus

    async def find_by_deployment(self, deployment_id: UUID) -> list[PodStatus]:
        """Get all pod statuses for a deployment."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == deployment_id
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def upsert(self, pod_status: PodStatus) -> PodStatus:
        """Upsert a pod status by (deployment_id, pod_name)."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == pod_status.deployment_id,
            self.model_class.pod_name == pod_status.pod_name,
        )
        result = await self.session.exec(statement)
        existing = result.first()

        if existing is not None:
            existing.phase = pod_status.phase
            existing.ready = pod_status.ready
            existing.restart_count = pod_status.restart_count
            existing.container_statuses = pod_status.container_statuses
            existing.node_name = pod_status.node_name
            existing.started_at = pod_status.started_at
            existing.last_polled_at = pod_status.last_polled_at
            existing.namespace = pod_status.namespace
            self.session.add(existing)
            return existing

        self.session.add(pod_status)
        await self.session.flush()
        await self.session.refresh(pod_status)
        return pod_status

    async def delete_stale(
        self, deployment_id: UUID, active_pod_names: set[str]
    ) -> int:
        """Delete pod statuses for pods no longer present using a SQL DELETE."""
        stmt = delete(self.model_class).where(
            self.model_class.deployment_id == deployment_id
        )
        if active_pod_names:
            stmt = stmt.where(self.model_class.pod_name.notin_(active_pod_names))  # type: ignore[union-attr]

        result = await self.session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    async def find_by_environment(self, environment_id: UUID) -> list[PodStatus]:
        """Get all pod statuses for an environment via Deployment -> Environment."""
        from styrmin_backend.db.models import Deployment

        statement = (
            select(self.model_class)
            .join(Deployment, self.model_class.deployment_id == Deployment.id)
            .where(Deployment.environment_id == environment_id)
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def find_by_cluster(self, cluster_id: UUID) -> list[PodStatus]:
        """Get all pod statuses for a cluster via Deployment -> Environment -> Cluster."""
        from styrmin_backend.db.models import Deployment, Environment

        statement = (
            select(self.model_class)
            .join(Deployment, self.model_class.deployment_id == Deployment.id)
            .join(Environment, Deployment.environment_id == Environment.id)
            .where(Environment.cluster_id == cluster_id)
        )
        result = await self.session.exec(statement)
        return list(result.all())
