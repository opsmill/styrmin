from collections.abc import Mapping
from uuid import UUID

from loguru import logger
from pydantic import ValidationError
from styrmin_sdk.driver_format.context.service_entries import build_service_entries

from styrmin_backend.agent.service.kubernetes.utils import (
    get_kubernetes_reference,
)
from styrmin_backend.context.models.components import (
    ProvenanceLevel,
    ResolvedComponentScheduling,
    driver_version_label,
)
from styrmin_backend.context.models.config import (
    ComponentConfigBlock,
    DeploymentConfig,
    EnvironmentConfig,
    SchedulingConfig,
)
from styrmin_backend.context.models.contexts import (
    GlobalContext,
    UtilityContext,
    UtilityKind,
)
from styrmin_backend.context.models.input import (
    ContextInput,
    UtilityInput,
    UtilityKindInput,
)
from styrmin_backend.context.resolvers import (
    _resolve_scheduling_config,
    resolve_global_context,
)
from styrmin_backend.domain.models import Deployment
from styrmin_backend.services.container_overrides.resolver import (
    ContainerOverridesResolver,
)
from styrmin_backend.services.env_vars.exceptions import (
    EnvVarSizeLimitExceededError,
)
from styrmin_backend.services.env_vars.resolver import EnvVarsResolver
from styrmin_backend.services.env_vars.validator import (
    PER_SCOPE_BYTE_CAP,
    _serialised_dict_bytes,
)
from styrmin_backend.services.exceptions import (
    DeploymentNotFoundError,
    InvalidSchedulingConfigError,
)
from styrmin_backend.services.image_overrides.resolver import ImageOverridesResolver
from styrmin_backend.services.scheduling.validator import (
    expand_deployment_references,
)
from styrmin_backend.services.unit_of_work import UnitOfWork

# FR-008a: post-merge size caps. The per-component cap reuses the same
# 256 KiB ceiling as input scopes (PER_SCOPE_BYTE_CAP) since the resolved
# dict is just one merged scope; the per-deployment cap caps the sum
# across components at 1 MiB so the deployment CRD stays comfortably
# under the Kubernetes 1.5 MiB resource size limit.
_RESOLVED_PER_COMPONENT_BYTE_CAP: int = PER_SCOPE_BYTE_CAP  # 256 KiB
_RESOLVED_PER_DEPLOYMENT_BYTE_CAP: int = 1024 * 1024  # 1 MiB


async def generate_context_from_deployment_id(
    deployment_id: UUID, uow: UnitOfWork
) -> GlobalContext:
    async with uow:
        # Fetch the deployment
        deployment = await uow.deployments.find(deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Instance with id {deployment_id} not found."
            )

        return await generate_context_from_deployment(deployment, uow)


def _resolve_release_reference(
    deployment: Deployment, release_reference: str | None
) -> str:
    """Decide the Helm release name for a deployment's next context.

    A deployment's Helm release name is chosen **once** and never changes:
    renaming it would orphan the live release and make the next Flux
    reconciliation *install* a second release over objects Helm already owns.
    Recomputing it from the deployment id on every context regeneration was
    only ever correct because the computed value happened to match — this
    resolution order makes the intent explicit.

    Order:

    1. an explicit ``release_reference`` (the clone flow, creating a
       counterpart that adopts the *source's* release name — 010 research D2);
    2. otherwise the value the deployment's active instance already carries,
       so an upgrade / config fan-out never renames a live release;
    3. otherwise ``styrmin-<deployment id>`` — the first instance of an
       ordinary deployment, unchanged from the shipped behaviour.
    """
    if release_reference:
        return release_reference
    active = deployment.active_instance
    if active is not None:
        existing = getattr(
            getattr(active.context, "instance", None), "release_reference", None
        )
        if existing:
            return str(existing)
    return get_kubernetes_reference(deployment.id)


