from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.db.models import ApplicationInstance as InstanceModel
from styrmin_backend.db.models import Component as ComponentModel
from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.db.models import DeploymentState as DeploymentStateModel
from styrmin_backend.db.models import InstanceStatus as InstanceStatusModel
from styrmin_backend.domain.models import Component as ComponentEntity
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentReferenceTarget
from styrmin_backend.domain.models import DeploymentState as DeploymentStateEntity
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
    async def find_reference_target(self, id: UUID) -> DeploymentReferenceTarget | None:
        """Return the id, name, environment and tombstone of a deployment, tombstones included."""
        raise NotImplementedError(
            "The find_reference_target method must be implemented in the subclass."
        )

    @abstractmethod
    async def get_by_name(
        self,
        name: str,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> DeploymentEntity | None:
        raise NotImplementedError(
            "The get_by_name method must be implemented in the subclass."
        )

    @abstractmethod
    async def find_one_by_name_and_environment(
        self,
        name: str,
        environment_id: UUID,
    ) -> DeploymentEntity | None:
        raise NotImplementedError(
            "The find_one_by_name_and_environment method must be implemented "
            "in the subclass."
        )

    @abstractmethod
    async def find_names_with_prefix(
        self,
        prefix: str,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> list[str]:
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

    @abstractmethod
    async def find_all_by_environment(
        self,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> list[DeploymentEntity]:
        raise NotImplementedError(
            "The find_all_by_environment method must be implemented in the subclass."
        )

    @abstractmethod
    async def delete_all_for_environment(self, environment_id: UUID) -> list[UUID]:
        raise NotImplementedError(
            "The delete_all_for_environment method must be implemented in the subclass."
        )

    @abstractmethod
    async def count_live(self) -> int:
        """Return the number of deployments that are not tombstoned."""
        raise NotImplementedError(
            "The count_live method must be implemented in the subclass."
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
                sequence=deployment.active_instance.sequence,
            )

        deployment_model = DeploymentModel(
            id=deployment.id,
            name=deployment.name,
            application_version=deployment.application_version,
            config=deployment.config,
            parameters=deployment.parameters or None,
            internal=deployment.internal,
            status=DeploymentStateModel(deployment.status.value),
            deleted_at=deployment.deleted_at,
            application_driver_version_id=deployment.application_driver_version_id,
            environment_id=deployment.environment_id,
            created_by_user_id=deployment.created_by_user_id,
            components=components,
            active_application_instance=instance_model,
        )

        return deployment_model

    async def save(self, deployment: DeploymentEntity) -> None:
        """Save a deployment, numbering its active instance when it is new."""
        instance = deployment.active_instance
        new_deployment_sequence = None
        if instance is not None and instance.sequence is None:
            sequence = await self._increment_instance_sequence(deployment.id)
            if sequence is None:  # The deployment row does not exist yet.
                sequence = new_deployment_sequence = 1
            deployment.set_active_instance(
                instance.model_copy(update={"sequence": sequence})
            )
        model = self._to_model(deployment)
        if new_deployment_sequence is not None:
            model.last_instance_sequence = new_deployment_sequence
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

    async def _increment_instance_sequence(self, deployment_id: UUID) -> int | None:
        """Increment the deployment's instance counter; None when the row does not exist.

        The UPDATE keeps the row locked until the transaction ends, so sequences
        follow the order in which the instances are committed (#386).
        """
        result = await self.session.exec(
            update(self.model_class)
            .where(col(self.model_class.id) == deployment_id)
            .values(
                last_instance_sequence=col(self.model_class.last_instance_sequence) + 1
            )
            .returning(col(self.model_class.last_instance_sequence))
        )
        return result.scalar_one_or_none()

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
            status=DeploymentStateEntity(entity.status.value),
            deleted_at=entity.deleted_at,
            created_by_user_id=entity.created_by_user_id,
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
                sequence=active_instance.sequence,
            )
        deployment.set_active_instance(application_instance)

        return deployment

    async def get_by_name(
        self,
        name: str,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> DeploymentEntity | None:
        """Get a deployment by ``(environment_id, name)`` scope.

        Tombstoned (soft-deleted) deployments are excluded by default
        so callers performing name-conflict checks see only the
        currently-occupying row. Pass ``include_deleted=True`` for
        forensic / cleanup paths that need the full history.
        """
        statement = (
            select(self.model_class)
            .where(self.model_class.name == name)
            .where(self.model_class.environment_id == environment_id)
            .options(*self._eager_load_options())
        )
        if not include_deleted:
            statement = statement.where(self.model_class.deleted_at.is_(None))  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        entity = result.first()
        if entity is None:
            return None
        return self._to_entity(entity)

    async def find_one_by_name_and_environment(
        self,
        name: str,
        environment_id: UUID,
    ) -> DeploymentEntity | None:
        """Find a non-tombstoned deployment by ``(name, environment_id)``.

        Thin wrapper over :meth:`get_by_name` that pins
        ``include_deleted=False`` and exposes the lookup under the natural
        identity name used by the GraphQL ``deployment(name, environmentId)``
        query (spec 009-deployments-apply). Reuses the existing
        ``unique_deployment_name_per_environment`` index — no new migration.
        """
        return await self.get_by_name(name, environment_id, include_deleted=False)

    async def find_names_with_prefix(
        self,
        prefix: str,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> list[str]:
        """Find deployment names matching ``<prefix>-<digits>`` within an env.

        Used by the auto-name generator to compute the next free suffix
        for a driver-derived name. Tombstoned rows are excluded by
        default — once a deployment is retired, its auto-generated name
        is freed for reuse.
        """
        like_pattern = f"{prefix}-%"
        statement = select(self.model_class.name).where(
            self.model_class.name.like(like_pattern)  # type: ignore[union-attr,attr-defined]
        )
        statement = statement.where(self.model_class.environment_id == environment_id)
        if not include_deleted:
            statement = statement.where(self.model_class.deleted_at.is_(None))  # type: ignore[union-attr]
        result = await self.session.exec(statement)
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

    async def find_reference_target(self, id: UUID) -> DeploymentReferenceTarget | None:
        """Read only the four columns, without the components and the active instance."""
        result = await self.session.exec(
            select(
                self.model_class.id,
                self.model_class.name,
                self.model_class.environment_id,
                self.model_class.deleted_at,
            ).where(self.model_class.id == id)
        )
        row = result.first()
        if row is None:
            return None
        deployment_id, name, environment_id, deleted_at = row
        return DeploymentReferenceTarget(
            id=deployment_id,
            name=name,
            environment_id=environment_id,
            deleted_at=deleted_at,
        )

    async def find_all_by_environment(
        self,
        environment_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> list[DeploymentEntity]:
        """Return every deployment in ``environment_id``.

        Used by the env-config fanout (009-environment-update / FR-006) to
        enumerate redeploy targets. Tombstoned (``deleted_at IS NOT NULL``)
        rows are excluded by default — set ``include_deleted=True`` only on
        the forensic / cleanup paths that need the full history. Internal
        rows are NOT filtered here; the caller decides whether to skip them
        (the fanout loop excludes them per FR-013, but other callers may
        want every row).
        """
        statement = (
            select(self.model_class)
            .where(self.model_class.environment_id == environment_id)
            .options(*self._eager_load_options())
        )
        if not include_deleted:
            statement = statement.where(self.model_class.deleted_at.is_(None))  # type: ignore[union-attr]
        result = await self.session.exec(statement)
        return [self._to_entity(entity) for entity in result.all()]

    async def delete_all_for_environment(self, environment_id: UUID) -> list[UUID]:
        """Hard-delete every deployment of an environment, dependents first.

        ``deployment.environment_id`` is a non-nullable FK, so a deployment row
        cannot outlive its environment. Without this cascade,
        :func:`~styrmin_backend.services.environments.delete_environment` fails
        the moment the environment has ever held a deployment: the ORM's
        reaction to a deleted parent is to *null* the child's FK, which trips
        the NOT NULL constraint and surfaces as an opaque ``INTERNAL_ERROR``.
        Same class of gap — and the same remedy — as
        ``delete_environment_backups_for_environment``, which had to be added
        for ``environmentbackup.environment_id`` for exactly this reason.

        Tombstoned rows are included: a ``DELETED`` deployment still holds the
        FK, so leaving it behind blocks the environment delete just as a live
        one would.

        Deletion follows the FK graph, and two edges need more than a delete:

        * ``deployment.active_application_instance_id`` points *back* at
          ``applicationinstance``, so the cycle is broken by nulling it before
          the instances go.
        * ``restore.target_instance_id`` names the instance a restore restored
          into: every restore created since #532 records it, in-place or
          cross-target, and records none when the deployment had no active
          instance. An in-place restore's row is deleted with its
          ``Backup``. A **cross-target** restore's row (an environment clone's
          constituent — 010 research D2) must survive, because its ``Backup``
          belongs to a *different* environment; it is detached rather than
          deleted, which keeps the clone record's ``restore_id`` resolvable and
          its recorded outcome intact.

        Returns:
            The ids of the deleted deployments.
        """
        # Local imports: these models are only needed for the cascade, and
        # hoisting them would widen this module's import surface for every
        # caller that just reads deployments.
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import update as sa_update

        from styrmin_backend.db.models import Backup as BackupModel
        from styrmin_backend.db.models import BackupSchedule as BackupScheduleModel
        from styrmin_backend.db.models import DeployedService as DeployedServiceModel
        from styrmin_backend.db.models import DeploymentStatus as DeploymentStatusModel
        from styrmin_backend.db.models import PodStatus as PodStatusModel
        from styrmin_backend.db.models import Restore as RestoreModel
        from styrmin_backend.db.models import Task as TaskModel

        deployment_ids = list(
            (
                await self.session.exec(
                    select(self.model_class.id).where(
                        self.model_class.environment_id == environment_id
                    )
                )
            ).all()
        )
        if not deployment_ids:
            return []

        instance_ids = list(
            (
                await self.session.exec(
                    select(InstanceModel.id).where(
                        InstanceModel.deployment_id.in_(deployment_ids)  # type: ignore[attr-defined]
                    )
                )
            ).all()
        )

        if instance_ids:
            # Every restore records the instance it restored into (#532), or
            # none when the deployment had no active instance. The rows of this
            # environment's own backups are deleted below; a cross-target
            # restore's row, whose backup belongs to another environment, keeps
            # its history and loses only the pointer.
            await self.session.execute(
                sa_update(RestoreModel)
                .where(RestoreModel.target_instance_id.in_(instance_ids))  # type: ignore[attr-defined]
                .values(target_instance_id=None)
            )
            backup_ids = list(
                (
                    await self.session.exec(
                        select(BackupModel.id).where(
                            BackupModel.instance_id.in_(instance_ids)  # type: ignore[attr-defined]
                        )
                    )
                ).all()
            )
            if backup_ids:
                await self.session.execute(
                    sa_delete(RestoreModel).where(
                        RestoreModel.backup_id.in_(backup_ids)  # type: ignore[attr-defined]
                    )
                )
                await self.session.execute(
                    sa_delete(BackupModel).where(BackupModel.id.in_(backup_ids))  # type: ignore[attr-defined]
                )

        await self.session.execute(
            sa_update(self.model_class)
            .where(self.model_class.id.in_(deployment_ids))  # type: ignore[attr-defined]
            .values(active_application_instance_id=None)
        )
        if instance_ids:
            await self.session.execute(
                sa_delete(InstanceModel).where(InstanceModel.id.in_(instance_ids))  # type: ignore[attr-defined]
            )

        for child in (
            ComponentModel,
            DeployedServiceModel,
            TaskModel,
            PodStatusModel,
            DeploymentStatusModel,
            BackupScheduleModel,
        ):
            await self.session.execute(
                sa_delete(child).where(child.deployment_id.in_(deployment_ids))  # type: ignore[attr-defined]
            )

        await self.session.execute(
            sa_delete(self.model_class).where(
                self.model_class.id.in_(deployment_ids)  # type: ignore[attr-defined]
            )
        )
        return list(deployment_ids)

    async def count_live(self) -> int:
        """Return the number of live deployments, internal ones included."""
        result = await self.session.exec(
            select(func.count())
            .select_from(self.model_class)
            .where(col(self.model_class.deleted_at).is_(None))
        )
        return result.one()

    async def find_internal_by_environment(
        self, environment_id: UUID
    ) -> DeploymentEntity | None:
        """Find the live internal ingress controller deployment for an environment."""
        result = await self.session.exec(
            select(self.model_class)
            .where(self.model_class.environment_id == environment_id)
            .where(self.model_class.internal == True)  # noqa: E712
            .where(self.model_class.deleted_at.is_(None))  # type: ignore[union-attr]
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
            status=DeploymentStateEntity(entity.status.value),
            deleted_at=entity.deleted_at,
            created_by_user_id=entity.created_by_user_id,
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
                sequence=active_instance.sequence,
            )
        deployment.set_active_instance(application_instance)

        return deployment
