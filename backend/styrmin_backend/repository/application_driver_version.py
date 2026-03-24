from abc import ABC, abstractmethod
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.db.models import ApplicationDriverVersion, HelmChart
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


# FIXME: Update repository for ApplicationDriverVersion to support domain models
class ApplicationDriverVersionRepository(BaseRepository[ApplicationDriverVersion], ABC):
    """Repository specific to applications."""

    @abstractmethod
    async def get_by_supported_versions(
        self, application_driver_id: UUID, versions: str
    ) -> ApplicationDriverVersion | None:
        """Get a helm chart by its version."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_driver_and_version(
        self, application_driver_id: UUID, version: str
    ) -> ApplicationDriverVersion | None:
        """Get a driver version by its driver ID and version string."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_source_path_and_version(
        self, application_driver_id: UUID, source_path: str, version: str
    ) -> ApplicationDriverVersion | None:
        """Get a local driver version by its source path and version string."""
        raise NotImplementedError


class SQLModelApplicationDriverVersionRepository(
    BaseSQLModelRepository[ApplicationDriverVersion], ApplicationDriverVersionRepository
):
    """The async SQLmodel application repository."""

    model_class = ApplicationDriverVersion

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.helm_chart).options(  # type: ignore[arg-type]
                selectinload(HelmChart.repository),  # type: ignore[arg-type]
            ),
            selectinload(self.model_class.component_configs),  # type: ignore[arg-type]
            selectinload(self.model_class.actions),  # type: ignore[arg-type]
            selectinload(self.model_class.application_driver),  # type: ignore[arg-type]
        ]

    async def get(self, id: UUID) -> ApplicationDriverVersion | None:
        """Get an application driver version by its ID with relationships eagerly loaded."""
        statement = (
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_all(self) -> Sequence[ApplicationDriverVersion]:
        """Get all application driver versions with relationships eagerly loaded."""
        statement = select(self.model_class).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.all()

    async def get_by_supported_versions(
        self, application_driver_id: UUID, versions: str
    ) -> ApplicationDriverVersion | None:
        """Get an application by its version."""
        statement = (
            select(self.model_class)
            .where(
                self.model_class.application_supported_versions == versions,
                self.model_class.id == application_driver_id,
            )
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_by_driver_and_version(
        self, application_driver_id: UUID, version: str
    ) -> ApplicationDriverVersion | None:
        """Get a driver version by its driver ID and version string."""
        statement = (
            select(self.model_class)
            .where(
                self.model_class.application_driver_id == application_driver_id,
                self.model_class.version == version,
            )
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()

    async def get_by_source_path_and_version(
        self, application_driver_id: UUID, source_path: str, version: str
    ) -> ApplicationDriverVersion | None:
        """Get a local driver version by its source path and version string."""
        statement = (
            select(self.model_class)
            .where(
                self.model_class.application_driver_id == application_driver_id,
                self.model_class.source_path == source_path,
                self.model_class.version == version,
            )
            .options(*self._eager_load_options())
        )
        result = await self.session.exec(statement)
        return result.first()
