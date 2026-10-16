"""Unit tests for the scheduling resolver (Phase 2 foundation).

These cover scalar/struct deepest-wins merge across env/dep/comp levels
(T028). Richer merge semantics (affinity accumulation, `replace: true`,
tolerations union, topology spread keyed union) are tested in dedicated
files under their respective user-story phases.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    DeploymentReference,
    LabelSelector,
    LabelSelectorRequirement,
    PostRenderInjection,
    ResourceRequirements,
    ResourceSpec,
    SchedulingConfig,
    Toleration,
    TopologySpreadConstraint,
    WeightedAffinityTerm,
)
from styrmin_backend.context.resolvers import (
    _resolve_scheduling_config,
    effective_inject_flag,
)
from styrmin_backend.services.exceptions import UnknownComponentInConfigError


def _affinity_term(app: str, key: str = "kubernetes.io/hostname") -> AffinityTerm:
    return AffinityTerm(
        topology_key=key,
        label_selector=LabelSelector(match_labels={"app": app}),
    )


def _weighted(app: str, weight: int = 50) -> WeightedAffinityTerm:
    return WeightedAffinityTerm(weight=weight, term=_affinity_term(app))


def _cfg(**kwargs: object) -> SchedulingConfig:
    return SchedulingConfig(**kwargs)  # type: ignore[arg-type]


def _node_term(**labels: str) -> AffinityTerm:
    return AffinityTerm(
        topology_key="", label_selector=LabelSelector(match_labels=labels)
    )


def _node_expressions(term: AffinityTerm) -> list[tuple[str, str, list[str] | None]]:
    assert term.label_selector is not None
    assert term.label_selector.match_labels is None
    return [
        (e.key, e.operator, e.values)
        for e in term.label_selector.match_expressions or []
    ]


class TestScalarMerge:
    def test_runtime_class_deepest_wins(self) -> None:
        env = _cfg(runtime_class="kata")
        dep = _cfg(runtime_class="gvisor")
        comp = _cfg(runtime_class="runc")

        resolved, prov = _resolve_scheduling_config(env, dep, comp)

        assert resolved.runtime_class == "runc"
        assert prov["runtime_class"] == "component"

    def test_runtime_class_inherits_from_env_when_unset_below(self) -> None:
        env = _cfg(runtime_class="kata")
        resolved, prov = _resolve_scheduling_config(env, None, None)

        assert resolved.runtime_class == "kata"
        assert prov["runtime_class"] == "environment"

    def test_runtime_class_inherits_from_deployment(self) -> None:
        dep = _cfg(runtime_class="gvisor")
        resolved, prov = _resolve_scheduling_config(None, dep, None)

        assert resolved.runtime_class == "gvisor"
        assert prov["runtime_class"] == "deployment"

    def test_all_none_yields_empty_config(self) -> None:
        resolved, prov = _resolve_scheduling_config(None, None, None)

        assert resolved.runtime_class is None
        assert resolved.resources is None
        assert "runtime_class" not in prov


class TestK8sQuantityParser:
    """T055: ``_parse_k8s_quantity`` accepts standard quantity strings and
    rejects unrecognised suffixes / formats.
    """

    def test_accepts_standard_quantities(self) -> None:
        from styrmin_backend.context.models.config import _parse_k8s_quantity

        for v in ("100m", "2", "256Mi", "2Gi", "1.5", "500n", "0.5", "4Ti"):
            _parse_k8s_quantity(v)

    def test_rejects_non_numeric(self) -> None:
        from styrmin_backend.context.models.config import _parse_k8s_quantity

        with pytest.raises(ValueError):
            _parse_k8s_quantity("two")

    def test_rejects_empty(self) -> None:
        from styrmin_backend.context.models.config import _parse_k8s_quantity

        with pytest.raises(ValueError):
            _parse_k8s_quantity("")

    def test_rejects_unknown_suffix(self) -> None:
        from styrmin_backend.context.models.config import _parse_k8s_quantity

        with pytest.raises(ValueError):
            _parse_k8s_quantity("1x")


class TestResourceFieldMerge:
    def test_field_level_deepest_wins(self) -> None:
        env = _cfg(
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="100m", memory="256Mi")
            )
        )
        dep = _cfg(
            resources=ResourceRequirements(
                limits=ResourceSpec(memory="2Gi"),
            )
        )
        comp = _cfg(
            resources=ResourceRequirements(
                requests=ResourceSpec(cpu="2"),
            )
        )

        resolved, prov = _resolve_scheduling_config(env, dep, comp)

        assert resolved.resources is not None
        assert resolved.resources.requests is not None
        assert resolved.resources.requests.cpu == "2"
        assert resolved.resources.requests.memory == "256Mi"
        assert resolved.resources.limits is not None
        assert resolved.resources.limits.memory == "2Gi"

        assert prov["resources.requests.cpu"] == "component"
        assert prov["resources.requests.memory"] == "environment"
        assert prov["resources.limits.memory"] == "deployment"

    def test_extended_map_key_by_key_merge(self) -> None:
        env = _cfg(
            resources=ResourceRequirements(
                requests=ResourceSpec(extended={"nvidia.com/gpu": "1"})
            )
        )
        comp = _cfg(
            resources=ResourceRequirements(
                requests=ResourceSpec(extended={"hugepages-2Mi": "128Mi"})
            )
        )

        resolved, prov = _resolve_scheduling_config(env, None, comp)

        assert resolved.resources is not None
        assert resolved.resources.requests is not None
        assert resolved.resources.requests.extended == {
            "nvidia.com/gpu": "1",
            "hugepages-2Mi": "128Mi",
        }
        assert prov["resources.requests.extended.nvidia.com/gpu"] == "environment"
        assert prov["resources.requests.extended.hugepages-2Mi"] == "component"

    def test_extended_map_key_deepest_wins(self) -> None:
        env = _cfg(
            resources=ResourceRequirements(
                requests=ResourceSpec(extended={"nvidia.com/gpu": "1"})
            )
        )
        comp = _cfg(
            resources=ResourceRequirements(
                requests=ResourceSpec(extended={"nvidia.com/gpu": "4"})
            )
        )

        resolved, prov = _resolve_scheduling_config(env, None, comp)

        assert resolved.resources is not None
        assert resolved.resources.requests is not None
        assert resolved.resources.requests.extended == {"nvidia.com/gpu": "4"}
        assert prov["resources.requests.extended.nvidia.com/gpu"] == "component"


class TestClearThenShallowerWins:
    """T108 (FR-020): a field set at a deeper level and then cleared (set
    to ``None`` at an even deeper level) resolves to the shallower-level
    value, not to a residual of the deeper-level one.

    The resolver treats missing fields as "inherit" (data-model I1), so
    "clearing" simply means the deeper level omits the key; the effective
    value must then equal whatever the next shallower level provided.
    """

    def test_cleared_deployment_level_falls_back_to_environment(self) -> None:
        env = _cfg(runtime_class="kata")
        # deployment level explicitly sets the scheduling block but omits
        # runtime_class — that field is "cleared" w.r.t. dep, so the
        # resolved value should fall back to the environment level.
        dep = _cfg(resources=ResourceRequirements(requests=ResourceSpec(cpu="100m")))

        resolved, prov = _resolve_scheduling_config(env, dep, None)

        assert resolved.runtime_class == "kata"
        assert prov["runtime_class"] == "environment"
        # The dep-level resource value is preserved.
        assert resolved.resources is not None
        assert resolved.resources.requests is not None
        assert resolved.resources.requests.cpu == "100m"
        assert prov["resources.requests.cpu"] == "deployment"

    def test_second_resolve_without_deployment_value_reverts_cleanly(self) -> None:
        """Simulate the operator-flow: set a field at deployment level,
        then clear it. Two independent resolver calls must produce the same
        "effective = env" result the second time — no residual state.
        """
        env = _cfg(runtime_class="kata")

        # Pass 1: deployment overrides runtime_class.
        dep_set = _cfg(runtime_class="gvisor")
        r1, p1 = _resolve_scheduling_config(env, dep_set, None)
        assert r1.runtime_class == "gvisor"
        assert p1["runtime_class"] == "deployment"

        # Pass 2: deployment clears the override (runtime_class is None).
        dep_cleared = _cfg()  # all fields None
        r2, p2 = _resolve_scheduling_config(env, dep_cleared, None)
        assert r2.runtime_class == "kata"
        assert p2["runtime_class"] == "environment"


class TestDeterminism:
    def test_same_inputs_produce_same_outputs(self) -> None:
        env = _cfg(
            runtime_class="kata",
            resources=ResourceRequirements(requests=ResourceSpec(cpu="100m")),
        )
        dep = _cfg(
            resources=ResourceRequirements(requests=ResourceSpec(memory="512Mi"))
        )
        comp = _cfg(resources=ResourceRequirements(limits=ResourceSpec(cpu="2")))

        a_cfg, a_prov = _resolve_scheduling_config(env, dep, comp)
        b_cfg, b_prov = _resolve_scheduling_config(env, dep, comp)

        assert a_cfg == b_cfg
        assert a_prov == b_prov


class TestAffinityAccumulation:
    """T031: required terms from all levels are ANDed; preferred terms merge
    into a single weighted list preserving each level's weights.
    Accumulation applies per-kind (pod/pod-anti/node) without cross-mixing.
    """

    def test_required_terms_accumulate_across_levels(self) -> None:
        env = _cfg(
            pod_affinity=AffinityBlock(required=[_affinity_term("web")]),
        )
        dep = _cfg(
            pod_affinity=AffinityBlock(required=[_affinity_term("db")]),
        )
        comp = _cfg(
            pod_affinity=AffinityBlock(required=[_affinity_term("cache")]),
        )

        resolved, prov = _resolve_scheduling_config(env, dep, comp)

        assert resolved.pod_affinity is not None
        required = resolved.pod_affinity.required
        assert len(required) == 3
        labels = [t.label_selector.match_labels["app"] for t in required]  # type: ignore[union-attr,index]
        assert labels == ["web", "db", "cache"]
        assert prov["pod_affinity"] == "component"

    def test_preferred_terms_merge_preserving_weights(self) -> None:
        env = _cfg(
            pod_affinity=AffinityBlock(preferred=[_weighted("web", weight=10)]),
        )
        dep = _cfg(
            pod_affinity=AffinityBlock(preferred=[_weighted("db", weight=50)]),
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.pod_affinity is not None
        preferred = resolved.pod_affinity.preferred
        assert [
            (w.weight, w.term.label_selector.match_labels["app"]) for w in preferred
        ] == [  # type: ignore[union-attr,index]
            (10, "web"),
            (50, "db"),
        ]

    def test_anti_affinity_accumulates_independently_of_pod_affinity(self) -> None:
        env = _cfg(
            pod_affinity=AffinityBlock(required=[_affinity_term("web")]),
            pod_anti_affinity=AffinityBlock(required=[_affinity_term("db")]),
        )
        dep = _cfg(
            pod_anti_affinity=AffinityBlock(required=[_affinity_term("cache")]),
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.pod_affinity is not None
        assert resolved.pod_anti_affinity is not None
        assert [
            t.label_selector.match_labels["app"] for t in resolved.pod_affinity.required
        ] == ["web"]  # type: ignore[union-attr,index]
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_anti_affinity.required
        ] == ["db", "cache"]

    def test_node_affinity_accumulates_separately(self) -> None:
        env = _cfg(
            node_affinity=AffinityBlock(required=[_affinity_term("web", key="")]),
        )
        comp = _cfg(
            node_affinity=AffinityBlock(required=[_affinity_term("cache", key="")]),
        )

        resolved, prov = _resolve_scheduling_config(env, None, comp)

        assert resolved.node_affinity is not None
        assert [_node_expressions(t) for t in resolved.node_affinity.required] == [
            [("app", "In", ["web"]), ("app", "In", ["cache"])]
        ]
        assert prov["node_affinity"] == "component"

    def test_no_levels_set_yields_none(self) -> None:
        resolved, prov = _resolve_scheduling_config(None, None, None)

        assert resolved.pod_affinity is None
        assert resolved.pod_anti_affinity is None
        assert resolved.node_affinity is None
        assert "pod_affinity" not in prov


class TestDeploymentReferenceValidator:
    """T033: exactly one of deployment_id / deployment_name must be set."""

    def test_id_only_accepted(self) -> None:
        DeploymentReference(deployment_id=uuid4())

    def test_name_only_accepted(self) -> None:
        DeploymentReference(deployment_name="prod-api")

    def test_both_set_rejected(self) -> None:
        with pytest.raises(ValueError):
            DeploymentReference(deployment_id=uuid4(), deployment_name="prod-api")

    def test_neither_set_rejected(self) -> None:
        with pytest.raises(ValueError):
            DeploymentReference()

    def test_components_narrowing_accepted(self) -> None:
        ref = DeploymentReference(
            deployment_name="prod-api",
            components=["server", "worker"],
        )
        assert ref.components == ["server", "worker"]


class TestTolerationsMerge:
    """T077: tolerations union across levels with stable tuple dedup."""

    def test_union_across_levels(self) -> None:
        env = _cfg(
            tolerations=[
                Toleration(
                    key="dedicated",
                    operator="Equal",
                    value="batch",
                    effect="NoSchedule",
                )
            ]
        )
        dep = _cfg(
            tolerations=[Toleration(key="gpu", operator="Exists", effect="NoSchedule")]
        )
        comp = _cfg(
            tolerations=[
                Toleration(
                    key="dedicated",
                    operator="Equal",
                    value="batch",
                    effect="NoSchedule",
                ),  # dup of env's
                Toleration(
                    key="memory-pressure",
                    operator="Exists",
                    effect="NoExecute",
                    toleration_seconds=60,
                ),
            ]
        )

        resolved, prov = _resolve_scheduling_config(env, dep, comp)

        assert resolved.tolerations is not None
        keys = [(t.key, t.operator, t.effect) for t in resolved.tolerations]
        # Order preserved from first occurrence; dup from comp dropped.
        assert keys == [
            ("dedicated", "Equal", "NoSchedule"),
            ("gpu", "Exists", "NoSchedule"),
            ("memory-pressure", "Exists", "NoExecute"),
        ]
        assert prov["tolerations"] == "component"

    def test_dedup_compares_full_tuple(self) -> None:
        """Same key/operator but different value/effect/seconds => NOT a dup."""
        env = _cfg(
            tolerations=[
                Toleration(key="x", operator="Equal", value="a", effect="NoSchedule"),
            ]
        )
        comp = _cfg(
            tolerations=[
                Toleration(key="x", operator="Equal", value="b", effect="NoSchedule"),
            ]
        )
        resolved, _ = _resolve_scheduling_config(env, None, comp)
        assert resolved.tolerations is not None
        assert len(resolved.tolerations) == 2

    def test_no_levels_set_yields_none(self) -> None:
        resolved, prov = _resolve_scheduling_config(None, None, None)
        assert resolved.tolerations is None
        assert "tolerations" not in prov

    def test_per_entry_provenance_tracks_contributing_level(self) -> None:
        """Per FR-009 audit: each output entry must expose which level put
        it there so operators can answer "why is this toleration here?"
        without guessing.
        """
        env = _cfg(
            tolerations=[
                Toleration(key="env-only", operator="Exists", effect="NoSchedule")
            ]
        )
        dep = _cfg(
            tolerations=[
                Toleration(key="dep-only", operator="Exists", effect="NoSchedule")
            ]
        )
        comp = _cfg(
            tolerations=[
                Toleration(key="comp-only", operator="Exists", effect="NoSchedule")
            ]
        )

        resolved, prov = _resolve_scheduling_config(env, dep, comp)

        assert resolved.tolerations is not None
        assert [t.key for t in resolved.tolerations] == [
            "env-only",
            "dep-only",
            "comp-only",
        ]
        assert prov["tolerations[0]"] == "environment"
        assert prov["tolerations[1]"] == "deployment"
        assert prov["tolerations[2]"] == "component"
        assert prov["tolerations"] == "component"


class TestTopologySpreadMerge:
    """T078: topology spread keyed union on (topology_key, when_unsatisfiable)."""

    def test_keyed_union_deepest_wins_per_key(self) -> None:
        env = _cfg(
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=1,
                    topology_key="zone",
                    when_unsatisfiable="DoNotSchedule",
                )
            ]
        )
        dep = _cfg(
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=5,
                    topology_key="zone",
                    when_unsatisfiable="DoNotSchedule",
                ),  # overrides env by key
                TopologySpreadConstraint(
                    max_skew=2,
                    topology_key="node",
                    when_unsatisfiable="ScheduleAnyway",
                ),
            ]
        )

        resolved, prov = _resolve_scheduling_config(env, dep, None)

        assert resolved.topology_spread_constraints is not None
        assert len(resolved.topology_spread_constraints) == 2
        by_key = {
            (c.topology_key, c.when_unsatisfiable): c.max_skew
            for c in resolved.topology_spread_constraints
        }
        assert by_key == {
            ("zone", "DoNotSchedule"): 5,  # dep won
            ("node", "ScheduleAnyway"): 2,
        }
        assert prov["topology_spread_constraints"] == "deployment"

    def test_per_entry_provenance_records_winning_level_per_key(self) -> None:
        """Keyed-union contributions must be per-key auditable so operators
        can tell which level won each ``(topology_key, when_unsatisfiable)``
        slot after a merge.
        """
        env = _cfg(
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=1, topology_key="zone", when_unsatisfiable="DoNotSchedule"
                )
            ]
        )
        dep = _cfg(
            topology_spread_constraints=[
                TopologySpreadConstraint(
                    max_skew=5, topology_key="zone", when_unsatisfiable="DoNotSchedule"
                ),
                TopologySpreadConstraint(
                    max_skew=2, topology_key="node", when_unsatisfiable="ScheduleAnyway"
                ),
            ]
        )

        resolved, prov = _resolve_scheduling_config(env, dep, None)

        assert resolved.topology_spread_constraints is not None
        assert prov["topology_spread_constraints[0]"] == "deployment"
        assert prov["topology_spread_constraints[1]"] == "deployment"
        assert prov["topology_spread_constraints"] == "deployment"


class TestNodeAffinityMerge:
    """T083: node_affinity reuses AffinityBlock merge; replace:true works
    independently of pod_affinity/pod_anti_affinity.
    """

    def test_node_affinity_replace_does_not_affect_pod_affinity(self) -> None:
        env = _cfg(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(match_labels={"node-type": "cpu"}),
                    )
                ]
            ),
            pod_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="kubernetes.io/hostname",
                        label_selector=LabelSelector(match_labels={"app": "web"}),
                    )
                ]
            ),
        )
        dep = _cfg(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(match_labels={"node-type": "gpu"}),
                    )
                ],
                replace=True,
            )
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        # Node-affinity was replaced
        assert resolved.node_affinity is not None
        assert [
            t.label_selector.match_labels["node-type"]  # type: ignore[union-attr,index]
            for t in resolved.node_affinity.required
        ] == ["gpu"]
        # pod_affinity untouched
        assert resolved.pod_affinity is not None
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_affinity.required
        ] == ["web"]


class TestNodeAffinityRequiredAcrossLevels:
    """#486: Kubernetes ORs ``nodeSelectorTerms``, so the resolver combines
    the required node terms of each level into terms that a node must match
    at every level (ADR-033).
    """

    def test_environment_and_deployment_terms_become_one_term(self) -> None:
        env = _cfg(node_affinity=AffinityBlock(required=[_node_term(pool="apps")]))
        dep = _cfg(node_affinity=AffinityBlock(required=[_node_term(zone="a")]))

        resolved, prov = _resolve_scheduling_config(env, dep, None)

        assert resolved.node_affinity is not None
        assert [_node_expressions(t) for t in resolved.node_affinity.required] == [
            [("pool", "In", ["apps"]), ("zone", "In", ["a"])]
        ]
        assert prov["node_affinity"] == "deployment"

    def test_alternatives_of_one_level_each_keep_the_other_levels_terms(
        self,
    ) -> None:
        env = _cfg(node_affinity=AffinityBlock(required=[_node_term(pool="apps")]))
        dep = _cfg(
            node_affinity=AffinityBlock(
                required=[_node_term(zone="a"), _node_term(zone="b")]
            )
        )
        comp = _cfg(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(
                            match_expressions=[
                                LabelSelectorRequirement(key="gpu", operator="Exists")
                            ]
                        ),
                    )
                ]
            )
        )

        resolved, _ = _resolve_scheduling_config(env, dep, comp)

        assert resolved.node_affinity is not None
        assert [_node_expressions(t) for t in resolved.node_affinity.required] == [
            [("pool", "In", ["apps"]), ("zone", "In", ["a"]), ("gpu", "Exists", None)],
            [("pool", "In", ["apps"]), ("zone", "In", ["b"]), ("gpu", "Exists", None)],
        ]

    def test_terms_of_a_single_level_stay_alternatives(self) -> None:
        dep = _cfg(
            node_affinity=AffinityBlock(
                required=[_node_term(pool="apps"), _node_term(pool="batch")]
            )
        )

        resolved, _ = _resolve_scheduling_config(None, dep, None)

        assert resolved.node_affinity is not None
        assert resolved.node_affinity.required == dep.node_affinity.required  # type: ignore[union-attr]

    def test_same_label_with_different_values_matches_no_node(self) -> None:
        env = _cfg(node_affinity=AffinityBlock(required=[_node_term(pool="apps")]))
        dep = _cfg(node_affinity=AffinityBlock(required=[_node_term(pool="db")]))

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.node_affinity is not None
        assert [_node_expressions(t) for t in resolved.node_affinity.required] == [
            [("pool", "In", ["apps"]), ("pool", "In", ["db"])]
        ]

    def test_replace_keeps_only_the_replacing_levels_terms(self) -> None:
        env = _cfg(node_affinity=AffinityBlock(required=[_node_term(pool="apps")]))
        dep = _cfg(
            node_affinity=AffinityBlock(required=[_node_term(zone="a")], replace=True)
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.node_affinity is not None
        assert resolved.node_affinity.required == [_node_term(zone="a")]

    def test_level_with_only_preferred_terms_adds_no_required_term(self) -> None:
        env = _cfg(node_affinity=AffinityBlock(required=[_node_term(pool="apps")]))
        dep = _cfg(
            node_affinity=AffinityBlock(
                preferred=[WeightedAffinityTerm(weight=10, term=_node_term(zone="a"))]
            )
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.node_affinity is not None
        assert resolved.node_affinity.required == [_node_term(pool="apps")]
        assert len(resolved.node_affinity.preferred) == 1

    def test_term_without_expressions_is_dropped_before_combining(self) -> None:
        env = _cfg(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(topology_key="", label_selector=LabelSelector()),
                    _node_term(pool="apps"),
                ]
            )
        )
        dep = _cfg(node_affinity=AffinityBlock(required=[_node_term(zone="a")]))

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.node_affinity is not None
        assert [_node_expressions(t) for t in resolved.node_affinity.required] == [
            [("pool", "In", ["apps"]), ("zone", "In", ["a"])]
        ]

    def test_level_with_only_terms_without_expressions_adds_no_requirement(
        self,
    ) -> None:
        env = _cfg(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(match_expressions=[]),
                    )
                ]
            )
        )
        dep = _cfg(node_affinity=AffinityBlock(required=[_node_term(zone="a")]))

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.node_affinity is not None
        assert resolved.node_affinity.required == [_node_term(zone="a")]

    def test_single_level_term_without_expressions_is_kept(self) -> None:
        # The post-render patch renders it as ``{matchExpressions: []}``, which
        # matches no node, as before #486.
        dep = _cfg(
            node_affinity=AffinityBlock(
                required=[
                    AffinityTerm(
                        topology_key="",
                        label_selector=LabelSelector(match_expressions=[]),
                    )
                ]
            )
        )

        resolved, _ = _resolve_scheduling_config(None, dep, None)

        assert resolved.node_affinity is not None
        assert resolved.node_affinity.required == dep.node_affinity.required  # type: ignore[union-attr]


class TestInjectFlagMerge:
    """T045: component-level ``inject`` flags override deployment-level
    flags per field. Environment-scope ``inject`` is accepted but ignored
    (data-model §1 — documented rather than rejected for schema symmetry).
    """

    def test_component_flag_overrides_deployment(self) -> None:
        dep = _cfg(inject=PostRenderInjection(pod_affinity=False, resources=False))
        comp = _cfg(inject=PostRenderInjection(pod_affinity=True))

        resolved, prov = _resolve_scheduling_config(None, dep, comp)

        assert resolved.inject is not None
        assert resolved.inject.pod_affinity is True  # from component
        assert resolved.inject.resources is False  # from deployment (inherited)
        assert prov["inject.pod_affinity"] == "component"
        assert prov["inject.resources"] == "deployment"

    def test_environment_inject_ignored(self) -> None:
        env = _cfg(inject=PostRenderInjection(pod_affinity=False))

        resolved, prov = _resolve_scheduling_config(env, None, None)

        # Env-scope inject is ignored; resolved.inject stays None.
        assert resolved.inject is None
        assert "inject.pod_affinity" not in prov

    def test_deployment_only_inject_preserved(self) -> None:
        dep = _cfg(inject=PostRenderInjection(tolerations=False))

        resolved, _ = _resolve_scheduling_config(None, dep, None)

        assert resolved.inject is not None
        assert resolved.inject.tolerations is False
        # Other fields remain None (= inherit/default True).
        assert resolved.inject.pod_affinity is None

    def test_effective_inject_flag_defaults_true(self) -> None:
        assert effective_inject_flag(None, "pod_affinity") is True
        assert effective_inject_flag(PostRenderInjection(), "pod_affinity") is True
        assert (
            effective_inject_flag(
                PostRenderInjection(pod_affinity=False), "pod_affinity"
            )
            is False
        )
        assert (
            effective_inject_flag(PostRenderInjection(resources=True), "pod_affinity")
            is True
        )


class TestDriverComponentValidation:
    def test_unknown_component_raises(self) -> None:
        with pytest.raises(UnknownComponentInConfigError) as exc:
            _resolve_scheduling_config(
                env=None,
                dep=None,
                comp=_cfg(runtime_class="kata"),
                driver_components=["server", "cache"],
                component_name="not-declared",
            )
        assert exc.value.error_metadata.get("component_name") == "not-declared"
        assert exc.value.error_metadata.get("path", "").startswith(
            "scheduling.components."
        )

    def test_known_component_passes(self) -> None:
        resolved, _ = _resolve_scheduling_config(
            env=None,
            dep=None,
            comp=_cfg(runtime_class="kata"),
            driver_components=["server", "cache"],
            component_name="server",
        )
        assert resolved.runtime_class == "kata"
