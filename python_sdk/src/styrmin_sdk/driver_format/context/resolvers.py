import logging
from collections.abc import Callable
from itertools import product
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from styrmin_sdk.driver_format.context.exceptions import ContextError
from styrmin_sdk.driver_format.context.models.components import (
    ComponentContext,
    ComponentsContext,
    ProvenanceLevel,
)
from styrmin_sdk.driver_format.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    LabelSelector,
    LabelSelectorRequirement,
    PostRenderInjection,
    ResolvedConfig,
    ResourceRequirements,
    ResourceSpec,
    SchedulingConfig,
    Toleration,
    TopologySpreadConstraint,
    WeightedAffinityTerm,
)
from styrmin_sdk.driver_format.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
    UtilityContext,
    UtilityKind,
)
from styrmin_sdk.driver_format.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_sdk.driver_format.context.models.input import (
    ApplicationInput,
    ComponentInput,
    ContextInput,
    UtilityInput,
)
from styrmin_sdk.driver_format.context.validators import format_config_validation_error
from styrmin_sdk.driver_format.errors import UnknownComponentInConfigError

logger = logging.getLogger(__name__)


def _resolve_cluster_context(cluster_config: ClusterConfig) -> ClusterContext:
    return ClusterContext(config=cluster_config)


def _resolve_environment_context(
    environment_config: EnvironmentConfig,
    name: str,
) -> EnvironmentContext:
    return EnvironmentContext(name=name, config=environment_config)


def _resolve_deployment_context(
    deployment_config: DeploymentConfig,
) -> DeploymentContext:
    return DeploymentContext(
        config=deployment_config,
    )


def _resolve_instance_config(
    cluster: ClusterConfig, environment: EnvironmentConfig, deployment: DeploymentConfig
) -> ResolvedConfig:
    # Merge the cluster, environment and deployment contexts
    resolved_context = {
        **cluster.model_dump(exclude_none=True),
        **environment.model_dump(exclude_none=True),
        **deployment.model_dump(exclude_none=True),
    }

    # T071 (data-model I2): InstanceContext.config.scheduling must be the
    # deepest-per-field merge of env + dep (component overrides are
    # per-component and live on ComponentContext.scheduling). The whole-
    # object dict merge above would lose env fields whenever dep also set
    # ``scheduling``; recompute it via ``_resolve_scheduling_config``.
    if environment.scheduling is not None or deployment.scheduling is not None:
        resolved_scheduling, _ = _resolve_scheduling_config(
            env=environment.scheduling,
            dep=deployment.scheduling,
            comp=None,
        )
        resolved_context["scheduling"] = resolved_scheduling.model_dump(exclude_none=True)
    else:
        resolved_context.pop("scheduling", None)

    # Same per-key-deepest-wins rule applies to env_vars (FR-002). The flat
    # dict spread above replaces ``env_vars`` wholesale whenever both env
    # and dep set it, dropping environment-scope keys that aren't also set
    # at deployment scope. The render-time broadcast (when no components
    # are declared, application.py:407) reads from this resolved dict and
    # would otherwise miss those keys — US2 Acceptance Scenario 1.
    if environment.env_vars is not None or deployment.env_vars is not None:
        merged_env_vars, _ = _merge_env_vars(
            env=environment.env_vars,
            dep=deployment.env_vars,
            comp=None,
        )
        resolved_context["env_vars"] = merged_env_vars
    else:
        resolved_context.pop("env_vars", None)

    return ResolvedConfig(**resolved_context)


def resolve_instance_config(
    cluster: ClusterConfig, environment: EnvironmentConfig, deployment: DeploymentConfig
) -> ResolvedConfig:
    """Return the config an instance resolves to, without building a whole ``GlobalContext``."""
    return _resolve_instance_config(cluster=cluster, environment=environment, deployment=deployment)


