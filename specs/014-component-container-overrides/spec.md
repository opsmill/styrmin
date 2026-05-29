# Feature Specification: Component-Scope `command` / `args` Overrides

**Feature Branch**: `014-component-container-overrides`
**Created**: 2026-05-28
**Status**: Draft
**Input**: Idea brief — component-scope overrides for a container's `command` and `args` on application deployments, following the deployment env-vars precedent (#4 / #209). Source issue: [opsmill/styrmin#283](https://github.com/opsmill/styrmin/issues/283).

## User Scenarios & Testing *(mandatory)*

The primary actor is the **deployment operator** — the persona who today edits a deployment (via SDK, CLI, or frontend) to change parameters or environment variables. The secondary actor is the **driver author**, who opts a component's `command` / `args` into being overridable.

Today the only way to change a container's entrypoint (`command`) or argument list (`args`) is to fork the application driver — edit the Helm chart and re-publish a new driver version. Legitimate operator-side reasons to change these (a debug entrypoint, a feature-flag CLI argument, `--max-connections=…`, swapping a CLI into worker mode) all currently demand a driver fork. This feature lets an operator set `command` / `args` on a single **component** of a deployment, scoped to that deployment only, without any driver fork.

### User Story 1 - Override `args` on a single component (Priority: P1)

A deployment operator needs to change the argument list of one component's container on a single running deployment — for example, raising the log level for debugging — without forking the driver or editing its chart. The operator sets `args` on the `server` component of the deployment; on the next reconcile, that component's container runs with the new argument list.

**Why this priority**: This is the core problem the feature exists to solve and the headline value. Shipping just this one slice already removes the "fork the driver to change args" pain for the most common case. Without it, the only escape hatch is a cross-team driver change or a driver fork.

**Independent Test**: Deploy a single-component app whose driver has wired the override, set `args=["--log-level=debug"]` on the `server` component via the update-deployment mutation (or its UI/CLI equivalent), confirm the redeploy, and verify that the rendered pod's container reports `args == ["--log-level=debug"]`. No driver change is required.

**Acceptance Scenarios**:

1. **Given** a deployment exists with a driver-wired `server` component and no override set, **When** the operator submits a component override of `args=["--log-level=debug"]` for `server` and confirms the redeploy, **Then** a new instance is generated, reconciliation plans the deployment update, and the `server` pod restarts with its container's `args` equal to `["--log-level=debug"]`.
2. **Given** the override above is applied, **When** the operator reads the deployment back, **Then** the stored `args` override on `server` is returned exactly as submitted.
3. **Given** an override that has not changed, **When** an unrelated reconcile runs, **Then** the override continues to apply and no spurious restart is caused by the override itself.

---

### User Story 2 - Override `command` independently of `args` (Priority: P2)

The same operator needs to swap a component's entrypoint for a one-off run (for example, `python -m foo.cli worker` instead of the default `serve`), while leaving any previously set `args` untouched. `command` and `args` are independent slots: setting one must not disturb the other, and leaving one unset must let the chart default flow through.

**Why this priority**: Entrypoint swaps are a real operator need (worker-mode swaps, alternate CLIs), but they are less frequent than argument tweaks and build directly on the US1 plumbing. Independence between the two fields is the property that makes partial edits safe.

**Independent Test**: On a deployment that already has `args` set on `server`, set `command=["python", "-m", "foo.cli", "worker"]` on the same component and leave `args` unspecified. Verify the rendered pod runs with the new `command` **and** still carries the previously set `args`.

**Acceptance Scenarios**:

1. **Given** a deployment with `args` already set on `server`, **When** the operator sets `command=["python", "-m", "foo.cli", "worker"]` on `server` and does not touch `args`, **Then** the rendered pod runs with the new `command` and the previously set `args` unchanged.
2. **Given** a component with `command` set but `args` left unset, **When** the deployment reconciles, **Then** the container's `args` fall through to the chart default (no override applied for the unset field).
3. **Given** a component with both `command` and `args` set, **When** the deployment reconciles, **Then** the container runs with both overrides applied.

---

### User Story 3 - Clear an override and fall back to the chart default (Priority: P2)

An operator decides an override was a mistake and removes it. The component must redeploy with the driver's default `command` / `args` as if the override had never been set. Clearing is an explicit, distinct operation from "set to empty".

**Why this priority**: An override that cannot be cleanly removed is a trap — operators must be able to return a component to its driver-defined baseline. It is P2 because it only matters once US1/US2 are in use, but it is part of the same minimal usable loop.

