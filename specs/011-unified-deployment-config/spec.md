# Feature Specification: Unified Deployment Configuration Surface

**Feature Branch**: `011-unified-deployment-config`
**Created**: 2026-05-16
**Status**: Draft
**Input**: User description: "Unified deployment configuration surface — Configuration tab + Edit drawer. Show every config knob applied to a deployment on the detail page, and let operators edit any subset of them through a single drawer ending in diff + impact review."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Inspect everything that was applied to a deployment (Priority: P1)

An SRE opens a deployment that is misbehaving compared to its siblings. They want to know — without leaving the UI — exactly what configuration was applied: which driver parameters, what scheduling resources, what tolerations, what env vars, what ingress and storage settings, what per-component overrides. For each group they want to see whether the value was inherited from the parent environment or explicitly overridden on this deployment.

**Why this priority**: Today operators must read the GraphQL response or driver source to learn this. The read view is the foundation everything else builds on; without it, the edit flow has no anchor. It is also independently shippable — even with no editing capability beyond what exists today, exposing the full applied config is a meaningful improvement.

**Independent Test**: Open a seeded deployment with a mix of inherited and overridden values across multiple config groups. Verify every group's values render correctly with the right inherited/overridden badge, that the hero summary correctly counts overridden vs inherited fields, and that no group requires opening a developer tool or the SDK to be inspected.

**Acceptance Scenarios**:

1. **Given** a deployment that overrides only the scheduling block on top of its environment, **When** the operator opens the Configuration tab, **Then** the scheduling card shows an "overridden" badge with a count of changed fields and lists the resource values, while all other group cards show an "inherited" badge and surface the inherited values in a muted style.
2. **Given** a deployment whose driver defines 8 parameters and the operator has overridden 8 of them, **When** the operator opens the Configuration tab, **Then** the Driver Parameters card lists all 8 values in a compact form and the hero bar reflects the overridden count.
3. **Given** a deployment with no overrides at all, **When** the operator opens the Configuration tab, **Then** every group shows "inherited" and the hero bar reports zero overridden fields.

---

### User Story 2 — Change non-scheduling configuration through the UI (Priority: P1)

An operator needs to add an environment variable, tighten the IP allowlist, or change the FQDN suffix on a single deployment. Today they have to drop into the SDK or CLI — the UI only edits scheduling. They want to open one form, change the fields, and apply.

**Why this priority**: The unified edit flow is the primary user value of the feature. P1 because it removes the SDK-only fallback for every non-scheduling field at once. It is independently testable: a single editable section (Env Vars or Networking) plus the confirmation dialog forms a complete shippable slice.

**Independent Test**: Open the edit drawer, change a value in any section other than Scheduling, walk through the confirmation dialog, apply, and verify the persisted config reflects the change and the read view re-renders correctly.

**Acceptance Scenarios**:

1. **Given** an operator with edit access to a deployment, **When** they click "Edit configuration" in the Configuration tab, **Then** a right-side drawer opens showing every config group as an editable section with the current persisted values pre-filled and the parent environment values visible as the "inherited" baseline.
2. **Given** the operator has changed the IP allowlist from three CIDRs to four, **When** they click "Review & apply", **Then** the confirmation dialog shows a path-level diff listing the added CIDR as a `+` line and lists "ingress controller will be reconfigured" in the Impact section.
3. **Given** the operator clicks "Apply & redeploy" in the confirmation dialog, **When** the underlying mutation succeeds, **Then** the dialog closes, the drawer closes, the Configuration tab refreshes with the new values, and any redeploy task triggered by the change is visible in the Timeline tab.
4. **Given** the operator has changes pending across more than one section, **When** they look at the drawer footer, **Then** it shows the total number of pending changes and a "Discard" action that reverts every change with one click.

---

### User Story 3 — Make a high-impact change with confidence (Priority: P2)