def _resolve_application_context(
    application: ApplicationInput,
) -> ApplicationContext:
    chart = ChartInfo(**application.chart.model_dump(exclude_none=True))
    repository = RepositoryInfo(**application.repository.model_dump(exclude_none=True))

    helm = HelmInfo(chart=chart, repository=repository)

    return ApplicationContext(
        name=application.name,
        version=application.version,
        helm=helm,
    )


def _resolve_instance_context(
    cluster_config: ClusterConfig,
    environment_config: EnvironmentConfig,
    deployment_config: DeploymentConfig,
    namespace: str,
    release_reference: str,
    deployment_id: UUID,
) -> InstanceContext:
    # Resolve the context between cluster, environment and instance
    resolved_config = _resolve_instance_config(
        cluster=cluster_config,
        environment=environment_config,
        deployment=deployment_config,
    )

    instance_context = InstanceContext(
        deployment_id=deployment_id,
        namespace=namespace,
        release_reference=release_reference,
        config=resolved_config,
    )

    return instance_context


_ResourceField = Literal["cpu", "memory", "ephemeral_storage"]
_AffinityKind = Literal["pod_affinity", "pod_anti_affinity", "node_affinity"]

_INJECT_FIELDS: tuple[str, ...] = (
    "pod_affinity",
    "node_affinity",
    "topology_spread",
    "resources",
    "tolerations",
    "runtime_class",
)


def _merge_env_vars(
    env: dict[str, str] | None,
    dep: dict[str, str] | None,
    comp: dict[str, str] | None,
) -> tuple[dict[str, str], dict[str, ProvenanceLevel]]:
    """Merge layered env var dicts with per-key deepest-wins.

    Layers (shallowest → deepest): ``env``, ``dep``, ``comp``. For every key
    present in any layer the deepest contributing level wins; provenance
    records that level under the key. Empty / ``None`` layers are skipped.
    Returns a fresh ``(config, provenance)`` pair so callers can mutate it
    without aliasing the inputs.

    Mirrors data-model.md §2.2. Used by the env vars resolver in
    ``services/env_vars/resolver.py`` (US1+) and exported here so unit tests
    can exercise the merge in isolation.
    """
    config: dict[str, str] = {}
    provenance: dict[str, ProvenanceLevel] = {}
    layers: list[tuple[dict[str, str] | None, ProvenanceLevel]] = [
        (env, "environment"),
        (dep, "deployment"),
        (comp, "component"),
    ]
    for src, level in layers:
        if not src:
            continue
        for k, v in src.items():
            config[k] = v  # later layers overwrite; deepest wins per key
            provenance[k] = level
    return config, provenance


def _merge_inject_flags(
    levels: list[tuple[ProvenanceLevel, SchedulingConfig | None]],
    provenance: dict[str, ProvenanceLevel],
) -> PostRenderInjection | None:
    """Merge ``PostRenderInjection`` per-field with deepest-wins.

    Environment-scope ``inject`` is accepted but ignored (data-model §1);
    when set at the environment level a warning is logged so operators can
    move it to deployment/component scope instead of silently seeing it
    dropped. ``None`` at every level is reported as ``None`` (no inject
    object is constructed); any explicit ``True``/``False`` at deployment
    or component level yields a :class:`PostRenderInjection` instance.
    """
    resolved: dict[str, bool] = {}
    for level, cfg in levels:
        if cfg is None or cfg.inject is None:
            continue
        if level == "environment":
            logger.warning(
                "scheduling.inject set at environment scope is ignored; move opt-outs to deployment or component scope"
            )
            continue
        for field_name in _INJECT_FIELDS:
            value = getattr(cfg.inject, field_name)
            if value is not None:
                resolved[field_name] = value
                provenance[f"inject.{field_name}"] = level
    if not resolved:
        return None
    return PostRenderInjection(**resolved)


def effective_inject_flag(inject: PostRenderInjection | None, field_name: str) -> bool:
    """Return the effective (defaulted) value of an inject flag.

    ``None`` — whether because no level set ``inject`` at all or because
    the field is inherited — resolves to ``True``. Recognises every flag
    declared on :class:`PostRenderInjection`.
    """
    if inject is None:
        return True
    value = getattr(inject, field_name, None)
    return value if value is not None else True


