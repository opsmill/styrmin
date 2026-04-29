# ADR-014: Pod-Status Records Observed Runtime State, Not Declared Component Intent

**Status**: Accepted
**Date**: 2026-04-29
**Source**: specs/005-match-pod-component/research.md (§2)

## Context

When the agent reports pod statuses, each pod can carry a `styrmin/component=<name>` label that ties the running pod back to a declared `Component` on the deployment's driver. Surfacing this attribution is necessary for any per-component status UI or component-level health rollup.

There are two natural places to enforce a coherent picture:

1. **Strict server-side validation** — when persisting a pod-status record, check that `component_name` matches a `Component` declared for that deployment. Reject (or coerce to `None`) anything else.
2. **Record observation as-is** — store whatever value the agent reports, including drift, missing labels, and labels that don't match any currently-declared component.

The first option is the conventional "referential integrity is good" instinct. The second option treats observed runtime state and declared intent as two different things that intentionally drift.

## Decision

The server stores `component_name` exactly as observed. There is no validation against the deployment's declared `Component` set, no foreign-key relationship from `PodStatus.component_name` to `Component.id`, and no coercion of unrecognized values to `None`.

Pods without the `styrmin/component` label, with a blank label, or with a label whose value doesn't match any declared component are all stored truthfully.

The agent normalizes blank/whitespace-only label values to `None` at the wire boundary so the server only sees two cases (a value or absence), but it does not coerce non-blank values.

## Consequences

- **Drift is recorded honestly.** During a rollout, old pods carry the old component name and new pods carry the new one. Both end up in the database with their actual labels, which is what an operator needs to see.
- **No write-path query into the components table.** `report_pod_statuses` runs every ~5 s against potentially many pods; not having to look up declared components per pod keeps that path cheap.
- **No cascade-delete coupling.** Pod-status rows do not depend on `Component` row identity. Deleting or renaming a component cannot orphan or invalidate pod-status records.
- **The `component_name` column is a free-form `str | None`.** Code that consumes it must handle the case where the value is present but doesn't match any currently-declared component. This is treated as "extra information operators want to see," not an error.
- **Boundary clarity.** The platform now has a clear distinction between the *desired-state* layer (drivers, components, deployments) and the *observed-state* layer (pod statuses, CRD statuses). Pod statuses join the latter unambiguously.

## Alternatives Considered

- **Strict validation: reject unrecognized component names.** Rejected — turns expected drift (rollouts, renames) into a failure mode with no agent-side recovery other than dropping the row, which violates the "don't silently drop pods" requirement (spec.md FR-002).
- **Lenient coercion: store `None` when the value doesn't match a declared component.** Rejected — silently destroys the actual observed label, which is exactly the data an operator needs when diagnosing a misconfigured workload.
- **Foreign key from `PodStatus.component_name` to `Component.id`.** Rejected — components are scoped per-deployment and can be deleted/renamed; foreign-keying observed runtime state to mutable declared state creates cascade-delete bugs and migration pain. The semantic relationship between an observed label and a declared component is informational, not structural.
