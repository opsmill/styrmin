# Tasks: TanStack Form Migration

**Input**: Design documents from `/specs/001-tanstack-form-migration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: No test tasks included — no form-specific tests exist and none were requested.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install TanStack Form dependencies and verify build

- [x] T001 Install `@tanstack/react-form` and `@tanstack/zod-form-adapter` in `frontend/package.json`
- [x] T002 Verify TypeScript compilation passes with new dependencies via `cd frontend && pnpm tsc --noEmit`
- [x] T003 Verify all existing tests still pass via `cd frontend && pnpm test`

**Checkpoint**: Dependencies installed, build and tests green — ready for form migrations

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No foundational tasks needed — TanStack Form requires no shared infrastructure, configuration, or wrapper components. Each form can be migrated independently using the `<form.Field>` render prop pattern directly.

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 1 - Simple Form Migration (Priority: P1) MVP

**Goal**: Migrate AddDriverPage (1-3 fields, two form instances) to TanStack Form, establishing the canonical migration pattern for all subsequent forms.

**Independent Test**: Navigate to Add Driver page, test both local and remote forms — fill fields, submit, verify driver creation. Test validation errors on invalid input. Test loading state during submission.

### Implementation for User Story 1

- [x] T004 [US1] Migrate local driver form in `frontend/src/pages/drivers/AddDriverPage.tsx`: replace `useForm`/`register`/`handleSubmit` with TanStack Form `useForm`/`<form.Field>` for the `localSchema` form instance. Retain `localSchema` Zod validation via `validatorAdapter: zodValidator()`. Preserve error display, submit loading state, and `useLoadLocalDriverMutation` submission flow.
- [x] T005 [US1] Migrate remote driver form in `frontend/src/pages/drivers/AddDriverPage.tsx`: replace the second `useForm`/`register`/`handleSubmit` with TanStack Form for the `remoteSchema` form instance. Retain `remoteSchema` Zod validation. Preserve error display, submit loading state, and `useLoadRemoteDriverMutation` submission flow.
- [x] T006 [US1] Remove `react-hook-form` and `@hookform/resolvers` imports from `frontend/src/pages/drivers/AddDriverPage.tsx`. Add `@tanstack/react-form` and `@tanstack/zod-form-adapter` imports.
- [x] T007 [US1] Verify AddDriverPage type-checks (`pnpm tsc --noEmit`), existing tests pass (`pnpm test`), and both local/remote forms work correctly in the browser.

**Checkpoint**: AddDriverPage fully migrated. Migration pattern proven for simple `register()`-only forms. Both local and remote driver loading forms work identically to pre-migration behavior.

---

## Phase 4: User Story 2 - Medium-Complexity Dialog Form Migration (Priority: P2)

**Goal**: Migrate CreateBackupStorageLocationDialog (6 fields, dialog pattern) and BackupStorageLocationDetailPage (2 fields, dialog credential update) to TanStack Form, proving the dialog + reset pattern.

**Independent Test**: Open Create BSL dialog, fill all 6 fields, submit, verify creation and dialog closes. Test validation on missing fields. Test BSL detail page credential update dialog — update, save, verify persistence. Test reset on dialog close.

### Implementation for User Story 2

- [x] T008 [P] [US2] Migrate form in `frontend/src/pages/backup-storage-locations/CreateBackupStorageLocationDialog.tsx`: replace `useForm`/`register`/`handleSubmit`/`reset` with TanStack Form. Retain `createBslSchema` Zod validation via `validatorAdapter: zodValidator()`. Preserve dialog open/close with `form.reset()` in `handleOpenChange`. Preserve per-field error display, submit loading state, and `useCreateBackupStorageLocationMutation` submission flow with query invalidation.
- [x] T009 [P] [US2] Migrate form in `frontend/src/pages/backup-storage-locations/BackupStorageLocationDetailPage.tsx`: replace `useForm`/`register`/`handleSubmit`/`reset` with TanStack Form for the credential update dialog. Retain `updateCredentialsSchema` Zod validation. Preserve dialog reset behavior and `useUpdateBackupStorageLocationMutation` submission flow. Leave delete functionality unchanged (it does not use RHF).
- [x] T010 [US2] Remove `react-hook-form` and `@hookform/resolvers` imports from both BSL files. Add TanStack Form imports.
- [x] T011 [US2] Verify both BSL pages type-check, tests pass, and dialog forms work correctly in the browser (create, update credentials, reset on close).

**Checkpoint**: Both BSL forms migrated. Dialog + form.reset() pattern proven. All medium-complexity forms work identically to pre-migration behavior.

---

## Phase 5: User Story 3 - High-Complexity Form Migration (Priority: P3)

**Goal**: Migrate DeployFormPage (dynamic fields, watch, setValue), CreateClusterDialog (conditional sections, cross-field validation), and CreateEnvironmentDialog (conditional sections, query-loaded select) to TanStack Form.

**Independent Test**: For DeployFormPage — select a driver with parameters, verify dynamic fields render and bind correctly, submit deployment. For CreateClusterDialog — toggle checkboxes, verify conditional sections show/hide, test cross-field validation (storage class required when enabled), submit. For CreateEnvironmentDialog — verify cluster select loads options, toggle ingress checkbox, submit.

### Implementation for User Story 3

- [x] T012 [P] [US3] Migrate form in `frontend/src/pages/deployments/DeployFormPage.tsx`: replace `useForm`/`register`/`Controller`/`watch`/`setValue`/`handleSubmit` with TanStack Form. Replace `Controller` for Radix Select (`applicationDriverVersionId`) with `<form.Field>` render prop using `field.state.value`/`field.handleChange`. Replace `watch("applicationDriverVersionId")` with `form.useStore(s => s.values.applicationDriverVersionId)`. Replace `setValue("applicationVersion", ...)` with `form.setFieldValue("applicationVersion", ...)`. Keep `dynamicParams` in `useState` (not part of form schema). Retain `deployFormSchema` Zod validation. Preserve `useDeployMutation` submission flow and `DynamicParameterField` component.
- [x] T013 [P] [US3] Migrate form in `frontend/src/pages/settings/CreateClusterDialog.tsx`: replace `useForm`/`register`/`Controller`/`watch`/`handleSubmit`/`reset` with TanStack Form. Replace `Controller` for Checkbox components with `<form.Field>` using `field.state.value`/`field.handleChange` mapped to `onCheckedChange`. Replace `watch("dedicated_ingress_enabled")` and `watch("standard_storage_enabled")` with `form.useStore()` selectors. Retain `createClusterSchema` with `.refine()` cross-field validation via form-level `validators: { onSubmit: createClusterSchema }`. Preserve dialog reset, `buildClusterConfig()` transform, and `useCreateClusterMutation` submission flow.
- [x] T014 [P] [US3] Migrate form in `frontend/src/pages/environments/CreateEnvironmentDialog.tsx`: replace `useForm`/`register`/`Controller`/`watch`/`handleSubmit`/`reset` with TanStack Form. Replace `Controller` for Radix Select (clusterId) and Checkbox (dedicated_ingress_enabled) with `<form.Field>` render props. Replace `watch("dedicated_ingress_enabled")` with `form.useStore()`. Retain `createEnvironmentSchema` Zod validation. Preserve dialog reset, IP whitelist comma-split logic, `buildEnvironmentConfig()` transform, and `useCreateEnvironmentMutation` submission flow. Preserve disabled state on Select while clusters are loading.
- [x] T015 [US3] Remove `react-hook-form` and `@hookform/resolvers` imports from all three files. Add TanStack Form imports.
- [x] T016 [US3] Verify all three high-complexity forms type-check, tests pass, and work correctly in the browser: dynamic parameters in Deploy, conditional sections in Create Cluster and Create Environment, cross-field validation in Create Cluster.

**Checkpoint**: All 6 forms migrated to TanStack Form. Every form works identically to pre-migration behavior. Zero RHF imports remain in page components.

---

## Phase 6: User Story 4 - Dependency Cleanup (Priority: P4)

**Goal**: Remove `react-hook-form` and `@hookform/resolvers` from the project. Verify zero references remain. Confirm build and tests pass.

**Independent Test**: Run `pnpm remove react-hook-form @hookform/resolvers`, then `pnpm tsc --noEmit && pnpm test && pnpm build`. Grep entire `frontend/src/` for any remaining `react-hook-form` or `@hookform/resolvers` imports — expect zero results.

### Implementation for User Story 4

- [x] T017 [US4] Remove `react-hook-form` and `@hookform/resolvers` from `frontend/package.json` via `cd frontend && pnpm remove react-hook-form @hookform/resolvers`
- [x] T018 [US4] Search `frontend/src/` for any remaining imports of `react-hook-form`, `@hookform/resolvers`, `useForm` from RHF, `Controller` from RHF, or `zodResolver`. Remove any found.
- [x] T019 [US4] Verify full build passes: `cd frontend && pnpm tsc --noEmit && pnpm test && pnpm build`

**Checkpoint**: Migration complete. Old dependencies fully removed. Clean build with only TanStack Form.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final verification and cleanup

- [x] T020 Run ESLint and Prettier across all modified files: `cd frontend && pnpm lint && pnpm format`
- [x] T021 Verify bundle size has not increased: compare `pnpm build` output stats before and after migration
- [x] T022 Run quickstart.md validation — follow the verification steps in `specs/001-tanstack-form-migration/quickstart.md` to confirm all patterns work

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: N/A — no foundational tasks
- **User Story 1 (Phase 3)**: Depends on Setup (Phase 1) completion
- **User Story 2 (Phase 4)**: Depends on Setup (Phase 1) — can run in parallel with US1 but recommended after US1 to leverage proven pattern
- **User Story 3 (Phase 5)**: Depends on Setup (Phase 1) — can run in parallel with US1/US2 but recommended after US1 to leverage proven pattern
- **User Story 4 (Phase 6)**: Depends on US1 + US2 + US3 all complete (ALL 6 forms must be migrated before removing old deps)
- **Polish (Phase 7)**: Depends on US4 completion

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories — establishes migration pattern
- **User Story 2 (P2)**: Independent of US1 (different files), but pattern knowledge from US1 is valuable
- **User Story 3 (P3)**: Independent of US1/US2 (different files), but builds on patterns from simpler forms
- **User Story 4 (P4)**: HARD dependency on US1 + US2 + US3 — cannot remove deps until all forms are migrated

### Within Each User Story

- Migrate form logic first, then update imports, then verify
- Each form file is self-contained — no cross-file dependencies within a story

### Parallel Opportunities

- T008 and T009 can run in parallel (different files in US2)
- T012, T013, and T014 can run in parallel (different files in US3)
- US1, US2, and US3 could theoretically run in parallel (all different files), though sequential is recommended for pattern refinement

---

## Parallel Example: User Story 3

```bash
# Launch all three high-complexity form migrations in parallel (different files):
Task: "Migrate DeployFormPage in frontend/src/pages/deployments/DeployFormPage.tsx"
Task: "Migrate CreateClusterDialog in frontend/src/pages/settings/CreateClusterDialog.tsx"
Task: "Migrate CreateEnvironmentDialog in frontend/src/pages/environments/CreateEnvironmentDialog.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (install deps)
2. Complete Phase 3: User Story 1 (migrate AddDriverPage)
3. **STOP and VALIDATE**: Both local and remote driver forms work correctly
4. Pattern proven — proceed with confidence

### Incremental Delivery

1. Setup → Dependencies installed
2. US1 → AddDriverPage migrated → Pattern proven (MVP!)
3. US2 → BSL forms migrated → Dialog pattern proven
4. US3 → Complex forms migrated → All patterns proven
5. US4 → Old deps removed → Migration complete
6. Polish → Build verified, bundle checked

### Parallel Team Strategy

With multiple developers:

1. All complete Phase 1: Setup together
2. Developer A: US1 (AddDriverPage) — first, to establish pattern
3. Once pattern proven:
   - Developer A: US3 DeployFormPage
   - Developer B: US2 (both BSL forms)
   - Developer C: US3 CreateClusterDialog + CreateEnvironmentDialog
4. All complete → Developer A: US4 cleanup

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each form migration is self-contained within its file — no shared form utilities or abstractions
- Zod schemas are preserved exactly — only the form library binding changes
- GraphQL mutation hooks and query invalidation are unchanged
- Refer to `quickstart.md` for the before/after code pattern reference
- Commit after each user story phase for clean git history
