---
description: "Task list for 011-unified-deployment-config"
---

# Tasks: Unified Deployment Configuration Surface

**Input**: Design documents from `/specs/011-unified-deployment-config/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are mandatory for this feature per the project constitution (§V) and per FR-027 / SC-006. Each editable section ships with an E2E scenario; unit tests cover diff, impact, inheritance, and the glob matcher.

**Organization**: Tasks are grouped by user story (US1, US2, US3, US4) per the spec's priorities (US1/US2 = P1, US3/US4 = P2). Setup and Foundational phases precede all user stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label — applied to user-story phase tasks only

## Path Conventions

- Web app structure: `frontend/src/` (this feature) and `backend/tests/e2e/configuration/` (E2E scenarios)
- All paths absolute from repo root unless noted

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repo-level preparation. No story-specific work.

- [ ] T001 Verify `frontend/node_modules/` is populated and `pnpm` works (`cd frontend && pnpm install`)
- [ ] T002 [P] Confirm TanStack Form and Radix Dialog versions are pinned to their feature-001 versions in `frontend/package.json`; no new top-level dependencies are introduced
- [ ] T003 Create the feature directory `frontend/src/components/deployment/configuration/` and an empty `index.ts` barrel file

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-story infrastructure — diff, impact, inheritance, shared UI primitives, GraphQL query extension. All user stories build on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### GraphQL query and codegen

- [ ] T004 Audit `frontend/src/graphql/get_deployment.graphql` and extend it to fetch `environment { id name config }`, `driver { parameterSchema }`, and `components { name }` if not already present. Validate with `uv run invoke validate-graphql`.
- [ ] T005 Regenerate types: `uv run invoke generate` (SDK + frontend codegen). Commit the regenerated files.
- [ ] T006 Audit `Deployment` GraphQL type for a `lastUpdateEvent` field or a server-issued version stamp (`updatedAt`). Record findings in a comment block in `specs/011-unified-deployment-config/research.md` under R-009 / R-012. If a small additive schema change is needed for slice 4's concurrent-edit detection, document it here — do NOT implement yet.

### Pure-function libraries (no UI dependencies)

- [ ] T007 [P] Create `frontend/src/lib/config-diff.ts` with `diff(before: UpdateDeploymentInput, after: UpdateDeploymentInput, driverSchema: DriverParameterSchema): ConfigurationDiff`. Walk the typed shape, attribute every entry to a `SectionId`, use stable keys for array entries (env-var name, toleration key, component name) to make order-changes invisible.
- [ ] T008 [P] Create `frontend/src/lib/config-diff.test.ts` with unit tests covering: identical inputs return empty diff; scalar change produces `change` entry; add/remove on env-var list produces `add`/`remove` entries keyed by name; reordering env vars produces no diff entries; nested component override change is attributed to `componentOverrides` section; worst-case shape (50 components × 50 fields) completes in <5ms (perf assertion).
- [ ] T009 [P] Create `frontend/src/lib/config-inheritance.ts` exporting `computeInheritance(deployment: UpdateDeploymentInput, environment: UpdateDeploymentInput, driverSchema: DriverParameterSchema): Map<SectionId, InheritanceState>`.
- [ ] T010 [P] Create `frontend/src/lib/config-inheritance.test.ts` covering: all-inherited deployment returns `inherited` for every section; partial override returns `overridden` with correct `overrideCount`; Driver Parameters always reports `overridden` for parameters that differ from driver defaults; Component Overrides reports `inherited` only when zero per-component blocks exist.
- [ ] T011 [P] Create `frontend/src/lib/impact-rules.ts` containing the rule array per `contracts/impact-rule-table.md`. Export `impactRules: ImpactRule[]`.
- [ ] T012 [P] Create `frontend/src/lib/config-impact.ts` exporting `evaluateImpact(diff: ConfigurationDiff, rules: ImpactRule[]): ImpactSummary` plus an internal `matchPath(pattern: string, path: string, kind: DiffKind, after: string): boolean` glob engine.
- [ ] T013 [P] Create `frontend/src/lib/config-impact.test.ts`. Glob-engine suite covers each syntax form (`*`, `**`, `[*]`, `value:`, `kind:`). Rule suite: every entry in `impact-rules.ts` ships with at least one positive case (rule fires on a matching diff) and one negative case (rule does not fire on a similar but non-matching diff). Empty-diff returns informational summary.

### Shared UI primitives

- [ ] T014 [P] Create `frontend/src/components/deployment/configuration/ConfigSummaryCard.tsx` — shared shell taking `{title, inheritance, children}` props; renders the section heading, inheritance badge, and slot for body.
- [ ] T015 [P] Create `frontend/src/components/deployment/configuration/InheritanceBadge.tsx` — read-only badge component taking `InheritanceState`; renders blue "overridden (N)" or gray "inherited".
- [ ] T016 [P] Create `frontend/src/components/deployment/configuration/ChangedFieldFrame.tsx` — wrapper that scopes TanStack Form `useStore` to one field, renders amber border + "changed" pill + "from X" annotation when dirty, no decoration when clean. Pulls original value from `initial` prop, env value from `environment` prop.
- [ ] T017 [P] Create `frontend/src/components/deployment/configuration/ChangedFieldFrame.test.tsx` — RTL coverage: renders children unchanged when value matches initial; renders amber border + pill + "from X" annotation when value differs; renders "from X (env)" suffix when the original came from the environment.
- [ ] T018 Extract `ParameterField` from `frontend/src/pages/deployments/DeployFormPage.tsx` into `frontend/src/components/deployment/configuration/ParameterField.tsx`. Keep imports in `DeployFormPage.tsx` pointed at the new location so the create form continues to work. Run `pnpm test` to confirm no regression.

**Checkpoint**: Foundation ready — user story work can now begin.

---

## Phase 3: User Story 1 — Inspect everything that was applied to a deployment (Priority: P1) 🎯 MVP slice 1

**Goal**: Replace today's Parameters tab with a Configuration tab that shows every applied configuration group as a read-only summary card with correct inherited/overridden state, plus a hero summary bar and a View JSON dialog. No editing capability beyond what exists today.

**Independent Test**: Open a seeded deployment with a mix of inherited and overridden values across multiple groups. Verify every group renders with the correct badge, the hero counts match the data, and the read view requires no developer tooling to inspect.

### Read summary components

- [ ] T019 [P] [US1] Create `frontend/src/components/deployment/configuration/sections/read/DriverParametersSummary.tsx` — chip-style row of `name value` for every parameter in `driverSchema`. Uses `ConfigSummaryCard` shell.
- [ ] T020 [P] [US1] Create `frontend/src/components/deployment/configuration/sections/read/SchedulingSummary.tsx` — resources summary, runtime class, tolerations count, topology spread, node affinity, pod anti-affinity.
- [ ] T021 [P] [US1] Create `frontend/src/components/deployment/configuration/sections/read/NetworkingSummary.tsx` — FQDN suffix, external URL, ingress class, external DNS source, dedicated ingress, IP allowlist.
- [ ] T022 [P] [US1] Create `frontend/src/components/deployment/configuration/sections/read/EnvVarsSummary.tsx` — list deployment-scoped overrides; summarize inherited count.
- [ ] T023 [P] [US1] Create `frontend/src/components/deployment/configuration/sections/read/StorageRuntimeSummary.tsx` — db size, standard storage class, node selector.
- [ ] T024 [P] [US1] Create `frontend/src/components/deployment/configuration/sections/read/ServiceOverridesSummary.tsx` — `driver service → override name` list.

### Tab shell, hero, View JSON

- [ ] T025 [US1] Create `frontend/src/components/deployment/configuration/HeroSummaryBar.tsx` — dark hero with total/inherited/overridden field counts, "Last changed" line (derived client-side from the deployment's most recent successful `update_deployment` task per research R-009 fallback), "View JSON" action, and "Edit configuration" CTA. The Edit button is rendered only when the auth context grants edit permission (FR-030); supply a `canEdit: boolean` prop that the parent computes.
- [ ] T026 [US1] Create `frontend/src/components/deployment/configuration/ViewJsonDialog.tsx` — Radix Dialog presenting `deployment.config` as syntax-highlighted JSON, read-only, with a copy-to-clipboard action.
- [ ] T027 [US1] Create `frontend/src/components/deployment/configuration/ConfigurationTab.tsx` — composes `HeroSummaryBar` + the 6 summary cards in the order Driver Parameters → Scheduling → Networking → Env Vars → Storage & Runtime → Service Overrides. Component Overrides summary is added in US4. Reads the deployment + environment from the urql query bound to `get_deployment.graphql`.

### Tab integration

- [ ] T028 [US1] Modify `frontend/src/pages/deployments/DeploymentDetailPage.tsx`: replace the existing "Parameters" tab with "Configuration"; route the tab to `ConfigurationTab`. Remove the parameters-tab-only code paths. Do not yet remove the "Scheduling" header button (slice 11).

### E2E

- [ ] T029 [US1] Create `backend/tests/e2e/configuration/test_configuration_tab_read.py` marked `@pytest.mark.api_only(reason="Reads via SDK then asserts UI rendering through Playwright snapshot; no UI mutation flow")` actually — re-check: this exercises the read tab UI, so it's `@pytest.mark.ui_only`. Seed a deployment with overrides in Scheduling, Env Vars, and Storage; open the Configuration tab via Playwright; assert: hero counts match; Scheduling card shows "overridden (N)" with N matching; Networking card shows "inherited"; Driver Parameters card lists every parameter from the driver schema; View JSON dialog opens and displays the full config.
- [ ] T030 [US1] Run T029 to a pass with `sleep infinity | uv run pytest backend/tests/e2e/configuration/test_configuration_tab_read.py -v -s --pdb 2>&1 | tee /tmp/pdb.log` per CLAUDE.md.
- [ ] T031 [US1] Run `cd frontend && pnpm lint && pnpm format:check && pnpm test` and `uv run invoke format lint` to verify the slice is committable.

**Checkpoint**: US1 fully functional. The Configuration tab replaces Parameters; all 6 summary cards render correctly; the legacy Scheduling header button and dialog still exist (removed in slice 11).

---

## Phase 4: User Story 2 — Change configuration through the unified drawer (Priority: P1)

**Goal**: Ship the right-side edit drawer with section nav and sticky footer; port the SchedulingConfigDialog's logic into the drawer's Scheduling section; add the remaining 5 sections (Identity, Env Vars, Storage & Runtime, Networking, Service Overrides, Driver Parameters). Apply mutations through the existing `updateDeployment`. Gate the drawer behind the edit-permission check (FR-030). Detect concurrent edits (FR-029).

**Independent Test**: Open the drawer, change a value in any one section, walk through Review & apply, confirm the persisted config reflects the change and the read tab refreshes.

### Drawer shell

- [ ] T032 [US2] Create `frontend/src/components/deployment/configuration/DrawerFooter.tsx` — sticky footer with pending-change count (subscribed via `form.useStore`), "Discard" button, "Review & apply" primary action. Disabled when no pending changes.
- [ ] T033 [US2] Create `frontend/src/components/deployment/configuration/SectionNav.tsx` — left rail listing every section; uses `IntersectionObserver` to highlight the in-view section; renders a per-section "changed" dot when that section has dirty fields.
- [ ] T034 [US2] Create `frontend/src/components/deployment/configuration/ConfigEditDrawer.tsx` — Radix Dialog with right-side slide-in animation (Tailwind utilities, 200 ms ease-out). Drawer width 760 px ≥1280 px viewport; full-width otherwise. Single TanStack Form instance whose initial value is `deploymentConfigToInput(deployment.config)`. Wires `SectionNav`, the scrollable form body, and `DrawerFooter`. Handles focus trap (Radix), keyboard navigation, focus restoration on close (FR-028).
- [ ] T035 [US2] Implement drawer close-with-dirty confirmation (FR-018): if the form is dirty when the user clicks X / presses Escape / clicks the backdrop, render a nested `Radix AlertDialog` "Discard pending changes?" with "Keep editing" (default) and "Discard" buttons.
- [ ] T036 [US2] Wire the "Edit configuration" button in `HeroSummaryBar` to open `ConfigEditDrawer`. The button is conditionally rendered based on `canEdit`, which is derived from the same authorization check that the `updateDeployment` resolver performs server-side (FR-030). If the auth context exposes a permission helper, use it; otherwise compute via a feature-flag fallback documented in `research.md` and flag an audit task.

### Identity section

- [ ] T037 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/IdentitySection.tsx` — input for `name` (validated by the existing deployment-name Zod schema); read-only display of driver version and app version (those mutations live on the existing Upgrade button per spec out-of-scope).