def _concatenate_terms(groups: list[list[AffinityTerm]]) -> list[AffinityTerm]:
    """Join each level's required terms; the scheduler ANDs pod (anti-)affinity terms."""
    return [term for group in groups for term in group]


def _node_term_expressions(term: AffinityTerm) -> list[LabelSelectorRequirement]:
    """Return a node term's ``matchExpressions``, with ``matchLabels`` as ``In`` expressions."""
    selector = term.label_selector
    if selector is None:
        return []
    expressions = list(selector.match_expressions or [])
    expressions.extend(
        LabelSelectorRequirement(key=key, operator="In", values=[value])
        for key, value in (selector.match_labels or {}).items()
    )
    return expressions


def _and_node_affinity_terms(groups: list[list[AffinityTerm]]) -> list[AffinityTerm]:
    """Combine each level's required node terms so a node must match one term of every level.

    Kubernetes ORs ``nodeSelectorTerms`` and ANDs the expressions of one term,
    so the result has one term for each combination of one term per level.
    The terms of a single level are returned unchanged. When several levels set
    terms, terms without expressions are dropped first, and a level left without
    terms adds no requirement.
    """
    if len(groups) > 1:
        groups = [kept for group in groups if (kept := [term for term in group if _node_term_expressions(term)])]
    if len(groups) <= 1:
        return groups[0] if groups else []
    return [
        AffinityTerm(
            topology_key="",
            label_selector=LabelSelector(
                match_expressions=[expression for term in combination for expression in _node_term_expressions(term)]
            ),
        )
        for combination in product(*groups)
    ]


def _merge_affinity_blocks(
    level_blocks: list[tuple[ProvenanceLevel, AffinityBlock | None]],
    provenance_key: str,
    provenance: dict[str, ProvenanceLevel],
    combine_required: Callable[[list[list[AffinityTerm]]], list[AffinityTerm]] = _concatenate_terms,
) -> AffinityBlock | None:
    """Accumulate affinity terms across levels with per-kind ``replace:true`` reset.

    ``required`` terms of the levels are ANDed: ``combine_required`` receives
    one list of terms per contributing level and returns the effective list
    (concatenated for pod affinity kinds, combined per node for
    ``node_affinity``). ``preferred`` terms are merged into a single weighted
    list. If any level sets ``replace: true`` the running accumulator is
    discarded at that point; levels deeper than the one that set
    ``replace: true`` continue to accumulate on top of the replacement
    unless they also set ``replace: true``.

    Returns ``None`` when no level contributed any terms at all (including
    the case where the only non-``None`` block at a given kind has empty
    ``required`` and ``preferred``). Provenance records the last level that
    contributed — i.e. the deepest level with either ``replace: true`` or a
    non-empty ``required``/``preferred`` entry.
    """
    required_groups: list[list[AffinityTerm]] = []
    preferred: list[WeightedAffinityTerm] = []
    last_contributing: ProvenanceLevel | None = None

    for level, block in level_blocks:
        if block is None:
            continue
        if block.replace:
            required_groups = []
            preferred = []
            last_contributing = level
        if block.required or block.preferred:
            last_contributing = level
        if block.required:
            required_groups.append(list(block.required))
        preferred.extend(block.preferred)

    if last_contributing is None:
        return None

    provenance[provenance_key] = last_contributing
    return AffinityBlock(required=combine_required(required_groups), preferred=preferred, replace=False)


