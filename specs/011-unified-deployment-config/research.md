# Research — Unified Deployment Configuration Surface

**Feature**: 011-unified-deployment-config
**Phase**: 0 (research / decisions)

This document resolves all design unknowns surfaced when filling Technical Context. Every decision below feeds into `plan.md`, `data-model.md`, and the section component contracts.

---

## R-001 · Form state management for the drawer

**Decision**: Use TanStack Form (`@tanstack/react-form`) with `zodValidator` per section, sharing a single form instance scoped to the drawer.

**Rationale**:
- TanStack Form is already adopted across the frontend (feature 001-tanstack-form-migration); using it preserves convention and avoids introducing a parallel form layer.
- The drawer contains nested field arrays (env vars, tolerations, components, IP allowlist) and per-component nested blocks — TanStack Form's `Field.Array` with stable `key`s handles this without ad-hoc array bookkeeping.
- Zod validators per section keep validation co-located with the section component, while a single form instance lets the drawer footer aggregate "pending changes across all sections" trivially via the form's `isDirty` and per-field dirty tracking.

**Alternatives considered**:
- Plain `useState` / `useReducer` — rejected: reinvents dirty tracking, field arrays, and validation.
- React Hook Form (`react-hook-form`) — rejected: not the project default; would split the codebase.
- Per-section forms with a parent aggregator — rejected: makes the global "5 pending changes across 4 sections" footer harder to compute and risks divergent submit handlers.

**Notes for implementation**:
- Initial form values come from `deploymentConfigToInput(deployment.config)` — i.e. we use the existing helper that projects the persisted config dict to a `UpdateDeploymentInput` shape. The form's domain model is `UpdateDeploymentInput`.
- "Original value" annotations come from the initial value snapshot at form mount; the form's `field.state.value` vs that snapshot is what powers the "from X" labels.

---

## R-002 · Drawer primitive and animation

**Decision**: Use Radix Dialog (`@radix-ui/react-dialog`) with custom CSS for the right-side slide-in. Do not introduce Vaul or another drawer library.

**Rationale**:
- Radix Dialog is already used elsewhere in the project; reusing it keeps focus-trap, escape-handling, and a11y semantics consistent.
- A right-side slide-in is a Dialog with `data-state="open"` driving a `transform: translateX(...)` animation — Tailwind utility classes plus a 200 ms ease-out transition. No new dependency.
- Vaul is appealing for mobile-style bottom sheets but adds a dependency and a different mental model; the desktop use case here is unambiguously a side panel.

