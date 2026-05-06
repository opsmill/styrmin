"""Unit tests for the env vars patch builder (008-deployment-env-vars / T027).

Covers:
* Deployment-level only — one TargetPatch per pod-template-bearing kind.
* ``inject.env_vars=False`` opt-out — zero patches.
* No-components fallback — broadcast applies without label selector.
* Multi-container injection — all containers receive the env entries via
  the strategic-merge ``name: "*"`` wildcard.
* CronJob path variant — patch nests under ``spec.jobTemplate``.
"""

from __future__ import annotations

import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    EnvVarsPatch,
)
from styrmin_backend.context.models.config import PostRenderInjection
from styrmin_backend.services.env_vars.patch_builder import (
    build_env_vars_post_rendering_patches,
)
from styrmin_backend.services.scheduling.patch_builder import (
    POD_TEMPLATE_BEARING_KINDS,
)


class TestEnvVarsPatchRendering:
    def test_renders_env_list_under_pod_template_containers(self) -> None:
        patch = EnvVarsPatch(env_vars={"LOG_LEVEL": "debug", "FOO": "bar"})
        doc = yaml.safe_load(patch.render_value())

        assert doc["apiVersion"] == "apps/v1"
        assert doc["kind"] == "Deployment"
        containers = doc["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        assert containers[0]["name"] == "*"
        env_list = containers[0]["env"]
        assert {"name": "LOG_LEVEL", "value": "debug"} in env_list
        assert {"name": "FOO", "value": "bar"} in env_list

    def test_cronjob_variant_uses_jobtemplate_path(self) -> None:
        patch = EnvVarsPatch(
            env_vars={"LOG_LEVEL": "debug"},
            api_version="batch/v1",
            kind="CronJob",
        )
        doc = yaml.safe_load(patch.render_value())

        assert doc["kind"] == "CronJob"
        containers = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"][
            "containers"
        ]
        assert containers[0]["env"][0]["name"] == "LOG_LEVEL"

    def test_render_is_deterministic_across_runs(self) -> None:
        patch_a = EnvVarsPatch(env_vars={"A": "1", "B": "2"})
        patch_b = EnvVarsPatch(env_vars={"A": "1", "B": "2"})
        assert patch_a.render_value() == patch_b.render_value()

    def test_empty_value_accepted(self) -> None:
        patch = EnvVarsPatch(env_vars={"FOO": ""})
        doc = yaml.safe_load(patch.render_value())
        env_list = doc["spec"]["template"]["spec"]["containers"][0]["env"]
        assert env_list == [{"name": "FOO", "value": ""}]


class TestBuildEnvVarsPatches:
    def test_emits_one_patch_per_pod_template_bearing_kind(self) -> None:
        patches = build_env_vars_post_rendering_patches({"LOG_LEVEL": "debug"})

        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)
        kinds = {tp.target.kind for tp in patches}
        assert kinds == set(POD_TEMPLATE_BEARING_KINDS)

    def test_empty_dict_emits_no_patches(self) -> None:
        assert build_env_vars_post_rendering_patches({}) == []

    def test_none_dict_emits_no_patches(self) -> None:
        assert build_env_vars_post_rendering_patches(None) == []

    def test_inject_false_suppresses_patches(self) -> None:
        inject = PostRenderInjection(env_vars=False)
        assert (
            build_env_vars_post_rendering_patches({"LOG_LEVEL": "debug"}, inject=inject)
            == []
        )

    def test_inject_default_none_treated_as_opt_in(self) -> None:
        # No PostRenderInjection at all — default is True → patches emitted.
        patches = build_env_vars_post_rendering_patches({"LOG_LEVEL": "debug"})
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_inject_field_default_none_treated_as_opt_in(self) -> None:
        # Explicit PostRenderInjection() with env_vars defaulting to None.
        inject = PostRenderInjection()
        patches = build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug"}, inject=inject
        )
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_no_label_selector_for_broadcast_path(self) -> None:
        """FR-004: when no components are declared the patch builder is
        invoked without a label_selector and the patches apply broadly."""
        patches = build_env_vars_post_rendering_patches({"LOG_LEVEL": "debug"})
        for tp in patches:
            assert tp.target.label_selector is None

    def test_label_selector_narrows_target(self) -> None:
        """Per-component path passes a selector to scope the patch."""
        patches = build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug"},
            label_selector="styrmin/component=worker",
        )
        for tp in patches:
            assert tp.target.label_selector == "styrmin/component=worker"

    def test_all_containers_receive_entries_via_wildcard(self) -> None:
        patches = build_env_vars_post_rendering_patches({"LOG_LEVEL": "debug"})
        for tp in patches:
            doc = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            spec_path = (
                doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                if tp.target.kind == "CronJob"
                else doc["spec"]["template"]["spec"]
            )
            containers = spec_path["containers"]
            assert containers[0]["name"] == "*"
            assert {"name": "LOG_LEVEL", "value": "debug"} in containers[0]["env"]
