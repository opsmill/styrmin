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


class TestEnvVarsResolverPerComponentPath:
    """T044 / US3: per-component precedence cases at the resolver surface.

    Locks in that
    :func:`EnvVarsResolver.resolve_for_deployment` produces one
    :class:`ResolvedComponentEnvVars` per **driver-declared** component when
    ``driver_components`` is supplied, with the component scope overriding
    deployment + environment scopes per FR-002 deepest-wins precedence.
    Stored blocks targeting components the driver does not declare are
    silently ignored (US5 Phase 7 will surface them as orphans).
    """

    def test_component_overrides_deployment_per_key(self) -> None:
        env = EnvironmentConfig(env_vars={"LOG_LEVEL": "info"})
        dep = DeploymentConfig(env_vars={"LOG_LEVEL": "info"})
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env,
            deployment=dep,
            component_env_vars={
                "worker": {"LOG_LEVEL": "debug", "WORKER_QUEUE": "orders"}
            },
            driver_components=["api", "worker"],
        )
        # Two driver components → two entries.
        assert {e.component_name for e in resolved.components} == {"api", "worker"}
        api_entry = next(e for e in resolved.components if e.component_name == "api")
        worker_entry = next(
            e for e in resolved.components if e.component_name == "worker"
        )
        # api inherits the deployment-level dict; component layer is empty.
        assert api_entry.resolved.config == {"LOG_LEVEL": "info"}
        assert api_entry.resolved.provenance == {"LOG_LEVEL": "deployment"}
        assert api_entry.resolved.is_orphaned is False
        # worker overrides LOG_LEVEL and adds WORKER_QUEUE; provenance flags
        # both keys as ``"component"``.
        assert worker_entry.resolved.config == {
            "LOG_LEVEL": "debug",
            "WORKER_QUEUE": "orders",
        }
        assert worker_entry.resolved.provenance == {
            "LOG_LEVEL": "component",
            "WORKER_QUEUE": "component",
        }

    def test_component_only_no_deployment_no_environment(self) -> None:
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=None,
            deployment=None,
            component_env_vars={"worker": {"WORKER_QUEUE": "orders"}},
            driver_components=["worker"],
        )
        assert len(resolved.components) == 1
        entry = resolved.components[0]
        assert entry.component_name == "worker"
        assert entry.resolved.config == {"WORKER_QUEUE": "orders"}
        assert entry.resolved.provenance == {"WORKER_QUEUE": "component"}

    def test_component_provenance_layers_per_key(self) -> None:
        """Mixed precedence: env / dep / comp each contribute disjoint keys
        plus one key the component overrides — provenance must reflect the
        per-key origin (data-model.md §2.2 deepest-wins)."""
        env = EnvironmentConfig(env_vars={"FROM_ENV": "1", "SHARED": "env"})
        dep = DeploymentConfig(env_vars={"FROM_DEP": "2", "SHARED": "dep"})
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=env,
            deployment=dep,
            component_env_vars={
                "worker": {"FROM_COMP": "3", "SHARED": "comp"},
            },
            driver_components=["worker"],
        )
        entry = resolved.components[0]
        assert entry.resolved.config == {
            "FROM_ENV": "1",
            "FROM_DEP": "2",
            "FROM_COMP": "3",
            "SHARED": "comp",
        }
        assert entry.resolved.provenance == {
            "FROM_ENV": "environment",
            "FROM_DEP": "deployment",
            "FROM_COMP": "component",
            "SHARED": "component",
        }

    def test_no_components_declared_fallback(self) -> None:
        """FR-004 broadcast path: when ``driver_components`` is None or
        empty, no per-component entries are produced; callers consume
        ``deployment_effective`` directly."""
        env = EnvironmentConfig(env_vars={"X": "1"})
        dep = DeploymentConfig(env_vars={"Y": "2"})
        resolved_none = EnvVarsResolver.resolve_for_deployment(
            environment=env, deployment=dep, driver_components=None
        )
        assert resolved_none.components == []
        assert resolved_none.deployment_effective == {"X": "1", "Y": "2"}

        resolved_empty = EnvVarsResolver.resolve_for_deployment(
            environment=env, deployment=dep, driver_components=[]
        )
        assert resolved_empty.components == []
        assert resolved_empty.deployment_effective == {"X": "1", "Y": "2"}

    def test_components_without_block_inherit_deployment_dict(self) -> None:
        """A component declared by the driver but absent from
        ``component_env_vars`` still produces an entry — its merged config
        is the env+dep dict (the component layer is empty)."""
        dep = DeploymentConfig(env_vars={"LOG_LEVEL": "info"})
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=None,
            deployment=dep,
            component_env_vars={},
            driver_components=["api", "worker"],
        )
        assert {e.component_name for e in resolved.components} == {"api", "worker"}
        for entry in resolved.components:
            assert entry.resolved.config == {"LOG_LEVEL": "info"}
            assert entry.resolved.provenance == {"LOG_LEVEL": "deployment"}
            assert entry.resolved.is_orphaned is False

    def test_unknown_component_blocks_are_silently_ignored_in_us3(self) -> None:
        """Stored blocks targeting components the driver does not declare
        are silently dropped in US3 — US5 (Phase 7) replaces this branch
        with orphan emission."""
        resolved = EnvVarsResolver.resolve_for_deployment(
            environment=None,
            deployment=DeploymentConfig(),
            component_env_vars={
                "worker": {"X": "1"},
                "removed": {"Y": "2"},  # not declared by the driver
            },
            driver_components=["worker"],
        )
        assert {e.component_name for e in resolved.components} == {"worker"}
        worker_entry = resolved.components[0]
        assert worker_entry.resolved.config == {"X": "1"}
        assert worker_entry.resolved.is_orphaned is False
