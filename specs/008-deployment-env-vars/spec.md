# Feature Specification: Deployment Env Vars (Free-Form, Post-Render Injected)

**Feature Branch**: `008-deployment-env-vars`
**Created**: 2026-05-06
**Status**: Draft
**Input**: User description: PRD from issue #4 comment 4372753082 — free-form `dict[str, str]` of environment variables settable at environment, deployment, and per-component scope, auto-injected into rendered workloads via the existing post-render injection mechanism, with optional doc-only declarations on the driver side.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Per-deployment env var override without driver change (Priority: P1)

A deployment operator needs to flip a knob on one running deployment — typically a log level, a telemetry endpoint, or a feature flag — without waiting on the driver author to add a typed parameter and without forking the driver. The operator sets a free-form env var on the deployment; on the next reconcile, every container in every workload of that deployment carries the new env entry.

**Why this priority**: This is the core problem the feature exists to solve. Without it, the only escape hatches are cross-team driver changes or driver forks, both of which the PRD calls out as bad. Shipping just this one slice already delivers the headline value: an operator can set `LOG_LEVEL=debug` on one deployment.

**Independent Test**: Deploy a single-component app, set `envVars: { LOG_LEVEL: "debug" }` on the deployment via the GraphQL mutation, and verify that the rendered pod's container has `LOG_LEVEL=debug` in its `env:` block. No driver change is required.

**Acceptance Scenarios**:

1. **Given** a deployed app whose driver does not declare any env var documentation, **When** the operator sets `envVars: { LOG_LEVEL: "debug" }` via `updateDeployment`, **Then** the next reconcile produces pod containers with `LOG_LEVEL=debug` present in their `env:` block alongside any chart-rendered env entries.
2. **Given** a deployment with `envVars: { LOG_LEVEL: "debug" }` set, **When** the operator clears the field by passing an empty dict, **Then** the next reconcile removes the post-render-injected entry and the rendered pods reflect only the chart's own env entries.
3. **Given** a deployment-level env var set on a multi-component driver, **When** the deployment reconciles, **Then** every component's pod containers receive the env var.

---

### User Story 2 - Environment-scoped baseline env vars (Priority: P1)

An operator running multiple deployments in a shared `staging` environment wants every deployment in that environment to receive a common env var (e.g., `OTEL_EXPORTER_OTLP_ENDPOINT`) without per-deployment editing. Setting it once at the environment scope propagates to every existing and future deployment in that environment, while individual deployments retain the ability to override on a per-key basis.

**Why this priority**: Environment-scoped propagation is the mechanism that makes the feature usable at fleet scale. Without it, operators would re-enter the same env vars on every deployment, defeating the purpose. The hierarchy is the feature's load-bearing model and the second slice that must ship for the feature to be worth using.

**Independent Test**: Set an env var at the environment scope on a `staging` environment containing two deployments. Reconcile both. Assert that both deployments' pod containers carry the env var. Then set a deployment-level env var with the same name on one of the two and assert that one shows the deployment-level value while the other still shows the environment-level value.

**Acceptance Scenarios**:

1. **Given** an environment with `envVars: { OTEL_EXPORTER_OTLP_ENDPOINT: "https://otel.staging" }` and two deployments inside it, **When** both deployments reconcile, **Then** the pods of both deployments include `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.staging`.
2. **Given** the environment-level env var above, **When** a deployment also sets `envVars: { OTEL_EXPORTER_OTLP_ENDPOINT: "https://otel.local" }` at the deployment scope, **Then** that deployment's pods carry the deployment-level value (`https://otel.local`) and the other deployment in the environment continues to carry the environment-level value.
3. **Given** an environment-level env var and a deployment that does not redefine it, **When** a new deployment is added to the same environment, **Then** the new deployment also receives the env var on its first reconcile without any per-deployment configuration.

---

### User Story 3 - Per-component scoping with deepest-wins precedence (Priority: P1)

An operator running a multi-component app (e.g., `api` + `worker`) needs to set an env var on only the `worker` component, and to override deployment-level baselines on a per-key basis at the component scope. Component-level env vars must apply only to the targeted component's pods, not bleed into other components.

