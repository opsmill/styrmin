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
from styrmin_backend.services.driver.models.resources.env_vars import (
    DriverEnvVarLevel as DriverEnvVarLevelPydantic,
)
from styrmin_backend.services.exceptions import ApplicationDriverNotFoundError

# 008 / US4: Strawberry mirror of the Pydantic enum. Uses ``strawberry.enum``
# with the existing ``str``-based Pydantic enum directly so the GraphQL
# enum values stay aligned with the Pydantic source of truth (mirrors the
# ``PodPhaseType`` pattern in ``api/definitions/pod_status/model.py``).
DriverEnvVarLevel = strawberry.enum(DriverEnvVarLevelPydantic, name="DriverEnvVarLevel")


@strawberry.type(
    description=(
        "Doc-only declaration of an env var the driver's app respects. "
        "Surfaces in the driver detail view; does not validate, default, "
        "or constrain operator-set values (FR-015)."
    )
)
class DriverEnvVarDoc:
    name: str
    description: str
    level: DriverEnvVarLevel  # type: ignore[valid-type]
    components: list[str]

    @classmethod
    def from_dict(cls, data: dict) -> DriverEnvVarDoc:
        # ``data`` is the JSON-column payload stored at registration
        # (see ``services/applications.py``: ``model_dump(mode="json")``);
        # ``level`` arrives as the enum's string value.
        return cls(
            name=data["name"],
            description=data["description"],
            level=DriverEnvVarLevelPydantic(data["level"]),
            components=list(data.get("components") or []),
        )


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

    @strawberry.field(
        description=(
            "Doc-only env var declarations from the driver's spec.env_vars "
            "block. Empty when the driver omits the block."
        )
    )
    def env_vars(self) -> list[DriverEnvVarDoc]:
        # The DB column is nullable; coerce NULL to ``[]`` so callers can
        # rely on the GraphQL ``[DriverEnvVarDoc!]!`` non-null contract.
        raw = self.instance.env_vars
        if not raw:
            return []
        return [DriverEnvVarDoc.from_dict(d) for d in raw]

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
