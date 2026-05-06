"""Environment variables resolver for the deployment env vars feature (008).

Layered per-component resolution that mirrors ``services/scheduling/``
(pure logic, no IO). The merge primitive (:func:`_merge_env_vars`) is
imported from :mod:`styrmin_backend.context.resolvers`; this module wires
it up to the ``EnvironmentConfig`` / ``DeploymentConfig`` Pydantic models
and produces :class:`ResolvedComponentEnvVars` records ready to attach to
a ``ComponentContext``.

US1 (this iteration) only computes the deployment-level effective dict —
the per-component path is not exercised yet. The signature already
accepts ``component_env_vars`` so US3 can fill it in without rewriting
callers.
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
class ResolvedDeploymentEnvVars:
    """Result of :func:`EnvVarsResolver.resolve_for_deployment`.

    ``deployment_effective`` is the merged ``env → dep → None`` dict (FR-004
    fallback used directly when no components are declared). ``components``
    is one :class:`ResolvedComponentEnvVars` per component declared by the
    deployment — empty for US1 since the per-component path lands in US3.
    """

    deployment_effective: dict[str, str]
    deployment_provenance: dict[str, ProvenanceLevel]
    components: list[ResolvedComponentEnvVars]


class EnvVarsResolver:
    """Pure-logic resolver for layered env vars (FR-001..FR-004)."""

    @staticmethod
    def resolve_for_deployment(
        environment: EnvironmentConfig | None,
        deployment: DeploymentConfig | None,
        component_env_vars: dict[str, dict[str, str] | None] | None = None,
    ) -> ResolvedDeploymentEnvVars:
        """Resolve effective env vars for a deployment.

        Layers (shallowest → deepest): ``environment`` → ``deployment`` →
        per-component. The function returns the deployment-level merged
        dict (used as the FR-004 fallback when no components are declared)
        plus one :class:`ResolvedComponentEnvVars` per entry in
        ``component_env_vars``.

        For US1 the per-component path is empty by default; US3 will pass
        a populated ``component_env_vars`` mapping. ``component_env_vars``
        values are the raw stored per-component dicts (the validator runs
        inside the Pydantic model that owns them).
        """
        env_vars = environment.env_vars if environment is not None else None
        dep_vars = deployment.env_vars if deployment is not None else None

        deployment_effective, deployment_provenance = _merge_env_vars(
            env_vars, dep_vars, None
        )

        components: list[ResolvedComponentEnvVars] = []
        if component_env_vars:
            for _name, comp_dict in component_env_vars.items():
                config, provenance = _merge_env_vars(env_vars, dep_vars, comp_dict)
                components.append(
                    ResolvedComponentEnvVars(
                        config=config,
                        provenance=provenance,
                        is_orphaned=False,
                    )
                )

        return ResolvedDeploymentEnvVars(
            deployment_effective=deployment_effective,
            deployment_provenance=deployment_provenance,
            components=components,
        )
