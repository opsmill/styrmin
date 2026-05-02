from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import strawberry
from loguru import logger

from styrmin_backend.api.definitions.application_driver.model import (
    ApplicationDriverVersion,
)
from styrmin_backend.api.definitions.deployment_status.model import (
    DeploymentStatusType,
)
from styrmin_backend.api.definitions.pod_status.model import (
    PodStatus as PodStatusType,
)
from styrmin_backend.api.definitions.service.model import (
    DeployedService as DeployedServiceType,
)
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.api.scalars import JSON
from styrmin_backend.context.fqdn import (
    compute_external_url,
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
class ResolvedComponentScheduling:
    """Per-component effective scheduling configuration plus provenance.

    ``config`` is the fully merged :class:`SchedulingConfig` as a JSON dict
    (shape defined in
    ``specs/001-pod-scheduling-config/contracts/scheduling-config.schema.json``).
    ``provenance`` maps each effective field (dotted path) to the level
    that contributed its final value —
    ``"environment" | "deployment" | "component"``.
    """

    component_name: str
    config: JSON
    provenance: JSON


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
    deleted_at: datetime | None = None

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

            # Resolve config hierarchy to get fqdn_suffix and external URL settings
            environment = await uow.environments.get(self.instance.environment_id)
            fqdn_suffix: str | None = None
            external_url_scheme: str | None = None
            external_url_port: int | None = None
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
                external_url_scheme = resolved.get("external_url_scheme")
                external_url_port = resolved.get("external_url_port")
                environment_name = environment.name

            driver_version = await uow.application_driver_versions.get(
                self.instance.application_driver_version_id
            )
            if driver_version is not None:
                app_name = driver_version.application_driver.name

            primary_fqdn = compute_primary_fqdn(app_name, str(self.id), fqdn_suffix)
            primary_url = compute_external_url(
                primary_fqdn, external_url_scheme, external_url_port
            )

            results: list[DeployedServiceType] = []
            for s in services:
                human_readable_fqdn = compute_human_readable_fqdn(
                    s.resolved_name, environment_name, fqdn_suffix
                )
                results.append(
                    DeployedServiceType.from_instance(
                        s,
                        primary_fqdn=primary_fqdn,
                        human_readable_fqdn=human_readable_fqdn,
                        primary_url=primary_url,
                        human_readable_url=compute_external_url(
                            human_readable_fqdn,
                            external_url_scheme,
                            external_url_port,
                        ),
                    )
                )
            return results

    @strawberry.field
    async def pod_statuses(self, info: strawberry.Info) -> list[PodStatusType]:
        """Latest pod status snapshots for this deployment."""
        from styrmin_backend.services.pod_status import get_pod_statuses

        uow = info.context["uow"]
        statuses = await get_pod_statuses(uow=uow, deployment_id=self.id)
        return [PodStatusType.from_instance(s) for s in statuses]

    @strawberry.field
    async def resolved_scheduling(
        self, info: strawberry.Info
    ) -> list[ResolvedComponentScheduling]:
        """Return the effective :class:`SchedulingConfig` per component plus
        per-field provenance (US5). Drivers that want to read the merged
        values in their Jinja templates use ``context.components[*].scheduling``;
        this GraphQL field surfaces the same data read-only to the API.

        Validation / resolution errors are propagated as typed service
        exceptions (``InvalidSchedulingConfigError``,
        ``UnknownComponentInConfigError``,
        ``UnresolvableAffinityReferenceError``) with a ``path`` identifying
        the offending config scope so the API error extension can surface
        actionable diagnostics. A missing deployment (race with deletion)
        is logged and returns an empty list.
        """
        from styrmin_backend.context.resolvers import _resolve_scheduling_config
        from styrmin_backend.services.context import _extract_scheduling
        from styrmin_backend.services.scheduling.validator import (
            expand_deployment_references,
        )

        uow = info.context["uow"]
        async with uow:
            deployment = await uow.deployments.find(self.id)
            if deployment is None:
                logger.warning(
                    "resolved_scheduling: deployment {} not found (likely "
                    "deleted between parent query and sub-field resolution)",
                    self.id,
                )
                return []
            environment = await uow.environments.get(deployment.environment_id)
            env_config = environment.config if environment is not None else None
            dep_config = deployment.config
            components = deployment.components or []

        env_scheduling = _extract_scheduling(
            env_config, path="environment.config.scheduling"
        )
        dep_scheduling = _extract_scheduling(
            dep_config, path=f"deployment[{self.id}].config.scheduling"
        )

        results: list[ResolvedComponentScheduling] = []
        for component in components:
            comp_scheduling = _extract_scheduling(
                component.config,
                path=f"component[{component.name}].config.scheduling",
            )
            resolved, provenance = _resolve_scheduling_config(
                env=env_scheduling,
                dep=dep_scheduling,
                comp=comp_scheduling,
            )
            resolved = await expand_deployment_references(
                uow=uow,
                environment_id=deployment.environment_id,
                config=resolved,
            )
            results.append(
                ResolvedComponentScheduling(
                    component_name=component.name,
                    config=resolved.model_dump(exclude_none=True, mode="json"),
                    provenance=dict(provenance),
                )
            )
        return results

    @strawberry.field
    async def crd_status(self, info: strawberry.Info) -> DeploymentStatusType | None:
        """Latest StyrminDeployment status snapshot for this deployment."""
        from styrmin_backend.services.deployment_status import (
            get_deployment_status,
        )

        uow = info.context["uow"]
        status = await get_deployment_status(deployment_id=self.id, uow=uow)
        if status is None:
            return None
        return DeploymentStatusType.from_instance(status)

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
            deleted_at=instance.deleted_at,
            instance=instance,
        )
