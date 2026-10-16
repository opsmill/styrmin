"""Unit tests for the scheduling patch builder.

Covers US6 cross-cutting behaviour for the post-renderer injection
dispatcher (T047 opt-out per feature, future phases for tolerations /
runtime class). US1's affinity-specific coverage lives in
``test_application_builder_scheduling.py``.
"""

from __future__ import annotations

import yaml

from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    LabelSelector,
    PostRenderInjection,
    ResourceRequirements,
    ResourceSpec,
    SchedulingConfig,
    Toleration,
    TopologySpreadConstraint,
)
from styrmin_backend.context.resolvers import _resolve_scheduling_config
from styrmin_backend.services.scheduling.patch_builder import (
    POD_TEMPLATE_BEARING_KINDS,
    build_affinity_patches,
    build_node_affinity_patches,
    build_resources_patches,
    build_tolerations_patches,
    build_topology_spread_patches,
)


def _term(app: str) -> AffinityTerm:
    return AffinityTerm(
        topology_key="kubernetes.io/hostname",
        label_selector=LabelSelector(match_labels={"app": app}),
    )


class TestInjectOptOut:
    """T047: opted-out features produce no patches while other features
    still patch. Uses affinity as the representative feature today;
    per-feature coverage of the other builders lands in later phases.
    """

    def test_pod_affinity_opt_out_suppresses_only_affinity(self) -> None:
        resolved = SchedulingConfig(
            pod_affinity=AffinityBlock(required=[_term("web")]),
            # Resources is set here so later phases can extend this test
            # to assert that resources patches STILL emit.
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="100m"),
            ),
        )
        inject = PostRenderInjection(pod_affinity=False)

        assert build_affinity_patches(resolved, inject=inject) == []

    def test_pod_affinity_opt_in_explicit_emits_patches(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))
        inject = PostRenderInjection(pod_affinity=True)

        patches = build_affinity_patches(resolved, inject=inject)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_inject_none_treated_as_opt_in(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))

        patches = build_affinity_patches(resolved, inject=None)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_field_default_none_treated_as_opt_in(self) -> None:
        resolved = SchedulingConfig(pod_affinity=AffinityBlock(required=[_term("web")]))
        # Explicit PostRenderInjection with all fields defaulted to None.
        inject = PostRenderInjection()

        patches = build_affinity_patches(resolved, inject=inject)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)


class TestBuildResourcesPatches:
    """US2: build_resources_patches emits container-resource patches across
    pod-template-bearing kinds; honours the ``inject.resources`` opt-out.
    """

    def test_no_resources_emits_nothing(self) -> None:
        assert build_resources_patches(SchedulingConfig()) == []

    def test_empty_resource_requirements_emits_nothing(self) -> None:
        resolved = SchedulingConfig(resources=ResourceRequirements())
        assert build_resources_patches(resolved) == []

    def test_requests_only_emits_one_patch_per_kind(self) -> None:
        resolved = SchedulingConfig(
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="100m", memory="256Mi")
            )
        )
        patches = build_resources_patches(resolved)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)
        kinds = {tp.target.kind for tp in patches}
        assert kinds == set(POD_TEMPLATE_BEARING_KINDS)

    def test_inject_resources_false_suppresses_patches(self) -> None:
        resolved = SchedulingConfig(
            resources=ResourceRequirements(requests=ResourceSpec(cpu="100m"))
        )
        inject = PostRenderInjection(resources=False)
        assert build_resources_patches(resolved, inject=inject) == []

    def test_affinity_and_resources_opt_outs_are_independent(self) -> None:
        """T047 for US2: opting out of resources leaves affinity patches alone."""
        resolved = SchedulingConfig(
            pod_affinity=AffinityBlock(required=[_term("web")]),
            resources=ResourceRequirements(requests=ResourceSpec(cpu="100m")),
        )
        inject = PostRenderInjection(resources=False)

        assert build_affinity_patches(resolved, inject=inject) != []
        assert build_resources_patches(resolved, inject=inject) == []

    def test_label_selector_narrows_target(self) -> None:
        resolved = SchedulingConfig(
            resources=ResourceRequirements(requests=ResourceSpec(cpu="100m"))
        )
        patches = build_resources_patches(resolved, label_selector="app=web")
        for tp in patches:
            assert tp.target.label_selector == "app=web"


