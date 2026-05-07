# Feature Specification: Environment-Config Update with Deployment Fanout

**Feature Branch**: `009-environment-update`
**Created**: 2026-05-07
**Status**: Draft
**Input**: User description: Replace the JSON-blob `updateEnvironment(environmentId, config: JSON)` mutation introduced in 008-deployment-env-vars with a structured GraphQL surface, fan out a redeploy to every deployment in the environment when the config changes, expose the full environment configuration to the frontend, and add a UI form for editing environment-scope env vars.

This feature is the sequel to 008-deployment-env-vars. It assumes the post-008 baseline: `Environment.config` carries a structured Pydantic model that includes env vars, ip_whitelist, dedicated_ingress, scheduling, fqdn_suffix, external_url_scheme, external_url_port, and external_dns_endpoints_type.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Environment-config updates redeploy every deployment in the environment (Priority: P1)

An operator changes a value in the environment's configuration — typically an environment-scope env var, an IP allowlist entry, or a scheduling override — and expects every running deployment in that environment to converge to the new desired state without per-deployment intervention. Today (post-008) the environment row updates in storage, but existing deployments don't pick up the change until their next reconcile is triggered for some other reason. This story closes that gap: every deployment in the environment is redeployed on the same logical operation, with a timeline entry on each deployment recording the env-config change as the trigger.

**Why this priority**: This is the core correctness fix. Without it, the typed `UpdateEnvironmentInput` (US2) and the frontend env-var form (US4) are misleading — the operator believes their change is live when in fact it is stranded in storage waiting for a reconcile. The redeploy fanout is the load-bearing behaviour the rest of the feature depends on.

**Independent Test**: Set `OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.staging` at the environment scope on a `staging` environment containing three deployments. Within one reconcile cycle of the mutation completing, every pod across all three deployments carries the new env entry. Each deployment's timeline shows a fresh entry recording the env-config update as the cause.

**Acceptance Scenarios**:

1. **Given** an environment containing three deployments (A, B, C), **When** the operator updates the environment's env vars to add `OTEL=https://otel.staging`, **Then** within one reconcile cycle every pod of A, B, and C carries `OTEL=https://otel.staging`, and each deployment's timeline lists a new entry whose context-diff records the env-config change.
2. **Given** an environment containing two deployments where deployment A would render successfully and deployment B would hit a deliberate render failure under the new config, **When** the operator updates the env config, **Then** the env-config row persists, deployment A converges to the new config, deployment B's timeline records a failed Task linked to the env-config update, and the mutation result is success (the failure on B does not roll back A's update or the persisted env-config row).
3. **Given** an environment with zero deployments, **When** the operator updates the env config, **Then** the env-config row persists, no fanout Tasks are dispatched, and the mutation returns success.
4. **Given** the operator submits an env-config update that is byte-for-byte identical to the persisted env-config (a no-op edit), **When** the mutation runs, **Then** the env-config row is updated with the same content, but the platform skips the redeploy fanout (no spurious timeline entries on deployments).

---

### User Story 2 - Structured `UpdateEnvironmentInput` GraphQL input (Priority: P1)

An API consumer (SDK user, GraphiQL user, frontend developer) constructing an environment-config update wants the mutation input to be **typed and self-documenting**, not a free-form JSON blob. The input must mirror the field shape of the underlying environment-config model: env vars as `[EnvVarInput!]`, IP allowlist as `[String!]`, dedicated ingress as a typed input, scheduling as a typed input, FQDN/external-DNS settings as their respective scalar types. The input is **full-replacement**: the input represents the complete desired config; any field not provided is unset on the persisted row.

**Why this priority**: Without the typed input, US3 and US4 (frontend) cannot generate type-safe SDK code, and SDK consumers cannot discover the writable surface from the schema. JSON-blob inputs also bypass static type checking, leaving validation entirely to runtime — which has historically caused error-code-collapse bugs (see 008-deployment-env-vars review history). Shipping the typed input alongside the redeploy fanout is the right pairing because both load-bearing changes touch the same write path.

