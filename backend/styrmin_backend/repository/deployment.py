from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import select

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.db.models import ApplicationInstance as InstanceModel
from styrmin_backend.db.models import Component as ComponentModel
from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.db.models import DeploymentStatus as DeploymentStatusModel
from styrmin_backend.db.models import InstanceStatus as InstanceStatusModel
from styrmin_backend.domain.models import Component as ComponentEntity
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentStatus as DeploymentStatusEntity
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity
from styrmin_backend.repository.base import BaseRepository
from styrmin_backend.repository.sqlmodel import BaseSQLModelRepository


class DeploymentRepository(BaseRepository[DeploymentModel], ABC):
    """Repository specific to deployments."""

    @abstractmethod
    async def save(self, deployment: DeploymentEntity) -> None:
        raise NotImplementedError(
            "The save method must be implemented in the subclass."
        )

    @abstractmethod
    async def find(self, id: UUID) -> DeploymentEntity | None:
        raise NotImplementedError(
            "The find method must be implemented in the subclass."
        )

    @abstractmethod
    async def get_by_name(self, name: str) -> DeploymentEntity | None:
        raise NotImplementedError(
            "The get_by_name method must be implemented in the subclass."
        )

    @abstractmethod
    async def find_names_with_prefix(self, prefix: str) -> list[str]:
        raise NotImplementedError(
            "The find_names_with_prefix method must be implemented in the subclass."
        )

    @abstractmethod
    async def find_internal_by_environment(
        self, environment_id: UUID
    ) -> DeploymentEntity | None:
        raise NotImplementedError(
            "The find_internal_by_environment method must be implemented in the subclass."
        )


class SQLModelDeploymentRepository(
    BaseSQLModelRepository[DeploymentModel], DeploymentRepository
):
    """The async SQLmodel deployment repository."""

    model_class = DeploymentModel

    def _eager_load_options(self) -> list[Any]:
        """Return options for eager loading all relationships."""
        return [
            selectinload(self.model_class.components),  # type: ignore[arg-type]
            selectinload(self.model_class.active_application_instance),  # type: ignore[arg-type]
        ]

    def _to_model(self, deployment: DeploymentEntity) -> DeploymentModel:
        """Convert a domain model to a SQLModel."""
        components = [
            ComponentModel(
                id=component.id,
                name=component.name,
                enabled=component.enabled,
                deployment_id=deployment.id,
                config=component.config,
            )
            for component in deployment.components
        ]

        # Handle instance mapping
        instance_model = None

        if deployment.active_instance is not None:
            instance_model = InstanceModel(
                id=deployment.active_instance.id,
                name=deployment.active_instance.name,
                application_version=deployment.active_instance.application_version,
                status=InstanceStatusModel(deployment.active_instance.status.value),
                context=deployment.active_instance.context.model_dump(mode="json"),
                deployment_id=deployment.id,
                application_driver_version_id=deployment.active_instance.application_driver_version_id,
            )

        deployment_model = DeploymentModel(
            id=deployment.id,
            name=deployment.name,
            application_version=deployment.application_version,
            config=deployment.config,
            parameters=deployment.parameters or None,
            internal=deployment.internal,
            status=DeploymentStatusModel(deployment.status.value),
            application_driver_version_id=deployment.application_driver_version_id,
            environment_id=deployment.environment_id,
            components=components,
            active_application_instance=instance_model,
        )

        return deployment_model

    async def save(self, deployment: DeploymentEntity) -> None:
        """Save a deployment."""
        model = self._to_model(deployment)
        merged = await self.session.merge(model)
        await self.session.flush()
        # Explicitly set the FK after flush. post_update=True relationships
        # don't reliably sync the FK column through merge(), and setting
        # active_application_instance_id in the constructor causes FK violations
        # due to the circular dependency with ApplicationInstance.
        if deployment.active_instance is not None:
            merged.active_application_instance_id = deployment.active_instance.id
        else:
            merged.active_application_instance_id = None

    def _to_entity(self, entity: DeploymentModel) -> DeploymentEntity:
        """Convert a database model to a domain entity."""
        deployment = DeploymentEntity(
            id=entity.id,
            name=entity.name,
            application_version=entity.application_version,
            config=entity.config,
            parameters=entity.parameters or {},
            internal=entity.internal,
            application_driver_version_id=entity.application_driver_version_id,
            environment_id=entity.environment_id,
            status=DeploymentStatusEntity(entity.status.value),
        )
        for component in entity.components:
            deployment.add_component(
                ComponentEntity(
                    id=component.id,
                    name=component.name,
                    enabled=component.enabled,
                    config=component.config,
                )
            )

        application_instance = None
        active_instance = entity.active_application_instance

        if active_instance is not None:
            application_instance = InstanceEntity(
                id=active_instance.id,
                name=active_instance.name,
                application_version=active_instance.application_version,
                status=InstanceStatusEntity(active_instance.status.value),
                context=GlobalContext.model_validate(active_instance.context),
                application_driver_version_id=active_instance.application_driver_version_id,
                deployment_id=entity.id,
            )
        deployment.set_active_instance(application_instance)

        return deployment

    async def get_by_name(self, name: str) -> DeploymentEntity | None:
        """Get a deployment by its name."""
        result = await self.session.exec(
            select(self.model_class)
            .where(self.model_class.name == name)
            .options(*self._eager_load_options())
        )
        entity = result.first()
        if entity is None:
            return None
        return self._to_entity(entity)

    async def find_names_with_prefix(self, prefix: str) -> list[str]:
        """Find all deployment names matching <prefix>-<digits> pattern."""
        like_pattern = f"{prefix}-%"
        result = await self.session.exec(
            select(self.model_class.name).where(
                self.model_class.name.like(like_pattern)  # type: ignore[union-attr,attr-defined]
            )
        )
        return list(result.all())

    async def find(self, id: UUID) -> DeploymentEntity | None:
        """Get a deployment by id."""
        result = await self.session.exec(
            select(self.model_class)
            .where(self.model_class.id == id)
            .options(*self._eager_load_options())
        )
        entity = result.first()

        if entity is None:
            return None

        return self._to_entity(entity)

    async def find_internal_by_environment(
        self, environment_id: UUID
    ) -> DeploymentEntity | None:
        """Find the internal ingress controller deployment for an environment."""
        result = await self.session.exec(
            select(self.model_class)
            .where(self.model_class.environment_id == environment_id)
            .where(self.model_class.internal == True)  # noqa: E712
            .options(*self._eager_load_options())
        )
        entity = result.first()

        if entity is None:
            return None

        deployment = DeploymentEntity(
            id=entity.id,
            name=entity.name,
            application_version=entity.application_version,
            config=entity.config,
            parameters=entity.parameters or {},
            internal=entity.internal,
            application_driver_version_id=entity.application_driver_version_id,
            environment_id=entity.environment_id,
            status=DeploymentStatusEntity(entity.status.value),
        )
        for component in entity.components:
            deployment.add_component(
                ComponentEntity(
                    id=component.id,
                    name=component.name,
                    enabled=component.enabled,
                    config=component.config,
                )
            )

        application_instance = None
        active_instance = entity.active_application_instance
        if active_instance is not None:
            application_instance = InstanceEntity(
                id=active_instance.id,
                name=active_instance.name,
                application_version=active_instance.application_version,
                status=InstanceStatusEntity(active_instance.status.value),
                context=GlobalContext.model_validate(active_instance.context),
                application_driver_version_id=active_instance.application_driver_version_id,
                deployment_id=entity.id,
            )
        deployment.set_active_instance(application_instance)

        return deployment
