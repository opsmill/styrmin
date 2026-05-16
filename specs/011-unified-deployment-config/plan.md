# Implementation Plan: Unified Deployment Configuration Surface

**Branch**: `011-unified-deployment-config` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/011-unified-deployment-config/spec.md`

## Summary

Replace today's read-only "Parameters" tab on the deployment detail page with a "Configuration" tab that exposes every applied configuration value (9 logical groups), and introduce a single right-side edit drawer that ends in a diff + impact confirmation dialog. The legacy `SchedulingConfigDialog` and its dedicated header button are removed; their functionality is folded into the unified drawer alongside seven other now-editable sections, including Component Overrides as first-class.

This is a **frontend-only feature**. No backend schema, mutation, or resolver changes are required — the existing `updateDeployment(input: UpdateDeploymentInput!)` mutation already supports every field we need to edit. The work splits into a thin section-by-section design rooted in the field grouping of `UpdateDeploymentInput`, with a shared draft/diff/impact pipeline that all sections feed into.

## Technical Context

**Language/Version**: TypeScript 5.9.3, Node 22 (frontend only; backend untouched)
**Primary Dependencies**: React 19.2.4, Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI primitives, TanStack Form (already adopted via feature 001-tanstack-form-migration), TanStack Router 1.168.x (already adopted via 001-tanstack-router-migration), TanStack Query v5, Tailwind, lucide-react. Fonts: Inter, JetBrains Mono.
**Storage**: N/A — all state is client-side draft + persisted GraphQL response; deployment config is already stored as JSON on the existing `Deployment` row, no schema changes.
**Testing**: Vitest + React Testing Library (frontend unit / component), pytest E2E suite under `backend/tests/e2e/` driven via Playwright in `[ui-chromium]` mode (per `dev/guides/dual-entrypoint-e2e.md`). Specific test obligations from critique:
- **Per-rule impact tests**: every entry in `frontend/src/lib/impact-rules.ts` ships with at least one positive case (rule fires on a matching diff) and at least one negative case (rule does not fire on a similar but non-matching diff). The matcher's glob engine has a dedicated unit suite covering each syntax form (`*`, `**`, `[*]`, `value:`, `kind:`).
- **Concurrent-edit E2E**: the multi-section roll-up E2E in `backend/tests/e2e/configuration/test_drawer_multi_section_edit.py` includes a scenario where a second client mutates the deployment via SDK between drawer-open and Apply; the test asserts that the dialog surfaces the conflict UX and that no silent overwrite occurs.
- **Permission-gating component test**: an RTL test confirms the "Edit configuration" button is omitted when the user's auth context lacks edit permission.
- **Accessibility**: each E2E scenario includes a keyboard-only path (no mouse) for the slice's primary user flow.
**Target Platform**: Web — Styrmin frontend single-page app, served via Vite dev server in development and bundled for production. Browser baseline matches the rest of the Styrmin frontend (modern evergreen Chrome / Firefox / Safari per `frontend/AGENTS.md`).
**Project Type**: Web application — frontend + backend repo; this feature touches `frontend/` only.
**Performance Goals**: Configuration tab first paint ≤ 200 ms after deployment fetch resolves (parallel to existing Overview tab). Drawer open animation ≤ 16 ms per frame at 60 fps. Diff computation across the full deployment config (~200 leaf fields max) ≤ 5 ms — well within frame budget.
**Constraints**: Drawer width fixed at 760 px on viewports ≥ 1280 px, collapses to full-width sheet below. No backend schema changes (Governance Gate). No new dependencies beyond what TanStack Form / Radix already bring. Must not regress the existing Scheduling edit flow during slice 11 cleanup.
**Scale/Scope**: ~21 new components, ~3 lib modules, 7 GraphQL queries (all existing, reused), 7+ Playwright `[ui-chromium]` E2E scenarios (one per editable section, plus a multi-section roll-up). The deployment config dict typically has 50–200 leaf fields across the 9 groups.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Notes |
|---|---|---|
| I. Declarative State Reconciliation | ✅ Pass | Feature edits the persisted desired-state config; reconciliation behaviour is unchanged. |
| II. Driver-Based Deployment | ✅ Pass | No driver schema changes; Driver Parameters section consumes the existing driver parameter schema (`driver.parameterSchema`) read-only. |
| III. Layered Architecture | ✅ Pass | No backend layers touched. Frontend has its own layering convention; this feature places GraphQL queries under `frontend/src/graphql/`, business helpers under `frontend/src/lib/`, components under `frontend/src/components/deployment/configuration/`. |
| IV. Type Safety and Typed Errors | ✅ Pass | All new code is TypeScript with strict types. Generated GraphQL types from `pnpm codegen` are used for the form's domain model. Error handling is per-field validation (Zod) plus mutation-error surfacing in the dialog. |
| V. Test-First Development & E2E | ✅ Pass | FR-027 / SC-006 enforce E2E per editable section. Each slice ships its own `[ui-chromium]` E2E scenario and must run green before the slice is "done". No deferral is acceptable; this is explicitly captured in `tasks.md`. |
| VI. Format and Lint Before Commit | ✅ Pass | `pnpm lint` / `pnpm format` and `uv run invoke format lint` run pre-commit per existing hooks. No exemptions. |
| Governance Gate — GraphQL schema | ⚠️ Conditional | No schema modifications planned. **Slice 4 conditionally introduces** a typed stale-write error code on `updateDeployment` if one does not already exist (see research R-012). If that change lands, it is additive (new error code, no schema-breaking change) and ships with a propagation test per Constitution §V. The audit happens in slice 1's GraphQL audit. |
| Governance Gate — Database schema | ✅ N/A | No DB changes. |
| Governance Gate — New dependencies | ✅ Pass | No new top-level dependencies. TanStack Form is already in `package.json` via 001-tanstack-form-migration. |
| Governance Gate — Auth/AuthZ | ✅ N/A | No auth changes; uses existing per-deployment edit-permission gating. |

**Result**: All gates pass, with one conditional flag on the GraphQL row tied to slice 4's concurrent-edit work (additive only). No complexity-tracking justifications needed.

## Project Structure

### Documentation (this feature)

```text
specs/011-unified-deployment-config/
├── plan.md                  # This file
├── research.md              # Phase 0 — design decisions
├── data-model.md            # Phase 1 — frontend domain model
├── contracts/
│   ├── update-deployment-mutation.md   # Existing GraphQL contract (reference, not new)
│   ├── section-component.md            # Section component prop contract (internal contract)
│   └── impact-rule-table.md            # Impact heuristic rule format
├── quickstart.md            # How to develop and E2E test the feature
├── checklists/
│   └── requirements.md      # Phase 0 — spec quality checklist (committed in Phase 1)
└── tasks.md                 # Phase 4 output (/speckit-tasks)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── pages/
│   │   └── deployments/
│   │       └── DeploymentDetailPage.tsx                [modify: tabs Parameters → Configuration; remove Scheduling button]
│   ├── components/
│   │   └── deployment/
│   │       ├── configuration/                          [NEW directory]
│   │       │   ├── ConfigurationTab.tsx
│   │       │   ├── HeroSummaryBar.tsx
│   │       │   ├── ConfigSummaryCard.tsx
│   │       │   ├── InheritanceBadge.tsx
│   │       │   ├── ViewJsonDialog.tsx
│   │       │   ├── ConfigEditDrawer.tsx
│   │       │   ├── SectionNav.tsx
│   │       │   ├── DrawerFooter.tsx
│   │       │   ├── ConfigDiffDialog.tsx
│   │       │   ├── ImpactList.tsx
│   │       │   ├── DiffEntryRow.tsx
│   │       │   ├── ChangedFieldFrame.tsx               [shared wrapper that renders amber border + "changed" pill + "from X" annotation]
│   │       │   ├── sections/
│   │       │   │   ├── read/
│   │       │   │   │   ├── DriverParametersSummary.tsx
│   │       │   │   │   ├── SchedulingSummary.tsx
│   │       │   │   │   ├── NetworkingSummary.tsx
│   │       │   │   │   ├── EnvVarsSummary.tsx
│   │       │   │   │   ├── StorageRuntimeSummary.tsx
│   │       │   │   │   ├── ServiceOverridesSummary.tsx
│   │       │   │   │   └── ComponentOverridesSummary.tsx
│   │       │   │   └── edit/
│   │       │   │       ├── IdentitySection.tsx
│   │       │   │       ├── DriverParametersSection.tsx
│   │       │   │       ├── SchedulingSection.tsx
│   │       │   │       ├── NetworkingSection.tsx
│   │       │   │       ├── EnvVarsSection.tsx
│   │       │   │       ├── StorageRuntimeSection.tsx
│   │       │   │       ├── ServiceOverridesSection.tsx
│   │       │   │       └── ComponentOverridesSection.tsx
│   │       └── scheduling/                              [REMOVE entire directory after slice 11]
│   │           ├── SchedulingConfigDialog.tsx           [delete]
│   │           └── sanitize.ts                          [delete; relevant logic moves into SchedulingSection]
│   ├── lib/
│   │   ├── deployment-input.ts                          [exists, keep — used to project persisted config to UpdateDeploymentInput]
│   │   ├── config-diff.ts                               [NEW: compute path-level diff between persisted config and draft]
│   │   ├── config-impact.ts                             [NEW: apply the static heuristic rule table to a diff]
│   │   ├── config-inheritance.ts                        [NEW: classify each top-level group as inherited vs overridden against parent env config]
│   │   └── impact-rules.ts                              [NEW: declarative list of impact rules — see contracts/impact-rule-table.md]
│   └── graphql/
│       ├── get_deployment.graphql                       [exists; verify it already fetches deployment.config and parent env.config]
│       ├── get_environment_config.graphql               [NEW if needed; alternatively extend get_deployment to embed parent env config]
│       └── update_deployment.graphql                    [exists; no changes]
└── tests/
    └── unit/components/deployment/configuration/        [vitest + RTL coverage for diff, impact, inheritance helpers + smoke for each section]