class TestBuildTolerationsPatches:
    """US3: build_tolerations_patches emits one patch per pod-template kind."""

    def test_no_tolerations_emits_nothing(self) -> None:
        assert build_tolerations_patches(SchedulingConfig()) == []

    def test_tolerations_emits_one_per_kind(self) -> None:
        resolved = SchedulingConfig(
            tolerations=[
                Toleration(
                    key="dedicated",
                    operator="Equal",
                    value="batch",
                    effect="NoSchedule",
                )
            ]
        )
        patches = build_tolerations_patches(resolved)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_inject_opt_out(self) -> None:
        resolved = SchedulingConfig(
            tolerations=[Toleration(key="x", operator="Exists")]
        )
        assert (
            build_tolerations_patches(
                resolved, inject=PostRenderInjection(tolerations=False)
            )
            == []
        )


class TestBuildTopologySpreadPatches:
    def test_no_constraints_emits_nothing(self) -> None:
        assert build_topology_spread_patches(SchedulingConfig()) == []

    def test_constraints_emits_one_per_kind(self) -> None:
        resolved = SchedulingConfig(
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=1,
                    topology_key="zone",
                    when_unsatisfiable="DoNotSchedule",
                )
            ]
        )
        patches = build_topology_spread_patches(resolved)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_inject_opt_out(self) -> None:
        resolved = SchedulingConfig(
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=1,
                    topology_key="zone",
                    when_unsatisfiable="DoNotSchedule",
                )
            ]
        )
        assert (
            build_topology_spread_patches(
                resolved, inject=PostRenderInjection(topology_spread=False)
            )
            == []
        )


class TestBuildNodeAffinityPatches:
    def test_no_node_affinity_emits_nothing(self) -> None:
        assert build_node_affinity_patches(SchedulingConfig()) == []

    def test_empty_node_affinity_emits_nothing(self) -> None:
        resolved = SchedulingConfig(node_affinity=AffinityBlock())
        assert build_node_affinity_patches(resolved) == []

    def test_node_affinity_emits_one_per_kind(self) -> None:
        resolved = SchedulingConfig(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(match_labels={"node-type": "gpu"}),
                    )
                ]
            )
        )
        patches = build_node_affinity_patches(resolved)
        assert len(patches) == len(POD_TEMPLATE_BEARING_KINDS)

    def test_environment_and_deployment_terms_render_as_one_node_selector_term(
        self,
    ) -> None:
        """#486: a pod must match the environment's and the deployment's terms."""

        def _level(**labels: str) -> SchedulingConfig:
            return SchedulingConfig(
                node_affinity=AffinityBlock(
                    required=[
                        AffinityTerm(
                            topology_key="",
                            label_selector=LabelSelector(match_labels=labels),
                        )
                    ]
                )
            )

        resolved, _ = _resolve_scheduling_config(
            _level(pool="apps"), _level(zone="a"), None
        )
        patch = next(
            tp.patch
            for tp in build_node_affinity_patches(resolved)
            if tp.target.kind == "Deployment"
        )

        rendered = yaml.safe_load(patch.render_value())
        node_affinity = rendered["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]
        assert node_affinity["requiredDuringSchedulingIgnoredDuringExecution"] == {
            "nodeSelectorTerms": [
                {
                    "matchExpressions": [
                        {"key": "pool", "operator": "In", "values": ["apps"]},
                        {"key": "zone", "operator": "In", "values": ["a"]},
                    ]
                }
            ]
        }

    def test_inject_opt_out(self) -> None:
        resolved = SchedulingConfig(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(match_labels={"a": "b"}),
                    )
                ]
            )
        )
        assert (
            build_node_affinity_patches(
                resolved, inject=PostRenderInjection(node_affinity=False)
            )
            == []
        )
