# ADR-012: Environment-Config Update — Typed Input, Per-Deployment Fanout, Clean Replace

**Status**: Accepted
**Date**: 2026-05-08
**Source**: specs/009-environment-update/ (spec, plan, research §7-§8, contracts/graphql.md)
**Supersedes**: the JSON-blob `updateEnvironment(environmentId, config: JSON)` write surface introduced in 008-deployment-env-vars.

## Context

008-deployment-env-vars shipped operator-set environment variables through a **JSON-blob** write surface (`updateEnvironment(environmentId, config: JSON)`) so the env vars feature could land alongside SchedulingConfig without forking validation. The JSON-blob shape was the right v1 trade-off but had two known gaps:

1. **No fanout.** Updating `Environment.config` updated the row in storage but did not redeploy the deployments living in that environment. Operators editing an env-scope env var believed their change was live; in reality it was stranded until each deployment's next reconcile was triggered for some other reason. Concretely, an operator setting `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.staging` on a `staging` environment with three deployments would see the env-config row update, but pods kept the old endpoint until a separate `updateDeployment` call (or a driver upgrade) re-rendered them.
2. **Untyped write surface.** The `config: JSON` argument bypassed schema introspection — SDK/GraphiQL consumers could not discover the writable shape from the schema, and validation lived only in the Pydantic round-trip at the resolver. Invalid inputs sometimes collapsed to `INVALID_CONTEXT` instead of the typed error codes (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`) that 008-deployment-env-vars had defined.

009-environment-update closes both gaps in one feature. Three load-bearing decisions are durable and not obvious from the code; they are recorded here.

## Decision

### 1. Per-deployment no-op detection — not mutation-level skip

The naive shape is "compare the submitted input against the persisted env-config; if they match, the mutation is a no-op and skips the fanout". We rejected that. The skip MUST happen **per deployment**, not per mutation call.

Concretely, the platform iterates every non-tombstoned, non-internal deployment in the environment and, for each one, dispatches a redeploy Task **if and only if** that deployment's currently-active `ApplicationInstance` was not generated against the now-persisted env-config. Equality is checked on the canonical-serialized form of the deployment's active-instance environment-config slice against the canonical-serialized persisted config.

This shape is load-bearing:

- **Fully-converged environment** (every deployment's active instance is already at the persisted config): every per-deployment check returns "skip", zero Tasks are dispatched, zero spurious timeline entries appear. This is the genuine no-op behaviour operators want — re-submitting an unchanged input doesn't churn pods.
- **Partial-fanout recovery**: if a prior fanout's dispatch on deployment B failed transiently (e.g., a Prefect dispatch retry exhausted), B's active instance is still at config v1 while A and C reached v2. A subsequent `updateEnvironment(input=v2)` call dispatches a redeploy Task for B only; A and C are skipped via the per-deployment check. Without per-deployment detection, the only recovery path would be a manual per-deployment intervention — defeating the whole point of fanout.
- **Distinguishes "true no-op" from "laggard recovery"**: the same code path handles both ends of the spectrum without a special-case branch.

Mutation-level skip would have collapsed both branches into "did the row change", missing the partial-failure recovery. The per-deployment check is the right granularity for the same reason `apply_state` is per-deployment in the existing reconciliation engine: deployments are the unit of convergence.

The implementation lives in `services/environments.py::_deployment_already_at_config`. It compares the canonical Pydantic round-trip of the active instance's environment-config slice against the canonical round-trip of the new config. Round-tripping through `EnvironmentConfig.model_validate(...).model_dump(...)` normalises encoding-order drift (`None` vs missing field, dict key ordering) so equality is stable across encodings.

### 2. Full-replacement input — not incremental update — in v1

`UpdateEnvironmentInput` is **full-replacement**: the input represents the complete desired environment configuration. Any field omitted from the input is persisted as its unset state. Operators editing one field MUST read the existing config first and re-submit the unchanged fields.

This is the conservative v1 choice. The alternatives were:

- **Incremental update with explicit per-field "leave-alone" semantics** (`Optional[T]` with sentinel "do not change" per field). Rejected for v1 because the semantics of "did the operator omit this field because they want it cleared, or because they don't want to touch it" are inherently ambiguous in GraphQL inputs without sentinel discipline (the "tristate optional" problem). Adding a structured sentinel — e.g., `OptionalUpdate(provided=True, value=...)` — would couple the schema to a non-standard idiom that no other mutation in the platform uses today. The decision was not "incremental is wrong" but "incremental is a separate design problem we don't want to bundle with the fanout".
- **PATCH-style merge with rules per field type** (lists are unioned, scalars are replaced, etc). Rejected — the platform already has a precedent (SchedulingConfig) where the entire config block is replaced atomically; introducing per-field merge rules in 009 would create a divergent precedent without a strong driver.

Full-replacement has a known sharp edge: callers who edit one field MUST re-supply every other field they want preserved. The frontend env-vars form (US4) handles this by reading the existing `Environment.config`, mapping it back into an `UpdateEnvironmentInput`, applying the operator's edits to the env-vars slice only, and submitting the result. SDK consumers do the same. This is documented in spec.md §"Functional Requirements" FR-003 and the `UpdateEnvironmentInput` GraphQL description string.

A future incremental-update mutation may be added when a real consumer demands it. The decision is not "no incremental ever"; it is "not in v1 alongside the fanout".

#### v1 form sharp edge: nested fields are NOT mapped

The frontend env-vars form (US4) only maps the `envVars` slice from `Environment.config` back into the full-replacement `UpdateEnvironmentInput`. The other top-level fields (`ipWhitelist`, `fqdnSuffix`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`) ride through unchanged because they are flat scalars/lists.