A platform engineer is changing the GPU toleration effect from `PreferNoSchedule` to `NoExecute`, which will immediately evict GPU pods. Before they commit they want to see exactly what fields will change and what concrete consequences the change will have on running workloads.

**Why this priority**: The diff + impact review is what makes the broader edit surface safe to ship. Without it, the unified drawer would feel reckless for disruptive changes. P2 because Story 2 is technically complete without it (the dialog can be a simple summary), but Story 3 is what makes operators willing to use the unified surface for high-stakes changes.

**Independent Test**: Make a change that the impact heuristic table classifies as disruptive (any scheduling or env var change), open the confirmation dialog, verify the diff lists the changed path with both old and new values and that the Impact section lists at least one concrete consequence drawn from the rule table.

**Acceptance Scenarios**:

1. **Given** the operator has changed `tolerations[1].effect` from `PreferNoSchedule` to `NoExecute`, **When** they open the confirmation dialog, **Then** the dialog shows a path-level diff line for the change and the Impact section calls out that existing pods on tainted GPU nodes will be drained.
2. **Given** the operator has made changes across scheduling and networking, **When** the confirmation dialog opens, **Then** every changed field is listed under its section heading and the Impact section consolidates the consequences without duplication.
3. **Given** the operator clicks "Back to edit" in the dialog, **When** the drawer reopens, **Then** every previously-pending change is still present and editable.
4. **Given** the operator clicks "Apply & redeploy", **When** the dialog is open, **Then** there is no additional friction step (no type-to-confirm input) between clicking the button and the mutation firing.

---

### User Story 4 — Operate on Component Overrides as a first-class section (Priority: P2)