**Why this priority**: Per-component scoping is the third leg of the hierarchy and the only way to set worker-only or sidecar-only env vars without polluting peer components. Without it, multi-component apps degrade to "set on all or set on none" — operationally inadequate.

**Independent Test**: Deploy a multi-component app with `api` and `worker` components. Set a deployment-level `LOG_LEVEL=info` and a component-level `LOG_LEVEL=debug` on `worker` and a component-level `WORKER_QUEUE=orders` on `worker`. Assert that `api` pods have `LOG_LEVEL=info` and no `WORKER_QUEUE`; that `worker` pods have `LOG_LEVEL=debug` and `WORKER_QUEUE=orders`.

**Acceptance Scenarios**:

1. **Given** a multi-component deployment with `envVars: { LOG_LEVEL: "info" }` and `componentEnvVars: [{ component: "worker", envVars: { LOG_LEVEL: "debug", WORKER_QUEUE: "orders" } }]`, **When** the deployment reconciles, **Then** pods labelled with the `api` component selector show only `LOG_LEVEL=info`, and pods labelled with the `worker` component selector show `LOG_LEVEL=debug` and `WORKER_QUEUE=orders`.
2. **Given** a per-component env var targeting a component the driver does not declare, **When** the operator submits the mutation, **Then** the mutation is rejected with a precise error listing the driver's known component names.
3. **Given** a deployment whose driver declares no components at all, **When** a deployment-level env var is set, **Then** every pod-template-bearing workload in the rendered release receives the env var.

---

### User Story 4 - Driver-side documentation surfaced in the driver detail view (Priority: P2)

Driver authors want to advertise the env vars their app respects (e.g., `LOG_LEVEL`, `OTEL_EXPORTER_OTLP_ENDPOINT`) so that consumers picking the driver see useful hints about what knobs are available. The declaration is doc-only — it does not constrain or validate user-set values, it does not become required, and it does not produce defaults. Driver authors can scope each documented env var to deployment-wide or to specific components.

**Why this priority**: The doc surface is independent of the runtime injection: the feature works without it (US1–US3), and it ships without it. But it materially improves discoverability for users browsing drivers, and it is the only mechanism that pulls driver authors into the feature loop, so it ships in v1.

**Independent Test**: Register a driver whose `driver.styrmin.yml` includes a `spec.env_vars` block with both deployment-level and component-level entries. Query the driver detail field via GraphQL and assert that the `envVars` field returns the documented entries grouped by scope. Then attempt to register a driver whose `spec.env_vars` references a component name not in the driver's component map; assert that the loader rejects it.

**Acceptance Scenarios**:

1. **Given** a driver with a `spec.env_vars` block listing one deployment-level and two component-level documented env vars, **When** the UI/SDK queries the driver detail, **Then** the `envVars` field exposes the documented entries with their `name`, `description`, `level`, and (for component-level entries) the targeted components.
2. **Given** a driver whose `spec.env_vars` contains an entry with `level: component` and `components: [does-not-exist]`, **When** the driver loader runs, **Then** registration fails with an error pointing at the offending entry.
3. **Given** a driver whose `spec.env_vars` contains an entry whose name violates the env var name regex, **When** the driver loader runs, **Then** registration fails with an error naming the invalid entry.

---

### User Story 5 - Visible orphan tracking across upgrades (Priority: P2)

When a driver upgrade renames or removes a component, an operator's previously-set per-component env vars on that component become orphaned. The operator must not have the upgrade blocked by stored config drift, and the orphaned blocks must remain visible (rather than silently disappear) so the operator can audit and clean them up. The platform emits a single timeline event when the upgrade orphans env vars.

