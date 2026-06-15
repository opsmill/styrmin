# ADR-028: Deployment history derived from existing `Task` + `ApplicationInstance.context`

**Status**: Accepted
**Date**: 2026-05-17
**Source**: specs/archive/001-deployment-history-timeline/research.md (R3, R4)

## Context

Operators wanted a per-deployment timeline showing every operation (deploys, upgrades, component starts/stops, jobs, deletes), the application version active at the time of each operation, and what changed between consecutive operations.

The schema already had what was needed, but not in obviously-named places:

- `Task` rows record every operation with `created_on` / `updated_on` timestamps (inherited from `StyrminModel`).
- `ApplicationInstance` rows are immutable snapshots — each create/upgrade produces a new instance row carrying `application_version` and a `context: dict` field holding the full resolved `GlobalContext` at that moment.

Two design options for filling in the timeline:

1. **Augment the schema** — add `application_version` and a serialized snapshot to `Task` itself.
2. **Derive everything at read time** from the existing `Task` + `ApplicationInstance` rows.

## Decision

Build the timeline **without schema changes**, deriving both fields server-side:

- **Per-task application version**: correlate each task's `created_on` against the deployment's `ApplicationInstance.created_on` history. For each task, pick the latest `ApplicationInstance` whose `created_on <= task.created_on`. If none exists, use the earliest instance.
- **Per-task context diff**: locate the previous operation's `ApplicationInstance` (by the same timestamp correlation) and diff the two `context: dict` blobs server-side. The diff is returned as a structured `ContextDiff` with a flat list of `ContextChange` entries (`path`, `action` ∈ {added, removed, modified}, `old_value`, `new_value`). The first operation in the timeline has `contextDiff = null`.

The wire surface is the `deploymentTimeline(deploymentId: UUID!): [DeploymentTimelineEntry!]!` query returning entries ordered `created_on DESC`. No pagination in v1 (deployments are not expected to exceed ~50 tasks; if they do, frontend virtual scrolling absorbs the volume).

## Consequences

- Zero schema migrations, zero backfills. The feature ships against the existing data shape, and historical deployments (before this feature) get full timeline coverage for free.
- The version field is **historically accurate**: each task carries the version that was active *at the time of the task*, not the deployment's current desired version. A task from three upgrades ago shows the old version, which is what operators expect when reading a history view.
- The context diff is a structured object (list of typed changes), not a unified-text diff. Frontends can render it however they like — collapse by category, group by path prefix, highlight specific fields — without re-parsing.
- Computing the diff on the server keeps the payload small: the wire carries the change list, not two full `GlobalContext` blobs. For a deployment that hasn't drifted between operations, the diff is short; for a major upgrade, it's the actual set of changed paths.
- A version-correlation edge case: `ApplicationInstance.created_on` is set when the instance is *created*, not when it becomes active. For the standard create/upgrade flow these are within milliseconds of each other; if a future feature decouples creation from activation, the correlation rule may need to switch to "active at" rather than "created at". Calling it out here so the next refactor doesn't quietly break the assumption.
- If task volume grows beyond comfortable single-query sizes, pagination can be added later as an additive change (cursor or offset) — the absence of pagination is a v1 decision, not a permanent one.

## Alternatives Considered

- **Add `application_version` directly on `Task`**: rejected. Requires a schema change and a historical backfill, both governance-gated. The timestamp-correlation approach gives the same information for free, and the join cost is negligible because `ApplicationInstance` rows are bounded per deployment.
- **Use `Deployment.application_version` for every task**: rejected. That field is the *current desired* version; using it for every historical task would silently rewrite history. A task from before an upgrade would show the post-upgrade version.
- **Frontend-side diffing**: rejected. Forces the wire to carry two full `GlobalContext` blobs per timeline entry (each one easily multi-kilobyte); duplicates the diff implementation across UI consumers; offers no benefit for read-only historical data.
- **Store explicit changelog rows**: rejected as overkill for v1. Adds a write-path responsibility (every operation has to author its own changelog) and a new table for what the existing immutable `ApplicationInstance.context` already records.
- **Text-based unified diff**: rejected. Less structured than the typed change list, harder to render selectively in the UI, and loses type information about old/new values (a number that became a string, a list that became an object).
