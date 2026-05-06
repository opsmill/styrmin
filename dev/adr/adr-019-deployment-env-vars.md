# ADR-019: Deployment Env Vars — Free-Form, Three-Scope, Post-Render Injected

**Status**: Accepted
**Date**: 2026-05-06
**Source**: specs/008-deployment-env-vars/ (spec, plan, research §7)

## Context

Operators routinely need to flip a single knob on a running deployment — a log level, a telemetry endpoint, a feature flag — without waiting for the driver author to add a typed parameter and without forking the driver. Before this feature the only escape hatches were a cross-team driver edit or a driver fork; both are slow and have been called out by users as anti-patterns.

The feature ships a free-form `dict[str, str]` of environment variables settable at three scopes (environment, deployment, per-component) with per-key deepest-wins precedence, auto-injected into rendered workloads via the existing post-render injection pipeline. It plugs into three already-load-bearing systems (the `ResolvedConfig` pipeline, the driver loader, the post-render patch builder) and adds nothing new of its own at runtime.

Several decisions on this feature are durable and not obvious from the code — they need a record so future maintainers don't relitigate them. This ADR captures them.

## Decision

### 1. Env vars exist parallel to typed parameters; the boundary is intentional

Drivers continue to declare **typed parameters** for inputs the app contract requires (validation, defaults, required-vs-optional, type checking). Env vars are the deliberately-untyped escape hatch for the long tail of inputs the app respects but the driver author cannot or will not enumerate ahead of time.

Concretely:

- Typed parameters: validated, defaulted, can be required, schema-driven UI editing.
- Env vars: free-form `dict[str, str]`, no defaults, no required-flag, doc-only declaration.

The boundary is by design. Operators who reach for env vars accept the trade-off (no validation, no UI hand-rails) in exchange for not blocking on a driver change. Driver authors who want validation use parameters.

### 2. Driver-side declaration is doc-only

`spec.env_vars` on the driver lists env vars the app respects with `name`, `description`, `level` (deployment/component), and (for component-level) the targeted components. The driver loader validates the **shape** of these declarations (name regex, name uniqueness, components-must-exist) but **does not validate, default, or constrain user-set values** against them.

A user can set any name they want. The driver-side block is a discoverability surface only — it tells consumers "here's what this app pays attention to" without becoming a second validation layer that competes with parameters. Crossing that line would re-introduce the parameter contract at one remove.

The driver-side docs are persisted in a dedicated `applicationdriverversion.env_vars` JSON column (Alembic migration `d0e1f2a3b4c5_add_env_vars_to_application_driver_version`), not embedded inside `spec_yaml`. This deviates from research.md's "no new column" hint but keeps the doc surface queryable independently of full driver re-parses, which the GraphQL resolver does on every driver detail read.

### 3. Conflict policy: post-render-wins, with best-effort warning

When a chart's rendered manifest already contains an `env:` entry with the same name as an operator-set env var, **the operator-set value wins**. This is enforced by the post-render JSON-patch which replaces the container's `env` list at index 0 (see ADR-006 + Assumptions in spec.md for the `container[0]`-only v1 limit).

Detection of these collisions is best-effort:

- **Primary channel**: a structured field on the deployment timeline entry (`DeploymentTimelineEntry.envVarCollisions`) populated when the agent layer can compare rendered chart output against the operator-set list.
- **Fallback channel**: a structured `logger.warning("env_var_potentially_chart_colliding", ...)` log line emitted unconditionally from the patch builder.

FR-028 explicitly authorises the degradation: when timeline emission can't be wired (which is the v1 state — there is no rendered-manifest fetch + diff seam yet), the feature does not block on it. The operator's value still wins; the warning surface is purely diagnostic. We did not consider blocking on collision (would break the headline use case) or "chart wins" (would silently drop the operator's intent).

### 4. Upgrade orphan policy: warn-and-keep, never block

A driver upgrade that renames or removes a component carrying per-component env vars **must succeed** without operator intervention. Stored env var blocks targeting components the new driver no longer declares are exposed via `ComponentEnvVars.isOrphaned = true` and skipped during effective-dict computation (so they are not injected into any pod).

Auto-deletion was rejected: the operator did not change anything, the driver did, and silently dropping their config would be worse than keeping it visible until the operator explicitly cleans it up. Blocking the upgrade was rejected by the PRD: this would invert the platform's job (drivers tell the platform what's possible, not the other way round).

