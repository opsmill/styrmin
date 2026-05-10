"""Environment variables resolver for the deployment env vars feature (008).

Layered per-component resolution that mirrors ``services/scheduling/``
(pure logic, no IO). The merge primitive (:func:`_merge_env_vars`) is
imported from :mod:`styrmin_backend.context.resolvers`; this module wires
it up to the ``EnvironmentConfig`` / ``DeploymentConfig`` Pydantic models
and produces :class:`ResolvedComponentEnvVars` records ready to attach to
a ``ComponentContext``.

US1 computed the deployment-level effective dict from environment+deployment
scopes. US2 (T031) wired environment-scope merging. US3 (T038) extended the
resolver to take per-component env var blocks and produce one
:class:`ResolvedComponentEnvVars` per **driver-declared** component, with
per-key deepest-wins precedence (FR-002). US5 (T056, Phase 7) now surfaces
stored blocks targeting components the driver does NOT declare as orphan
entries (``is_orphaned=True``) instead of silently dropping them — so
operators can see the leftover configuration and clean it up after a driver
upgrade renames or removes a component (FR-029..FR-033).

Read-vs-write asymmetry (FR-029): the resolver tolerates orphan state so
operators can audit it through the GraphQL surface. The mutation validators
in :mod:`styrmin_backend.services.deployment` raise
:class:`UnknownComponentEnvVarError` on every write that targets an unknown
component — so new typos are blocked at the boundary while existing blocks
that became orphans through a driver upgrade remain visible.
"""

from __future__ import annotations

from dataclasses import dataclass

from styrmin_backend.context.models.components import (
    ProvenanceLevel,
    ResolvedComponentEnvVars,
)
from styrmin_backend.context.models.config import (
    DeploymentConfig,
    EnvironmentConfig,
)
from styrmin_backend.context.resolvers import _merge_env_vars


@dataclass(frozen=True)
class ResolvedComponentEnvVarsEntry:
    """One :class:`ResolvedComponentEnvVars` plus its target component name.

    The resolver records the component name alongside the resolved record so
    callers can attach it to the matching :class:`ComponentContext` without
    relying on iteration order. Live entries (``is_orphaned=False``) target
    a component the current driver still declares. Orphan entries
    (``is_orphaned=True``, US5 / FR-029..FR-033) target a component name that
    is no longer in the driver's component map (e.g. after a driver upgrade
    that renamed or removed the component); they remain queryable but the
    patch builder skips them so no env entries are injected.
    """

    component_name: str
    resolved: ResolvedComponentEnvVars


@dataclass(frozen=True)
class ResolvedDeploymentEnvVars:
    """Result of :func:`EnvVarsResolver.resolve_for_deployment`.

    ``deployment_effective`` is the merged ``env → dep → None`` dict (FR-004
    fallback used directly when no components are declared). ``components``
    is one :class:`ResolvedComponentEnvVarsEntry` per **driver-declared**
    component — each merging ``env → dep → component_env_vars[name]`` per
    FR-002 deepest-wins — followed by zero or more orphan entries (US5):
    one per stored ``component_env_vars`` key whose component is not in the
    current driver's component map. Orphan entries carry only the stored
    component-scope values (provenance ``"component"`` for every key) and
    are skipped by the patch builder.
    """

    deployment_effective: dict[str, str]
    deployment_provenance: dict[str, ProvenanceLevel]
    components: list[ResolvedComponentEnvVarsEntry]


class EnvVarsResolver:
    """Pure-logic resolver for layered env vars (FR-001..FR-004)."""

    @staticmethod
    def resolve_for_deployment(
        environment: EnvironmentConfig | None,
        deployment: DeploymentConfig | None,
        component_env_vars: dict[str, dict[str, str] | None] | None = None,
        driver_components: list[str] | None = None,
    ) -> ResolvedDeploymentEnvVars:
        """Resolve effective env vars for a deployment.

        Layers (shallowest → deepest): ``environment`` → ``deployment`` →
        per-component. Returns the deployment-level merged dict (used as the
        FR-004 broadcast fallback when no components are declared) plus one
        :class:`ResolvedComponentEnvVarsEntry` per **driver-declared**
        component.

        ``component_env_vars`` is the raw stored per-component dicts keyed by
        component name (sourced from
        ``DeploymentConfig.components[<name>].env_vars``). ``driver_components``
        is the list of component names the deployment's current driver
        declares. Stored blocks whose key is NOT in ``driver_components`` are
        emitted as orphan entries (``is_orphaned=True``, FR-029..FR-033)
        carrying only the stored component-scope values; their provenance
        records every key as ``"component"`` and the patch builder skips
        them so no env entries are injected.

        When ``driver_components`` is ``None`` the resolver behaves as in US1
        (no per-component output, no orphan detection) — used when the caller
        does not yet have the driver's component map (e.g. when computing the
        broadcast ``deployment_effective`` ahead of context resolution).
        """
        env_vars = environment.env_vars if environment is not None else None
        dep_vars = deployment.env_vars if deployment is not None else None

        deployment_effective, deployment_provenance = _merge_env_vars(
            env_vars, dep_vars, None
        )

        components: list[ResolvedComponentEnvVarsEntry] = []
        if driver_components is not None:
            comp_blocks = component_env_vars or {}
            known = set(driver_components)
            for name in driver_components:
                comp_dict = comp_blocks.get(name)
                config, provenance = _merge_env_vars(env_vars, dep_vars, comp_dict)
                components.append(
                    ResolvedComponentEnvVarsEntry(
                        component_name=name,
                        resolved=ResolvedComponentEnvVars(
                            config=config,
                            provenance=provenance,
                            is_orphaned=False,
                        ),
                    )
                )
            # US5 (FR-029..FR-033): emit orphan entries for stored blocks whose
            # target component name is no longer in the driver's component
            # map. Sorted for stable surface ordering. Empty / None blocks
            # are dropped — there's nothing to display.
            for name in sorted(comp_blocks):
                if name in known:
                    continue
                comp_dict = comp_blocks.get(name)
                if not comp_dict:
                    continue
                # Orphan entries carry only the stored component-scope values.
                # We deliberately do NOT layer env / deployment scopes on top:
                # an orphan represents a stale operator-set block, and the
                # operator-visible config should reflect what they stored.
                config = dict(comp_dict)
                provenance = {k: "component" for k in comp_dict}
                components.append(
                    ResolvedComponentEnvVarsEntry(
                        component_name=name,
                        resolved=ResolvedComponentEnvVars(
                            config=config,
                            provenance=provenance,
                            is_orphaned=True,
                        ),
                    )
                )

        return ResolvedDeploymentEnvVars(
            deployment_effective=deployment_effective,
            deployment_provenance=deployment_provenance,
            components=components,
        )