### Scheduling section (slice 3 — first editable section)

- [ ] T038 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/SchedulingSection.tsx` porting the form structure from `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx`. Sub-blocks: Resources (CPU/memory request+limit), Tolerations (field array), Topology Spread (field array), Node Affinity (field array), Pod Affinity, Pod Anti-Affinity, Runtime Class, Post-Render Injection toggles. Every input wrapped in `ChangedFieldFrame`. Export `schedulingSchema` Zod object.
- [ ] T039 [P] [US2] Migrate any helpers from `frontend/src/components/deployment/scheduling/sanitize.ts` that `SchedulingSection` needs into a new co-located file `frontend/src/components/deployment/configuration/sections/edit/schedulingSanitize.ts`. Do NOT delete the original `sanitize.ts` yet — that happens in slice 11.

### Confirmation dialog (slice 4 — required for any section to be "done")

- [ ] T040 [US2] Create `frontend/src/components/deployment/configuration/DiffEntryRow.tsx` — one row in the dialog's diff section. Renders the path-segment label, kind (`add`/`remove`/`change`) with appropriate colour treatment, before and after values.
- [ ] T041 [US2] Create `frontend/src/components/deployment/configuration/ImpactList.tsx` — renders `ImpactSummary` as a vertical list of consequences with severity icons; surfaces "disruptive" amber banner when `topSeverity === 'high'`.
- [ ] T042 [US2] Create `frontend/src/components/deployment/configuration/ConfigDiffDialog.tsx` — Radix Dialog showing the path-level diff (grouped by section, scrollable), the `ImpactList`, "Back to edit" and primary "Apply & redeploy" buttons. No type-to-confirm input (FR-022). Dispatches the `updateDeployment` mutation on Apply; on success closes itself and the drawer and triggers urql cache invalidation so the Configuration tab refreshes. On failure, stays open and surfaces the error.
- [ ] T043 [US2] Implement concurrent-edit handling (FR-029) inside `ConfigDiffDialog`'s Apply handler. If the deployment's version stamp at apply time differs from the version stamp at drawer-open time (or the resolver returns a typed stale-write error code), render the "this deployment was modified by Y at Z" reload panel with a Reload action that refetches and recomputes the diff baseline against the new persisted state, preserving the operator's pending edits against the new baseline. The mutation does not retry until reload completes.

### Remaining editable sections (slices 5–9)

- [ ] T044 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/EnvVarsSection.tsx` — field array of `{name, value}` rows with add/remove. Validates names with the POSIX env-var regex; flags duplicates. Export `envVarsSchema`.
- [ ] T045 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/StorageRuntimeSection.tsx` — db size enum select, standard storage class input, node selector input. Export `storageRuntimeSchema`.
- [ ] T046 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/NetworkingSection.tsx` — FQDN suffix input, external URL scheme select, external URL port input, external DNS source select, ingress class input, dedicated ingress nested form, IP allowlist field array. Export `networkingSchema`.
- [ ] T047 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/ServiceOverridesSection.tsx` — field array of `{driverServiceName, overrideName}`; `driverServiceName` is constrained to services declared by the driver schema. Export `serviceOverridesSchema`.
- [ ] T048 [P] [US2] Create `frontend/src/components/deployment/configuration/sections/edit/DriverParametersSection.tsx` — renders the extracted `ParameterField` once per parameter in `driverSchema`. Each field wrapped in `ChangedFieldFrame`. Export `driverParametersSchema`.
- [ ] T049 [US2] Wire all sections (Identity, Driver Parameters, Scheduling, Networking, Env Vars, Storage & Runtime, Service Overrides) into `ConfigEditDrawer`'s form body and `SectionNav`'s nav list in the order from FR-011.

### E2E per section

- [ ] T050 [P] [US2] Create `backend/tests/e2e/configuration/test_drawer_scheduling_edit.py` (`@pytest.mark.ui_only`). Seed a deployment, open drawer via Playwright, change CPU request in Scheduling section, click Review & apply, verify diff lists the change and impact lists "Pods will be recreated", click Apply & redeploy, wait for the deployment task, assert the deployment's persisted config reflects the new CPU value and the underlying pods have restarted. Include a keyboard-only path variant of the primary flow (FR-028).
- [ ] T051 [P] [US2] Create `backend/tests/e2e/configuration/test_drawer_env_vars_edit.py` (`@pytest.mark.ui_only`). Add an env var, verify it appears as a pod env var after redeploy.
- [ ] T052 [P] [US2] Create `backend/tests/e2e/configuration/test_drawer_storage_runtime_edit.py` (`@pytest.mark.ui_only`). Change db size; verify expected impact text and persisted result.
- [ ] T053 [P] [US2] Create `backend/tests/e2e/configuration/test_drawer_networking_edit.py` (`@pytest.mark.ui_only`). Add a CIDR to the IP allowlist; verify the Kubernetes Ingress's allowlist annotation updates.
- [ ] T054 [P] [US2] Create `backend/tests/e2e/configuration/test_drawer_service_overrides_edit.py` (`@pytest.mark.ui_only`). Add a service-name override; verify the Service object is renamed.
- [ ] T055 [P] [US2] Create `backend/tests/e2e/configuration/test_drawer_driver_params_edit.py` (`@pytest.mark.ui_only`). Change `enable_pdb=false`; verify the PodDisruptionBudget resource is removed from the cluster.
- [ ] T056 [US2] Create `backend/tests/e2e/configuration/test_drawer_multi_section_edit.py` (`@pytest.mark.ui_only`). Roll-up: change scheduling + env vars in one drawer trip; assert both diff entries appear, both consequences listed, both persisted after apply. Includes the concurrent-edit conflict scenario (SDK mutates the deployment between drawer-open and Apply; dialog surfaces the reload UX and does not silently overwrite).
- [ ] T057 [US2] Run every test from T050–T056 with `--pdb` per CLAUDE.md until green. Iterate on UI + backend until each scenario passes.

### Permission gating tests

- [ ] T058 [P] [US2] Create `frontend/src/components/deployment/configuration/HeroSummaryBar.test.tsx` — RTL test confirming the "Edit configuration" button is omitted when `canEdit={false}` and present when `canEdit={true}`.

### Lint + format

- [ ] T059 [US2] Run `cd frontend && pnpm lint && pnpm format:check && pnpm test`; resolve any failures. Run `uv run invoke format lint` for the new E2E python files.

**Checkpoint**: US2 fully functional. Every section in the spec's FR-011 list is editable through the drawer, the impact dialog gates every apply, concurrent edits are detected, and permission gating is in effect. The legacy SchedulingConfigDialog still exists (removed in slice 11). Component Overrides section is the only one missing — added in US4.

---

## Phase 5: User Story 3 — High-impact change with confidence (Priority: P2)

**Goal**: Strengthen the impact-rule coverage so that the diff dialog reliably communicates consequences for high-impact paths. Most infrastructure ships in US2 (T040–T043); this phase focuses on rule-table breadth, severity treatment, and the disruptive-banner UX.

**Independent Test**: Make a change classified `high` by the rule table (e.g., toleration effect → `NoExecute` or service-name override). Open the diff dialog and verify the disruptive amber banner is shown and the consequence text is present.

- [ ] T060 [US3] Audit `frontend/src/lib/impact-rules.ts` against the table in `contracts/impact-rule-table.md`. Ensure every documented rule is present and severity matches.
- [ ] T061 [US3] Implement the disruptive-banner treatment in `ImpactList`: when `topSeverity === 'high'`, the dialog header gets an amber background and a "disruptive" label; the "Apply & redeploy" button gets the amber primary style from the Paper mock.
- [ ] T062 [US3] Add per-rule unit-test cases to `frontend/src/lib/config-impact.test.ts` ensuring every rule in `impact-rules.ts` has a positive case (rule fires on a matching diff) and a negative case (similar diff does not fire). The matcher-engine cases from T013 are reused; add per-rule cases here.
- [ ] T063 [US3] Create `backend/tests/e2e/configuration/test_drawer_disruptive_change.py` (`@pytest.mark.ui_only`). Change a toleration effect from `PreferNoSchedule` to `NoExecute`; open the diff dialog; assert the amber disruptive banner is rendered, the "Existing pods on tainted nodes will be drained immediately" impact entry is listed, and Apply & redeploy still works without a type-to-confirm input.
- [ ] T064 [US3] Run T063 to a pass.

**Checkpoint**: US3 fully functional. Disruptive changes get the right visual treatment and every rule in the table has positive + negative coverage.

---

## Phase 6: User Story 4 — Component Overrides as a first-class section (Priority: P2)

**Goal**: Ship the Component Overrides section in both read view (US1's missing 7th card) and edit drawer (US2's missing 8th section). The section structure is intentionally roomy so future per-component fields (per-component env vars, image overrides, etc.) drop in without restructuring.

**Independent Test**: Open the drawer, expand Component Overrides, set a CPU resource override on one component, apply, and verify only that component's pods are recreated with the new limit.

- [ ] T065 [P] [US4] Create `frontend/src/components/deployment/configuration/sections/read/ComponentOverridesSummary.tsx` — list every component declared by the driver; each row shows status (overridden vs no override) and a one-line summary of the override scope when present.
- [ ] T066 [US4] Wire `ComponentOverridesSummary` into `ConfigurationTab` after Service Name Overrides.
- [ ] T067 [P] [US4] Create `frontend/src/components/deployment/configuration/sections/edit/ComponentOverridesSection.tsx` — collapsible block per component (Radix Collapsible). Inside each block: per-component resources (CPU/memory request+limit), replicas override, future-extension placeholder section. Field array semantics keyed on component name; never positional. Export `componentOverridesSchema`.
- [ ] T068 [US4] Wire `ComponentOverridesSection` into `ConfigEditDrawer`'s form body and `SectionNav`'s nav list as the last section.
- [ ] T069 [P] [US4] Create `backend/tests/e2e/configuration/test_drawer_component_overrides_edit.py` (`@pytest.mark.ui_only`). Seed a deployment with 3 components; set CPU resource overrides on one component via the drawer; assert only that component's Deployment resource gets the new request/limit and the other two are untouched.
- [ ] T070 [US4] Run T069 to a pass.

**Checkpoint**: US4 fully functional. Component Overrides ships as a first-class section in both surfaces with room to grow.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Cleanup of the legacy scheduling dialog, final regression sweep, doc and ADR follow-up.

- [ ] T071 Delete `frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx` and `frontend/src/components/deployment/scheduling/sanitize.ts`. Delete the now-empty `frontend/src/components/deployment/scheduling/` directory.
- [ ] T072 Remove the "Scheduling" header button from `frontend/src/pages/deployments/DeploymentDetailPage.tsx` and any helper code (mutation hooks, state) that was used only by the legacy dialog.
- [ ] T073 Run every E2E test under `backend/tests/e2e/configuration/` end-to-end to confirm no regression after the cleanup.
- [ ] T074 Run `cd frontend && pnpm lint && pnpm format:check && pnpm test` and `uv run invoke format lint` one more time. CI must be green.
- [ ] T075 [P] Update `frontend/AGENTS.md` to reference the new `components/deployment/configuration/` directory as the canonical location for deployment-config UI; remove any references to the legacy `scheduling/` directory.
- [ ] T076 [P] Walk through `specs/011-unified-deployment-config/quickstart.md` end-to-end on a fresh dev stack; tick every manual smoke check listed under "Manual smoke checks per slice".
- [ ] T077 If the slice-4 audit (T006, T043) added a stale-write error code on the `updateDeployment` resolver, file the propagation test per Constitution §V in `backend/tests/test_graphql_propagation/` and document the new error code in `dev/guides/graphql-error-codes.md`. Otherwise mark this task complete with "no schema change shipped" in the commit message.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** — no dependencies; T001–T003 can run immediately.
- **Phase 2 (Foundational)** — depends on Phase 1; blocks every user story.
- **Phase 3 (US1)** — depends on Phase 2. Independent of US2/US3/US4 after that; can ship as a standalone PR (slice 1).
- **Phase 4 (US2)** — depends on Phase 2. Sub-tasks have internal dependencies:
  - T032–T036 (drawer shell + permission gating) before any section can render.
  - T037 (Identity) parallel to T038 (Scheduling).
  - T040–T043 (dialog + concurrency) must land before any E2E in T050–T057 can pass.
  - T044–T048 (remaining sections) parallel to each other but each requires T040–T043 in place.
  - T049 (drawer composition) depends on all section components.
- **Phase 5 (US3)** — depends on Phase 4 (uses the dialog and rule infra). Sub-tasks mostly parallel.
- **Phase 6 (US4)** — depends on Phase 4 (uses the drawer + dialog). Can run in parallel with Phase 5.
- **Phase 7 (Polish)** — depends on Phase 3, Phase 4, Phase 5, Phase 6 all complete. T077 is conditional on T006/T043.

### User Story Dependencies

- **US1** depends on Foundational only. Ships independently as the MVP slice 1 PR.
- **US2** depends on Foundational. Internally, the drawer shell + dialog must land before per-section E2E passes; the per-section components themselves can be parallelized across developers.
- **US3** depends on Foundational + US2's dialog + rule-engine infra. Effectively absorbed into US2 unless staffed separately.
- **US4** depends on Foundational + US2's drawer. Lands as the final feature slice before cleanup.

### Within Each User Story

- Tests are mandatory and ship in the same slice as the implementation. Per Constitution §V, every E2E must be observed to pass before the slice is "done".
- Pure-function modules (Phase 2) before UI components that consume them.
- Shared UI primitives (Phase 2) before section components that compose them.
- Section components before drawer wiring (T049).

### Parallel Opportunities

- T002 alongside T001 (different files).
- T007/T009/T011/T012 in parallel (different lib files, no cross-deps yet).
- T008/T010/T013 (their respective unit tests) in parallel with each other once their implementation tasks finish.
- T014/T015/T016 in parallel (different shared-UI files).
- T019–T024 (six US1 summary cards) in parallel.
- T037/T038 (Identity + Scheduling sections) in parallel.
- T044–T048 (five remaining sections) in parallel once T040–T043 are in place.
- T050–T056 (six section E2E tests) in parallel.
- T065/T067 (Component Overrides summary + section) in parallel.
- T075/T076 polish tasks in parallel.

---

## Parallel Example — User Story 1 summary cards

```bash
# After Foundational completes, launch all six US1 summary card tasks together:
Task: "T019 Create DriverParametersSummary.tsx"
Task: "T020 Create SchedulingSummary.tsx"
Task: "T021 Create NetworkingSummary.tsx"
Task: "T022 Create EnvVarsSummary.tsx"
Task: "T023 Create StorageRuntimeSummary.tsx"
Task: "T024 Create ServiceOverridesSummary.tsx"
```

## Parallel Example — User Story 2 section components

```bash
# After T040–T043 (dialog + concurrency) land, launch all remaining section tasks together:
Task: "T044 EnvVarsSection.tsx"
Task: "T045 StorageRuntimeSection.tsx"
Task: "T046 NetworkingSection.tsx"
Task: "T047 ServiceOverridesSection.tsx"
Task: "T048 DriverParametersSection.tsx"
```

---

## Implementation Strategy

### MVP first — US1 only (slice 1)

1. Setup (Phase 1)
2. Foundational (Phase 2) — full
3. US1 (Phase 3)
4. **STOP and VALIDATE** — Configuration tab is the only tab between Overview and Pods; all 6 summary cards render; View JSON works; legacy Scheduling button still present and still works.
5. Ship as the slice-1 PR.

### Incremental delivery

Each phase below is one shippable PR (mapped to the slice numbers in plan.md):

1. **Slice 1** = Phase 1 + Phase 2 + Phase 3 (US1).
2. **Slice 2** = Drawer shell tasks T032–T036 + smoke test that the drawer opens/closes (no editable sections yet).
3. **Slice 3** = Scheduling section T038–T039 + drawer wiring T049 (partial).
4. **Slice 4** = Dialog T040–T043 + Scheduling E2E T050 + concurrent-edit handling.
5. **Slice 5** = Env Vars T044 + T051.
6. **Slice 6** = Storage & Runtime T045 + T052.
7. **Slice 7** = Networking T046 + T053.
8. **Slice 8** = Service Overrides T047 + T054.
9. **Slice 9** = Driver Parameters T048 + T055.
10. **Slice 10** = Multi-section roll-up + permission gating tests T056–T059.
11. **Slice 11** = US3 (T060–T064).
12. **Slice 12** = US4 (T065–T070).
13. **Slice 13** = Polish + cleanup (Phase 7).

Each slice ships its own E2E and may not regress earlier slices.

### Parallel team strategy

With multiple developers, after Foundational completes:

- Developer A: Phase 3 (US1) → Phase 7 polish
- Developer B: Phase 4 drawer shell (T032–T036), then alternates with Developer C on sections
- Developer C: Phase 4 dialog + concurrency (T040–T043), then alternates with Developer B on sections
- Developer D: Phase 5 (US3) and Phase 6 (US4) once Phase 4's dialog is in place
- All four converge on Phase 7 cleanup once their slices land.

---

## Notes

- [P] marks tasks that touch distinct files with no in-progress dependency.
- Every editable section ships with both a Vitest schema unit test (within the section file's `.test.ts` companion) and a `[ui-chromium]` E2E scenario under `backend/tests/e2e/configuration/`.
- Every E2E uses `@pytest.mark.ui_only(reason=...)` — none uses `[api-chromium]`. Rationale documented in research R-010.
- Commit at the end of each phase using `speckit.checkpoint.commit`. During Phase 4 (the largest), also commit per slice (Scheduling section, dialog, each remaining section).
- All paths in this document are absolute from the repo root.
- Total: 77 tasks across 7 phases.