The nested object fields (`dedicatedIngress`, `scheduling`) are **not yet** carried through the form. They are ignored at form-state construction time and therefore submitted as `null`, which under full-replacement semantics **clears them on the persisted row**.

**Operational impact (mitigated)**: under full-replacement semantics, omitting the nested fields from `UpdateEnvironmentInput` clears them on the persisted row. To prevent the v1 form from doing this silently, **the form blocks submission** when the persisted config carries `dedicated_ingress` or `scheduling` overrides:

- The Environment Variables section detects either field on the persisted config (non-empty object) and renders a destructive Alert above the env-var rows explaining that saving from this form would clear the overrides and pointing operators to the SDK / GraphiQL.
- The Save button is disabled while the warning is present. The handler-level guard short-circuits even if a caller bypasses the disabled attribute. The env-var rows remain readable + editable so operators can review the current values and copy them into their SDK call.
- When neither nested field is set, the form behaves normally — no warning, Save enabled — which is the common case at this stage of the platform.

The block lives in `frontend/src/pages/environments/EnvironmentConfigurationTab.tsx` (`detectNestedOverridesBlock`) and `frontend/src/components/environment/EnvVarsForm.tsx` (`blockedReason` prop). Vitest regression coverage in `frontend/src/__tests__/EnvVarsForm.test.tsx` and `EnvironmentConfigurationTab.test.tsx` pins both the warning render and the disabled-Save behaviour.

**Path forward**: a follow-up iteration will extend the form's read-then-write loop to cover the nested fields, at which point both the warning Alert and this footnote disappear. Until then, operators on environments with nested overrides use the SDK (`client.environments.update(environment_id, input=UpdateEnvironmentInput(...))`) or GraphiQL — re-supplying the existing nested overrides verbatim in the `UpdateEnvironmentInput`.

### 3. Clean replace — no deprecation window — for the schema migration

The user explicitly chose **clean replace** over a deprecation window for the `updateEnvironment` schema migration: `config: JSON` is removed in the same PR that adds `input: UpdateEnvironmentInput!`. There is no overlapping window where both shapes are accepted.

This is recorded in research.md §7. The reasoning:

- All known callers are internal (the SDK, the frontend, E2E tests) and updated in the same PR.
- The deprecation-window alternative would have required a `config: JSON` field on `UpdateEnvironmentInput` to carry through during the transition, then a removal in a follow-up PR. That intermediate state has no consumer benefit (every internal caller migrates atomically) and a non-zero maintenance cost (two write paths to keep in sync, two validation pipelines to test).
- CI's GraphQL schema freshness hook + the propagation test suite catch any reintroduction of the old shape (FR-024).

External consumers, if any future ones materialise, learn about the breaking change through the schema diff in the release notes. The platform does not commit to GraphQL-level back-compat for the prior shape; the post-feature schema is the contract.

### 4. Commit ordering — env-config row before any fanout dispatch

The unit-of-work ordering invariant is pinned: the env-config row is committed to persistent storage **before** any redeploy Task is dispatched (FR-009a).

The reason is simple: the persisted row is the source of truth for "what the environment's desired state is". Tasks are downstream consumers of that source of truth — each Task reads the deployment's current state, generates a new instance against the (now-persisted) env-config, and dispatches the reconcile. If a fanout dispatch fails halfway through, the row stays committed (peers continue independently per FR-008), and a subsequent `updateEnvironment` call picks up the laggards via per-deployment no-op detection (decision §1 above).

