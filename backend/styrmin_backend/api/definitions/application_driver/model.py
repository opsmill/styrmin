from __future__ import annotations

from datetime import datetime
from uuid import UUID

import strawberry

from styrmin_backend import config as styrmin_config
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
from styrmin_backend.services.driver.models.resources.driver import (
    ArbitrarySectionModel,
    parse_stored_component_declaration,
)
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


@strawberry.type(
    description=(
        "A link a driver declares under `spec.info.links`, such as its homepage or "
        "documentation."
    )
)
class DriverLink:
    label: str = strawberry.field(
        description="Link text, from the `link` key of the entry."
    )
    url: str = strawberry.field(
        description="Absolute http or https URL, from the `url` key of the entry."
    )

    @classmethod
    def from_dict(cls, data: dict) -> DriverLink:
        # ``data`` is the JSON-column payload stored at registration: ``{"link", "url"}``.
        return cls(label=data["link"], url=data["url"])


# FIXME: Support domain models serialization instead


@strawberry.type
class ComponentConfig:
    id: UUID
    name: str
    config: JSON | None = None
    # Names the driver version in the warning about ignored replica keys.
    driver_version: strawberry.Private[str | None] = None

    @strawberry.field(
        description=(
            "The component container the driver declares for this component "
            "(`components.<name>.container` in the driver specification file): the "
            "container that receives per-component post-render overrides such as "
            "env vars. Null when the driver declares none — component-scope env "
            "vars are then rejected and broader scopes skip this component."
        )
    )
    def container(self) -> str | None:
        # Rows stored before the field existed have no ``container`` key.
        if not isinstance(self.config, dict):
            return None
        return self.config.get("container")

    @strawberry.field(
        description=(
            "Default replica count the driver version declares "
            "(components.<name>.replicas). Null when not declared."
        )
    )
    def replicas(self) -> int | None:
        declaration = self._replica_declaration()
        return declaration.replicas if declaration is not None else None

    @strawberry.field(
        description=(
            "The driver version marks the component as a singleton component: "
            "its replica count is fixed at 1."
        )
    )
    def singleton(self) -> bool:
        declaration = self._replica_declaration()
        return declaration.singleton if declaration is not None else False

    def _replica_declaration(self) -> ArbitrarySectionModel | None:
        # Invalid stored keys read as unset, as in ``componentReplicas`` and the patch builder.
        if not isinstance(self.config, dict):
            return None
        return parse_stored_component_declaration(
            self.config, driver_version=self.driver_version, component=self.name
        )

    @classmethod
    def from_instance(
        cls, instance: DomainComponentConfig, *, driver_version: str | None = None
    ) -> ComponentConfig:
        return cls(
            id=instance.id,
            name=instance.name,
            config=instance.config,
            driver_version=driver_version,
        )


@strawberry.type
class ApplicationDriver:
    id: UUID
    name: str
    created_on: datetime

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
            created_on=instance.created_on,
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
    content_hash: str | None = None
    source_commit_sha: str | None = None

    created_on: datetime

    components: JSON | None = None

    icon: str | None = strawberry.field(
        default=None,
        description=(
            "URL of the driver's logo image, from `spec.info.icon` in the driver "
            "specification file. An absolute https URL; the browser of each viewer "
            "loads the image from it. Null when the driver does not set it, or when "
            "the server setting `STYRMIN_DRIVER_SHOW_LOGOS` is false."
        ),
    )
    description: str | None = strawberry.field(
        default=None,
        description=(
            "Description of the application, from `spec.info.description`. Null "
            "when the driver does not set it."
        ),
    )

    load_warnings: list[str] = strawberry.field(
        default_factory=list,
        description=(
            "Values of `spec.info` that the load left out of this driver version, "
            "with the reason, such as an icon that is not an https URL. The load "
            "still succeeds. Filled only in the result of "
            "`loadLocalApplicationDriverVersion` and "
            "`loadRemoteApplicationDriverVersion`; empty everywhere else."
        ),
    )

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

    @strawberry.field(
        description=(
            "Links from `spec.info.links`, in file order. Empty when the driver does "
            "not set any."
        )
    )
    def links(self) -> list[DriverLink]:
        return [DriverLink.from_dict(d) for d in self.instance.links or []]

    @strawberry.field
    def component_configs(self) -> list[ComponentConfig]:
        return [
            ComponentConfig.from_instance(  # type: ignore[arg-type]
                component, driver_version=f"driver version {self.id}"
            )
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
            content_hash=instance.content_hash,
            source_commit_sha=instance.source_commit_sha,
            created_on=instance.created_on,
            icon=instance.icon if styrmin_config.SETTINGS.driver.show_logos else None,
            description=instance.description,
            instance=instance,
        )