backend/tests/e2e/configuration/                          [NEW directory]
├── test_configuration_tab_read.py                       [API + UI: read view shows correct inherited/overridden state]
├── test_drawer_scheduling_edit.py                       [UI-only: change CPU via drawer, verify pods restart]
├── test_drawer_env_vars_edit.py                         [UI-only]
├── test_drawer_storage_runtime_edit.py                  [UI-only]
├── test_drawer_networking_edit.py                       [UI-only]
├── test_drawer_service_overrides_edit.py                [UI-only]
├── test_drawer_driver_params_edit.py                    [UI-only]
├── test_drawer_component_overrides_edit.py              [UI-only]
└── test_drawer_multi_section_edit.py                    [UI-only: roll-up across two sections in one apply]
```

**Structure Decision**: Web-app structure (Option 2). All work concentrates in `frontend/`. A `configuration/` directory under `components/deployment/` houses the entire feature so it is easy to grep, lift, and (later) generalize to environment-level config. E2E scenarios go under `backend/tests/e2e/configuration/` to mirror the existing E2E layout under `backend/tests/e2e/`. The `scheduling/` directory is deleted in slice 11.

## Complexity Tracking

No constitution-check violations to justify. The feature stays within established patterns:

- TanStack Form is already on the project (no new form library).
- Radix Dialog is already used for existing dialogs (drawer animation is a Radix Dialog with a `data-side="right"` CSS variant rather than introducing Vaul or a custom drawer library — see `research.md`).
- Diff and impact are pure-function modules under `lib/`, mirroring the existing `lib/deployment-input.ts` pattern.
- No new lib/test directories beyond what the project already uses.