**Alternatives considered**:
- `vaul` (Emil Kowalski's drawer library) — rejected: extra dependency, wrong default ergonomics for desktop side panels.
- Custom `<aside>` with portal and `useEffect`-driven escape/focus management — rejected: reinvents Radix and is a known source of accessibility bugs.

**Implementation notes**:
- Backdrop uses `Radix Dialog.Overlay` with `bg-black/55` to match the Paper mock's dimmed page treatment.
- Drawer width: `760px` on `≥1280px` viewports; `100vw - 32px` below — Tailwind responsive utilities.
- Closing the drawer (X button, Escape, backdrop click) when dirty triggers a nested `AlertDialog` confirmation; not dirty closes immediately.

---

## R-003 · Path-level diff algorithm

**Decision**: Hand-roll a small structural diff in `lib/config-diff.ts` (~80 LoC). Do not bring in `just-diff`, `deep-object-diff`, or `rfc6902`.

**Rationale**:
- The `UpdateDeploymentInput` shape is well-typed and well-bounded (≤200 leaf fields). A dedicated diff walks the typed structure once, producing entries shaped exactly for the dialog's needs (`{path: string[], section: SectionId, label: string, before: string, after: string, kind: 'add' | 'remove' | 'change'}`).
- Generic diff libraries return JSON Patch-style results that we'd have to re-classify into sections and re-format anyway. Doing it in one pass against our typed shape is simpler and faster.
- Field arrays (env vars, tolerations) need order-insensitive comparison keyed by `name` / `key` — generic libs don't know that.

**Alternatives considered**:
- `just-diff` — rejected: returns positional patches for arrays; misclassifies "reordered env vars" as a change.
- `deep-object-diff` — rejected: similar issue, plus no section attribution.
- JSON Patch (`fast-json-patch`) — rejected: outputs are positional and verbose; reshaping costs as much as writing our own.

**Implementation notes**:
- The diff function takes `(before: UpdateDeploymentInput, after: UpdateDeploymentInput, schema: DriverParameterSchema)` and returns `ConfigurationDiff` (see `data-model.md`).
- Sections are attributed at the top of the walk: every entry knows which section produced it. This is what powers the "Diff · Scheduling & Resources" section headers in the dialog and the section nav rail's per-section change dot.

---

## R-004 · Impact heuristic rule table

**Decision**: Static rule table in `lib/impact-rules.ts` — declarative array of `{matcher, consequence, severity}` entries; matcher is a path-pattern (e.g., `scheduling.resources.*`, `envVars`, `name`). Rule evaluation is a small function in `lib/config-impact.ts` that takes a `ConfigurationDiff` and returns a `ImpactSummary`.

**Rationale**:
- A declarative rule table is easy to evolve as we learn from production what actually causes restarts. It is also trivial to swap with backend-computed impact later by replacing the rule evaluator with a remote query — the consumer (the dialog) sees the same `ImpactSummary` shape regardless of source.
- Keeping rules in TypeScript (not JSON) lets us colocate type-safe matchers, severity enums, and unit tests right next to the rules.

**Alternatives considered**:
- Inline impact logic in the dialog component — rejected: untestable in isolation; mixes presentation with policy.
- Backend dry-run query in v1 — explicitly out of scope per spec (locked decision). Deferred to a follow-up feature that adds `previewUpdateDeployment` GraphQL query and swaps `config-impact.ts` to call it.

**Initial rule set** (frozen here for slice 4; refined in critique phase):

| Matcher | Consequence | Severity |
|---|---|---|
| `name` | "Deployment will be renamed; no pod restart" | informational |
| `parameters.*` | "Driver will be re-rendered; pods may restart depending on parameter semantics" | warning |
| `scheduling.resources.*` | "Pods will be recreated with new resource limits" | warning |
| `scheduling.tolerations` | "Pods on affected tainted nodes may be evicted" | warning |
| `scheduling.tolerations[*].effect` (change to `NoExecute`) | "Existing pods on tainted nodes will be drained immediately" | high |
| `scheduling.nodeAffinity`, `scheduling.podAffinity`, `scheduling.podAntiAffinity` | "Pods will be rescheduled to match new affinity" | warning |
| `scheduling.topologySpreadConstraints` | "Pods will be redistributed across topology domains" | warning |
| `scheduling.runtimeClass` | "Pods will be recreated under new runtime class" | warning |
| `envVars` (any add/remove/change) | "Pods will be recreated to pick up new environment" | warning |
| `ipWhitelist` | "Ingress controller allowlist will be reconfigured" | informational |
| `dedicatedIngress` | "Dedicated ingress controller will be reconciled" | warning |
| `ingressClass`, `fqdnSuffix`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType` | "Ingress + external DNS records will be reconfigured" | warning |
| `dbSize`, `standardStorage.storageClass` | "Database resize / storage class change may schedule a managed-DB action" | warning |
| `nodeSelector` | "Pods will be rescheduled to match new node selector" | warning |
| `serviceNameOverrides` | "Kubernetes Service objects will be renamed; DNS clients will see new names" | high |
| `components[*].resources.*` | "Affected component's pods will be recreated" | warning |

**Implementation notes**:
- The matcher uses a minimal glob syntax: `.` is the segment separator, `*` matches one segment, `**` matches multiple. No regex needed.
- Each rule outputs at most one consequence per evaluation, even if multiple matching diff entries exist (deduplication is the rule table's job). Severity bubbles up — if any rule fires `high`, the dialog gets the disruptive amber treatment.

---

## R-005 · Inheritance computation

**Decision**: Compute inheritance client-side from the parent environment config, which we fetch alongside the deployment in the same GraphQL query. New helper: `lib/config-inheritance.ts`.

**Rationale**:
- The GraphQL `Deployment` type already exposes `environment.config`. We can include it in `get_deployment.graphql` and compute, per top-level group, whether any field in the group is explicitly set on the deployment vs only present on the parent.
- "Overridden" means: the deployment has at least one field set in this group whose value differs from the environment's value for the same field (or the env has no value and the deployment does).
- "Inherited" means: every value seen in the group on the deployment is identical to the parent's, or the deployment has no fields set in the group at all.

**Alternatives considered**:
- Backend computes inheritance state and returns per-group flags — rejected for v1: introduces a schema change for what is a 30-line function with the data already on the client.
- Don't show inheritance state — rejected: it's a P1 acceptance criterion (FR-003).

**Implementation notes**:
- The helper returns `Map<SectionId, {state: 'inherited' | 'overridden', overrideCount: number}>`.
- Driver Parameters has no environment equivalent (parameters are deployment-scoped only), so it's always "overridden" with `overrideCount = number of parameters whose value differs from the driver's default`.
- Special-case Component Overrides: "inherited" means zero per-component blocks; "overridden" means ≥ 1 component has any override.

---

## R-006 · Section navigation in the drawer

**Decision**: Use `IntersectionObserver` to track which section is in view during scroll, plus clickable nav entries that call `element.scrollIntoView({behavior: 'smooth'})`. No third-party scrollspy library.

**Rationale**:
- Browser-native APIs are fine for ~8 sections and a single scrollable container. Existing code in `frontend/src/components/` uses the same pattern in at least one place (verified during plan phase).
- `IntersectionObserver` with a 50%-visible threshold matches Stripe / Linear scroll-spy semantics.

**Alternatives considered**:
- `react-scroll` — rejected: extra dependency for a 40-line hook.
- Anchor links + `:target` CSS — rejected: doesn't update the active state on scroll, only on click.

---

## R-007 · Closing the drawer with unsaved changes

**Decision**: Show a `Radix AlertDialog` "Discard pending changes?" confirmation. Two buttons: "Keep editing" (default), "Discard". No auto-save to local storage in v1.

**Rationale**:
- Auto-save (e.g., to `sessionStorage`) was considered as an alternative — rejected because the drawer is a synchronous workflow, not a long-running compose surface like an email draft. Losing five fields of pending edits is annoying but not catastrophic, and auto-save would surprise operators if a saved draft re-opened next time they clicked Edit.
- Explicit "Discard" confirmation matches FR-018 ("MUST NOT silently lose changes").

**Alternatives considered**:
- `beforeunload` blocking on browser close — rejected: doesn't fire reliably on tab close, and conflates drawer close with browser close.
- Auto-save to `sessionStorage` — rejected for v1 reasons above. Can be added in a future iteration if telemetry shows operators routinely lose drafts.

---

## R-008 · Driver Parameters field rendering

**Decision**: Reuse the existing `ParameterField` component from `frontend/src/pages/deployments/DeployFormPage.tsx` (parameter renderer used by the create form). Extract it from `DeployFormPage.tsx` into `frontend/src/components/deployment/configuration/ParameterField.tsx` before slice 9 so both create and drawer share it.

**Rationale**:
- The create form already renders driver parameters dynamically based on the driver's `parameterSchema`. Re-implementing that in the drawer would duplicate handling for integer / string / boolean / select / multi-select / object inputs, plus the schema-driven validation.
- Extracting before slice 9 means the drawer's Driver Parameters section is a thin wrapper, and the future create-page redesign (out of scope here) gets the same component for free.

**Alternatives considered**:
- Re-implement Driver Parameters rendering inside `DriverParametersSection.tsx` — rejected: duplication that will rot.
- Reuse via copy-paste — rejected for the same reason.

---

## R-009 · GraphQL query strategy

**Decision**: Extend `get_deployment.graphql` to also fetch `environment { id name config }` if it doesn't already. Use a single query for the Configuration tab and the drawer. No new top-level queries are introduced in v1.

**Rationale**:
- The Configuration tab needs `deployment.config`, `deployment.parameters`, `deployment.driver.parameterSchema`, `deployment.components` (for Component Overrides), `deployment.environment.config` (for inheritance), and the last-update event for the hero summary.
- One query keeps urql's cache hits high and avoids waterfall fetches when opening the drawer.
- `get_deployment.graphql` already fetches `.config`; verify it fetches `.environment.config` and `.driver.parameterSchema` and `.lastUpdateEvent` (or equivalent) — if not, extend it. Per CLAUDE.md, regenerating SDK types is required after any GraphQL query change.

**Alternatives considered**:
- Separate `get_environment_config.graphql` fetched in parallel — rejected: extra round-trip for data we already have access to.
- Lazy-load the parent env config only when the drawer opens — rejected: inheritance state is needed on the read tab too.

**Implementation notes**:
- After modifying `get_deployment.graphql`, run `uv run invoke generate` (regenerates Python SDK Pydantic models) and `pnpm codegen` (regenerates frontend TS types).
- The "last update event" line can be sourced from the existing Timeline tab's data — the most recent successful `update_deployment` task. If that field isn't exposed yet, prefer a small additive field on `Deployment` (e.g., `lastUpdateEvent { timestamp actor summary }`) which IS a GraphQL schema change and would require Governance Gate sign-off. As a v1 fallback, render the line based on the most recent task entry available client-side, with the rich form deferred to a follow-up. This is the **only** open question on backend touch — flagged in `tasks.md` for resolution during critique or the read-summary slice.

---

## R-010 · E2E testing approach

**Decision**: Every editable section ships a `[ui-chromium]`-only E2E test in `backend/tests/e2e/configuration/`. The `[api-chromium]` variant is *not* used (no SDK-equivalent flow exists for the drawer — the entire point is to exercise the UI). Mark every test `@pytest.mark.ui_only(reason=...)` per the dual-entrypoint guideline in `CLAUDE.md`.

**Rationale**:
- Per `dev/guides/dual-entrypoint-e2e.md`, the `[ui-chromium]` variant drives Playwright; `[api-chromium]` drives the SDK directly. The drawer is a UI artifact — the SDK already had this capability before the feature (`update_deployment` mutation), so an `[api-chromium]` re-run would just call the mutation directly with no UI interaction. That fails the "exercises new behaviour" bar and burns ~20 min of CI per test for zero new coverage.
- Constitution §V is non-negotiable: every new section ships an E2E that is observed to pass before the slice is "done".

**Test pattern**:
- Seed a deployment in the `Production` environment with overrides in a known subset.
- Open the Configuration tab via Playwright, verify the read view.
- Open the drawer, navigate to the section under test, change a value.
- Click Review & apply, verify diff entries, click Apply & redeploy.
- Wait for the deployment task to converge.
- Verify the persisted deployment config reflects the change (via SDK from the same test) and, where applicable, that pods restarted (via `kubectl get pod -A` in the test's vcluster).

**Alternatives considered**:
- Component tests via Vitest + RTL only — rejected: doesn't exercise the GraphQL mutation, draft persistence, or the read tab's re-render after apply. Lower confidence per slice.
- One mega-test per section that does many edits — rejected: harder to debug failures.

---

## R-011 · Removal of legacy SchedulingConfigDialog

**Decision**: Delete the `frontend/src/components/deployment/scheduling/` directory entirely (component + `sanitize.ts`) in slice 11, after every other slice is shipped and the drawer has been used in production for at least one merge window. Remove the "Scheduling" button from `DeploymentDetailPage.tsx` in the same commit.

**Rationale**:
- Sequencing removal last avoids accidentally breaking the existing edit flow if a regression is found mid-rollout.
- Tying removal to a commit (rather than spreading it across multiple) makes the cleanup PR easy to revert if needed.

**Alternatives considered**:
- Remove in slice 3 alongside the SchedulingSection port — rejected: forces a hard cutover before the rest of the unified flow is wired up; if slice 3 ships but slice 4 (impact dialog) regresses, scheduling editing becomes unavailable in the UI.
- Leave the legacy dialog forever as a fallback — rejected: defeats the unification goal and grows the surface area indefinitely.

---

## R-012 · Concurrent-edit detection and reload UX

**Decision**: On Apply, the client passes the deployment's `updatedAt` timestamp (or equivalent server-issued version stamp) that was present at drawer-open time. The backend's `updateDeployment` resolver compares against the persisted record and raises a typed conflict error (`STALE_WRITE` or similar) when they diverge. The dialog renders a "this deployment was modified by Y at Z — reload to merge?" panel with a Reload action that refetches the deployment, recomputes the diff baseline against the new persisted state, and keeps the operator's pending edits visible against the new baseline. The mutation does not proceed until reload.

**Rationale**:
- Optimistic concurrency on a server-issued version stamp is the standard idiom and avoids the read-your-writes ambiguity of relying on the operator to manually reconcile.
- The "Reload, keep pending edits" UX preserves the operator's work; it does not throw away the draft.
- Forcing reload (no overwrite) for v1 is the safer default. An "overwrite anyway" affordance can be added later if telemetry shows operators need it.

**Alternatives considered**:
- Long-polling the deployment from the drawer to detect concurrent edits live — rejected: heavier, requires subscriptions infra, and the conflict is rare enough that a synchronous check at apply time is fine.
- Silent server-side last-write-wins — rejected: directly contradicts FR-029 and the spec's silent-overwrite-is-unacceptable stance.

**Implementation notes**:
- **Backend touch required**: if the resolver does not already raise a typed stale-write error, this needs a small additive change (and triggers the propagation-test gate per Constitution §V). Audit during slice 4. If the resolver currently last-writes-wins, the slice-4 PR introduces the typed error and the propagation test.
- The version stamp field on `Deployment` (e.g., `updatedAt: DateTime!`) is likely already present from SQLModel auditing; verify in slice 1's GraphQL audit.
- Fallback for v1 if no server-side support exists: client compares the deployment's `updatedAt` from the original fetch to a re-fetch issued right before mutation. Race window remains but is tiny (single round-trip). Document this trade-off in the slice-4 PR.

---

## R-013 · Environment variable plaintext exposure

**Decision**: The unified drawer continues today's posture: env-var values are visible in plaintext to any user with deployment-read access, identical to what `View JSON`, the SDK, and the Kubernetes ConfigMap already expose. The feature **does not** introduce a new exposure surface, but it **does** make these values one click more discoverable than they used to be.

**Rationale**:
- The GraphQL `EnvVar.value` contract documents that values are not for secret material (the type's docstring is the authoritative source). Operators have been told via tooling for as long as the field has existed.
- Anyone with deployment-read can already read `deployment.config`, which embeds env vars; the unified drawer surfaces them in a friendlier UI but does not lower a trust boundary.
- A first-class secrets facility (Kubernetes Secret references, external secret manager) is a separate feature and out of scope here.

**Alternatives considered**:
- Mask env-var values behind a "Reveal" toggle — rejected for v1: gives a false impression that the UI is the trust boundary, when in reality the backend GraphQL response carries the plaintext.
- Block this feature on a secrets facility landing first — rejected: secrets are a much bigger workstream, and operators would lose the env-var edit capability for the entire intervening time.

**Implementation notes**:
- The Configuration tab's Environment Variables summary card and the drawer's Env Vars section render values in plaintext (`JetBrains Mono` colour-coded by inherited vs overridden), matching the existing `View JSON` posture.
- A non-blocking telemetry follow-up may track adoption of env-var edits to inform a future secrets-facility prioritization.

---

## Summary

All NEEDS CLARIFICATION items are resolved. The one open question (backend-side: does `Deployment` expose a `lastUpdateEvent`?) is captured in R-009 with a v1 fallback that requires no backend changes. The critique phase added R-012 (concurrent-edit detection) and R-013 (env-var plaintext decision). R-012 may require a small additive backend change in slice 4 — that decision is made during slice 4's GraphQL audit; if it triggers Governance Gate review, the slice's PR handles it under the standard propagation-test rule.
