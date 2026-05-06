"""Unit tests for the env vars patch builder (008-deployment-env-vars / T027).

Covers:
* Deployment-level only — one TargetPatch per pod-template-bearing kind.
* ``inject.env_vars=False`` opt-out — zero patches.
* No-components fallback — broadcast applies without label selector.
* Single-container injection on container[0] — JSON-patch ``replace`` shape
  mirroring :class:`ResourcesPatch`. Multi-container per-pod fan-out is out
  of scope for v1 (see spec.md §Assumptions / data-model.md §5.1).
* CronJob path variant — patch nests under ``spec.jobTemplate``.
* ``ChartEnvCollision`` dataclass shape and the FR-027/FR-028 structured
  warning emission for every operator-set env var key.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import yaml
from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    EnvVarsPatch,
)
from styrmin_backend.context.models.config import PostRenderInjection
from styrmin_backend.services.env_vars.patch_builder import (
    ChartEnvCollision,
    build_env_vars_post_rendering_patches,
)
from styrmin_backend.services.scheduling.patch_builder import (
    POD_TEMPLATE_BEARING_KINDS,
)


@pytest.fixture
def loguru_caplog(
    caplog: pytest.LogCaptureFixture,
) -> Iterator[pytest.LogCaptureFixture]:
    """Bridge ``loguru`` records into pytest's ``caplog`` so the structured
    warning emitted by the patch builder can be asserted on directly.
    """
    handler_id = logger.add(
        caplog.handler,
        format="{message}",
        level=0,
        filter=lambda record: True,
    )
    yield caplog
    logger.remove(handler_id)


class TestEnvVarsPatchRendering:
    def test_renders_json_patch_replace_on_container_zero_env(self) -> None:
        patch = EnvVarsPatch(env_vars={"LOG_LEVEL": "debug", "FOO": "bar"})
        ops = yaml.safe_load(patch.render_value())

        assert isinstance(ops, list)
        assert len(ops) == 1
        op = ops[0]
        assert op["op"] == "replace"
        assert op["path"] == "/spec/template/spec/containers/0/env"
        assert {"name": "LOG_LEVEL", "value": "debug"} in op["value"]
        assert {"name": "FOO", "value": "bar"} in op["value"]

    def test_cronjob_variant_uses_jobtemplate_path(self) -> None:
        patch = EnvVarsPatch(
            env_vars={"LOG_LEVEL": "debug"},
            api_version="batch/v1",
            kind="CronJob",
        )
        ops = yaml.safe_load(patch.render_value())

        assert ops[0]["op"] == "replace"
        assert ops[0]["path"] == "/spec/jobTemplate/spec/template/spec/containers/0/env"
        assert ops[0]["value"][0]["name"] == "LOG_LEVEL"

    def test_render_is_deterministic_across_runs(self) -> None:
        patch_a = EnvVarsPatch(env_vars={"A": "1", "B": "2"})
        patch_b = EnvVarsPatch(env_vars={"A": "1", "B": "2"})
        assert patch_a.render_value() == patch_b.render_value()

    def test_empty_value_accepted(self) -> None:
        patch = EnvVarsPatch(env_vars={"FOO": ""})
        ops = yaml.safe_load(patch.render_value())
        assert ops[0]["value"] == [{"name": "FOO", "value": ""}]

    def test_explicit_container_index_propagates(self) -> None:
        """An explicit ``container_index`` parameter targets the chosen
        container — leaves the door open for callers that need to address a
        non-zero index even though v1 callers always pass 0."""
        patch = EnvVarsPatch(env_vars={"X": "y"}, container_index=2)
        ops = yaml.safe_load(patch.render_value())
        assert ops[0]["path"] == "/spec/template/spec/containers/2/env"


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

    def test_container_zero_env_path_for_each_kind(self) -> None:
        """v1 narrows the patch to container[0] (mirrors ``ResourcesPatch``).
        Multi-container per-pod fan-out is deferred — see spec §Assumptions
        and data-model.md §5.1.
        """
        patches = build_env_vars_post_rendering_patches({"LOG_LEVEL": "debug"})
        for tp in patches:
            ops = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            assert len(ops) == 1
            op = ops[0]
            assert op["op"] == "replace"
            if tp.target.kind == "CronJob":
                assert (
                    op["path"]
                    == "/spec/jobTemplate/spec/template/spec/containers/0/env"
                )
            else:
                assert op["path"] == "/spec/template/spec/containers/0/env"
            assert {"name": "LOG_LEVEL", "value": "debug"} in op["value"]


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
            ops = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            assert {"name": "WORKER_QUEUE", "value": "orders"} in ops[0]["value"]

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
            ops = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            names = {entry["name"] for entry in ops[0]["value"]}
            assert "WORKER_QUEUE" not in names
            assert "LOG_LEVEL" in names
        # worker patches carry both names.
        for tp in worker_patches:
            ops = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            names = {entry["name"] for entry in ops[0]["value"]}
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


class TestUS6ComponentLevelOptOut:
    """T063 / US6: per-component opt-out invariants.

    The patch builder is the single primitive every per-component invocation
    funnels through. These tests pin down that the ``inject.env_vars=False``
    opt-out at the component level (a) suppresses patch emission for that
    component without affecting peer-component invocations, and (b) the same
    flag set at the deployment scope (no-components fallback) suppresses
    everything emitted by the broadcast path. Together they fully cover the
    three branches the application builder relies on.
    """

    def test_component_opt_out_emits_zero_patches_at_component_scope(self) -> None:
        """A component-scoped opt-out yields no patches even when the
        resolved dict is non-empty and a selector is supplied."""
        inject = PostRenderInjection(env_vars=False)
        patches = build_env_vars_post_rendering_patches(
            {"DB_POOL_SIZE": "5"},
            inject=inject,
            label_selector="styrmin/component=database",
        )
        assert patches == []

    def test_peer_component_still_receives_env_vars_when_one_opts_out(
        self,
    ) -> None:
        """Multi-component scenario: one component opts out, the peer does
        not. The peer's invocation still emits the full patch set scoped by
        its own selector — no cross-contamination from the opt-out branch.
        """
        opted_out = build_env_vars_post_rendering_patches(
            {"DB_POOL_SIZE": "5"},
            inject=PostRenderInjection(env_vars=False),
            label_selector="styrmin/component=database",
        )
        peer = build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug"},
            inject=PostRenderInjection(),  # default — env_vars unset → opt-in
            label_selector="styrmin/component=server",
        )
        assert opted_out == []
        assert len(peer) == len(POD_TEMPLATE_BEARING_KINDS)
        for tp in peer:
            assert tp.target.label_selector == "styrmin/component=server"
            ops = yaml.safe_load(tp.patch.render_value())  # type: ignore[attr-defined]
            names = {entry["name"] for entry in ops[0]["value"]}
            assert names == {"LOG_LEVEL"}
            # The opted-out component's key must never bleed across.
            assert "DB_POOL_SIZE" not in names

    def test_deployment_level_opt_out_suppresses_broadcast_path(self) -> None:
        """No-components fallback (FR-004 broadcast): when the resolved
        deployment-scope ``inject.env_vars=False``, the broadcast invocation
        emits zero patches across every pod-template-bearing kind. Mirrors
        the contract the application builder's no-components branch relies
        on — the deployment-wide opt-out gates the broadcast cleanly.
        """
        inject = PostRenderInjection(env_vars=False)
        patches = build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug"},
            inject=inject,
            label_selector=None,
        )
        assert patches == []


class TestUS7ChartEnvCollision:
    """T071 / US7: chart-vs-user env var collision dataclass + structured
    warning emission per FR-027/FR-028.

    v1 NOTE — degradation path: the backend has no line-of-sight into the
    post-rendered manifest at the patch layer (the env-var patch is shipped
    to FluxCD as a JSON-patch document and Kustomize processes it
    on-cluster). FR-028 explicitly authorises the structured-log fallback
    when timeline emission is not feasible. These tests pin the shape of
    :class:`ChartEnvCollision` and the unconditional log emission per
    operator-set env var key — the always-on signal support uses to
    correlate against chart-rendered values when triaging. The
    "user value wins in the rendered output" assertion called out in the
    task description is intentionally out of scope here: it requires real
    Helm rendering against a live cluster and is exercised by the E2E
    suite (T073 — currently skipped pending the rendered-manifest seam).
    """

    def test_chart_env_collision_dataclass_shape(self) -> None:
        """The dataclass mirrors the GraphQL ``EnvVarCollision`` field
        order so the ``EnvVarCollision.from_data`` projection is a
        straight-through pass-through.
        """
        collision = ChartEnvCollision(
            component="worker",
            container="app",
            name="LOG_LEVEL",
            chart_value="warn",
            user_value="debug",
        )
        assert collision.component == "worker"
        assert collision.container == "app"
        assert collision.name == "LOG_LEVEL"
        assert collision.chart_value == "warn"
        assert collision.user_value == "debug"

    def test_chart_env_collision_component_optional(self) -> None:
        """``component`` is ``None`` for FR-004 broadcast scenarios where
        the workload is not under any component (driver declares zero
        components).
        """
        collision = ChartEnvCollision(
            component=None,
            container="app",
            name="LOG_LEVEL",
            chart_value="warn",
            user_value="debug",
        )
        assert collision.component is None

    def test_emits_structured_warning_per_operator_set_key(
        self, loguru_caplog: pytest.LogCaptureFixture
    ) -> None:
        """Per FR-027/FR-028: every operator-set env var key triggers an
        ``env_var_potentially_chart_colliding`` warning carrying the
        deployment id, optional component, name, and user value. Support
        correlates these log lines against chart values when triaging,
        which is the v1 substitute for the rendered-manifest collision
        diff.
        """
        loguru_caplog.set_level("WARNING")
        build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug", "FOO": "bar"},
            label_selector="styrmin/component=worker",
            component="worker",
            deployment_id="dep-123",
        )
        warning_records = [r for r in loguru_caplog.records if r.levelname == "WARNING"]
        collision_records = [
            r
            for r in warning_records
            if "env_var_potentially_chart_colliding" in r.getMessage()
        ]
        assert len(collision_records) == 2, [r.getMessage() for r in warning_records]
        # Each operator-set name MUST appear in exactly one warning record.
        emitted_names = {
            name
            for name in ("LOG_LEVEL", "FOO")
            for r in collision_records
            if f"name={name}" in r.getMessage()
        }
        assert emitted_names == {"LOG_LEVEL", "FOO"}
        # Deployment id and component are threaded through so triage can
        # correlate against the right rendered manifest.
        assert all("deployment_id=dep-123" in r.getMessage() for r in collision_records)
        assert all("component=worker" in r.getMessage() for r in collision_records)

    def test_warning_emitted_with_no_component_for_broadcast_path(
        self, loguru_caplog: pytest.LogCaptureFixture
    ) -> None:
        """FR-004 broadcast (no components): ``component`` is ``None`` in
        the structured log entry; the operator-set key is still surfaced.
        """
        loguru_caplog.set_level("WARNING")
        build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug"},
            deployment_id="dep-broadcast",
        )
        collision_records = [
            r
            for r in loguru_caplog.records
            if "env_var_potentially_chart_colliding" in r.getMessage()
        ]
        assert len(collision_records) == 1
        assert "component=None" in collision_records[0].getMessage()
        assert "name=LOG_LEVEL" in collision_records[0].getMessage()

    def test_no_warning_when_inject_opted_out(
        self, loguru_caplog: pytest.LogCaptureFixture
    ) -> None:
        """When ``inject.env_vars=False`` the patch builder short-circuits
        BEFORE the warning emission — there is no operator-set entry
        making it onto the rendered pod, so no triage signal is needed.
        """
        loguru_caplog.set_level("WARNING")
        build_env_vars_post_rendering_patches(
            {"LOG_LEVEL": "debug"},
            inject=PostRenderInjection(env_vars=False),
        )
        collision_records = [
            r
            for r in loguru_caplog.records
            if "env_var_potentially_chart_colliding" in r.getMessage()
        ]
        assert collision_records == []

    def test_no_warning_when_resolved_dict_empty(
        self, loguru_caplog: pytest.LogCaptureFixture
    ) -> None:
        """An empty resolved dict carries no operator-set entries, so no
        triage signal is emitted.
        """
        loguru_caplog.set_level("WARNING")
        build_env_vars_post_rendering_patches({})
        collision_records = [
            r
            for r in loguru_caplog.records
            if "env_var_potentially_chart_colliding" in r.getMessage()
        ]
        assert collision_records == []
