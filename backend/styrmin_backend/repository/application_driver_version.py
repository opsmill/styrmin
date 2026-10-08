from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select

from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    Deployment,
    HelmChart,
)
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


@dataclass(frozen=True)
class DriverVersionUsage:
    """One driver version and its live deployment count, without its source location."""

    name: str
    version: str
    source_type: str
    deployment_count: int


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
    async def get_by_identity(
        self,
        *,
        application_driver_id: UUID,
        source_type: str,
        source_repository: str,
        source_branch: str | None,
        source_path: str | None,
        version: str,
        content_hash: str | None,
        source_commit_sha: str | None,
    ) -> ApplicationDriverVersion | None:
        """Get an application driver version by its full identity tuple.

        The identity is widened (per spec 013) to include a provenance
        fingerprint: ``content_hash`` for ``source_type == "local"`` and
        ``source_commit_sha`` for ``source_type == "git"``. Two rows with
        the same (driver, source, version) but distinct fingerprints are
        distinct identities. Nullable identity columns use ``IS NULL`` to
        mirror the UNIQUE-index ``nulls_not_distinct`` semantics.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_usage(self) -> list[DriverVersionUsage]:
        """Return one row per driver version with its live deployment count."""
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

    async def get_by_identity(
        self,
        *,
        application_driver_id: UUID,
        source_type: str,
        source_repository: str,
        source_branch: str | None,
        source_path: str | None,
        version: str,
        content_hash: str | None,
        source_commit_sha: str | None,
    ) -> ApplicationDriverVersion | None:
        """Get an application driver version by its full identity tuple."""
        m = self.model_class
        conditions: list[Any] = [
            m.application_driver_id == application_driver_id,
            m.source_type == source_type,
            m.source_repository == source_repository,
            m.version == version,
        ]
        # Nullable identity columns use IS NULL when the lookup value is
        # None, mirroring the UNIQUE index's ``nulls_not_distinct`` semantics
        # introduced in T006.
        for column, value in (
            (m.source_branch, source_branch),
            (m.source_path, source_path),
            (m.content_hash, content_hash),
            (m.source_commit_sha, source_commit_sha),
        ):
            conditions.append(column.is_(None) if value is None else column == value)
        statement = select(m).where(*conditions).options(*self._eager_load_options())
        result = await self.session.exec(statement)
        return result.first()

    async def list_usage(self) -> list[DriverVersionUsage]:
        """Return one row per driver version with its live deployment count.

        The source repository, branch, path and fingerprint are not selected
        (spec 020, FR-002).
        """
        version = self.model_class
        statement = (
            select(
                ApplicationDriver.name,
                version.version,
                version.source_type,
                func.count(col(Deployment.id)),
            )
            .select_from(version)
            .join(
                ApplicationDriver,
                col(ApplicationDriver.id) == col(version.application_driver_id),
            )
            .outerjoin(
                Deployment,
                and_(
                    col(Deployment.application_driver_version_id) == col(version.id),
                    col(Deployment.deleted_at).is_(None),
                ),
            )
            .group_by(
                col(version.id),
                col(ApplicationDriver.name),
                col(version.version),
                col(version.source_type),
            )
        )
        result = await self.session.exec(statement)
        return [
            DriverVersionUsage(
                name=name,
                version=driver_version,
                source_type=source_type,
                deployment_count=deployment_count,
            )
            for name, driver_version, source_type, deployment_count in result.all()
        ]