The opposite ordering — dispatch Tasks first, commit the row at the end — was rejected: a crash mid-fanout would leave Tasks running against a config that was never persisted, and the reconcile result would diverge from the row's desired state. The current ordering means a crash mid-fanout is recoverable: the row is the authoritative state, the laggards converge on the next mutation.

## Consequences

- **Easier**: operators get end-to-end correctness on environment-scope env-config changes — the API surface, the fanout, and the per-deployment convergence are all in one mutation.
- **Easier**: SDK and GraphiQL consumers can discover the writable shape from schema introspection. Validation produces typed error codes (`INVALID_ENV_VAR_NAME`, etc.) at the GraphQL boundary, not the `INVALID_CONTEXT` collapse that 008's JSON-blob path occasionally produced.
- **Easier**: partial-fanout recovery is automatic. Operators don't need a separate "re-trigger laggards" mutation — a re-submission of the same `updateEnvironment` input picks up exactly the deployments that lag.
- **Convention to replicate**: the per-deployment no-op detection pattern (canonical-serialized comparison of the active instance's relevant config slice against the desired config) generalises to any future "environment-scope change fans out to deployments" feature. New cross-cutting environment fields should adopt the same shape.
- **Convention to replicate**: structured GraphQL input mirrors of Pydantic configuration models (one Strawberry input per Pydantic class, one enum mirror per Pydantic enum) — adopted consistently across `UpdateEnvironmentInput`, `DedicatedIngressInput`, `SchedulingInput`, `AffinityBlockInput`, etc. Any future config-shaped input should follow this 1:1 mapping rather than reverting to JSON-blob shortcuts.
- **Harder**: full-replacement semantics require the frontend form (and any caller editing one field) to read-then-write the full config. This is a UX cost on the form layer paid in exchange for atomic-replace simplicity at the storage layer. The frontend form's v1 nested-field gap (decision §2 footnote) is the visible edge.
- **Harder**: per-deployment no-op detection adds one extra `EnvironmentConfig.model_validate` round-trip per deployment per fanout. Cost is dominated by the canonical Pydantic dump; benchmarks at typical environment sizes (≤50 deployments) show the round-trip is sub-millisecond per deployment. Larger environments may need the comparison cached on a per-instance basis; not a v1 concern.
- **Harder**: the metric `env_config_fanout_deployments_total{environment, outcome}` (FR-023a) is a stub in v1. The call site exists at `services/environments.py::_emit_fanout_metric` and logs the would-be metric at `info` level with a clear marker. A real Prometheus/OTel exporter wiring is a separate ticket; until then, fanout-failure-rate dashboards (SC-011) read from the structured log instead of the metric. The TODO in the helper marks the wiring point.
- **Harder**: clean replace breaks any external caller of the prior `config: JSON` mutation shape. We do not believe such consumers exist (the platform has no external API consumers at this stage), but the contract is recorded here so the choice is visible.

## Alternatives Considered

- **Mutation-level no-op skip** (compare submitted input vs persisted row, skip the entire fanout if they match): rejected. Conflates "true no-op" with "partial-fanout recovery"; would silently strand laggards.
- **Incremental-update input** (per-field "leave-alone" sentinel, PATCH-style merge): deferred — see decision §2. Not "wrong", just out of scope for the v1 alongside fanout.
- **Deprecation window for `config: JSON`**: rejected — see decision §3. No internal consumer needs the overlap; the maintenance cost of two write paths during the transition is non-zero.
- **Tasks dispatched before row commit** (with rollback on dispatch failure): rejected — see decision §4. Inverts the source-of-truth invariant; a crash mid-fanout would diverge from the persisted row.
- **A new mutation `setEnvironmentEnvVars`** (env-vars-only write surface, leaves other fields untouched): rejected. Would fork the validation pipeline (env-vars surface + full-config surface) and create a long tail of "but what about IP allowlist?" sibling mutations. The full-config typed input is the right consolidation.
- **Per-environment lock to serialise overlapping fanouts**: rejected for v1. The existing per-deployment Task machinery already serialises reconciles per deployment; environment-level locking would add a second serialisation primitive without a clear payoff. Operators submitting rapid back-to-back env updates accept that whichever lands second wins (recorded in spec.md §"Edge Cases" + §"Assumptions").
- **A dedicated `EnvConfigFanoutTask` type**: rejected. The fanout is N invocations of the existing per-deployment redeploy Task machinery; introducing a new Task type for the umbrella event would set a precedent for splitting Task types by triggering source. The structured log line (FR-023) is the umbrella audit record; the per-deployment Tasks remain the authoritative work-items.
