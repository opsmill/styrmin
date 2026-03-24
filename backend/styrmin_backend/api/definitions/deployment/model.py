from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.service.model import (
    DeployedService as DeployedServiceType,
)
from styrmin_backend.api.scalars import JSON
from styrmin_backend.domain.models import Component as ComponentEntity
from styrmin_backend.domain.models import (
    Deployment as DeploymentEntity,
)
from styrmin_backend.domain.models import (
    Instance as ApplicationInstanceEntity,
)


@strawberry.type
class Component:
    id: UUID
    name: str
    enabled: bool

    @classmethod
    def from_instance(cls, instance: ComponentEntity) -> Component:
        return cls(
            id=instance.id,
            name=instance.name,
            enabled=instance.enabled,
        )


@strawberry.type
class ApplicationInstance:
    id: UUID
    name: str
    status: str
    application_version: str
    application_driver_version_id: UUID
    deployment_id: UUID

    instance: strawberry.Private[ApplicationInstanceEntity]

    @classmethod
    def from_instance(cls, instance: ApplicationInstanceEntity) -> ApplicationInstance:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status,
            application_version=instance.application_version,
            application_driver_version_id=instance.application_driver_version_id,
            deployment_id=instance.deployment_id,
            instance=instance,
        )


@strawberry.type
class Deployment:
    id: UUID
    name: str
    status: str
    config: JSON
    parameters: JSON = strawberry.field(default_factory=dict)
    application_version: str
    application_driver_version_id: UUID
    environment_id: UUID
    internal: bool

    instance: strawberry.Private[DeploymentEntity]

    @strawberry.field
    def application_instance(self) -> ApplicationInstance | None:
        if self.instance.active_instance:
            return ApplicationInstance.from_instance(self.instance.active_instance)
        return None

    @strawberry.field
    def components(self) -> list[Component]:
        return [
            Component.from_instance(component) for component in self.instance.components
        ]

    @strawberry.field
    async def deployed_services(
        self, info: strawberry.Info
    ) -> list[DeployedServiceType]:
        uow = info.context["uow"]
        async with uow:
            services = await uow.deployed_services.get_by_deployment_id(self.id)
            return [DeployedServiceType.from_instance(s) for s in services]

    @classmethod
    def from_instance(cls, instance: DeploymentEntity) -> Deployment:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status,
            config=instance.config,
            parameters=instance.parameters,
            application_version=instance.application_version,
            application_driver_version_id=instance.application_driver_version_id,
            environment_id=instance.environment_id,
            internal=instance.internal,
            instance=instance,
        )