**Independent Test**: On a deployment with `args` set on `server`, clear the override (submit a null value for `args`, or omit the `args` field — distinct from omitting the whole `server` component entry, which would clear every field on it), confirm the redeploy, and verify the rendered pod's container uses the chart's default `args` and carries no override.

**Acceptance Scenarios**:

1. **Given** a deployment with `args` set on `server`, **When** the operator clears `args` (null / omit) and confirms the redeploy, **Then** the next instance carries no `args` override and the chart's default `args` reach the pod.
2. **Given** a component with both `command` and `args` set, **When** the operator clears only `args`, **Then** `command` remains overridden and only `args` falls back to the chart default.
3. **Given** an override has been cleared, **When** the operator reads the deployment back, **Then** the cleared field is absent from the returned overrides.

---

### User Story 4 - Safe rejection of invalid overrides (Priority: P2)

When an operator submits an override that cannot be honoured — targeting a component the driver does not declare, an empty list, or a list containing a non-string entry — the platform must reject it at the point of submission with a precise, typed error, **before** any redeploy is triggered. No instance is generated and no container is restarted on rejection.

**Why this priority**: This is the safety boundary for US1–US3. A malformed override that slipped through to reconciliation could restart a workload into a broken state. Rejecting early, with a clear message, is what makes the feature safe to expose. It is P2 because it guards the write path that the P1 story depends on.

**Independent Test**: Against a deployment whose driver declares `server`, submit (a) an override for a component named `ghost` and assert a typed unknown-component error listing the driver's known components; (b) `args=[]` and assert a typed empty-list error; (c) `args=[123]` (a non-string entry) and assert a typed malformed-entry error. In every case assert that no redeploy was triggered.

**Acceptance Scenarios**:

1. **Given** a driver that declares only `server`, **When** the operator submits an override targeting a component name not declared by the driver, **Then** the mutation is rejected with a typed unknown-component error naming the driver's known components, and no reconcile is planned.
2. **Given** any component, **When** the operator submits `command=[]` or `args=[]` (an empty list), **Then** the mutation is rejected with a typed invalid-`command` / invalid-`args` error, and no reconcile is planned. (An explicit clear is null / omit, not an empty list.)
3. **Given** any component, **When** the operator submits a `command` or `args` list containing a non-string entry, **Then** the mutation is rejected with the corresponding typed error identifying the offending field.
4. **Given** a `command` or `args` list that contains an empty string element (e.g. `["sh", "-c", ""]`), **When** the operator submits it, **Then** the override is accepted (empty string elements are valid, mirroring the Kubernetes container API).

---

### User Story 5 - Orphaned override visibility after a driver upgrade (Priority: P3)

When a driver upgrade renames or removes a component, an operator's previously-set override on that component becomes orphaned. The upgrade must not be blocked by the stale override, the orphaned override must remain **visible** (rather than silently disappear) so the operator can audit and clean it up, and it must **not** reach any pod. This intentionally mirrors the env-vars orphan-tracking behaviour.

**Why this priority**: This is the operational safety net for component-scoped overrides. Without it, a routine driver upgrade would either fail (bad UX) or silently strand operator-set config (worse — the operator believes the override applies when it does not). It is P3 because it only matters after US1/US2 are in use and a driver upgrade changes the component set.

**Independent Test**: Deploy a driver v1 with a `server` component, set an `args` override on `server`, then upgrade to a driver v2 in which `server` has been renamed or removed. Assert that the upgrade succeeds, that reading the deployment's overrides returns the `server` block flagged as orphaned, and that the rendered pods carry no override from the orphaned block.

**Acceptance Scenarios**:

1. **Given** a deployment with an override on `server`, **When** the deployment is upgraded to a driver version that no longer declares `server`, **Then** the upgrade succeeds and the stored override block is preserved.
2. **Given** the upgrade above, **When** the operator reads the deployment's overrides, **Then** the `server` block is returned flagged as orphaned, carrying only its stored values.
3. **Given** an orphaned override block, **When** the deployment reconciles, **Then** the renderer skips the orphaned block and no override from it reaches any container.
4. **Given** an orphaned override block, **When** the operator removes it via the standard update-deployment flow, **Then** the block disappears from subsequent reads.

---

### User Story 6 - Driver author declares and wires an overridable component (Priority: P3)