def _merge_resource_spec(
    level_specs: list[tuple[ProvenanceLevel, ResourceSpec | None]],
    provenance_path_prefix: str,
    provenance: dict[str, ProvenanceLevel],
) -> ResourceSpec | None:
    """Merge a list of (level, ResourceSpec) entries with deepest-wins per field.

    ``level_specs`` is ordered shallowest → deepest. ``extended`` maps are
    merged key-by-key (deepest wins per key). Provenance paths are recorded
    as ``<prefix>.cpu``, ``<prefix>.memory``, ``<prefix>.ephemeral_storage``,
    and ``<prefix>.extended.<key>``. Returns ``None`` when no level sets the
    spec at all.
    """
    if not any(spec is not None for _, spec in level_specs):
        return None

    merged_scalars: dict[str, tuple[str, ProvenanceLevel]] = {}
    merged_extended: dict[str, tuple[str, ProvenanceLevel]] = {}
    fields: tuple[_ResourceField, ...] = ("cpu", "memory", "ephemeral_storage")

    for level, spec in level_specs:
        if spec is None:
            continue
        for field_name in fields:
            value = getattr(spec, field_name)
            if value is not None:
                merged_scalars[field_name] = (value, level)
        for key, value in spec.extended.items():
            merged_extended[key] = (value, level)

    for field_name, (_, level) in merged_scalars.items():
        provenance[f"{provenance_path_prefix}.{field_name}"] = level
    for key, (_, level) in merged_extended.items():
        provenance[f"{provenance_path_prefix}.extended.{key}"] = level

    return ResourceSpec(
        cpu=merged_scalars["cpu"][0] if "cpu" in merged_scalars else None,
        memory=merged_scalars["memory"][0] if "memory" in merged_scalars else None,
        ephemeral_storage=(merged_scalars["ephemeral_storage"][0] if "ephemeral_storage" in merged_scalars else None),
        extended={key: value for key, (value, _) in merged_extended.items()},
    )


def _merge_resource_requirements(
    level_reqs: list[tuple[ProvenanceLevel, ResourceRequirements | None]],
    provenance: dict[str, ProvenanceLevel],
) -> ResourceRequirements | None:
    if not any(req is not None for _, req in level_reqs):
        return None

    requests = _merge_resource_spec(
        [(level, req.requests if req is not None else None) for level, req in level_reqs],
        "resources.requests",
        provenance,
    )
    limits = _merge_resource_spec(
        [(level, req.limits if req is not None else None) for level, req in level_reqs],
        "resources.limits",
        provenance,
    )
    if requests is None and limits is None:
        return None
    return ResourceRequirements(requests=requests, limits=limits)


def _merge_tolerations(
    level_tolerations: list[tuple[ProvenanceLevel, list[Toleration] | None]],
    provenance: dict[str, ProvenanceLevel],
) -> list[Toleration] | None:
    """Union tolerations across levels with stable dedup (FR-009).

    Deduplication compares the full tuple
    ``(key, operator, value, effect, toleration_seconds)``; first occurrence
    wins in iteration order (env → dep → comp). Provenance records the
    contributing level per output entry under ``tolerations[<index>]``;
    the bare ``tolerations`` key reports the deepest level that contributed
    any entry for at-a-glance summaries.
    """
    if not any(t is not None for _, t in level_tolerations):
        return None

    seen: set[tuple] = set()
    merged: list[Toleration] = []
    entry_levels: list[ProvenanceLevel] = []
    for level, tolerations in level_tolerations:
        if not tolerations:
            continue
        for tol in tolerations:
            tup = (tol.key, tol.operator, tol.value, tol.effect, tol.toleration_seconds)
            if tup in seen:
                continue
            seen.add(tup)
            merged.append(tol)
            entry_levels.append(level)
    if not entry_levels:
        return None
    for idx, level in enumerate(entry_levels):
        provenance[f"tolerations[{idx}]"] = level
    provenance["tolerations"] = entry_levels[-1]
    return merged


