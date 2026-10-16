# ADR-033: Scheduling merge — affinity accumulate with per-kind `replace:true`; topology-spread keyed by `(topologyKey, whenUnsatisfiable)`

**Status**: Accepted — amended 2026-10-16 (#482): a cluster config refuses `scheduling` instead of ignoring it
**Date**: 2026-05-17
**Source**: specs/archive/001-pod-scheduling-config/research.md (Decisions 2, 4, 5)

## Context

`SchedulingConfig` propagates through three levels — **Environment → Deployment → Component** — and the resolver has to merge them into one effective config per component before post-render injection. Most fields on `SchedulingConfig` are scalars (`runtime_class`, `node_selector`, `inject.*` booleans) and follow the deepest-wins rule already established for [[0029-config-additions-via-baseconfigsection-no-migration]] siblings.

Two fields, though, are intrinsically list-shaped and force a non-trivial merge semantics decision:

1. **Affinity** (`pod_affinity`, `pod_anti_affinity`, `node_affinity`) — Kubernetes splits each into `requiredDuringSchedulingIgnoredDuringExecution` (a list ANDed by the scheduler) and `preferredDuringSchedulingIgnoredDuringExecution` (a weighted list).
2. **Topology-spread constraints** — a list keyed by `topologyKey`, but two entries with the same `topologyKey` but different `whenUnsatisfiable` are genuinely independent constraints (one hard, one soft).

A naïve deepest-wins on either of these would let a deployment-level setting silently shadow an environment-wide safety rule. Operators expressed strongly that this is the *opposite* of what they want — environment-wide rules ("never co-locate two replicas of a critical service across the cluster") must layer with deployment-specific rules.

A naïve "always concatenate" lets contradictions accumulate (two zone-spread constraints with conflicting `whenUnsatisfiable` semantics).

Additionally, Cluster-level scheduling is **out of scope**. Node labels and taints are a cluster-admin concern, not a per-application concern; mixing them with operator-level scheduling muddles two distinct ownership boundaries.

## Decision

### Levels accepted

Scheduling defaults are accepted at **Environment, Deployment, and Component** levels. Cluster-level values are ignored: `ClusterConfig.scheduling` is left at `None` by convention and the resolver explicitly skips it. The field still lives on `BaseConfigSection` for Pydantic-class consistency — placing it everywhere except `ClusterConfig` would fragment the model hierarchy for marginal gain — but the merge logic excludes cluster-level values in a one-line guard.

Amended 2026-10-16 ([#482](https://github.com/opsmill/styrmin/issues/482)): the API accepted a
cluster `scheduling` value and the cluster page showed it as "Scheduling defaults", although no
pod got it. The convention is now enforced instead of ignored:

- `ClusterConfig` rejects the `scheduling` key whatever its value, `null` and `{}` included, so
  `createCluster` refuses it as `updateCluster` does. The field stays on `BaseConfigSection`, so
  the class hierarchy that this ADR kept does not change. `DeploymentConfig` and `ResolvedConfig`
  inherit from `ClusterConfig` and still take the field.
- `UpdateClusterInput` has no `scheduling` field.
- Revision `eac41bb71a65` deletes the stored cluster values, and `ClusterContext` drops the key
  when it loads a context stored before the change.

#482 left two options open: refuse the value, or keep accepting it and say on the cluster page and
in the API that it has no effect. Refusing it was chosen for two reasons:

- A label on the cluster page does not reach API, `styrminctl` and SDK clients, which would still
  save a value that no pod gets.
- #472 had the same problem for `node_selector`, and PR #481 removed that field instead of
  labeling it.

### Affinity merge — accumulate by default, `replace:true` per kind

For each of the three affinity kinds (`podAffinity`, `podAntiAffinity`, `nodeAffinity`):

- `requiredDuringSchedulingIgnoredDuringExecution` terms across levels are **concatenated** (the scheduler ANDs them).
- `preferredDuringSchedulingIgnoredDuringExecution` terms are **merged into a single weighted list**, preserving per-level weights.

Any level's affinity block may set `replace: true` for a specific kind to **discard shallower-level terms for that kind**. The flag is scoped per affinity-kind so replacing `podAntiAffinity` does not affect `nodeAffinity` or `podAffinity`. Walking levels Environment → Deployment → Component: if a level sets `replace: true` for a kind, the accumulator resets before that level's terms are added; deeper levels continue accumulating unless they too set `replace: true`.

### Topology-spread merge — union keyed by `(topologyKey, whenUnsatisfiable)`

Topology-spread constraints are unioned across levels with the compound key `(topologyKey, whenUnsatisfiable)`. When two levels set a constraint with the same compound key, the deepest-level entry wins for that key — scalar-style precedence on the key. Two entries with the same `topologyKey` but different `whenUnsatisfiable` are independent constraints and both survive.

## Consequences

- An environment-wide safety rule layers cleanly with a per-deployment affinity tweak by default. Operators don't have to copy environment rules into every deployment to keep them in force.
- The `replace: true` escape hatch exists for genuine "this deployment is special, throw out the parent rules for *this* kind" cases. Per-kind scoping means a narrow override of one affinity kind doesn't accidentally clobber the others.
- The topology-spread compound key matches how the Kubernetes scheduler itself treats these constraints (each `(topologyKey, whenUnsatisfiable)` pair is an independent rule). The mental model is the same between operator config and scheduler behaviour.
- A cluster config refuses `scheduling` (amended 2026-10-16, #482), which makes the ownership boundary clear: cluster admins manage node taints/labels via Kubernetes-native means; platform operators manage scheduling defaults via Environment/Deployment/Component scheduling config.
- The merge implementation is uniform: a single resolver walks the three levels in order, maintains separate accumulators per affinity-kind and per topology-spread key, and respects the per-kind `replace` flag. New scheduling fields with list-like merge semantics can follow the same recipe.

## Alternatives Considered

- **Deepest-level wins by default for affinity**: rejected. Makes environment-wide safety rules impossible to express without restating them at every deployment, which scales poorly and is exactly what the hierarchical model exists to avoid.
- **Global `replace: true` flag**: rejected. Too blunt — operators usually want to override one affinity kind, not all three. Per-kind scoping keeps the override narrow.
- **Topology-spread keyed on `topologyKey` only**: rejected. Two levels legitimately want the same `topologyKey` with different `whenUnsatisfiable` (one hard, one soft); collapsing them by `topologyKey` alone would silently lose one of the two rules.
- **Topology-spread always concatenated, no dedup**: rejected. Two levels both setting zone-spread would produce duplicate, possibly-contradictory rules that the scheduler would surface as scheduling failures with confusing diagnostics.
- **Split the class hierarchy so `ClusterConfig` doesn't inherit `scheduling` at all**: rejected. Trading one resolver guard line for a fragmented type hierarchy (Pydantic multi-inheritance gymnastics, downstream tools that introspect `BaseConfigSection` getting confused) is the wrong tradeoff.
