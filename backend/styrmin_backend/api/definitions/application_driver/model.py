from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.api.definitions.action.model import Action
from styrmin_backend.api.definitions.application_driver.parameter import (
    ParameterDefinition,
)
from styrmin_backend.api.definitions.helm_chart.model import HelmChart
from styrmin_backend.api.definitions.service.model import (
    ServiceDefinition as ServiceDefinitionType,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.api.scalars import JSON
from styrmin_backend.db.models import ApplicationDriver as ApplicationDriverModel
from styrmin_backend.db.models import (
    ApplicationDriverVersion as ApplicationDriverVersionModel,
)
from styrmin_backend.domain.models import ComponentConfig as DomainComponentConfig
from styrmin_backend.services.exceptions import ApplicationDriverNotFoundError

# FIXME: Support domain models serialization instead


@strawberry.type
class ComponentConfig:
    id: UUID
    name: str
    config: JSON | None = None

    @classmethod
    def from_instance(cls, instance: DomainComponentConfig) -> ComponentConfig:
        return cls(
            id=instance.id,
            name=instance.name,
            config=instance.config,
        )


@strawberry.type
class ApplicationDriver:
    id: UUID
    name: str

    instance: strawberry.Private[ApplicationDriverModel]

    @strawberry.field
    def versions(self) -> list[ApplicationDriverVersion]:
        return [
            ApplicationDriverVersion.from_instance(version)
            for version in self.instance.versions
        ]

    @classmethod
    def from_instance(cls, instance: ApplicationDriverModel) -> ApplicationDriver:
        return cls(
            id=instance.id,
            name=instance.name,
            instance=instance,
        )


@strawberry.type
class ApplicationDriverVersion:
    id: UUID
    application_driver_id: UUID
    version: str
    supported_versions: str
    default_version: str | None = None

    source_type: str
    source_repository: str
    source_branch: str | None
    source_path: str | None

    components: JSON | None = None

    instance: strawberry.Private[ApplicationDriverVersionModel]

    @strawberry.field
    async def application_driver(self, info: strawberry.Info) -> ApplicationDriver:
        return await resolve_related(
            info,
            "application_drivers",
            self.application_driver_id,
            ApplicationDriver,
            ApplicationDriverNotFoundError,
        )

    @strawberry.field
    def services(self) -> list[ServiceDefinitionType]:
        raw = self.instance.services
        if not raw:
            return []
        return [ServiceDefinitionType.from_dict(s) for s in raw]

    @strawberry.field
    def parameters(self) -> list[ParameterDefinition]:
        raw = self.instance.parameters
        if not raw:
            return []
        return [ParameterDefinition.from_dict(p) for p in raw]

    @strawberry.field
    def component_configs(self) -> list[ComponentConfig]:
        return [
            ComponentConfig.from_instance(component)  # type: ignore[arg-type]
            for component in self.instance.component_configs
        ]

    @strawberry.field
    def helm_chart(self) -> HelmChart:
        return HelmChart.from_instance(self.instance.helm_chart)

    @strawberry.field
    def actions(self) -> list[Action]:
        return [Action.from_instance(action) for action in self.instance.actions]

    @classmethod
    def from_instance(
        cls, instance: ApplicationDriverVersionModel
    ) -> ApplicationDriverVersion:
        return cls(
            id=instance.id,
            application_driver_id=instance.application_driver_id,
            version=instance.version,
            supported_versions=instance.application_supported_versions,
            default_version=instance.default_version,
            components=instance.components,
            source_type=instance.source_type,
            source_repository=instance.source_repository,
            source_branch=instance.source_branch,
            source_path=instance.source_path,
            instance=instance,
        )