async def generate_context_from_deployment(
    deployment: Deployment,
    uow: UnitOfWork,
    release_reference: str | None = None,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> GlobalContext:
    """Build the resolved :class:`GlobalContext` for a deployment.

    Args:
        deployment: The deployment to resolve a context for.
        uow: Unit of work supplying the repositories.
        release_reference: Override the Helm release name instead of deriving
            it (see :func:`_resolve_release_reference`). Only the environment
            clone path passes it, for a counterpart that adopts the source's
            release; every other caller omits it.
        upcoming_deployments: Ids and names of the deployments that the current
            operation creates; an affinity term that names one of these ids
            resolves without a lookup.
    """
    # FIXME: Fix the context generation
    logger.debug("Generating context for deployment: {}", deployment.id)
    async with uow:
        # Fetch the application driver version
        application_driver_version = await uow.application_driver_versions.get(
            deployment.application_driver_version_id
        )
        assert application_driver_version is not None, "Application not found"

        # Fetch the application driver
        application_driver = await uow.application_drivers.get(
            application_driver_version.application_driver_id
        )
        assert application_driver is not None, "Application driver not found"

        # Fetch the environment
        environment = await uow.environments.get(deployment.environment_id)
        assert environment is not None, "Environment not found"

        # Fetch the cluster
        cluster = await uow.clusters.get(environment.cluster_id)
        assert cluster is not None, "Cluster not found"

        # Fetch the helm chart
        helm_chart = await uow.helm_charts.get(application_driver_version.helm_chart_id)
        assert helm_chart is not None, "Helm chart not found"

        # Fetch the helm repository
        helm_repository = await uow.helm_repositories.get(helm_chart.repository_id)
        assert helm_repository is not None, "Helm repository not found"

        # Prepare the utilities information to send to the workflow
        # Internal deployments (e.g. ingress controller) do not need utilities
        # such as NetworkPolicies or Middlewares, which would interfere with
        # their operation.
        utilities_input: list[UtilityInput] = []
        if not deployment.internal:
            utilities = await uow.utilities.get_all()
            for utility in utilities:
                utilities_input.append(
                    UtilityInput(
                        kind=UtilityKindInput(utility.kind),
                    )
                )

        namespace = get_kubernetes_reference(deployment.id)
        resolved_release_reference = _resolve_release_reference(
            deployment, release_reference
        )
        context_input = ContextInput.model_validate(
            {
                "config": {
                    "cluster": cluster.config or {},
                    "environment": environment.config or {},
                    "deployment": deployment.config or {},
                },
                "instance": {
                    "deployment_id": deployment.id,
                    "namespace": namespace,
                    "release_reference": resolved_release_reference,
                },
                "application": {
                    "name": application_driver.name,
                    "version": deployment.application_version,
                    "chart": {
                        "id": helm_chart.id,
                        "name": helm_chart.name,
                        "version": helm_chart.version,
                        "values_template": helm_chart.values_template,
                    },
                    "repository": {
                        "id": helm_repository.id,
                        "url": helm_repository.url,
                    },
                },
                "components": [
                    component.model_dump(exclude={"id", "deployment_id"})
                    for component in deployment.components or []
                ],
                "utilities": utilities_input,
                "environment_name": environment.name,
                "labels": {
                    "environment_id": environment.id,
                    "deployment_id": deployment.id,
                },
                "parameters": deployment.parameters,
                "driver_version": driver_version_label(application_driver_version.id),
            }
        )

        context = resolve_global_context(context_input=context_input)

        # Populate capabilities from persisted data
        context.cluster.capabilities = cluster.capabilities or {}
        context.environment.capabilities = environment.capabilities or {}

        # Build services context from deployed services in the environment
        fqdn_suffix = context.instance.config.fqdn_suffix
        app_name = application_driver.name
        env_name = environment.name

        deployed_services = await uow.deployed_services.get_by_environment_id(
            deployment.environment_id
        )
        (
            context.services,
            context.deployed_services,
            has_own_services,
        ) = build_service_entries(
            deployed_services,
            app_name=app_name,
            deployment_id=deployment.id,
            environment_name=env_name,
            fqdn_suffix=fqdn_suffix,
        )

        # Auto-add service-discovery utility when this deployment has services
        if has_own_services:
            context.utilities.append(UtilityContext(kind=UtilityKind.SERVICE_DISCOVERY))

        # Resolve scheduling configuration per component and expand any
        # affinity ``deployment_ref`` terms into concrete label selectors.
        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=deployment.environment_id,
            environment_config=environment.config,
            deployment_config=deployment.config,
            deployment_components=deployment.components or [],
            upcoming_deployments=upcoming_deployments,
        )

        # Resolve env vars per component (008-deployment-env-vars / US3).
        # Reads per-component blocks from
        # ``DeploymentConfig.components[<name>].env_vars`` and assigns the
        # merged ``env → dep → comp`` dict to each
        # ``ComponentContext.env_vars``. Components without an explicit block
        # still receive the deployment-level merged dict (FR-002 deepest-wins
        # falls through to the deployment scope).
        _populate_component_env_vars(
            context=context,
            environment_config=environment.config,
            deployment_config=deployment.config,
        )

        # Attach each live component's ``command``/``args`` (component scope only) to
        # ``ComponentContext.container_override``; orphaned blocks are not attached here,
        # only the GraphQL read path returns them.
        _populate_component_container_overrides(
            context=context,
            deployment_config=deployment.config,
        )

        # Image overrides per component (018): live components only, token not substituted.
        _populate_component_image_overrides(
            context=context,
            deployment_config=deployment.config,
        )

        return context


