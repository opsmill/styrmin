"""Environment variables resolver for the deployment env vars feature (008).

Layered per-component resolution that mirrors ``services/scheduling/``
(pure logic, no IO). The merge primitive (:func:`_merge_env_vars`) is
imported from :mod:`styrmin_backend.context.resolvers`; this module wires
it up to the ``EnvironmentConfig`` / ``DeploymentConfig`` Pydantic models
and produces :class:`ResolvedComponentEnvVars` records ready to attach to
a ``ComponentContext``.

US1 computed the deployment-level effective dict from environment+deployment
scopes. US2 (T031) wired environment-scope merging. US3 (T038) extends the
resolver to take per-component env var blocks and produce one
:class:`ResolvedComponentEnvVars` per **driver-declared** component, with
per-key deepest-wins precedence (FR-002). Stored blocks targeting components
the driver does not declare are silently ignored in US3 — US5 (Phase 7)
will surface them as orphaned blocks via ``is_orphaned=True``.
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
    relying on iteration order. For US3 every entry has ``is_orphaned=False``;
    US5 will add orphan entries for stored blocks that no longer match a
    driver-declared component.
    """

    component_name: str
    resolved: ResolvedComponentEnvVars


@dataclass(frozen=True)
class ResolvedDeploymentEnvVars:
    """Result of :func:`EnvVarsResolver.resolve_for_deployment`.

    ``deployment_effective`` is the merged ``env → dep → None`` dict (FR-004
    fallback used directly when no components are declared). ``components``
    is one :class:`ResolvedComponentEnvVarsEntry` per **driver-declared**
    component — for US3 each entry merges
    ``env → dep → component_env_vars[name]`` per FR-002 deepest-wins.
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
        silently ignored in US3 — US5 will emit them as orphan entries.

        When ``driver_components`` is ``None`` the resolver behaves as in US1
        (no per-component output) — used when the caller does not yet have
        the driver's component map (e.g. when computing the broadcast
        ``deployment_effective`` ahead of context resolution).
        """
        env_vars = environment.env_vars if environment is not None else None
        dep_vars = deployment.env_vars if deployment is not None else None

        deployment_effective, deployment_provenance = _merge_env_vars(
            env_vars, dep_vars, None
        )

        components: list[ResolvedComponentEnvVarsEntry] = []
        if driver_components is not None:
            comp_blocks = component_env_vars or {}
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
            # Stored blocks targeting unknown components are silently dropped
            # in US3. US5 will replace this branch with orphan emission.

        return ResolvedDeploymentEnvVars(
            deployment_effective=deployment_effective,
            deployment_provenance=deployment_provenance,
            components=components,
        )