def _merge_topology_spread(
    level_constraints: list[tuple[ProvenanceLevel, list[TopologySpreadConstraint] | None]],
    provenance: dict[str, ProvenanceLevel],
) -> list[TopologySpreadConstraint] | None:
    """Keyed union on ``(topology_key, when_unsatisfiable)`` with deepest-wins.

    Per FR-010b: entries at deeper levels replace entries at shallower
    levels that share the same key. Iteration order is preserved for
    entries that only appear at one level. Provenance records the
    contributing level per output entry under
    ``topology_spread_constraints[<index>]``; the bare
    ``topology_spread_constraints`` key reports the deepest level that
    contributed any entry.
    """
    if not any(c is not None for _, c in level_constraints):
        return None

    by_key: dict[tuple[str, str], TopologySpreadConstraint] = {}
    level_by_key: dict[tuple[str, str], ProvenanceLevel] = {}
    for level, constraints in level_constraints:
        if not constraints:
            continue
        for c in constraints:
            key = (c.topology_key, c.when_unsatisfiable)
            by_key[key] = c
            level_by_key[key] = level
    if not level_by_key:
        return None
    for idx, key in enumerate(by_key):
        provenance[f"topology_spread_constraints[{idx}]"] = level_by_key[key]
    provenance["topology_spread_constraints"] = next(reversed(level_by_key.values()))
    return list(by_key.values())


def _resolve_scheduling_config(
    env: SchedulingConfig | None,
    dep: SchedulingConfig | None,
    comp: SchedulingConfig | None,
    driver_components: list[str] | None = None,
    component_name: str | None = None,
) -> tuple[SchedulingConfig, dict[str, ProvenanceLevel]]:
    """Resolve effective scheduling configuration for one component.

    Layers (shallowest → deepest): ``env``, ``dep``, ``comp``. Per-field
    merge strategy:

    * ``runtime_class``, ``resources.requests.*``, ``resources.limits.*``,
      ``resources.*.extended[<key>]`` — deepest-wins, per scalar/key.
    * ``pod_affinity`` / ``pod_anti_affinity`` / ``node_affinity`` —
      ``required`` and ``preferred`` terms accumulate across levels;
      ``replace: true`` at any level discards the running accumulator for
      that affinity kind only (US1 / FR-010a). Required ``node_affinity``
      terms of different levels are combined so a node must match one term
      of every level (#486).
    * ``tolerations`` — union across levels with stable tuple dedup on
      ``(key, operator, value, effect, toleration_seconds)`` (FR-009).
    * ``topology_spread_constraints`` — keyed union on
      ``(topology_key, when_unsatisfiable)``, deepest entry wins per key
      (FR-010b).
    * ``inject.*`` — per-field deepest-wins; environment-scope ``inject``
      is accepted but ignored (data-model §1).

    ``provenance`` records the level that contributed each effective field.
    For union fields (``tolerations`` and ``topology_spread_constraints``)
    each entry carries its own provenance under a ``[<index>]`` suffix; a
    summary entry under the bare key reports the deepest level that
    contributed any entry. ``driver_components`` is validated against
    ``component_name`` when both are supplied.
    """
    if component_name is not None and driver_components is not None and component_name not in driver_components:
        raise UnknownComponentInConfigError(
            component_name=component_name,
            path=f"scheduling.components.{component_name}",
        )

    provenance: dict[str, ProvenanceLevel] = {}
    levels: list[tuple[ProvenanceLevel, SchedulingConfig | None]] = [
        ("environment", env),
        ("deployment", dep),
        ("component", comp),
    ]

    def _of(attr: str) -> list:
        return [(level, getattr(cfg, attr) if cfg is not None else None) for level, cfg in levels]

    runtime_class: str | None = None
    for level, cfg in levels:
        if cfg is not None and cfg.runtime_class is not None:
            runtime_class = cfg.runtime_class
            provenance["runtime_class"] = level

    resources = _merge_resource_requirements(_of("resources"), provenance)

    # Affinity blocks accumulate per-kind with replace:true reset (US1).
    pod_affinity = _merge_affinity_blocks(_of("pod_affinity"), "pod_affinity", provenance)
    pod_anti_affinity = _merge_affinity_blocks(_of("pod_anti_affinity"), "pod_anti_affinity", provenance)
    node_affinity = _merge_affinity_blocks(
        _of("node_affinity"),
        "node_affinity",
        provenance,
        combine_required=_and_node_affinity_terms,
    )

    # Tolerations: union with stable tuple dedup (FR-009).
    tolerations = _merge_tolerations(_of("tolerations"), provenance)

    # Topology spread: keyed union on (topology_key, when_unsatisfiable) (FR-010b).
    topology_spread_constraints = _merge_topology_spread(_of("topology_spread_constraints"), provenance)

    # Inject flags merge per-field (FR-016): environment-scope `inject` is
    # accepted but ignored per data-model.md §1; component-level flags
    # override deployment-level flags field-by-field. A ``None`` anywhere
    # means "inherit" — resolved to ``True`` downstream via
    # ``effective_inject_flag``.
    inject = _merge_inject_flags(levels, provenance)

    resolved = SchedulingConfig(
        runtime_class=runtime_class,
        resources=resources,
        pod_affinity=pod_affinity,
        pod_anti_affinity=pod_anti_affinity,
        node_affinity=node_affinity,
        topology_spread_constraints=topology_spread_constraints,
        tolerations=tolerations,
        inject=inject,
    )
    return resolved, provenance


