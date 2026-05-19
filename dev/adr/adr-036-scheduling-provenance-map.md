# ADR-036: Scheduling provenance map — dotted-path → source level alongside resolved config

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-pod-scheduling-config/research.md (Decision 10)

## Context

A resolved `SchedulingConfig` is the result of merging Environment → Deployment → Component (see [[adr-033-scheduling-merge-semantics]]). After the merge, the value of any given field can no longer self-report which level contributed it — an effective `resources.limits.cpu = "2"` looks the same whether it came from the environment-wide default, a deployment-specific override, or a per-component pin.

Operators inspecting a deployment need to answer "which level set this value?" to diagnose unexpected scheduling behaviour:

- "Why is this pod getting 4Gi of memory? I never set that on the deployment."
  (Answer: it's a component-level setting in the chart's `values.yaml`.)
- "Why is this affinity rule in force? My deployment doesn't have it."
  (Answer: it's accumulated from environment-wide affinity defaults — see [[adr-033-scheduling-merge-semantics]].)

FR-012 explicitly requires "enough metadata for a template to determine which level provided each value". The frontend deployment detail page surfaces this as a per-field source-level chip (SC-004: identify the resolved effective value and its source level in under 30 seconds).

## Decision

Alongside each resolved `SchedulingConfig` in every `ComponentContext`, the platform produces a parallel `resolved_scheduling.provenance: dict[str, Literal["environment", "deployment", "component"]]` map:

- **Keys** are dotted paths into the resolved structure (e.g., `"resources.limits.cpu"`, `"affinity.pod.required[0]"`, `"tolerations[2]"`, `"runtime_class"`).
- **Values** are the level that contributed that path's value.
- For **accumulated lists** (affinity terms, tolerations, topology-spread constraints), provenance is recorded **per element**, indexed into the resolved list.

The map is computed at the same time as the merge — the resolver walks levels in order, and for each field/index it writes, it records its current level as the provenance value for that dotted path.

The provenance map is exposed via:

- `GlobalContext.components[<name>].resolved_scheduling.provenance` — readable from Jinja templates (drivers that want granular source information can index into the map).
- `Deployment.resolvedScheduling: [ResolvedComponentScheduling!]!` on GraphQL — surfaces both the resolved config and the provenance map for the frontend.

## Consequences

- Operators get a precise, machine-readable answer to "where did this value come from?" without the platform having to retain the unmerged per-level config alongside the resolved one.
- Dotted paths are trivially consumed from Jinja templates and JS — no special accessor library, no parser. `provenance["resources.limits.cpu"]` is one indexing operation.
- Per-element provenance for accumulated lists is **strictly more useful** than a single list-level source ("tolerations come from multiple levels"). When debugging a specific toleration's presence, the operator can identify exactly which level added that toleration.
- The map's size is bounded by the resolved scheduling tree depth and width — small compared to the resolved scheduling object itself, and proportional to it.
- The cost: the resolver has to record provenance while merging. A naive merge that just composes dicts has to grow to write a parallel map. The cost is paid once per resolve, which happens once per reconcile cycle per deployment — not a hot path.

## Alternatives Considered

- **Second parallel `SchedulingConfig` shaped with `(value, source)` tuples per field**: rejected. Doubles the schema complexity for a rarely-read field. Templates and frontends would have to know two parallel shapes; the dotted-path map is one auxiliary structure with a simple shape.
- **Only record provenance for scalars; not for accumulated lists**: rejected. Operators need to know which level added a given toleration (or affinity term) when debugging — this is the case where it matters most, not least. Lists are exactly where the merge is non-trivial and provenance is hardest to reason about without help.
- **Surface the unmerged per-level config to operators and let them do the merge in their heads**: rejected. The whole point of hierarchical config is that the platform does the merge. Asking operators to mentally re-merge to find a value's source defeats the abstraction.
- **Store the unmerged per-level config and compute provenance on demand**: rejected. The merge logic is non-trivial (affinity accumulation with per-kind `replace:true`, topology compound key), and computing provenance on every read would duplicate that logic. Recording it once at merge time is strictly cheaper.