**Independent Test**: A GraphiQL user composes an `updateEnvironment(environmentId: ..., input: { envVars: [{name: "OTEL", value: "https://otel.staging"}], ipWhitelist: ["10.0.0.0/8"] })` mutation entirely from the schema's introspection (no JSON-blob fallback). The SDK's regenerated client method accepts a typed `UpdateEnvironmentInput` Pydantic model. Submitting an invalid env var name returns the precise typed error code (`INVALID_ENV_VAR_NAME`), not a generic `INVALID_CONTEXT`.

**Acceptance Scenarios**:

1. **Given** the GraphQL schema after this feature ships, **When** an introspection query lists the `Mutation` type, **Then** `updateEnvironment` accepts an `input: UpdateEnvironmentInput!` argument and `config: JSON` is no longer present.
2. **Given** the typed input is full-replacement, **When** the operator submits an input that omits the `ipWhitelist` field while the persisted row has a non-empty allowlist, **Then** the persisted allowlist is cleared (set to its empty/unset state). Operators editing one field must read the existing config first and re-submit the unchanged fields, or use a future incremental-update mutation when one exists.
3. **Given** the typed input contains an invalid env var name (e.g., `1invalid`), **When** the mutation is submitted, **Then** the response carries one error with `extensions.code = "INVALID_ENV_VAR_NAME"` and a payload identifying the offending name.
4. **Given** the SDK is regenerated after the schema change, **When** a Python SDK consumer calls `client.environments.update(environment_id, input=UpdateEnvironmentInput(...))`, **Then** the call accepts a typed Pydantic model whose fields mirror `EnvironmentConfig`'s shape; the old `config: JSON` parameter is no longer in the SDK API.

---

### User Story 3 - Environment detail page renders the full environment config (Priority: P2)

An operator browsing the platform's frontend wants to inspect everything an environment carries — its env vars, IP allowlist, dedicated ingress configuration, scheduling overrides, FQDN/external-DNS settings — without dropping into the SDK or GraphiQL. The environment detail page surfaces all of these in a structured layout, grouped by section, read-only. This sets the visual contract that US4 will edit on top of.