def _resolve_utilities_context(
    utilities: list[UtilityInput],
) -> list[UtilityContext]:
    utilities_context = []
    for utility in utilities:
        utility_context = UtilityContext(
            kind=UtilityKind(utility.kind.value),
        )
        utilities_context.append(utility_context)

    return utilities_context


def _resolve_component_context(
    component: ComponentInput,
    *,
    deployment_config: DeploymentConfig,
    driver_version: str | None,
) -> ComponentContext:
    """Build one declared component's context, with its replica override (023)."""
    raw = component.model_dump()
    block = (deployment_config.components or {}).get(component.name)
    raw["replica_override"] = block.replicas if block is not None else None
    return ComponentContext.model_validate(raw, context={"driver_version": driver_version})


def resolve_global_context(context_input: ContextInput) -> GlobalContext:
    # Create the components context
    if context_input.components:
        driver_version = context_input.driver_version or None
        try:
            components_context = ComponentsContext.model_validate(
                {
                    component.name: _resolve_component_context(
                        component,
                        deployment_config=context_input.config.deployment,
                        driver_version=driver_version,
                    )
                    for component in context_input.components
                }
            )
        except ValidationError as e:
            # Same treatment as the ``validate_*_config`` surfaces (563610b):
            # keep the field path and the validator's message, drop Pydantic's
            # repr. It matters more here than anywhere else — a component's
            # ``config`` is an arbitrary section, so ``input_value`` would echo
            # a whole driver-defined submodel back at the caller.
            raise ContextError(f"The components context validation failed. {format_config_validation_error(e)}") from e
    else:
        components_context = None

    # Create the cluster context
    cluster_context: ClusterContext = _resolve_cluster_context(context_input.config.cluster)

    # Create the environment context
    environment_context: EnvironmentContext = _resolve_environment_context(
        context_input.config.environment,
        name=context_input.environment_name,
    )

    # Create the deployment context
    deployment_context: DeploymentContext = _resolve_deployment_context(context_input.config.deployment)

    # Create the instance context
    instance_context = _resolve_instance_context(
        cluster_config=context_input.config.cluster,
        environment_config=context_input.config.environment,
        deployment_config=context_input.config.deployment,
        namespace=context_input.instance.namespace,
        release_reference=context_input.instance.release_reference,
        deployment_id=context_input.instance.deployment_id,
    )

    # Create the application context
    application_context = _resolve_application_context(context_input.application)

    # Create the utilities context
    utilities_context = _resolve_utilities_context(context_input.utilities)

    # Create the global context object with original contexts and resolved context
    global_context = GlobalContext(
        app=application_context,
        cluster=cluster_context,
        environment=environment_context,
        deployment=deployment_context,
        instance=instance_context,
        components=components_context,
        labels=context_input.labels,
        utilities=utilities_context,
        parameters=context_input.parameters,
    )

    return global_context
