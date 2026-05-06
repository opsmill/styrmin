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


class TestComponentLevelInvocations:
    """T043 / US3: component-only and mixed deployment+component invocations.

    The patch builder is a primitive that takes a resolved dict and an
    optional ``label_selector``. The per-component path drives multiple
    calls — one per declared component, each with its own selector. These
    tests pin down the invariants the application builder relies on:
    every call narrows by the supplied selector, and disjoint dicts produce
    disjoint patch sets that can be concatenated without overlap.
    """

    def test_component_only_dict_emits_narrowed_patches(self) -> None:
        """Component-level only — every emitted patch must carry the
        component's label selector so the patch never bleeds onto peer
        components."""
        patches = build_env_vars_post_rendering_patches(
            {"WORKER_QUEUE": "orders"},
            label_selector="styrmin/component=worker",
        )
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)
        for tp in patches:
            assert tp.target.label_selector == "styrmin/component=worker"
            doc = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            spec_path = (
                doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                if tp.target.kind == "CronJob"
                else doc["spec"]["template"]["spec"]
            )
            assert {"name": "WORKER_QUEUE", "value": "orders"} in spec_path[
                "containers"
            ][0]["env"]

    def test_mixed_deployment_and_component_dicts_are_disjoint(self) -> None:
        """Mixed deployment + component — when the application builder
        invokes the primitive once per component with the merged dict,
        every component's patch set carries that component's selector and
        the entries the resolver assembled. Peer components do not see
        each other's patches."""
        api_patches = build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "info"},
            label_selector="styrmin/component=api",
        )
        worker_patches = build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug", "WORKER_QUEUE": "orders"},
            label_selector="styrmin/component=worker",
        )
        # Selectors are mutually exclusive — concatenation never broadcasts.
        api_selectors = {tp.target.label_selector for tp in api_patches}
        worker_selectors = {tp.target.label_selector for tp in worker_patches}
        assert api_selectors == {"styrmin/component=api"}
        assert worker_selectors == {"styrmin/component=worker"}
        # api patches do NOT carry WORKER_QUEUE.
        for tp in api_patches:
            doc = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            spec_path = (
                doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                if tp.target.kind == "CronJob"
                else doc["spec"]["template"]["spec"]
            )
            names = {entry["name"] for entry in spec_path["containers"][0]["env"]}
            assert "WORKER_QUEUE" not in names
            assert "LOG_LEVEL" in names
        # worker patches carry both names.
        for tp in worker_patches:
            doc = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            spec_path = (
                doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                if tp.target.kind == "CronJob"
                else doc["spec"]["template"]["spec"]
            )
            names = {entry["name"] for entry in spec_path["containers"][0]["env"]}
            assert names >= {"LOG_LEVEL", "WORKER_QUEUE"}

    def test_component_inject_false_short_circuits_emission(self) -> None:
        """Component-scope ``inject.env_vars=False`` (T015 / US6 surface)
        must short-circuit the per-component branch the same way it does the
        deployment-level branch — peer components are unaffected."""
        inject = PostRenderInjection(env_vars=False)
        patches = build_env_vars_post_rendering_patches(
            {"WORKER_QUEUE": "orders"},
            inject=inject,
            label_selector="styrmin/component=worker",
        )
        assert patches == []