async def _populate_component_scheduling(
    *,
    context: GlobalContext,
    uow: UnitOfWork,
    environment_id: UUID,
    environment_config: dict | None,
    deployment_config: dict | None,
    deployment_components: list,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> None:
    """Populate ``ComponentContext.scheduling`` for each component.

    Reads ``scheduling`` from each level's raw JSON config, resolves and merges
    the levels of each component with :func:`resolve_component_scheduling`, and
    stores the resulting :class:`ResolvedComponentScheduling` on the matching
    :class:`ComponentContext`. Deployment-level ``runtime_class``
    values are passed through without cluster-side validation — an unknown
    name surfaces later as a Pending pod with a scheduler error rather than
    a pre-rollout rejection.
    """
    if context.components is None:
        return

    env_scheduling = _extract_scheduling(
        environment_config, path="environment.config.scheduling"
    )
    dep_scheduling = _extract_scheduling(
        deployment_config, path="deployment.config.scheduling"
    )

    component_scheduling_by_name: dict[str, SchedulingConfig | None] = {}
    for component in deployment_components:
        component_scheduling_by_name[component.name] = _extract_scheduling(
            component.config,
            path=f"component[{component.name}].config.scheduling",
        )

    for name, component_ctx in context.components.root.items():
        comp_scheduling = component_scheduling_by_name.get(name)
        if (
            env_scheduling is None
            and dep_scheduling is None
            and comp_scheduling is None
        ):
            continue
        resolved, provenance = await resolve_component_scheduling(
            uow,
            environment_id,
            env=env_scheduling,
            dep=dep_scheduling,
            comp=comp_scheduling,
            component_name=name,
            upcoming_deployments=upcoming_deployments,
        )
        component_ctx.scheduling = ResolvedComponentScheduling(
            config=resolved, provenance=provenance
        )


async def resolve_component_scheduling(
    uow: UnitOfWork,
    environment_id: UUID,
    *,
    env: SchedulingConfig | None,
    dep: SchedulingConfig | None,
    comp: SchedulingConfig | None,
    component_name: str,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> tuple[SchedulingConfig, dict[str, ProvenanceLevel]]:
    """Resolve the deployment references of one component's three levels, then merge them.

    A pod affinity block that a deeper level discards with ``replace: true`` is
    dropped first, so its terms are not resolved: a deployment can discard a term of
    the environment's config that names a deleted deployment. Every other term is
    resolved in its own level, so an error path names the config that holds it.
    """
    env, dep, comp = _drop_replaced_affinity_blocks(env, dep, comp)
    env = await _expand_scheduling(
        uow,
        environment_id,
        env,
        path_prefix="environment.config.scheduling",
        upcoming_deployments=upcoming_deployments,
    )
    dep = await _expand_scheduling(
        uow,
        environment_id,
        dep,
        path_prefix="deployment.config.scheduling",
        upcoming_deployments=upcoming_deployments,
    )
    comp = await _expand_scheduling(
        uow,
        environment_id,
        comp,
        path_prefix=f"component[{component_name}].config.scheduling",
        upcoming_deployments=upcoming_deployments,
    )
    return _resolve_scheduling_config(env=env, dep=dep, comp=comp)


async def check_deployment_scheduling(
    uow: UnitOfWork,
    deployment: Deployment,
    environment_config: dict | None,
) -> None:
    """Raise the error that building the deployment's next instance would raise for its scheduling.

    Lets a write refuse a term that names a deleted deployment, at any level,
    before it saves anything.
    """
    env = _extract_scheduling(environment_config, path="environment.config.scheduling")
    dep = _extract_scheduling(deployment.config, path="deployment.config.scheduling")
    for component in deployment.components:
        comp = _extract_scheduling(
            component.config, path=f"component[{component.name}].config.scheduling"
        )
        if env is None and dep is None and comp is None:
            continue
        await resolve_component_scheduling(
            uow,
            deployment.environment_id,
            env=env,
            dep=dep,
            comp=comp,
            component_name=component.name,
        )


_POD_AFFINITY_FIELDS = ("pod_affinity", "pod_anti_affinity")


def _drop_replaced_affinity_blocks(
    *levels: SchedulingConfig | None,
) -> list[SchedulingConfig | None]:
    """Remove each pod affinity block that a deeper level discards with ``replace: true``.

    ``levels`` run shallowest to deepest. The merge gives the same result with or
    without the removed blocks.
    """
    trimmed = list(levels)
    for field_name in _POD_AFFINITY_FIELDS:
        replacing = [
            index
            for index, level in enumerate(levels)
            if level is not None
            and (block := getattr(level, field_name)) is not None
            and block.replace
        ]
        if not replacing:
            continue
        for index in range(replacing[-1]):
            level = trimmed[index]
            if level is not None and getattr(level, field_name) is not None:
                trimmed[index] = level.model_copy(update={field_name: None})
    return trimmed


async def _expand_scheduling(
    uow: UnitOfWork,
    environment_id: UUID,
    scheduling: SchedulingConfig | None,
    *,
    path_prefix: str,
    upcoming_deployments: Mapping[UUID, str] | None = None,
) -> SchedulingConfig | None:
    """Expand the affinity ``deployment_ref`` terms of one config level, if it has scheduling."""
    if scheduling is None:
        return None
    return await expand_deployment_references(
        uow,
        environment_id,
        scheduling,
        path_prefix=path_prefix,
        upcoming_deployments=upcoming_deployments,
    )


def _populate_component_env_vars(
    *,
    context: GlobalContext,
    environment_config: dict | None,
    deployment_config: dict | None,
) -> None:
    """Populate ``ComponentContext.env_vars`` with per-component merged dicts.

    Reads per-component env var blocks from
    ``DeploymentConfig.components[<name>].env_vars`` and assigns each
    :class:`ComponentContext` a :class:`ResolvedComponentEnvVars` whose
    ``config`` is the FR-002 deepest-wins merge of
    ``env → dep → component_block``. Components without a stored block still
    receive the deployment-level merged dict (the merge falls through to the
    ``dep`` layer and stops).

    Stored blocks targeting components the deployment's current driver does
    NOT declare are silently ignored in US3 — Phase 7 (US5) will surface
    them as ``is_orphaned=True`` entries. Mutation-side validation is the
    place for hard rejection (T040).

    Enforces the FR-008a post-merge size caps: 256 KiB per component, 1 MiB
    summed across components per deployment. Failures raise
    :class:`EnvVarSizeLimitExceededError(scope="resolved", ...)`.
    """
    env_cfg = _validate_env_section(environment_config, scope="environment")
    dep_cfg = _validate_env_section(deployment_config, scope="deployment")

    # Extract per-component env var blocks from the typed DeploymentConfig.
    component_env_vars: dict[str, dict[str, str] | None] = {}
    if dep_cfg is not None and isinstance(dep_cfg, DeploymentConfig):
        for name, block in (dep_cfg.components or {}).items():
            component_env_vars[name] = block.env_vars

    driver_components: list[str] | None = None
    if context.components is not None:
        driver_components = list(context.components.root.keys())

    resolved = EnvVarsResolver.resolve_for_deployment(
        environment=env_cfg,
        deployment=dep_cfg,
        component_env_vars=component_env_vars,
        driver_components=driver_components,
    )

    deployment_dict = resolved.deployment_effective

    # FR-004 broadcast path — no components declared. The deployment-level
    # effective dict is consumed directly by the patch builder via
    # ``context.instance.config.env_vars``; nothing to attach to a component
    # context here. Still enforce the FR-008a per-component cap because the
    # broadcast applies to every workload.
    if context.components is None or len(context.components.root) == 0:
        if deployment_dict:
            per_component_bytes = _serialised_dict_bytes(deployment_dict)
            if per_component_bytes > _RESOLVED_PER_COMPONENT_BYTE_CAP:
                raise EnvVarSizeLimitExceededError(
                    scope="resolved",
                    bytes=per_component_bytes,
                    cap=_RESOLVED_PER_COMPONENT_BYTE_CAP,
                )
        return

    # FR-008a caps — applied per-component on the post-merge dict, plus the
    # 1 MiB per-deployment cap summed across components. Orphan entries
    # (US5) carry stale operator-set values that the patch builder skips,
    # so they don't consume runtime budget — exclude them from cap
    # accounting.
    total_bytes = 0
    for entry in resolved.components:
        if entry.resolved.is_orphaned:
            continue
        per_component_bytes = _serialised_dict_bytes(entry.resolved.config)
        if per_component_bytes > _RESOLVED_PER_COMPONENT_BYTE_CAP:
            raise EnvVarSizeLimitExceededError(
                scope="resolved",
                component=entry.component_name,
                bytes=per_component_bytes,
                cap=_RESOLVED_PER_COMPONENT_BYTE_CAP,
            )
        total_bytes += per_component_bytes
    if total_bytes > _RESOLVED_PER_DEPLOYMENT_BYTE_CAP:
        raise EnvVarSizeLimitExceededError(
            scope="resolved",
            bytes=total_bytes,
            cap=_RESOLVED_PER_DEPLOYMENT_BYTE_CAP,
        )

    # Attach per-component resolved env vars. Components with empty merged
    # dicts get ``None`` so the patch builder skips them cleanly.
    for entry in resolved.components:
        component_ctx = context.components.root.get(entry.component_name)
        if component_ctx is None:
            continue
        if not entry.resolved.config:
            component_ctx.env_vars = None
            continue
        component_ctx.env_vars = entry.resolved


def _populate_component_container_overrides(
    *,
    context: GlobalContext,
    deployment_config: dict | None,
) -> None:
    """Populate ``ComponentContext.container_override`` per component.

    Reads per-component ``command``/``args`` blocks from
    ``DeploymentConfig.components[<name>]`` and assigns each
    :class:`ComponentContext` a :class:`ResolvedComponentContainerOverride`.
    Component-scope only — there is NO ``env → dep → comp`` layering
    (research.md D2): the resolved value is the stored block's value or
    ``None``.

    Orphan entries (stored blocks whose component the driver no longer
    declares) are produced by the resolver for the read surface but are NOT
    attached to any component context here — there is no live
    ``ComponentContext`` to attach them to, and the post-render patch builder
    must never apply an orphaned override (FR-005). Components whose resolved
    ``command`` and ``args`` are both ``None`` get ``None``, so the patch builder
    writes neither and the chart's values apply.
    """
    if context.components is None or len(context.components.root) == 0:
        return

    dep_cfg = _validate_env_section(deployment_config, scope="deployment")
    component_blocks: dict[str, ComponentConfigBlock | None] = {}
    if dep_cfg is not None and isinstance(dep_cfg, DeploymentConfig):
        component_blocks = dict(dep_cfg.components or {})

    driver_components = list(context.components.root.keys())
    entries = ContainerOverridesResolver.resolve_for_deployment(
        component_overrides=component_blocks,
        driver_components=driver_components,
    )

    for entry in entries:
        # Orphans are never attached to a live component context — they exist
        # only for the GraphQL read surface and must not reach a pod.
        if entry.resolved.is_orphaned:
            continue
        component_ctx = context.components.root.get(entry.component_name)
        if component_ctx is None:
            continue
        if entry.resolved.command is None and entry.resolved.args is None:
            component_ctx.container_override = None
            continue
        component_ctx.container_override = entry.resolved


def _populate_component_image_overrides(
    *,
    context: GlobalContext,
    deployment_config: dict | None,
) -> None:
    """Populate ``ComponentContext.image_override`` for live components with an override.

    The reference stays unsubstituted; the patch builder resolves ``{{ app.version }}`` at render.
    Orphans are never attached, and components without an override keep ``None`` (SC-002).
    """
    if context.components is None or len(context.components.root) == 0:
        return

    dep_cfg = _validate_env_section(deployment_config, scope="deployment")
    component_blocks: dict[str, ComponentConfigBlock | None] = {}
    if isinstance(dep_cfg, DeploymentConfig):
        component_blocks = dict(dep_cfg.components or {})

    entries = ImageOverridesResolver.resolve_for_deployment(
        component_overrides=component_blocks,
        driver_components=list(context.components.root.keys()),
    )
    for entry in entries:
        if entry.resolved.is_orphaned:
            continue
        component_ctx = context.components.root.get(entry.component_name)
        if component_ctx is not None:
            component_ctx.image_override = entry.resolved


def _validate_env_section(
    raw_config: dict | None, *, scope: str
) -> EnvironmentConfig | DeploymentConfig | None:
    """Build the typed config model from a raw dict so the env_vars
    Pydantic field validators run before resolution. Defensive: the
    deployment service already validates on the write path, but resolution
    can run from sources that bypass the mutation (e.g. context-from-CRD).
    """
    if not raw_config:
        return None
    if scope == "environment":
        return EnvironmentConfig.model_validate(raw_config)
    return DeploymentConfig.model_validate(raw_config)


def _extract_scheduling(
    raw_config: dict | None, *, path: str
) -> SchedulingConfig | None:
    if not raw_config:
        return None
    payload = raw_config.get("scheduling") if isinstance(raw_config, dict) else None
    if payload is None:
        return None
    try:
        return SchedulingConfig.model_validate(payload)
    except ValidationError as e:
        raise InvalidSchedulingConfigError(
            message=f"Invalid scheduling configuration at {path}: {e!s}",
            path=path,
        ) from e
