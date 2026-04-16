from abc import ABC, abstractmethod
from uuid import UUID

from sqlmodel import select

from styrmin_backend.db.models import DeploymentCrdStatus
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class DeploymentCrdStatusRepository(BaseRepository[DeploymentCrdStatus], ABC):
    """Repository specific to deployment CRD statuses."""

    @abstractmethod
    async def find_by_deployment(
        self, deployment_id: UUID
    ) -> DeploymentCrdStatus | None:
        """Get the CRD status for a deployment."""
        raise NotImplementedError("Method not implemented yet.")

    @abstractmethod
    async def upsert(self, crd_status: DeploymentCrdStatus) -> DeploymentCrdStatus:
        """Upsert a CRD status by deployment_id."""
        raise NotImplementedError("Method not implemented yet.")


class SQLModelDeploymentCrdStatusRepository(
    BaseSQLModelRepository[DeploymentCrdStatus], DeploymentCrdStatusRepository
):
    """The async SQLModel deployment CRD status repository."""

    model_class = DeploymentCrdStatus

    async def find_by_deployment(
        self, deployment_id: UUID
    ) -> DeploymentCrdStatus | None:
        """Get the CRD status for a deployment."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == deployment_id
        )
        result = await self.session.exec(statement)
        return result.first()

    async def upsert(self, crd_status: DeploymentCrdStatus) -> DeploymentCrdStatus:
        """Upsert a CRD status by deployment_id."""
        statement = select(self.model_class).where(
            self.model_class.deployment_id == crd_status.deployment_id
        )
        result = await self.session.exec(statement)
        existing = result.first()

        if existing is not None:
            existing.phase = crd_status.phase
            existing.message = crd_status.message
            existing.conditions = crd_status.conditions
            existing.managed_resource_counts = crd_status.managed_resource_counts
            existing.last_polled_at = crd_status.last_polled_at
            self.session.add(existing)
            return existing

        self.session.add(crd_status)
        await self.session.flush()
        await self.session.refresh(crd_status)
        return crd_status