An operator wants to set per-component resource caps (e.g., raise the `rate-limiter` component's CPU limit) without touching the rest of the deployment's scheduling. The Component Overrides section must be present and editable from day one, with room to grow into richer per-component configuration in later iterations.

**Why this priority**: Component Overrides could be technically deferred to a follow-up, but the product direction is that more functionality is coming to this section, so it ships first-class in v1 and must not be hidden behind a "v2 scope" door. P2 because Story 2 covers the unified drawer at the framework level; this story makes sure Component Overrides specifically is not the section that gets skipped.

**Independent Test**: Open the drawer, expand the Component Overrides section, set a CPU override on one component, apply, and verify the override persists on that component only.

**Acceptance Scenarios**:

1. **Given** a deployment with three components, **When** the operator opens the Component Overrides section, **Then** all three components are listed and each can be expanded into its own override block.
2. **Given** the operator sets a CPU resource override on one component, **When** they apply, **Then** only that component's override block is updated in the persisted config and other components remain unchanged.

---

### Edge Cases

- **Unsaved changes when closing the drawer**: Closing the drawer (X button, Escape, or backdrop click) while pending changes exist must prompt the operator to confirm discard or to keep editing; it must not silently lose changes. Final interaction pattern is finalized during planning.
- **Concurrent edits**: Another operator or an SDK client mutates the deployment while the drawer is open. The apply request must surface a clear conflict message (the underlying persisted config is no longer what the diff was computed against) rather than silently overwriting.
- **Invalid input**: Per-field validation (CIDR format, port range 1–65535, non-empty FQDN suffix, valid Kubernetes label/value) blocks the "Review & apply" action with inline errors on the offending fields and the affected section in the nav rail marked as invalid.
- **Empty or unset parent environment values**: When a config field has no environment-level value (e.g., environment did not set `fqdnSuffix`), the read view shows "not set" rather than the env name, and the inherited badge is preserved unless the deployment explicitly sets the field.
- **Driver schema drift**: The driver version's parameter schema changed between the deployment's last apply and now (new required parameter added, existing parameter removed). The Driver Parameters section flags removed parameters as deprecated values and prompts the operator to provide a value for any newly required parameter before "Review & apply" enables.
- **Mutation failure**: The `Apply & redeploy` action fails server-side (validation error, backend down). The dialog stays open, surfaces the server error message, and preserves the pending changes; the operator can fix and retry.
- **Brand-new deployment with no overrides at all**: Every section shows "inherited" with no overridden count, the hero bar reads "0 overridden", and the Component Overrides section shows components with "no override" affordances.
- **Screen-reader users**: A user navigating with VoiceOver or NVDA opens the drawer; focus is announced moving into the drawer, each section heading is reachable by heading navigation, dirty state on a field is announced when it changes (e.g., "field changed, original value 500m"), and the diff dialog announces itself as a modal with its primary action reachable.
- **Viewer without edit permission**: A user with read-only access to the deployment sees the Configuration tab and every summary card, but the hero bar shows no "Edit configuration" button and the drawer route is unreachable. The "View JSON" affordance remains available.

## Requirements *(mandatory)*

### Functional Requirements

#### Read view (Configuration tab)

- **FR-001**: The deployment detail page MUST present a Configuration tab that replaces today's Parameters tab; no parallel "Parameters" tab remains.
- **FR-002**: The Configuration tab MUST render every applied configuration group as a summary card. The groups are: Driver Parameters, Scheduling & Resources, Networking & Ingress, Environment Variables, Storage & Runtime, Service Name Overrides, Component Overrides.
- **FR-003**: Each summary card MUST display an inheritance badge — either "inherited" when no field in the group is overridden on the deployment, or "overridden" with a count of fields whose values differ from the parent environment.
- **FR-004**: The Configuration tab MUST display a hero summary at the top that reports total configured field count, count inherited from the parent environment, and count overridden on this deployment.
- **FR-005**: The hero summary MUST display a "last changed" record (timestamp, actor, brief change summary) drawn from the most recent successful deployment update event.
- **FR-006**: The hero summary MUST expose a single "Edit configuration" action and a "View JSON" action that opens a read-only modal showing the raw persisted config dict.
- **FR-007**: Within Driver Parameters, every parameter the driver defines MUST be visible in a compact chip-style row showing name and current value, regardless of whether the parameter is overridden.
- **FR-008**: Within Environment Variables, deployment-scoped overrides MUST be listed individually with their values; environment-scoped values that are not overridden MUST be summarized as an inherited count.
- **FR-009**: Within Component Overrides, every component declared by the driver MUST be listed; components with no override MUST be visually distinguishable from those with one.

#### Edit drawer

- **FR-010**: Clicking "Edit configuration" MUST open a right-side drawer over the deployment detail page; the page behind the drawer MUST be visually dimmed to indicate context preserved but not interactive.
- **FR-011**: The drawer MUST contain a section navigation rail listing every editable section: Identity, Driver Parameters, Scheduling & Resources, Networking & Ingress, Environment Variables, Storage & Runtime, Service Name Overrides, Component Overrides.
- **FR-012**: Every section listed in FR-011 MUST be editable; no section may be read-only inside the drawer.
- **FR-013**: Component Overrides MUST be a first-class editable section in the initial release, with collapsible per-component blocks and visual room to accommodate additional override fields in future iterations.
- **FR-014**: When a field's value differs from its persisted state, the field MUST be visually marked (border treatment) and labelled as "changed", and the original persisted value MUST be visible alongside the input (e.g., "from 500m").
- **FR-015**: When any field in a section is changed, the section's heading in the form MUST show a "N changed" chip, and the section nav rail MUST display a change indicator next to that section's entry.
- **FR-016**: The drawer MUST display a sticky footer that shows the total count of pending changes across all sections, a "Discard" action, and a "Review & apply" action.
- **FR-017**: "Discard" MUST revert every pending change to its persisted value and leave the drawer open; the operator MUST be able to keep editing without re-opening the drawer.
- **FR-018**: Attempting to close the drawer while pending changes exist MUST prompt the operator to confirm discard; the drawer MUST NOT silently lose changes.
- **FR-019**: Per-field validation MUST run inline as the operator edits; "Review & apply" MUST be disabled when any field is invalid, and the section nav rail MUST mark sections containing invalid fields.

#### Confirmation dialog

- **FR-020**: Clicking "Review & apply" MUST open a confirmation dialog showing a path-level diff of every changed field across every section. Each diff entry MUST show both the previous value (marked `−`) and the new value (marked `+`).
- **FR-021**: The dialog MUST include an Impact section listing concrete consequences derived from a frontend rule table that maps changed-field paths to predicted effects (e.g., "pods will be recreated", "ingress controller will be reconfigured", "no restart required").
- **FR-022**: The dialog MUST provide a single primary action labelled "Apply & redeploy" and a secondary "Back to edit" action. There MUST NOT be a type-to-confirm input or any additional friction step.
- **FR-023**: "Back to edit" MUST close the dialog and return the operator to the drawer with every pending change preserved.
- **FR-024**: "Apply & redeploy" MUST submit the deployment update with the full set of changes such that fields not edited remain unchanged and edited fields are applied. After a successful response, the dialog and drawer MUST close, the Configuration tab MUST refresh to reflect the new values, and any task spawned by the update MUST appear on the Timeline tab.
- **FR-025**: If the apply fails for any reason, the dialog MUST stay open, surface the server error, and preserve the pending changes for retry.

#### Cleanup

- **FR-026**: The existing Scheduling-only dialog and the "Scheduling" button in the deployment header MUST be removed in this feature; their behaviour MUST be fully covered by the unified drawer.

#### Testing

- **FR-027**: Each editable section MUST ship with end-to-end test coverage that drives a change through the drawer and confirmation dialog and asserts the persisted result.

#### Accessibility

- **FR-028**: The Configuration tab and the edit drawer MUST be operable by keyboard alone (open drawer, navigate sections, edit fields, submit, dismiss) and MUST follow the project's a11y baseline. Specifically:
  - Opening the drawer MUST move focus to the first editable control in the drawer; closing MUST return focus to the "Edit configuration" button.
  - The drawer MUST trap focus while open and release it on close.
  - The diff dialog MUST be a labelled modal; primary and secondary actions MUST be reachable in tab order.
  - "Changed" state on a field MUST be communicated to assistive technologies via an `aria-describedby`-style mechanism (not by colour alone).
  - The amber "changed" border, blue "overridden" badge, and green "running" indicator MUST meet WCAG 2.1 AA contrast against the surfaces they sit on.

#### Concurrency

- **FR-029**: When the operator clicks "Apply & redeploy", the mutation MUST detect whether the underlying deployment has been modified since the drawer was opened. On detection of a concurrent modification, the confirmation dialog MUST surface a clear "this deployment was modified by another actor since you started editing" message with a "Reload" action that refetches the deployment, recomputes the diff baseline against the new persisted state, and keeps the operator's pending edits visible against the new baseline. The mutation MUST NOT proceed until the operator reloads or explicitly chooses to overwrite (overwrite is a follow-up; v1 only supports reload).

#### Permissions

- **FR-030**: The "Edit configuration" button in the hero summary bar MUST be visible only to users with edit permission on the deployment, per the same authorization check the `updateDeployment` mutation enforces server-side. Users without edit permission see the read-only Configuration tab without an Edit affordance, no misleading disabled-button tooltip, and no route by which to open the drawer.

### Key Entities

- **Deployment Configuration**: The set of values applied to a deployment, organized into the 9 groups listed in FR-002 plus an Identity group (name, driver version, app version). Each value is either inherited from the parent environment or explicitly set on the deployment.
- **Environment Configuration**: The parent record from which a deployment inherits unset fields. Reading the environment record is necessary to determine inherited vs overridden state for every section.
- **Configuration Draft**: The in-memory state of the drawer form — the persisted deployment configuration plus any pending edits. The draft persists until the operator applies or discards.
- **Configuration Diff**: The path-level difference between the persisted deployment configuration and the draft, computed when the operator clicks "Review & apply".
- **Impact Rule**: An entry in the frontend rule table mapping a configuration path (e.g., `scheduling.resources.*`, `envVars`, `name`) to a predicted consequence string used in the dialog's Impact section.
- **Update Event**: A record of a successful deployment update — timestamp, actor, brief summary — used to populate the hero summary's "last changed" line.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can identify every configuration value applied to a deployment, including its inherited-vs-overridden state, within 10 seconds of landing on the Configuration tab — without opening developer tools, inspecting raw JSON, or running an SDK call.
- **SC-002**: Time to change any single non-scheduling configuration field (env var, IP allowlist, FQDN suffix, ingress class, storage size, service-name override, per-component resource) drops from "SDK-only path" (currently several minutes including context switch) to under 60 seconds end-to-end through the unified drawer.
- **SC-003**: 100% of configuration field groups exposed by the deployment update contract are editable through the unified drawer. No supported field requires falling back to the SDK or CLI.
- **SC-004**: 0% of deployment-config mutations submitted through the UI bypass the diff + impact review step. Every apply must show the diff first.
- **SC-005**: The legacy Scheduling-only dialog and the "Scheduling" header button are removed in this feature's PR sequence; no parallel scheduling-edit affordance survives.
- **SC-006**: For every editable section, an end-to-end test exists that drives a change through the drawer, completes the confirmation dialog, and asserts the persisted result. CI passes for all of them as a precondition for shipping the feature.
- **SC-007**: The Component Overrides section is present in v1 and supports at least the same level of per-component edit as the legacy Scheduling dialog supported globally, with the section structure visibly designed to accommodate richer per-component fields in future iterations (e.g., per-component env vars, per-component image overrides).
- **SC-008**: 100% of editable fields and interactive controls in the Configuration tab and drawer are operable by keyboard alone and meet WCAG 2.1 AA contrast on the amber "changed" border, blue "overridden" badge, and green "running" indicator. The diff dialog is announced as a modal by VoiceOver and NVDA in manual smoke testing on the first slice that ships it (slice 4).
- **SC-009**: When two operators edit the same deployment concurrently, the second operator's Apply attempt is detected as a conflict and routed through the reload UX rather than silently overwriting; 0% of concurrent edits result in silent overwrite (verified by an E2E scenario in the multi-section roll-up test).

## Assumptions

- The existing deployment update contract is sufficient to support every editable field in v1; no backend schema changes are required.
- The parent environment configuration is available alongside the deployment configuration in the same data fetch, so inheritance state can be computed client-side without a second round-trip.
- Users without edit permission on a deployment see the Configuration tab in read-only mode (no "Edit configuration" affordance); see FR-030. The drawer is the only mutation surface and is gated on the same server-side authorization check that `updateDeployment` enforces.
- Environment variable values are not considered secret material per the existing GraphQL `EnvVar.value` contract. The unified drawer continues today's posture (env values are visible to anyone with deployment read access via this UI, View JSON, or the SDK). Secret material belongs in a separate facility outside this feature's scope; see `research.md` R-013.
- The impact heuristic table can be expressed entirely client-side from the configuration diff in v1. A future iteration may add a backend-computed impact preview; the dialog's contract is designed to absorb that change without UI restructuring.
- Driver-version upgrades stay on the existing "Upgrade" header button; the unified drawer does not change driver versions.
- The create-deployment form and the environment-level configuration UI are explicitly out of scope for this feature; both will reuse the section components from this feature in follow-up work.
- Today's date (2026-05-16) reflects the state where this feature is being specified; the constitutional requirement to ship E2E coverage for every new feature (CLAUDE.md §V) applies and is enforced via FR-027 and SC-006.