A driver author wants to make a component's `command` / `args` overridable and to document which container the override targets, so operators can discover the capability before setting an override. The author adds a doc-only declaration block to the driver spec and wires the override-consuming filters into the chart templates. The declaration is informational — the platform does not require that a declared component actually consume the override, mirroring the env-vars documentation policy.

**Why this priority**: Operator-facing value (US1–US5) is delivered against drivers that have already wired the override; the authoring surface is what lets new drivers opt in. It is P3 because the override mechanism functions without it for already-wired drivers, but it ships in v1 so authors have a documented, supported path.

**Independent Test**: Author a driver whose spec includes a doc-only `command` / `args` declaration block on `server` and wires the override-consuming filters into the chart. Materialise the driver version and assert the declaration appears on it. Deploy, set an override, and confirm it reaches the pod. Then confirm a driver that declares but does not wire the filters stores the override and silently never applies it (no error).

**Acceptance Scenarios**:

1. **Given** a driver spec containing a doc-only `command` / `args` declaration block per component, **When** the driver version is materialised, **Then** the declaration is present on the resulting driver version and visible to consumers.
2. **Given** a driver that declares an overridable component **and** wires the override-consuming filters into its chart, **When** an operator sets an override and the deployment reconciles, **Then** the override reaches the component's container.
3. **Given** a driver that declares an overridable component but does **not** wire the filters into its chart, **When** an operator sets an override, **Then** the override is stored without error and never reaches the pod (silent no-op, matching the env-vars consumption contract).

---

### Edge Cases

- **Unknown component on write** → typed error at the mutation boundary; no reconcile, no pod restart (US4).
- **Component renamed/removed by a driver upgrade** → stored override preserved, surfaced as an orphan on read, skipped by the renderer; read-vs-write asymmetry is by design (US5).
- **Driver hasn't wired the filters** → override stored but never reaches the pod (silent, identical to env-vars consumption per ADR-013) (US6).
- **Override set, then driver rolled back to a version predating the filter** → same silent no-op as above.
- **Multi-container component** → the platform exposes exactly one resolved `command` and one resolved `args` per component; the driver author chooses which container in the rendered chart the override lands on. Targeting a non-default container in a multi-container pod is **out of scope for v1**.
- **Concurrent updates both setting `args` on the same component** → standard last-writer-wins on the deployment's stored config; no special merge.
- **Empty list (`command=[]` / `args=[]`)** → rejected at validation; an explicit clear is null / omit (US4).
- **Empty string inside the list (`["sh", "-c", ""]`)** → accepted (mirrors the Kubernetes container API) (US4).
- **`command` set without `args` (and vice versa)** → the unset field falls through to the chart default; the two are independent (US2).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST persist `command` and `args` on a per-component override slot as two **independent**, optional fields, scoped to a single deployment.
- **FR-002**: An operator MUST be able to set `command` and/or `args` on any component declared by the deployment's application driver version, via the update-deployment and deploy flows (SDK, CLI, and frontend).
- **FR-003**: Overrides MUST be scoped to the **component** of a single deployment only. There is no environment-scope or deployment-wide `command` / `args` override.
- **FR-004**: On **write** (the mutation boundary), the system MUST reject any override entry whose component name is not declared by the deployment's driver version, with a typed error that names the driver's known components, and MUST NOT trigger any reconcile.
- **FR-005**: On **resolve** (the render boundary), the system MUST tolerate override entries left over from a driver-version upgrade that no longer declares the component, flag them as orphaned, preserve their stored values, and skip them when rendering so no override reaches a container.
- **FR-006**: The system MUST validate the shape of each override before any reconcile runs: every list element MUST be a string; empty-string elements ARE accepted; the list MUST be non-empty when set; an empty list MUST be rejected with a typed error distinct per field (`command` vs `args`).
- **FR-007**: Clearing an override MUST be expressed as null / omission of the field, distinct from an empty list. A cleared field MUST fall back to the chart default on the next reconcile and MUST be absent from subsequent reads. Clearing one field MUST NOT affect the other.
- **FR-008**: Setting, changing, or clearing `command` / `args` MUST trigger the same redeploy-confirmation flow that env-var changes use, and MUST result in a new instance and a planned deployment update.
- **FR-009**: Application drivers MUST be able to consume a resolved override through typed template filters — one for `command` and one for `args` — that return the override's list of strings, or an omit/none marker when no override is set for that component, so the chart default flows through.
- **FR-010**: The driver spec format MUST accept an optional, doc-only `command` / `args` declaration block per component (analogous to the env-vars declaration block). The declaration is informational: the platform MUST NOT require that a declared component actually consume the override.
- **FR-011**: The materialised application driver version MUST expose the doc-only declaration so consumers (UI / SDK) can see which components advertise overridable `command` / `args`.
- **FR-012**: The deploy and update-deployment mutations MUST accept the overrides as a single nested input list keyed by component name, with `command` and `args` each optional and nullable per entry so partial updates and explicit clears work; the shape MUST mirror the existing component env-vars input.
- **FR-013**: The read side MUST return the stored overrides per component, including orphaned entries, each carrying an orphaned flag so operators can audit and clean them up.
- **FR-014**: Override values MUST be passed through verbatim — no templating or variable expansion is performed on `command` / `args` values (matching the env-vars contract).
- **FR-015**: When a driver upgrade orphans one or more overrides, the platform MUST surface the orphaned state on read; it MUST NOT block the upgrade and MUST NOT silently discard the stored override.

