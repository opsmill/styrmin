from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.application_driver.model import (
    ApplicationDriverVersion,
)
from styrmin_backend.api.definitions.service.model import (
    DeployedService as DeployedServiceType,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.api.scalars import JSON
from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_backend.domain.models import Component as ComponentEntity
from styrmin_backend.domain.models import (
    Deployment as DeploymentEntity,
)
from styrmin_backend.domain.models import (
    Instance as ApplicationInstanceEntity,
)
from styrmin_backend.services.exceptions import (
    ApplicationDriverVersionNotFoundError,
    EnvironmentNotFoundError,
)

if TYPE_CHECKING:
    from styrmin_backend.api.definitions.environment.model import Environment


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

    @strawberry.field
    async def application_driver_version(
        self, info: strawberry.Info
    ) -> ApplicationDriverVersion:
        return await resolve_related(
            info,
            "application_driver_versions",
            self.application_driver_version_id,
            ApplicationDriverVersion,
            ApplicationDriverVersionNotFoundError,
        )

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
    async def environment(
        self, info: strawberry.Info
    ) -> Annotated[
        "Environment",
        strawberry.lazy("styrmin_backend.api.definitions.environment.model"),
    ]:
        from styrmin_backend.api.definitions.environment.model import Environment

        return await resolve_related(
            info,
            "environments",
            self.environment_id,
            Environment,
            EnvironmentNotFoundError,
        )

    @strawberry.field
    async def application_driver_version(
        self, info: strawberry.Info
    ) -> ApplicationDriverVersion:
        return await resolve_related(
            info,
            "application_driver_versions",
            self.application_driver_version_id,
            ApplicationDriverVersion,
            ApplicationDriverVersionNotFoundError,
        )

    @strawberry.field
    async def deployed_services(
        self, info: strawberry.Info
    ) -> list[DeployedServiceType]:
        uow = info.context["uow"]
        async with uow:
            services = await uow.deployed_services.get_by_deployment_id(self.id)

            # Resolve config hierarchy to get fqdn_suffix
            environment = await uow.environments.get(self.instance.environment_id)
            fqdn_suffix: str | None = None
            environment_name: str = ""
            app_name: str = ""

            if environment is not None:
                cluster_config = (
                    environment.cluster.config if environment.cluster else {}
                )
                resolved = {
                    **(cluster_config or {}),
                    **(environment.config or {}),
                    **(self.instance.config or {}),
                }
                fqdn_suffix = resolved.get("fqdn_suffix")
                environment_name = environment.name

            driver_version = await uow.application_driver_versions.get(
                self.instance.application_driver_version_id
            )
            if driver_version is not None:
                app_name = driver_version.application_driver.name

            return [
                DeployedServiceType.from_instance(
                    s,
                    primary_fqdn=compute_primary_fqdn(
                        app_name, str(self.id), fqdn_suffix
                    ),
                    human_readable_fqdn=compute_human_readable_fqdn(
                        s.resolved_name, environment_name, fqdn_suffix
                    ),
                )
                for s in services
            ]

    @classmethod
    def from_instance(cls, instance: DeploymentEntity) -> Deployment:
        return cls(
            id=instance.id,
            name=instance.name,
            status=instance.status,
            config=instance.config or {},
            parameters=instance.parameters,
            application_version=instance.application_version,
            application_driver_version_id=instance.application_driver_version_id,
            environment_id=instance.environment_id,
            internal=instance.internal,
            instance=instance,
        )