**Why this priority**: Visibility before editability. The operator needs to see the current state of the environment before they can usefully change it. Read-only first cut also catches data-shape mismatches (e.g., a future field added to `EnvironmentConfig` that the page hasn't been updated to render) before the form-edit story (US4) makes them harder to spot. P2 because the API surface (US1+US2) is the headline value; the UI is the operator-facing wrapper.

**Independent Test**: An operator navigates to the environment detail page for a `staging` environment with one deployment-level env var, two IP allowlist entries, a dedicated-ingress configuration, and a scheduling override on `pod_affinity`. Every value is visible on the page in its respective section without further clicks. A second environment with no overrides displays an empty/default state in each section without crashing.

**Acceptance Scenarios**:

1. **Given** a `staging` environment with `env_vars: { OTEL: "https://otel.staging", FOO: "bar" }`, **When** the operator opens the environment detail page, **Then** an "Environment Variables" section lists both entries with name and value visible.
2. **Given** an environment with `ip_whitelist: ["10.0.0.0/8", "192.168.0.0/16"]`, **When** the operator opens the page, **Then** an "IP Allowlist" section shows both CIDRs.
3. **Given** an environment with no scheduling overrides set, **When** the operator opens the page, **Then** a "Scheduling" section displays explicitly that no overrides are configured (not a blank panel and not an error).
4. **Given** an environment with a `dedicated_ingress` configuration, **When** the operator opens the page, **Then** a "Dedicated Ingress" section shows the configured fields.

---

### User Story 4 - Form on the environment detail page to edit env vars (Priority: P2)

The operator wants to add, edit, or remove environment-scope env vars from the environment detail page. The form provides one row per env var (name + value text inputs), with add/remove buttons. Client-side validation rejects bad names (regex), oversized values, oversized dicts, and duplicate names before submission. On submit, the operator is shown a confirmation that the change will redeploy every deployment in the environment (per US1), and after confirmation the form posts the change and refreshes the page state. The form does NOT yet pull autocomplete suggestions from drivers' `spec.env_vars` declarations — that's a P3/post-v1 enhancement.

**Why this priority**: This is the operator-facing write surface for the most common environment-config change in practice (env var edits). Without it, operators must use the SDK or GraphiQL to flip a `LOG_LEVEL`. Shipping it once the read view (US3) is in place is natural — the UI shape is already established. P2 because the API surface (US1+US2) handles the contract; the form is the convenience wrapper.

**Independent Test**: An operator opens the environment detail page, adds an env var (`OTEL=https://otel.staging`), removes a stale entry (`DEPRECATED_FLAG`), edits an existing value (`LOG_LEVEL: info → debug`), and clicks Save. The confirmation dialog explicitly names the deployments that will be redeployed. After confirming, the form refreshes; the new env var rows match the operator's edits; navigating to one of the affected deployment's detail pages shows a fresh timeline entry recording the env-config change.

**Acceptance Scenarios**:

1. **Given** an empty Environment Variables form, **When** the operator clicks "Add Variable" and types `name=LOG_LEVEL`, `value=debug`, **Then** the row is added to the form's local state but not yet submitted.
2. **Given** the operator types `name=1invalid` (regex violation), **When** the form is submitted or the field is blurred, **Then** the form displays an inline error for that row identifying the regex requirement, and the submit button is disabled until the row is fixed or removed.
3. **Given** the operator types two rows with identical names, **When** the form is submitted or the second row is blurred, **Then** the form displays an inline error on the duplicate row, and the submit button is disabled until one is renamed or removed.
4. **Given** the form contains a valid edit and the operator clicks Save, **When** the confirmation dialog appears, **Then** the dialog explicitly names the deployments that will be redeployed (or states "no deployments are currently in this environment" when the count is zero).
5. **Given** the operator confirms the redeploy, **When** the form submits, **Then** the page refreshes; the new env var rows reflect the submitted state; affected deployment detail pages each show a fresh timeline entry for the env-config update.
6. **Given** the operator submits a valid edit on an environment with zero deployments, **When** the confirmation dialog appears, **Then** the dialog states no deployments will be redeployed; on confirm the form refreshes and the env-config row updates.
7. **Given** the operator's submission fails for any reason (network, server error), **When** the form receives the error, **Then** the form remains in its edited (unsaved) state with an error notice; the operator can retry without re-typing.

---

### Edge Cases

- An operator submits an env-config update while a previous redeploy fanout for the same environment is still in progress — the new fanout starts as soon as the prior batch's Tasks have been dispatched (or fails with a clear contention error if the platform cannot dispatch overlapping fanouts; see Assumptions).
- An operator submits a typed `UpdateEnvironmentInput` whose `envVars` is empty `[]` while the persisted row has env vars set — the persisted env vars are cleared and every deployment in the environment redeploys with the env vars removed.
- A deployment in the environment is currently being deleted (in tombstone state) — it is excluded from the redeploy fanout (no Task dispatched for a deployment that is going away).
- A deployment in the environment is internally-managed (e.g., the platform's ingress controller) — it is excluded from the redeploy fanout to avoid recursive control-plane churn.
- The mutation is submitted with an `environmentId` that does not exist — rejected at the GraphQL boundary with an `ENVIRONMENT_NOT_FOUND` error; no env-config row is touched and no fanout Tasks are dispatched.
- The operator submits a no-op update (input byte-for-byte identical to persisted state) — the env-config row is updated (potentially incrementing an updated-at timestamp) but no redeploy Tasks are dispatched.
- A per-deployment redeploy Task in the fanout fails due to a render error — the env-config row remains updated, that deployment's timeline records the failed Task, peer deployments are unaffected.
- The frontend form is submitted while another operator concurrently updates the same environment — the typed full-replacement input means whichever submission lands second wins; the platform does not implement optimistic concurrency control in v1 (no `If-Match` or version field).
- The frontend page is opened while a fanout is mid-flight — the displayed config reflects the persisted desired state (the env-config row, just updated); deployments may briefly show pre-fanout state in their pod-status sections until reconciles complete.

## Requirements *(mandatory)*

### Functional Requirements

#### Mutation Surface

- **FR-001**: The platform MUST replace the `updateEnvironment(environmentId: UUID!, config: JSON)` mutation with `updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!)`. The `config: JSON` argument MUST NOT be present in the post-feature schema.
- **FR-002**: `UpdateEnvironmentInput` MUST mirror the full field shape of the persisted environment configuration model: `envVars: [EnvVarInput!]`, `ipWhitelist: [String!]`, `dedicatedIngress: DedicatedIngressInput`, `scheduling: SchedulingInput`, `fqdnSuffix: String`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`. Where the underlying field is itself a typed object (dedicated_ingress, scheduling), the input MUST use the corresponding typed Strawberry input.
- **FR-003**: The mutation input MUST be **full-replacement**: the input represents the complete desired environment configuration. Any field not provided in the input MUST be persisted as its unset state. Operators editing one field MUST read the existing config and re-submit the unchanged fields. (A future incremental-update mutation may be added; out of scope for v1.)
- **FR-004**: The mutation MUST validate the input through the same Pydantic-driven validation pipeline that the JSON-blob path used (see 008-deployment-env-vars), preserving precise error codes at the GraphQL boundary (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, plus any other typed errors raised by the underlying validators).
- **FR-005**: The SDK Python client MUST regenerate to expose `client.environments.update(environment_id, input=UpdateEnvironmentInput(...))`. The old `config: JSON` SDK parameter MUST be removed.

#### Redeploy Fanout

- **FR-006**: After persisting a non-no-op env-config update, the platform MUST dispatch a redeploy Task for every deployment in the environment that is not tombstoned and not internally-managed. Each Task MUST result in a new `ApplicationInstance` version recorded against its deployment.
- **FR-007**: Each redeploy MUST surface as a fresh entry on the affected deployment's timeline, with the entry's context diff recording the env-config change as the trigger.
- **FR-008**: A redeploy Task that fails (render error, validation error, or any other reason) MUST NOT roll back the env-config row update. The failure MUST be recorded on that deployment's timeline / Task entry, and peer deployments' Tasks MUST proceed independently.
- **FR-009**: The mutation MUST return success once the env-config row is persisted and the fanout Tasks are dispatched, regardless of the eventual outcome of those Tasks. The mutation result MUST NOT block on Task completion.
- **FR-010**: When the submitted input is byte-for-byte identical to the persisted env-config (a no-op edit), the platform MUST persist the row but MUST NOT dispatch redeploy Tasks (no spurious timeline entries on deployments).
- **FR-011**: When the environment contains zero deployments at fanout time, the mutation MUST persist the env-config row and return success without dispatching any Tasks.
- **FR-012**: The platform MUST exclude tombstoned deployments (those in deletion-pending state) from the redeploy fanout to avoid resurrecting deployments that are going away.
- **FR-013**: The platform MUST exclude internally-managed deployments (e.g., the ingress controller deployment, marked `internal=True`) from the redeploy fanout to avoid recursive control-plane churn. Internally-managed deployments resolve env config through the same channel but their reconcile cadence is the platform's responsibility, not the operator's.

#### Frontend — Environment Detail Page (Read)

- **FR-014**: The frontend MUST provide an environment detail page that renders the full environment configuration from `Environment.config` (or its typed projection). The page MUST display sections for env vars, IP allowlist, dedicated ingress, scheduling, FQDN suffix, and external URL / external-DNS settings.
- **FR-015**: Each section MUST handle the empty/unset case gracefully — displaying an explicit "no overrides set" message rather than a blank panel or error — so the operator can distinguish "no overrides" from "page didn't load".
- **FR-016**: The page MUST refresh its displayed config after a successful US4 form submission, so the operator immediately sees the updated state.

#### Frontend — Env Var Edit Form (Write)

- **FR-017**: The environment detail page MUST include a form for editing environment-scope env vars. The form MUST allow the operator to add new rows, edit existing rows, and remove rows.
- **FR-018**: The form MUST perform client-side validation mirroring the backend rules: name regex `^[A-Za-z_][A-Za-z0-9_]*$`, per-value cap 64 KiB, per-scope dict cap 100 entries / 256 KiB total, no duplicate names within the form. Invalid rows MUST display inline errors and MUST disable the submit button until corrected.
- **FR-019**: On submit, the form MUST display a confirmation dialog that explicitly names the count of deployments in the environment that will be redeployed (per US1). When the count is zero, the dialog MUST state that no deployments will be redeployed.
- **FR-020**: After the operator confirms, the form MUST submit through the typed `updateEnvironment(input: UpdateEnvironmentInput!)` mutation (not via raw GraphQL or JSON blob). The full env-config replacement input MUST carry the existing values for fields the form does not touch (env vars are the only field this v1 form edits; IP allowlist, scheduling, etc. ride through unchanged).
- **FR-021**: On submit failure (network error, server error, validation rejection from the server), the form MUST remain in its edited state with an error notice and MUST allow the operator to retry without re-typing.
- **FR-022**: The form MUST NOT yet implement env-var-name autocomplete from drivers' `spec.env_vars` declarations. This is a deliberate post-v1 enhancement.

#### Documentation & Telemetry

- **FR-023**: The platform MUST emit one structured log entry per fanout dispatch, recording the environment ID, the count of deployments enqueued, and whether the update was a no-op. This is the operational observability anchor for fanout debugging.
- **FR-024**: The deprecated `config: JSON` argument MUST NOT remain in the schema, the SDK, or the documentation after this feature ships. CI MUST fail if any reference to it is reintroduced.

### Key Entities

- **Environment Configuration (`EnvironmentConfig`)**: the typed Pydantic model carrying the environment's desired state (env vars, IP allowlist, dedicated ingress, scheduling, FQDN/external-DNS settings). Already exists post-008; this feature exposes it through a typed GraphQL input.
- **Update Environment Input (`UpdateEnvironmentInput`)**: the GraphQL input mirror of `EnvironmentConfig`, full-replacement semantics.
- **Redeploy Fanout**: the dispatch of one redeploy Task per non-excluded deployment in the environment, triggered by a non-no-op env-config update.
- **Per-deployment Redeploy Task**: an existing Task type — the same machinery that drives `updateDeploymentVersion` and similar — instantiated once per deployment in the fanout.
- **Environment Detail Page**: a frontend route rendering the full environment configuration, including the env vars edit form.
- **Env Vars Edit Form**: a sub-component of the environment detail page that mediates the operator's env var edits and their submission through the typed mutation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can update environment-scope env vars and see the new value on every pod of every non-excluded deployment in the environment within one reconcile cycle of the mutation completing, with no per-deployment intervention required.
- **SC-002**: 100% of environment-config updates that succeed at the API boundary persist the env-config row before any fanout Task is dispatched. A fanout Task failure on one deployment never rolls back the env-config row or affects peer deployments' Tasks.
- **SC-003**: 100% of mutations that submit invalid env var inputs (regex violations, oversized values or dicts, duplicate names) are rejected at the GraphQL boundary with the precise typed error codes from 008-deployment-env-vars (`INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`) — no `INVALID_CONTEXT` collapse.
- **SC-004**: A no-op env-config update (input byte-for-byte identical to persisted state) results in zero redeploy Tasks and zero new timeline entries on any deployment.
- **SC-005**: The GraphQL schema after this feature ships exposes `updateEnvironment(environmentId, input: UpdateEnvironmentInput!)` with no remaining `config: JSON` argument anywhere in the public schema, SDK, or generated frontend types.
- **SC-006**: The Python SDK exposes a typed `client.environments.update(environment_id, input=UpdateEnvironmentInput(...))` method whose argument shape is the regenerated Pydantic mirror of `UpdateEnvironmentInput`.
- **SC-007**: An operator can navigate to an environment detail page and read every field of the environment's configuration (env vars, IP allowlist, dedicated ingress, scheduling, FQDN/external-DNS settings) without dropping into the SDK or GraphiQL.
- **SC-008**: An operator can add, edit, or remove environment-scope env vars from the frontend form. Submission triggers an explicit confirmation dialog naming the count of deployments that will be redeployed; on confirm, the page refreshes with the new state and affected deployments show fresh timeline entries.
- **SC-009**: 100% of new GraphQL fields and arguments introduced by this feature are covered by a propagation test that hits the real service and repository layers, per Constitution §V.
- **SC-010**: An end-to-end scenario covering US1 (env-config update fans out to all deployments) passes against a real cluster as part of the feature's E2E suite. A second end-to-end scenario covers US1's failure-isolation requirement (one deployment in a multi-deployment environment hits a deliberate render-fail; the env-config update still persists; the other deployments still converge).

## Assumptions

- The post-008 `EnvironmentConfig` Pydantic model is the source of truth for the environment-config schema. This feature does NOT add new fields to `EnvironmentConfig` — it exposes the existing fields through a new mutation input.
- The platform's existing per-deployment redeploy Task machinery (used by `updateDeploymentVersion`, etc.) is the right substrate for the fanout. No new Task type is introduced; the fanout is N invocations of the existing machinery.
- The platform does NOT implement optimistic concurrency control on environment updates in v1 (no `If-Match` header or version field). Concurrent submissions of `updateEnvironment` against the same environment race; whichever lands second wins. If concurrency control becomes load-bearing it is a separate feature.
- Per-deployment redeploy Task failure semantics already exist on the platform — Tasks already track success/failure independently. This feature relies on that machinery rather than introducing a new failure-isolation primitive.
- The platform's frontend already has a routing skeleton for environment detail (or can have one added trivially). This feature adds content to that route; it does not redesign the navigation.
- The frontend's existing GraphQL client is the channel for the mutation. The form constructs an `UpdateEnvironmentInput` from the persisted config + the operator's edits and submits through the SDK / generated client.
- A "no-op" env-config update is determined by comparing the canonical-serialized form of the input against the canonical-serialized persisted config. Implementations may choose either a deep-equal Pydantic comparison or a JSON-canonicalized hash; either is acceptable as long as the result is stable across encoding orderings.
- The existing `Environment.config` GraphQL projection (read side) is already typed enough to support US3's read view. If projection gaps are discovered during implementation, those projections become part of US3's scope; new top-level Environment query fields are out of scope.
- "Internally-managed deployments" refers to the existing `Deployment.internal: Boolean!` flag (set by the platform on resources like the dedicated ingress controller). Excluding `internal=True` deployments from the fanout is the same exclusion already applied by `updateDeployment` / `deleteDeployment`.
- Frontend client-side validation is a UX convenience, not a security boundary. The backend MUST still validate every input independently — the operator is the trust boundary, and the form is just one of many possible clients.
- Concurrency on overlapping fanouts is handled by the existing Task machinery's serialization per deployment; an in-flight redeploy Task on deployment A does not block US1's mutation but does mean A's eventual reconcile picks up whichever desired-state was persisted last. Operators submitting rapid back-to-back env updates accept this race.
