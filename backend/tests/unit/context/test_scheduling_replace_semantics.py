"""T032: ``replace: true`` is scoped per-affinity-kind.

``replace: true`` on ``pod_affinity`` at a given level must discard all
shallower-level terms for ``pod_affinity`` ONLY — ``pod_anti_affinity`` and
``node_affinity`` accumulators at that level are unaffected. Levels deeper
than the one that set ``replace: true`` continue to accumulate on top of the
replacement unless they also set ``replace: true``.
"""

from __future__ import annotations

from styrmin_backend.context.models.config import (
    AffinityBlock,
    AffinityTerm,
    LabelSelector,
    SchedulingConfig,
    WeightedAffinityTerm,
)
from styrmin_backend.context.resolvers import _resolve_scheduling_config


def _term(app: str, key: str = "kubernetes.io/hostname") -> AffinityTerm:
    return AffinityTerm(
        topology_key=key, label_selector=LabelSelector(match_labels={"app": app})
    )


def _cfg(**kwargs: object) -> SchedulingConfig:
    return SchedulingConfig(**kwargs)  # type: ignore[arg-type]


class TestReplaceTrueSemantics:
    def test_replace_on_deployment_discards_env_terms_for_same_kind(self) -> None:
        env = _cfg(pod_affinity=AffinityBlock(required=[_term("web")]))
        dep = _cfg(
            pod_affinity=AffinityBlock(
                required=[_term("db")],
                replace=True,
            )
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.pod_affinity is not None
        apps = [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_affinity.required
        ]
        assert apps == ["db"]

    def test_replace_does_not_affect_other_kinds(self) -> None:
        env = _cfg(
            pod_affinity=AffinityBlock(required=[_term("web")]),
            pod_anti_affinity=AffinityBlock(required=[_term("db")]),
            node_affinity=AffinityBlock(required=[_term("large", key="")]),
        )
        dep = _cfg(
            pod_affinity=AffinityBlock(
                required=[_term("cache")],
                replace=True,
            )
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.pod_affinity is not None
        assert resolved.pod_anti_affinity is not None
        assert resolved.node_affinity is not None
        # pod_affinity wiped and re-seeded
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_affinity.required
        ] == ["cache"]
        # pod_anti_affinity untouched
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_anti_affinity.required
        ] == ["db"]
        # node_affinity untouched
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.node_affinity.required
        ] == ["large"]

    def test_deeper_level_accumulates_on_top_of_replacement(self) -> None:
        env = _cfg(pod_affinity=AffinityBlock(required=[_term("web")]))
        dep = _cfg(pod_affinity=AffinityBlock(required=[_term("db")], replace=True))
        comp = _cfg(pod_affinity=AffinityBlock(required=[_term("cache")]))

        resolved, _ = _resolve_scheduling_config(env, dep, comp)

        assert resolved.pod_affinity is not None
        apps = [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_affinity.required
        ]
        assert apps == ["db", "cache"]

    def test_component_replace_wipes_all_shallower_levels(self) -> None:
        env = _cfg(pod_affinity=AffinityBlock(required=[_term("web")]))
        dep = _cfg(pod_affinity=AffinityBlock(required=[_term("db")]))
        comp = _cfg(
            pod_affinity=AffinityBlock(
                required=[_term("cache")],
                replace=True,
            )
        )

        resolved, _ = _resolve_scheduling_config(env, dep, comp)

        assert resolved.pod_affinity is not None
        apps = [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_affinity.required
        ]
        assert apps == ["cache"]

    def test_empty_replace_block_erases_shallower_terms(self) -> None:
        env = _cfg(pod_affinity=AffinityBlock(required=[_term("web")]))
        dep = _cfg(pod_affinity=AffinityBlock(replace=True))

        resolved, prov = _resolve_scheduling_config(env, dep, None)

        # replace:true alone (no new terms) still counts as a contribution
        # and must discard env's terms.
        assert resolved.pod_affinity is not None
        assert resolved.pod_affinity.required == []
        assert resolved.pod_affinity.preferred == []
        assert prov["pod_affinity"] == "deployment"

    def test_preferred_weighted_terms_also_replaced(self) -> None:
        env = _cfg(
            pod_affinity=AffinityBlock(
                preferred=[WeightedAffinityTerm(weight=10, term=_term("web"))]
            )
        )
        dep = _cfg(pod_affinity=AffinityBlock(replace=True))

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.pod_affinity is not None
        assert resolved.pod_affinity.preferred == []

    def test_simultaneous_replace_across_kinds_is_independent(self) -> None:
        """Replace on two kinds at the same level must not bleed — each kind's
        accumulator is discarded separately and re-seeded from its own terms.
        """
        env = _cfg(
            pod_affinity=AffinityBlock(required=[_term("env-pod")]),
            pod_anti_affinity=AffinityBlock(required=[_term("env-anti")]),
            node_affinity=AffinityBlock(required=[_term("env-node", key="")]),
        )
        dep = _cfg(
            pod_affinity=AffinityBlock(required=[_term("dep-pod")], replace=True),
            pod_anti_affinity=AffinityBlock(required=[_term("dep-anti")], replace=True),
            # node_affinity NOT replaced — should still inherit from env.
        )

        resolved, _ = _resolve_scheduling_config(env, dep, None)

        assert resolved.pod_affinity is not None
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_affinity.required
        ] == ["dep-pod"]
        assert resolved.pod_anti_affinity is not None
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.pod_anti_affinity.required
        ] == ["dep-anti"]
        assert resolved.node_affinity is not None
        assert [
            t.label_selector.match_labels["app"]  # type: ignore[union-attr,index]
            for t in resolved.node_affinity.required
        ] == ["env-node"]
