from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.cluster.model import Cluster
from styrmin_backend.api.definitions.deployment.model import Deployment
from styrmin_backend.api.scalars import JSON
from styrmin_backend.db.models import Deployment as DeploymentDBModel
from styrmin_backend.db.models import Environment as EnvironmentModel

if TYPE_CHECKING:
    from styrmin_backend.api.definitions.backup_storage_location.model import (
        BackupStorageLocation,
    )
from styrmin_backend.domain.models import Component as ComponentEntity
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentStatus as DeploymentStatusEntity
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity


def _db_deployment_to_domain(db_deployment: DeploymentDBModel) -> DeploymentEntity:
    """Convert a DB deployment model to a domain entity for GraphQL."""
    entity = DeploymentEntity(
        id=db_deployment.id,
        name=db_deployment.name,
        application_version=db_deployment.application_version,
        config=db_deployment.config,
        parameters=db_deployment.parameters or {},
        application_driver_version_id=db_deployment.application_driver_version_id,
        environment_id=db_deployment.environment_id,
        status=DeploymentStatusEntity(db_deployment.status.value),
    )
    for component in db_deployment.components:
        entity.add_component(
            ComponentEntity(
                id=component.id,
                name=component.name,
                enabled=component.enabled,
                config=component.config,
            )
        )
    active_instance = db_deployment.active_application_instance
    if active_instance is not None:
        from styrmin_backend.context.models.contexts import GlobalContext

        entity.set_active_instance(
            InstanceEntity(
                id=active_instance.id,
                name=active_instance.name,
                application_version=active_instance.application_version,
                status=InstanceStatusEntity(active_instance.status.value),
                context=GlobalContext.model_validate(active_instance.context),
                application_driver_version_id=active_instance.application_driver_version_id,
                deployment_id=db_deployment.id,
            )
        )
    return entity


@strawberry.type
class Environment:
    id: UUID
    name: str
    config: JSON

    instance: strawberry.Private[EnvironmentModel]

    @strawberry.field
    def cluster(self) -> Cluster:
        return Cluster.from_instance(self.instance.cluster)

    @strawberry.field
    def backup_storage_location(
        self,
    ) -> (
        Annotated[
            "BackupStorageLocation",
            strawberry.lazy(
                "styrmin_backend.api.definitions.backup_storage_location.model"
            ),
        ]
        | None
    ):
        from styrmin_backend.api.definitions.backup_storage_location.model import (
            BackupStorageLocation,
        )

        if self.instance.backup_storage_location is None:
            return None
        return BackupStorageLocation.from_instance(
            self.instance.backup_storage_location
        )

    @strawberry.field
    def deployments(self) -> list[Deployment]:
        return [
            Deployment.from_instance(_db_deployment_to_domain(deployment))
            for deployment in self.instance.deployments
        ]

    @classmethod
    def from_instance(cls, instance: EnvironmentModel) -> Environment:
        return cls(
            id=instance.id,
            name=instance.name,
            instance=instance,
            config=instance.config,
        )
