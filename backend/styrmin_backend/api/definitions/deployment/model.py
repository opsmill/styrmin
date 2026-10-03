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
from styrmin_backend.api.definitions.user.model import User as UserType
from styrmin_backend.api.resolvers import resolve_related
from styrmin_backend.api.scalars import JSON
from styrmin_backend.context.fqdn import (
    compute_external_url,
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_backend.context.models.config import (
    ComponentConfigBlock,
    DeploymentConfig,
    EnvironmentConfig,
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
    container: str | None = strawberry.field(
        default=None,
        description=(
            "The component container declared by the deployment's pinned driver "
            "version, or null when it declares none. See `ComponentConfig.container`."
        ),
    )

    @classmethod
    def from_instance(cls, instance: ComponentEntity) -> Component:
        return cls(
            id=instance.id,
            name=instance.name,
            enabled=instance.enabled,
            # Rows copied before 017 have no ``container`` key.
            container=instance.config.get("container"),
        )


@strawberry.type(
    description=(
        "A single environment variable to inject into rendered containers.\n\n"
        "WARNING: This surface is for non-secret values only. The platform "
        "stores values in plaintext and exposes them through any query that "
        "selects them. Do not store credentials, API keys, or other secret "
        "material here — use the dedicated secret env var path (separate "
        "ticket) once available."
    )
)
class EnvVar:
    name: str = strawberry.field(
        description="POSIX-portable env var name, matching ^[A-Za-z_][A-Za-z0-9_]*$."
    )
    value: str = strawberry.field(
        description=(
            "The value to set. May be the empty string. NOT for secret "
            "material; see the EnvVar type description."
        )
    )


@strawberry.type(
    description=(
        "A bundle of environment variables targeting one component of a "
        "deployment. Applicable env vars are injected by a post-render patch "
        "into the component container the driver declares. ``isOrphaned`` "
        "flags blocks whose component the deployment's current driver no "
        "longer declares; ``isApplicable`` flags whether the env vars can "
        "reach any container. Non-applicable blocks remain visible in the "
        "API but are NOT injected into rendered pods."
    )
)
class ComponentEnvVars:
    component: str = strawberry.field(description="Name of the targeted component.")
    env_vars: list[EnvVar] = strawberry.field(
        description="The effective env vars set on this component (env+dep+component merged)."
    )
    is_orphaned: bool = strawberry.field(
        description=(
            "True when the deployment's current driver no longer declares "
            "this component (the upgrade renamed or removed it). Orphaned "
            "blocks are visible in the API but are NOT injected into "
            "rendered pods, so the user can audit and clean them up."
        )
    )
    is_applicable: bool = strawberry.field(
        description=(
            "False when these env vars cannot reach any container: the "
            "component is orphaned (`isOrphaned`) or the driver declares no "
            "component container for it. Stored values are kept but not "
            "injected."
        )
    )


@strawberry.type(
    description=(
        "The resolved container ``command``/``args`` override targeting one "
        "component of a deployment, plus an ``isOrphaned`` flag indicating "
        "whether the deployment's current driver still declares the targeted "
        "component. Orphaned blocks remain visible in the API but are NOT "
        "injected into rendered pods. ``command``/``args`` are ``null`` when "
        "no override is set for that slot (the chart default flows through)."
    )
)
class ComponentContainerOverrides:
    component: str = strawberry.field(description="Name of the targeted component.")
    command: list[str] | None = strawberry.field(
        description=(
            "Resolved entrypoint override for this component, or ``null`` "
            "when unset (the chart/image default applies)."
        )
    )
    args: list[str] | None = strawberry.field(
        description=(
            "Resolved args override for this component, or ``null`` when "
            "unset (the chart/image default applies)."
        )
    )
    is_orphaned: bool = strawberry.field(
        description=(
            "True when the deployment's current driver no longer declares "
            "this component (the upgrade renamed or removed it). Orphaned "
            "blocks are visible in the API but are NOT injected into rendered "
            "pods, so the operator can audit and clean them up."
        )
    )


@strawberry.type(
    description=(
        "The image override for one component's component container. Orphaned "
        "or non-applicable overrides stay visible but are not rendered."
    )
)
class ComponentImageOverride:
    component: str = strawberry.field(description="Name of the targeted component.")
    reference: str = strawberry.field(
        description="The stored image reference, `{{ app.version }}` tokens included."
    )
    resolved_reference: str = strawberry.field(
        description=(
            "`reference` with every `{{ app.version }}` token replaced by the "
            "deployment's `applicationVersion`."
        )
    )
    is_orphaned: bool = strawberry.field(
        description=(
            "True when the deployment's current driver no longer declares this "
            "component (the upgrade renamed or removed it)."
        )
    )
    is_applicable: bool = strawberry.field(
        description=(
            "False when the override cannot reach a container: the component is "
            "orphaned (`isOrphaned`) or the driver declares no component container "
            "for it. The stored reference is kept but not rendered."
        )
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


def _component_containers(deployment: DeploymentEntity) -> dict[str, str | None]:
    """Map each deployment component to its component container (``None`` if undeclared)."""
    return {c.name: c.config.get("container") for c in (deployment.components or [])}


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
    created_by_user_id: strawberry.Private[UUID]

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

    @strawberry.field(
        description=(
            "Effective deployment-level env vars (after merging environment "
            "& deployment scopes, but BEFORE component-level overrides). "
            "Empty when none are set."
        )
    )
    async def env_vars(self, info: strawberry.Info) -> list[EnvVar]:
        """Resolve the effective deployment-level env vars.

        Mirrors the merge done by the resolver: environment-scope values are
        layered first, deployment-scope values overwrite per-key (FR-002
        deepest-wins). For US1 environment-scope env vars are not yet
        wired through write-side validation but the read-side merge
        already honours them so US2 only adds the write path.
        """
        from styrmin_backend.services.env_vars.resolver import EnvVarsResolver

        uow = info.context["uow"]
        async with uow:
            deployment = await uow.deployments.find(self.id)
            if deployment is None:
                logger.warning(
                    "env_vars: deployment {} not found (likely deleted "
                    "between parent query and sub-field resolution)",
                    self.id,
                )
                return []
            environment = await uow.environments.get(deployment.environment_id)
            env_config_raw = environment.config if environment is not None else None
            dep_config_raw = deployment.config

        env_cfg = (
            EnvironmentConfig.model_validate(env_config_raw) if env_config_raw else None
        )
        dep_cfg = (
            DeploymentConfig.model_validate(dep_config_raw) if dep_config_raw else None
        )

        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env_cfg,
            deployment=dep_cfg,
            component_env_vars=None,
        )
        return [
            EnvVar(name=k, value=v) for k, v in resolved.deployment_effective.items()
        ]

    @strawberry.field(
        description=(
            "Per-component effective env vars, including orphaned blocks "
            "(``isOrphaned=true``). Component-level entries override "
            "deployment- and environment-level entries on a per-key basis "
            "(FR-002 deepest-wins). Non-applicable blocks "
            "(``isApplicable=false``: component renamed or removed by a driver "
            "upgrade, or no component container declared) are visible here "
            "but skipped by the post-render injector so no env entries reach "
            "rendered pods."
        )
    )
    async def component_env_vars(self, info: strawberry.Info) -> list[ComponentEnvVars]:
        """Resolve effective env vars per declared component.

        Pulls per-component blocks from
        ``DeploymentConfig.components[<name>].env_vars`` and merges them with
        the environment + deployment scopes via :class:`EnvVarsResolver`.
        Components without an explicit block still appear in the result with
        the deployment-level merged dict (the merge falls through to the
        ``deployment`` layer). Live components for which the merged dict is
        empty are omitted to keep the surface tidy. Orphaned blocks
        (US5 / FR-029..FR-033) are always surfaced regardless of dict size —
        their whole purpose is user visibility after a driver upgrade.
        ``isApplicable`` reads the component container from the deployment's
        components, which mirror its pinned driver version.
        """
        from styrmin_backend.services.env_vars.resolver import EnvVarsResolver

        uow = info.context["uow"]
        async with uow:
            deployment = await uow.deployments.find(self.id)
            if deployment is None:
                logger.warning(
                    "component_env_vars: deployment {} not found (likely "
                    "deleted between parent query and sub-field resolution)",
                    self.id,
                )
                return []
            environment = await uow.environments.get(deployment.environment_id)
            env_config_raw = environment.config if environment is not None else None
            dep_config_raw = deployment.config
            containers = _component_containers(deployment)
            driver_components = list(containers)

        env_cfg = (
            EnvironmentConfig.model_validate(env_config_raw) if env_config_raw else None
        )
        dep_cfg = (
            DeploymentConfig.model_validate(dep_config_raw) if dep_config_raw else None
        )

        component_env_vars: dict[str, dict[str, str] | None] = {}
        if dep_cfg is not None:
            for name, block in (dep_cfg.components or {}).items():
                component_env_vars[name] = block.env_vars

        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env_cfg,
            deployment=dep_cfg,
            component_env_vars=component_env_vars,
            driver_components=driver_components,
        )

        results: list[ComponentEnvVars] = []
        for entry in resolved.components:
            # Live entries with an empty merged dict are dropped so the
            # surface stays tidy (a component declared by the driver but
            # carrying no env vars at any layer adds no signal). Orphans are
            # always surfaced — their visibility is the whole point of US5.
            if not entry.resolved.is_orphaned and not entry.resolved.config:
                continue
            results.append(
                ComponentEnvVars(
                    component=entry.component_name,
                    env_vars=[
                        EnvVar(name=k, value=v)
                        for k, v in entry.resolved.config.items()
                    ],
                    is_orphaned=entry.resolved.is_orphaned,
                    is_applicable=(
                        not entry.resolved.is_orphaned
                        and containers.get(entry.component_name) is not None
                    ),
                )
            )
        return results

    @strawberry.field(
        description=(
            "Per-component container ``command``/``args`` overrides, including "
            "orphaned blocks (``isOrphaned=true``). Component-scope only — "
            "there is NO environment/deployment layering. Live components with "
            "neither slot set are omitted to keep the surface tidy. Orphaned "
            "blocks (component renamed or removed by a driver upgrade — FR-005) "
            "are always surfaced here but skipped by the renderer so no value "
            "reaches a rendered pod. Cleared slots are returned as ``null``."
        )
    )
    async def component_container_overrides(
        self, info: strawberry.Info
    ) -> list[ComponentContainerOverrides]:
        """Resolve container overrides per declared component.

        Pulls per-component blocks from ``DeploymentConfig.components[<name>]``
        and runs :class:`ContainerOverridesResolver` (direct per-component
        lookup, no merge). Orphaned blocks are always surfaced regardless of
        whether they carry both slots — their purpose is operator visibility
        after a driver upgrade.
        """
        from styrmin_backend.services.container_overrides.resolver import (
            ContainerOverridesResolver,
        )

        uow = info.context["uow"]
        async with uow:
            deployment = await uow.deployments.find(self.id)
            if deployment is None:
                logger.warning(
                    "component_container_overrides: deployment {} not found "
                    "(likely deleted between parent query and sub-field "
                    "resolution)",
                    self.id,
                )
                return []
            dep_config_raw = deployment.config
            driver_components = [c.name for c in (deployment.components or [])]

        dep_cfg = (
            DeploymentConfig.model_validate(dep_config_raw) if dep_config_raw else None
        )

        component_blocks: dict[str, ComponentConfigBlock | None] = {}
        if dep_cfg is not None:
            component_blocks = dict(dep_cfg.components or {})

        entries = ContainerOverridesResolver.resolve_for_deployment(
            component_overrides=component_blocks,
            driver_components=driver_components,
        )

        results: list[ComponentContainerOverrides] = []
        for entry in entries:
            # Live entries with neither slot set carry no override signal —
            # drop them to keep the surface tidy. Orphans are always surfaced.
            if (
                not entry.resolved.is_orphaned
                and entry.resolved.command is None
                and entry.resolved.args is None
            ):
                continue
            results.append(
                ComponentContainerOverrides(
                    component=entry.component_name,
                    command=entry.resolved.command,
                    args=entry.resolved.args,
                    is_orphaned=entry.resolved.is_orphaned,
                )
            )
        return results

    @strawberry.field(
        description=(
            "Per-component image overrides: live components in driver order, then "
            "orphaned blocks (``isOrphaned=true``) by name. Components without an "
            "override are omitted."
        )
    )
    async def component_image_overrides(
        self, info: strawberry.Info
    ) -> list[ComponentImageOverride]:
        from styrmin_backend.services.image_overrides.reference import (
            substitute_app_version,
        )
        from styrmin_backend.services.image_overrides.resolver import (
            ImageOverridesResolver,
        )

        uow = info.context["uow"]
        async with uow:
            deployment = await uow.deployments.find(self.id)
            if deployment is None:
                logger.warning(
                    "component_image_overrides: deployment {} not found (likely "
                    "deleted between parent query and sub-field resolution)",
                    self.id,
                )
                return []
            dep_config_raw = deployment.config
            version = deployment.application_version
            containers = _component_containers(deployment)

        dep_cfg = (
            DeploymentConfig.model_validate(dep_config_raw) if dep_config_raw else None
        )
        entries = ImageOverridesResolver.resolve_for_deployment(
            component_overrides=dict(dep_cfg.components or {}) if dep_cfg else None,
            driver_components=list(containers),
        )
        return [
            ComponentImageOverride(
                component=entry.component_name,
                reference=entry.resolved.reference,
                # Leave tokens visible rather than substituting an empty version.
                resolved_reference=(
                    substitute_app_version(entry.resolved.reference, version)
                    if version
                    else entry.resolved.reference
                ),
                is_orphaned=entry.resolved.is_orphaned,
                is_applicable=(
                    not entry.resolved.is_orphaned
                    and containers.get(entry.component_name) is not None
                ),
            )
            for entry in entries
        ]

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

    @strawberry.field
    async def created_by(self, info: strawberry.Info) -> UserType:
        """The user who created this deployment.

        The returned ``User`` type role-gates its admin-only fields per
        ADR-017: a non-admin caller selecting ``role`` / ``effectiveRole``
        / ``active`` / ``groups`` / ``createdOn`` / ``updatedOn`` receives
        a field-level ``FORBIDDEN`` error, while ``id`` / ``username`` /
        ``displayName`` always resolve.
        """
        from sqlalchemy.orm import selectinload
        from sqlmodel import select

        from styrmin_backend.db.models import User as UserDBModel

        uow = info.context["uow"]
        # Eager-load groups for ``effectiveRole`` so the User serialiser
        # does not trigger a lazy load on a closed async session.
        result = await uow.session.exec(
            select(UserDBModel)
            .where(UserDBModel.id == self.created_by_user_id)
            .options(selectinload(UserDBModel.groups))  # type: ignore[arg-type]
        )
        user = result.first()
        assert user is not None, (
            "Deployment.created_by_user_id is a non-null FK; the user row "
            "must exist for any deployment that resolves this field."
        )
        return UserType.from_instance(user)

    @strawberry.field(
        description=(
            "Username of the user who created this deployment, or ``null`` "
            "if the creator row has been removed (forward-compatible with "
            "``ondelete=SET NULL`` even though the FK is currently non-null). "
            "Unlike ``createdBy``, this field is NOT admin-gated — drivers "
            "and the UI can surface attribution without elevated access per "
            "FR-028."
        )
    )
    async def created_by_username(self, info: strawberry.Info) -> str | None:
        from sqlmodel import select

        from styrmin_backend.db.models import User as UserDBModel

        if self.created_by_user_id is None:
            return None
        uow = info.context["uow"]
        result = await uow.session.exec(
            select(UserDBModel.username).where(
                UserDBModel.id == self.created_by_user_id
            )
        )
        username = result.first()
        return username if username is not None else None

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
            created_by_user_id=instance.created_by_user_id,
            instance=instance,
        )