**Why this priority**: This is the operational safety net for the per-component scope (US3). Without orphan tracking, a routine driver upgrade would either fail (bad UX) or silently strand operator-set config (worse — the operator believes their changes apply when they don't). It is P2 because it only matters once US3 is in use.

**Independent Test**: Deploy a driver v1 with components `api` and `worker`, set a component env var on `worker`, then upgrade to driver v2 where `worker` has been renamed to `processor`. Assert that the upgrade succeeds, that the `componentEnvVars` query exposes the `worker` block with `isOrphaned: true`, and that a single timeline event is emitted recording the orphan.

**Acceptance Scenarios**:

1. **Given** a deployment with a per-component env var on `worker`, **When** the deployment is upgraded to a driver version that no longer declares `worker`, **Then** the upgrade succeeds, the `componentEnvVars` query returns the `worker` block with `isOrphaned: true`, and a single timeline event recording the orphan is created.
2. **Given** an orphaned per-component env var block, **When** the operator removes the block via `updateDeployment`, **Then** the block disappears from the query result and no further timeline events are emitted on subsequent reconciles.
3. **Given** an orphaned per-component env var block that has not been cleaned up, **When** subsequent reconciles run, **Then** no additional timeline events are emitted (the orphan event is one-shot per upgrade transition).

---

### User Story 6 - Component-level injection opt-out (Priority: P3)

Some components — typically sidecars, debug containers, or workloads with strict env-handling requirements — must not receive automatic env var injection. The driver author (or, where relevant, the operator) can opt a specific component out of injection, and the post-renderer leaves that component's pod containers untouched while still injecting on peer components.

**Why this priority**: This is a guard rail for a small set of components, not a daily-driver feature. It matters when it matters (a sidecar's env handling breaks under injection), but most deployments will never use it. P3 reflects that.

**Independent Test**: Deploy a multi-component driver where the `debug-sidecar` component sets the `inject_env_vars=False` flag in its `PostRenderInjection`. Set both deployment-level and component-level env vars. Assert that all other components' pods receive the env vars, while the `debug-sidecar` pod's `env:` block is untouched.

**Acceptance Scenarios**:

1. **Given** a component with `inject_env_vars=False` and an unrelated component with the default flag, **When** deployment-level env vars are set, **Then** only the unrelated component's pods receive the env vars; the opted-out component's pods retain their original chart-rendered env entries.
2. **Given** a component with `inject_env_vars=False`, **When** a component-level env var block targets that same component, **Then** the env var block is still recorded in storage and visible in the query, but no env entries are injected into the component's pod containers.

---

### User Story 7 - Conflict warning when chart already renders a colliding env entry (Priority: P3)

When the chart's rendered manifest already contains an `env:` entry with the same name as an operator-set env var, the operator-set value wins (post-render replaces). The platform emits a non-blocking warning to the deployment timeline so the operator can audit unexpected behaviour after the fact, even when their value still takes effect.

**Why this priority**: The behaviour is correct without the warning — the operator's value wins. The warning is purely diagnostic, helping operators understand why a chart-default value isn't visible in their pods. It is P3 because the absence of the warning does not prevent any user from accomplishing their goal.

**Independent Test**: Deploy a chart whose values render a container with `env: [{ name: LOG_LEVEL, value: warn }]`. Set `envVars: { LOG_LEVEL: "debug" }` on the deployment. Assert that the rendered pod has `LOG_LEVEL=debug` and that the deployment timeline contains a warning entry naming `LOG_LEVEL` as overridden.

**Acceptance Scenarios**:

1. **Given** a chart that renders a container with `env: [{ name: LOG_LEVEL, value: warn }]` and an operator-set `envVars: { LOG_LEVEL: "debug" }`, **When** the deployment reconciles, **Then** the rendered pod's container has exactly one entry for `LOG_LEVEL` with value `debug`, and the deployment timeline contains a warning entry recording the override.
2. **Given** an environment where conflict detection cannot be wired at the patch layer (degradation path), **When** a collision occurs, **Then** the override still wins, a structured log entry is emitted, and the absence of the timeline warning does not block the feature.

---

### Edge Cases

- An operator sets a value at the per-value cap (64 KiB) — accepted; one byte beyond — rejected with a precise error.
- An operator submits the 101st key in a single scope's dict — rejected with a precise error citing the 100-entry limit.
- An operator submits a dict whose keys are valid but whose total serialized bytes exceed 256 KiB — rejected with a precise error.
- An operator submits an env var name that violates the regex (e.g., starts with a digit, contains a hyphen) — rejected with a precise error.
- An operator submits an empty value (`""`) — accepted; rendered pod has the env entry with an empty value.
- An operator submits two entries with the same name in a single scope's input list — rejected with a duplicate-name error before the dict is built.
- The driver is upgraded to a version that renames a component currently carrying per-component env vars — upgrade succeeds, block becomes `isOrphaned: true`, single timeline event emitted.
- The driver is upgraded back to a version that re-introduces the previously-orphaned component name — the previously-orphaned block becomes live again (`isOrphaned: false`) and its env vars apply on the next reconcile.
- A deployment carries an orphaned block and the operator does nothing — the block remains visible in the query and the timeline carries the original orphan event but no further events are emitted on subsequent reconciles.
- A deployment whose driver declares zero components has a deployment-level env var — every pod-template-bearing workload in the rendered release receives the env var.
- An operator attempts to set `envVars` for a component the current driver does not declare — mutation rejected with the list of known component names.
- A documented env var entry on the driver references `level: component` but provides an empty `components` list — driver registration fails.
- An operator stores a credential-shaped value (e.g., a long base64 string) in an env var — accepted (the platform does not detect "secrets"); the field-level documentation calls this out as unsupported and unsafe.

## Requirements *(mandatory)*

### Functional Requirements

#### Hierarchy & Resolution

- **FR-001**: The platform MUST allow free-form env vars (a string-to-string dictionary) to be set at the **environment**, **deployment**, and **per-component** scopes.
- **FR-002**: The platform MUST resolve effective env vars per component using **per-key deepest-wins** precedence: component overrides deployment overrides environment.
- **FR-003**: The platform MUST pre-compute the effective env var dict per component during config resolution (mirroring the existing scheduling resolver) so that downstream consumers receive a fully merged result.
- **FR-004**: When the driver declares no components, deployment-level env vars MUST apply broadly to every pod-template-bearing workload in the rendered release.
- **FR-005**: The platform MUST NOT support a cluster scope for env vars in v1.

#### Validation

- **FR-006**: Env var **names** MUST be validated against the regex `^[A-Za-z_][A-Za-z0-9_]*$`. Names that fail this check MUST be rejected at the GraphQL mutation boundary.
- **FR-007**: Env var **values** MUST allow any string, including the empty string. Each value MUST be capped at 64 KiB; values exceeding the cap MUST be rejected with a precise error.
- **FR-008**: Each scope's env var dict MUST be capped at 100 entries, and the dict's total serialized size MUST be capped at 256 KiB. Submissions exceeding either cap MUST be rejected with a precise error.
- **FR-008a**: The **resolved** (post-merge) env var dict per component MUST be capped at 256 KiB total. The sum of resolved per-component env var bytes across all components of a deployment MUST be capped at 1 MiB to leave headroom under the Kubernetes 1.5 MiB resource size limit (the deployment CRD context-embedding mechanism, ADR-006, carries the resolved config alongside other context). Resolution MUST fail with a precise error when either cap is exceeded; the failure MUST surface to the operator via the same error path as a mutation rejection so the operator can identify and trim the offending scope.
- **FR-009**: Within a single scope's input, duplicate names MUST be rejected with a precise error before the dict is constructed.
- **FR-010**: Component-level env vars whose target component is not declared by the deployment's current driver MUST be rejected at the GraphQL mutation boundary, and the error MUST list the driver's known component names.
- **FR-011**: The platform MUST NOT maintain a reserved-name blocklist for env var names in v1; documentation MUST call out the `PATH` / `LD_*` family as risky.

#### Driver-Side Documentation

- **FR-012**: Drivers MAY include a `spec.env_vars` block listing env vars the app respects. Each entry MUST carry a `name`, a free-text `description`, a `level` (`deployment` or `component`), and (when `level=component`) a non-empty `components` list.
- **FR-013**: The driver loader MUST validate `spec.env_vars` entries: the `name` MUST match the env var name regex, names within the list MUST be unique, `level=component` entries MUST have a non-empty `components` list, and every `components` reference MUST resolve to a component declared by the driver.
- **FR-014**: A driver whose `spec.env_vars` block fails any of the validations in FR-013 MUST fail to register; the error MUST identify the offending entry.
- **FR-015**: Driver-side documentation MUST NOT validate, default, or constrain user-set env var values in any way. It is purely informational.

#### GraphQL Surface

- **FR-016**: The GraphQL schema MUST add types `EnvVar`, `ComponentEnvVars`, `EnvVarInput`, `ComponentEnvVarsInput`, and a driver-side documentation type (`DriverEnvVarDoc` or equivalent).
- **FR-017**: `Deployment` MUST gain `envVars: [EnvVar!]!` and `componentEnvVars: [ComponentEnvVars!]!` query fields. `ComponentEnvVars` MUST expose `component`, `envVars`, and `isOrphaned`.
- **FR-018**: The driver type MUST gain a documentation field exposing `spec.env_vars` declarations.
- **FR-019**: Existing mutation inputs `deploy()` and `updateDeployment()` MUST gain optional fields for environment-, deployment-, and component-level env vars. **No new mutation MUST be added.**
- **FR-020**: The environment type and its mutation MUST gain an env vars field paralleling the deployment-side surface.
- **FR-021**: All env-var-bearing input lists MUST enforce the per-list invariants (no duplicate names within a scope) server-side at mutation handling, in addition to client-side conventions.

#### Storage

- **FR-022**: Env vars MUST merge into the existing environment-config and deployment-config Pydantic models (and the per-component config block within the deployment config) such that the resolved configuration flows through the existing pipeline without a parallel persistence path.
- **FR-023**: The storage shape MUST flow into the deployment CRD via the existing context-embedding mechanism (ADR-006); no env-var-specific operator/agent code path is required.

#### Post-Render Injection

- **FR-024**: The post-render injection layer MUST gain an `env_vars` flag in `PostRenderInjection`, three-valued (`None` inherits, `False` opts out, `True` is the default behaviour), matching the existing `affinity` / `resources` / `tolerations` / `runtime_class` pattern.
- **FR-025**: A new patch builder MUST emit deployment-level patches that apply broadly and component-level patches that narrow by the component's identifier label selector.
- **FR-026**: The patch builder MUST inject env entries into every container of the matched pod template. When a container already carries an env entry with the same name, the user-set value MUST replace the chart-rendered value.
- **FR-027**: The patch builder MUST detect chart-vs-user-env collisions during render and surface them as structured warnings to the agent layer; the agent layer MUST emit a deployment timeline warning per collision when feasible.
- **FR-028**: When timeline emission is not feasible (the conflict-detection path degrades), the warning MUST appear as a structured log entry and the feature MUST NOT block on it.

#### Upgrade Behaviour

- **FR-029**: A driver upgrade that renames or removes a component carrying per-component env vars MUST succeed; the platform MUST NOT block the upgrade.
- **FR-030**: After such an upgrade, the affected `ComponentEnvVars` block MUST be exposed in the query with `isOrphaned: true` and MUST NOT be injected into any rendered workload.
- **FR-031**: A single deployment timeline event MUST be emitted recording the orphan transition. The event is one-shot per upgrade transition; subsequent reconciles MUST NOT emit additional events for the same orphan.
- **FR-032**: When an operator removes an orphaned block via `updateDeployment`, the block MUST disappear from the query result on the next reconcile.
- **FR-033**: When a subsequent driver upgrade re-introduces a previously-orphaned component name, the previously-orphaned block MUST become live again (`isOrphaned: false`) and its env vars MUST be injected on the next reconcile.

#### Non-Goals (codified)

- **FR-034**: The platform MUST NOT provide a secret-typed env var variant in v1 (no `valueFrom.secretKeyRef`, no encrypted-at-rest storage, no UI masking).
- **FR-035**: The platform MUST NOT expose container-level granularity in v1; all containers in a matched pod template receive the same env entries.
- **FR-036**: The platform MUST NOT migrate or rewrite existing typed parameters into env vars.

### Key Entities

- **Env Var (`EnvVar`)**: A name/value pair representing a single environment variable to inject into rendered containers. The smallest atomic unit of the feature.
- **Component Env Vars (`ComponentEnvVars`)**: A bundle of env vars targeted at a single component, plus an `isOrphaned` flag indicating that the targeted component is no longer declared by the deployment's current driver.
- **Environment Env Var Configuration**: Env vars set at the environment scope, inherited by every deployment in the environment.
- **Deployment Env Var Configuration**: Env vars set at the deployment scope (a single dict applying to all of the deployment's components) and at the per-component scope (a list of `ComponentEnvVars`).
- **Driver Env Var Documentation (`DriverEnvVarDoc`)**: A doc-only declaration of an env var the driver's app respects, with `name`, `description`, `level`, and (for `level=component`) `components` references. Surfaces in the driver detail view; does not affect runtime injection.
- **PostRenderInjection — `env_vars` flag**: A new three-valued flag governing whether the post-renderer injects env vars into a given component's containers.
- **Deployment Timeline Event — Env Var Orphan**: A one-shot event emitted when a driver upgrade orphans a per-component env var block.
- **Deployment Timeline Event — Env Var Conflict Warning**: A warning event emitted (best-effort) when an operator-set env var collides with a chart-rendered env entry of the same name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can set an env var on a single deployment via the API and see it on every pod container of that deployment within one reconcile cycle, with no driver change required.
- **SC-002**: An env var set at the environment scope propagates to every deployment in that environment without any per-deployment edit; an env var set at the deployment scope or component scope overrides the environment value on a per-key basis on the targeted scope only.
- **SC-003**: 100% of mutations that submit invalid env var names, oversized values or dicts, or duplicate names within a scope are rejected at the API boundary with a precise error message that names the offending entry and the rule it violated.
- **SC-004**: 100% of mutations that target a component the deployment's current driver does not declare are rejected with an error that lists the driver's known component names.
- **SC-005**: A driver upgrade that renames or removes a component carrying per-component env vars succeeds in the same end-to-end time as an upgrade with no env vars set; the orphaned block is visible in the query result with `isOrphaned: true` and a single timeline event records the transition.
- **SC-006**: A component flagged with `inject_env_vars=False` retains its chart-rendered env entries unchanged across reconciles, while peer components in the same deployment continue to receive operator-set env vars.
- **SC-007**: When an operator-set env var collides with a chart-rendered env entry of the same name, the operator-set value is observable on the rendered pod and a warning entry is observable in the deployment timeline (or, when timeline emission degrades, a structured log entry exists).
- **SC-008**: The driver detail view exposes documented env vars grouped by scope (deployment-wide vs per-component) for any driver that ships a `spec.env_vars` block; drivers whose block fails validation cannot register.
- **SC-009**: The end-to-end scenario covering deployment-level + component-level env vars (with collision behaviour) passes against a real cluster as part of the feature's E2E suite, marked `api_only`.
- **SC-010**: A GraphQL propagation test exists for every new field and argument introduced by the feature, per the project's mandatory propagation-test rule.

## Assumptions

- The existing `ResolvedConfig` pipeline is the right substrate for env var resolution; no parallel resolution system is introduced (per Implementation Decision §"Boundary against parameters" and Further Notes in the PRD).
- The deployment CRD context-embedding mechanism (ADR-006) carries the resolved env vars to the operator/agent layer; no env-var-specific reconcile-loop wiring is required.
- The post-render injection mechanism's existing patterns (`affinity`, `resources`, `tolerations`, `runtime_class`) are the right shape for the new flag and patch builder; the feature uses the same three-valued `PostRenderInjection` semantics.
- Component identification at the patch layer relies on the existing component identifier label selector; no new label scheme is introduced.
- Conflict detection runs at render time (after Helm rendering, before the agent applies the manifest); a render-time path is sufficient because the operator-set value wins regardless of detection success.
- "Per-value cap 64 KiB", "per-scope dict 100 entries", and "per-scope dict 256 KiB total" are reasonable defaults for the size limits and do not require external clarification. They are tunable via configuration if a real workload demands it; v1 ships hard-coded.
- The feature does not require frontend UI work in v1 (the driver detail field is queryable via the API; UI editing surfaces are explicitly out of scope per the PRD).
- A separate ticket for the secret-typed env var variant will be filed before this ships; the data model in v1 leaves no plaintext-disguised-as-secret door open.
- The feature is an ADR candidate (likely `adr-019-deployment-env-vars`); the ADR is drafted alongside the implementation, not in this spec.
