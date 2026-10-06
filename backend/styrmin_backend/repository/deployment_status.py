from abc import ABC, abstractmethod
from collections.abc import Collection
from uuid import UUID

from sqlmodel import col, select

from styrmin_backend.db.models import DeploymentStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class DeploymentStatusRepository(BaseRepository[DeploymentStatus], ABC):
    """Repository specific to deployment status snapshots."""

    @abstractmethod
    async def find_by_deployment(self, deployment_id: UUID) -> DeploymentStatus | None:
        """Get the status snapshot for a deployment."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def find_by_deployments(
        self, deployment_ids: Collection[UUID]
    ) -> list[DeploymentStatus]:
        """Get the status snapshots of several deployments in one query."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def upsert(self, status: DeploymentStatus) -> DeploymentStatus:
        """Upsert a status snapshot by deployment_id."""
        raise NotImplementedError("Method not implemented yet.")


class SQLModelDeploymentStatusRepository(
    BaseSQLModelRepository[DeploymentStatus], DeploymentStatusRepository
):
    """The async SQLModel deployment status repository."""

    model_class = DeploymentStatus

    async def find_by_deployment(self, deployment_id: UUID) -> DeploymentStatus | None:
        """Get the status snapshot for a deployment."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == deployment_id
        )
        result = await self.session.exec(statement)
        return result.first()

    async def find_by_deployments(
        self, deployment_ids: Collection[UUID]
    ) -> list[DeploymentStatus]:
        """Get the status snapshots of several deployments in one query."""
        if not deployment_ids:
            return []
        statement = select(self.model_class).where(
            col(self.model_class.deployment_id).in_(deployment_ids)
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def upsert(self, status: DeploymentStatus) -> DeploymentStatus:
        """Upsert a status snapshot by deployment_id."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == status.deployment_id
        )
        result = await self.session.exec(statement)
        existing = result.first()

        if existing is not None:
            existing.phase = status.phase
            existing.message = status.message
            existing.conditions = status.conditions
            existing.managed_resource_counts = status.managed_resource_counts
            existing.last_polled_at = status.last_polled_at
            self.session.add(existing)
            return existing

        self.session.add(status)
        await self.session.flush()
        await self.session.refresh(status)
        return status