The orphan transition itself is captured by the existing `context_diff` machinery — no new event type. If the operator rolls the driver back to a version that re-introduces the orphaned component, the previously-orphaned block becomes live again on the next reconcile (`isOrphaned: false`).

### 5. No cluster scope in v1

The PRD originally floated a fourth `cluster` scope above environment. We deferred it because it has cross-team blast radius without an auth model: an env var set on a shared cluster would propagate to every environment of every team using that cluster, and we have no per-team / per-environment authorization gate to scope writes. Re-introducing it later requires the auth model first; meanwhile, environment-level scoping covers the same operational need at a safer granularity.

### 6. `isOrphaned` is a first-class API contract, not a derived view

The orphan flag is exposed as `ComponentEnvVars.isOrphaned: Boolean!` on every `componentEnvVars` entry. We considered making it a derived field (recomputed on every query from "current driver components vs stored block target"), but committed to it as a first-class persisted/computed contract because:

- The orphan path is also a degradation path — when the resolver fails to identify the current driver's components for any reason, every block would be falsely flagged orphaned. Keeping the flag explicit means callers see the actual platform state, not a side-effect of resolver health.
- UI and SDK consumers need a stable surface to render "this block is no longer effective" without having to know about the driver's component map themselves. Surfacing the flag at the API boundary keeps the responsibility on the platform.

## Consequences

- **Easier**: operators get a one-shot escape hatch for app-respected env vars without a driver round-trip. The headline use case (`set LOG_LEVEL=debug on one deployment`) requires a single GraphQL mutation and one reconcile cycle.
- **Easier**: the three-scope hierarchy lets fleet-wide baselines (environment), per-deployment overrides (deployment), and component-narrow tweaks (per-component) compose without duplicate config.
- **Easier**: driver upgrades never break on orphaned env var blocks — they remain visible for audit and become live again if the component name is re-introduced.
- **Convention to replicate**: per-key deepest-wins merge across (env, deployment, component) with provenance recording — this mirrors the SchedulingConfig precedent, and any future cross-cutting `dict[str, T]` config (labels, annotations, resource hints) should follow the same `_merge_*` shape next to it.
- **Harder**: operators can store secret-shaped values in env vars and the platform won't stop them. The risk is documented at the type level (`EnvVar.value` description warns explicitly) and must be re-litigated if/when a typed-secret variant lands.
- **Harder**: the v1 patch targets `container[0]` only (a JSON-patch limitation, mirroring `ResourcesPatch`). Multi-container components have to either narrow by component scope or wait for a follow-up that fans out one patch per declared container.
- **Harder**: collision detection's primary channel (timeline entries) is currently inert — the rendered-manifest fetch + diff seam doesn't exist yet, so `envVarCollisions` always returns `[]` in v1. The structured-log fallback is the only signal until that seam lands.

## Alternatives Considered

- **Strict-typed mutation arguments** (`envVars: [EnvVarInput!]` as a top-level mutation arg): rejected. Would duplicate the existing `config: JSON` write surface and fork validation between Pydantic (for `config`) and Strawberry input types (for `envVars`). The scheduling feature took the same JSON-for-writes / typed-for-reads path and the precedent is sound.
- **A new `setDeploymentEnvVars` mutation**: explicitly forbidden by the PRD — the existing `deploy()` / `updateDeployment()` mutations are the contract.
- **A dedicated `deployment_env_vars` table**: rejected. Would require a migration, repository changes, and a parallel persistence path. Env vars are always read together with the rest of the deployment config; a JSON merge into the existing `EnvironmentConfig` / `DeploymentConfig` Pydantic models is the smaller, lower-risk change. (The driver-side doc column is a separate decision — see §2.)
- **Auto-delete orphaned blocks at upgrade time**: rejected. The PRD's "warn-and-keep rather than block" rule means the operator must be the one to decide an orphaned block is no longer wanted.
- **A dedicated `EnvVarOrphanedEvent` deployment timeline event type**: rejected for v1. The existing `context_diff` channel naturally records the visible drift, and a new event type would set a precedent for splitting timeline events by feature. Deferred until a real second event type accumulates.
- **A `cluster` scope above environment**: deferred — see §5.
- **Per-container env var scoping**: deferred. The component is the smallest addressable unit in v1; multi-container fan-out is a follow-up ticket.
- **A typed-secret env var variant** (`valueFrom.secretKeyRef`-style): out of scope for this feature. A separate ticket will address it before any production user is asked to store credentials in env vars.