### Key Entities *(include if feature involves data)*

- **Component override** — the per-component slot, stored on a deployment's configuration, that holds the optional `command` and `args` lists. Both fields are independently optional and nullable; absence means "use the chart default". Stored alongside the existing per-component configuration (env-vars, parameters) on the deployment; no new storage table.
- **Application driver version** — the versioned deployment spec. Declares the components an operator may target and, optionally and informationally, documents which of those components expose overridable `command` / `args` and which container they target.
- **Resolved deployment context** — the merged, per-component context handed to the chart-rendering layer. Carries the resolved `command` / `args` per component (or an omit marker), exactly as it already carries resolved env-vars. Orphaned overrides are surfaced here but not rendered.
- **Component container override input** — the operator-facing input on the deploy / update-deployment surface: a list of entries, each naming a component and optionally carrying a `command` list and/or an `args` list.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can set `args` (or `command`) on one component and observe it on the running container within a single redeploy cycle, with **zero** driver-source changes, for any driver that has already wired the override.
- **SC-002**: A driver author can make a component's `command` / `args` overridable end-to-end — declaration in the driver spec, override consumption in the chart's value template, and the chart-default fallback — in **10 or fewer lines** of change across those files.
- **SC-003**: Every invalid override (unknown component, empty list, or malformed list element) is rejected at the submission boundary **before** any redeploy is triggered — **zero** containers are restarted on a rejected submission.
- **SC-004**: No regression: the existing env-vars, parameters, and configuration end-to-end and propagation tests continue to pass unchanged.
- **SC-005**: After a driver upgrade that renames or removes an overridden component, the operator can see the orphaned override on read in **100%** of cases, the upgrade succeeds, and no orphaned value reaches any container.

## Assumptions

- The per-component override slot extends the deployment's existing configuration storage with no schema/migration change (consistent with the established pattern for additive configuration sections).
- The doc-only driver declaration is informational only — the platform does not enforce that a declared component actually consumes the override (matches the env-vars documentation policy).
- **One resolved override per component, driver-wired.** The platform exposes exactly one resolved `command` and one resolved `args` per component to the rendering layer; the driver author chooses which container in the rendered chart the override lands on. The platform never injects `command` / `args` into a container the driver template did not wire (mirrors the env-vars consumption contract).
- For multi-container components, v1 does not support targeting a non-default container — operators continue to fork the driver if they need that. A future iteration can add per-container granularity without breaking this contract.
- The behaviour, error shapes, input shape, and orphan-tracking semantics intentionally mirror the deployment env-vars precedent so operators and driver authors face a consistent model.

## Out of Scope (v1)

- Environment-scope or deployment-wide `command` / `args` overrides (excluded by design — heterogeneous component entrypoints make a single broad-scope override semantically meaningless).
- Overriding other container fields (`image`, `resources`, `securityContext`, `workingDir`, env-from-secret, and similar).
- Per-container override targeting inside a multi-container pod with a stable contract.
- Templating or variable expansion inside override values (values are passed through verbatim).

## Dependencies

- The existing application-driver component model (the set of components a driver version declares) — the source of truth for write-side validation and orphan detection.
- The existing deployment configuration storage and the per-component configuration that already carries env-vars and parameters.
- The existing redeploy-confirmation flow used by env-var changes, reused unchanged.
- The existing chart-rendering / template-filter mechanism that already exposes resolved env-vars to driver charts.
