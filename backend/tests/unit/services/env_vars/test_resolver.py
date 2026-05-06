"""Unit tests for the env vars merge helper (008-deployment-env-vars, T018).

Targets ``_merge_env_vars`` in ``backend/styrmin_backend/context/resolvers.py``
which implements per-key deepest-wins merge across env / deployment /
component layers (data-model.md §2.2). The end-to-end resolver
(``EnvVarsResolver.resolve_for_deployment``) lands in US1 (T019), so this
file pins down the merge primitive in isolation.

US2 (T035) adds high-level :class:`EnvVarsResolver` tests that lock in the
environment-scope precedence cases at the resolver surface — env-only,
env-overridden-by-deployment per-key, env-and-deployment-disjoint-keys-merge.
"""

from __future__ import annotations

import pytest

from styrmin_backend.context.models.config import (
    DeploymentConfig,
    EnvironmentConfig,
)
from styrmin_backend.context.resolvers import _merge_env_vars
from styrmin_backend.services.env_vars.resolver import EnvVarsResolver


class TestMergeEnvVars:
    def test_all_none_returns_empty(self) -> None:
        config, prov = _merge_env_vars(None, None, None)
        assert config == {}
        assert prov == {}

    def test_environment_only(self) -> None:
        config, prov = _merge_env_vars({"FOO": "1"}, None, None)
        assert config == {"FOO": "1"}
        assert prov == {"FOO": "environment"}

    def test_deployment_only(self) -> None:
        config, prov = _merge_env_vars(None, {"FOO": "1"}, None)
        assert config == {"FOO": "1"}
        assert prov == {"FOO": "deployment"}

    def test_component_only(self) -> None:
        config, prov = _merge_env_vars(None, None, {"FOO": "1"})
        assert config == {"FOO": "1"}
        assert prov == {"FOO": "component"}

    def test_deployment_overrides_environment_per_key(self) -> None:
        env = {"FOO": "env", "SHARED": "env"}
        dep = {"BAR": "dep", "SHARED": "dep"}
        config, prov = _merge_env_vars(env, dep, None)
        assert config == {"FOO": "env", "BAR": "dep", "SHARED": "dep"}
        assert prov == {
            "FOO": "environment",
            "BAR": "deployment",
            "SHARED": "deployment",
        }

    def test_component_overrides_deployment_overrides_environment(self) -> None:
        env = {"A": "env", "B": "env", "C": "env"}
        dep = {"B": "dep", "C": "dep"}
        comp = {"C": "comp"}
        config, prov = _merge_env_vars(env, dep, comp)
        assert config == {"A": "env", "B": "dep", "C": "comp"}
        assert prov == {"A": "environment", "B": "deployment", "C": "component"}

    def test_disjoint_keys_across_layers(self) -> None:
        env = {"A": "env"}
        dep = {"B": "dep"}
        comp = {"C": "comp"}
        config, prov = _merge_env_vars(env, dep, comp)
        assert config == {"A": "env", "B": "dep", "C": "comp"}
        assert prov == {"A": "environment", "B": "deployment", "C": "component"}

    def test_empty_dicts_are_skipped(self) -> None:
        # FR-004 fallback path: when components are absent, callers pass
        # comp=None or {}; both must behave identically.
        config_a, prov_a = _merge_env_vars({"FOO": "1"}, {}, None)
        config_b, prov_b = _merge_env_vars({"FOO": "1"}, None, {})
        assert config_a == config_b == {"FOO": "1"}
        assert prov_a == prov_b == {"FOO": "environment"}

    @pytest.mark.parametrize(
        "env,dep,comp,expected_config,expected_prov",
        [
            (
                {"K": "1"},
                {"K": "2"},
                {"K": "3"},
                {"K": "3"},
                {"K": "component"},
            ),
            (
                {"K": "1"},
                {"K": "2"},
                None,
                {"K": "2"},
                {"K": "deployment"},
            ),
            (
                {"K": "1"},
                None,
                {"K": "3"},
                {"K": "3"},
                {"K": "component"},
            ),
            (
                None,
                {"K": "2"},
                {"K": "3"},
                {"K": "3"},
                {"K": "component"},
            ),
        ],
        ids=[
            "all-three-comp-wins",
            "env-and-dep-dep-wins",
            "env-and-comp-comp-wins",
            "dep-and-comp-comp-wins",
        ],
    )
    def test_precedence_matrix(
        self,
        env: dict[str, str] | None,
        dep: dict[str, str] | None,
        comp: dict[str, str] | None,
        expected_config: dict[str, str],
        expected_prov: dict[str, str],
    ) -> None:
        config, prov = _merge_env_vars(env, dep, comp)
        assert config == expected_config
        assert prov == expected_prov

    def test_inputs_are_not_mutated(self) -> None:
        env = {"FOO": "1"}
        dep = {"FOO": "2"}
        config, _ = _merge_env_vars(env, dep, None)
        assert env == {"FOO": "1"}
        assert dep == {"FOO": "2"}
        # Mutating the result must not alias either input.
        config["FOO"] = "mutated"
        assert env == {"FOO": "1"}
        assert dep == {"FOO": "2"}


class TestEnvVarsResolverEnvironmentPrecedence:
    """T035 / US2: precedence cases at the high-level resolver surface.

    Locks in that ``EnvVarsResolver.resolve_for_deployment`` merges the
    environment layer ahead of the deployment layer (FR-002 deepest-wins)
    and reports ``"environment"`` provenance for keys whose value comes
    from the environment scope.
    """

    def test_environment_only_propagates(self) -> None:
        env = EnvironmentConfig(env_vars={"OTEL_ENDPOINT": "https://otel"})
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env, deployment=None
        )
        assert resolved.deployment_effective == {"OTEL_ENDPOINT": "https://otel"}
        assert resolved.deployment_provenance == {"OTEL_ENDPOINT": "environment"}
        assert resolved.components == []

    def test_environment_overridden_by_deployment_per_key(self) -> None:
        env = EnvironmentConfig(env_vars={"FOO": "env", "SHARED": "env"})
        dep = DeploymentConfig(env_vars={"SHARED": "dep"})
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env, deployment=dep
        )
        # Deployment value wins on the colliding key; the disjoint
        # environment key still propagates.
        assert resolved.deployment_effective == {"FOO": "env", "SHARED": "dep"}
        assert resolved.deployment_provenance == {
            "FOO": "environment",
            "SHARED": "deployment",
        }

    def test_environment_and_deployment_disjoint_keys_merge(self) -> None:
        env = EnvironmentConfig(env_vars={"OTEL_ENDPOINT": "https://otel"})
        dep = DeploymentConfig(env_vars={"LOG_LEVEL": "debug"})
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env, deployment=dep
        )
        assert resolved.deployment_effective == {
            "OTEL_ENDPOINT": "https://otel",
            "LOG_LEVEL": "debug",
        }
        assert resolved.deployment_provenance == {
            "OTEL_ENDPOINT": "environment",
            "LOG_LEVEL": "deployment",
        }

    def test_both_unset_returns_empty(self) -> None:
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=EnvironmentConfig(), deployment=DeploymentConfig()
        )
        assert resolved.deployment_effective == {}
        assert resolved.deployment_provenance == {}
        assert resolved.components == []

    def test_none_inputs_return_empty(self) -> None:
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=None, deployment=None
        )
        assert resolved.deployment_effective == {}
        assert resolved.deployment_provenance == {}
