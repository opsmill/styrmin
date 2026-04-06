# Tasks: Migrate Frontend from Radix UI to Base UI

**Input**: Design documents from `/specs/001-base-ui-migration/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, quickstart.md

**Tests**: Not explicitly requested in the feature specification. Test tasks are limited to verifying existing tests still pass (FR-009).

**Organization**: US1 (interactive behavior), US2 (visual consistency), and US3 (accessibility) are all P1 and inherently achieved together when each component is migrated. They are grouped as a single migration phase. US4 (tests pass) and US5 (dependency cleanup) follow as separate phases.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Dependency Swap)

**Purpose**: Install Base UI and remove Radix packages so the migration can begin

- [x] T001 Record pre-migration bundle size by running `cd frontend && pnpm build` and noting the output size
- [x] T002 Swap dependencies: run `cd frontend && pnpm add @base-ui/react && pnpm remove @radix-ui/react-checkbox @radix-ui/react-collapsible @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-label @radix-ui/react-select @radix-ui/react-separator @radix-ui/react-slot` in `frontend/package.json`

**Checkpoint**: `@base-ui/react` is in `frontend/package.json` dependencies, no `@radix-ui/*` packages remain. Build will fail until components are migrated.

---

## Phase 2: Foundational (Slot Utility)

**Purpose**: Create the Slot utility needed by Button before any component migration

**⚠️ CRITICAL**: The Button component depends on this utility. Must complete before Phase 3.

- [x] T003 Create minimal Slot utility component in `frontend/src/components/ui/slot.tsx` that merges props, className (via `cn`), and refs onto a single child element — replacing `@radix-ui/react-slot` per research decision R3. Must accept `React.PropsWithChildren` and use `React.cloneElement`. Keep under 20 lines.

**Checkpoint**: Slot utility ready for Button migration.

---

## Phase 3: User Stories 1+2+3 — Component Migration (Priority: P1) 🎯 MVP

**Goal**: Migrate all 8 Radix-based UI wrapper components to Base UI equivalents, preserving identical interactive behavior (US1), visual appearance (US2), and keyboard/screen-reader accessibility (US3).

**Independent Test**: Exercise every interactive component in the application — open dialogs, select options, toggle checkboxes, expand collapsibles, use dropdown menus. All behavior, styling, and keyboard navigation must match pre-migration behavior.

### Trivial Components (parallel — different files, no interdependencies)

- [x] T004 [P] [US1] Migrate `frontend/src/components/ui/separator.tsx`: replace `import * as SeparatorPrimitive from "@radix-ui/react-separator"` with `import { Separator as SeparatorPrimitive } from "@base-ui/react/separator"`. Update `SeparatorPrimitive.Root` to `SeparatorPrimitive`. Preserve `forwardRef`, `displayName`, `orientation` and `decorative` props, and all Tailwind classes. Exported name `Separator` must not change.

- [x] T005 [P] [US1] Migrate `frontend/src/components/ui/label.tsx`: remove `import * as LabelPrimitive from "@radix-ui/react-label"`, replace `LabelPrimitive.Root` with a native HTML `<label>` element per research decision R7. Preserve the `forwardRef` wrapper, CVA `labelVariants`, `cn` class merging, and `displayName`. Exported name `Label` and its prop types (including `VariantProps<typeof labelVariants>`) must not change. Update the `ComponentRef` / `ComponentPropsWithoutRef` types to use `HTMLLabelElement` instead of `typeof LabelPrimitive.Root`.

- [x] T006 [P] [US1] Migrate `frontend/src/components/ui/collapsible.tsx`: replace `import * as CollapsiblePrimitive from "@radix-ui/react-collapsible"` with `import { Collapsible as CollapsiblePrimitive } from "@base-ui/react/collapsible"`. Map: `CollapsiblePrimitive.Root` → `CollapsiblePrimitive.Root`, `CollapsiblePrimitive.CollapsibleTrigger` → `CollapsiblePrimitive.Trigger`, `CollapsiblePrimitive.CollapsibleContent` → `CollapsiblePrimitive.Panel`. Exported names `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` must not change.

- [x] T007 [P] [US1] Migrate `frontend/src/components/ui/button.tsx`: replace `import { Slot } from "@radix-ui/react-slot"` with `import { Slot } from "@/components/ui/slot"` (the utility created in T003). All other code remains identical — the `asChild` prop, CVA `buttonVariants`, `forwardRef`, `displayName`, and exported names `Button` and `buttonVariants` must not change.

### Simple Components (parallel — different files)

- [x] T008 [P] [US1] Migrate `frontend/src/components/ui/checkbox.tsx`: replace `import * as CheckboxPrimitive from "@radix-ui/react-checkbox"` with `import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"`. Map `CheckboxPrimitive.Root` → `CheckboxPrimitive.Root`, `CheckboxPrimitive.Indicator` → `CheckboxPrimitive.Indicator`. Update Tailwind classes: `data-[state=checked]:bg-primary` → `data-[checked]:bg-primary`, `data-[state=checked]:text-primary-foreground` → `data-[checked]:text-primary-foreground`. Preserve `forwardRef`, `displayName`, Lucide `Check` icon, and exported name `Checkbox`.

### Medium Components (parallel — different files)

- [x] T009 [P] [US1] Migrate `frontend/src/components/ui/dropdown-menu.tsx`: replace `import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu"` with `import { Menu } from "@base-ui/react/menu"`. Map: `DropdownMenuPrimitive.Root` → `Menu.Root`, `DropdownMenuPrimitive.Trigger` → `Menu.Trigger`, `DropdownMenuPrimitive.Portal` → `Menu.Portal`, `DropdownMenuPrimitive.Content` → `Menu.Positioner` wrapping `Menu.Popup`, `DropdownMenuPrimitive.Item` → `Menu.Item`, `DropdownMenuPrimitive.Separator` → `Menu.Separator`. Convert `sideOffset` prop to `Menu.Positioner` `sideOffset` prop. Update Tailwind classes: all `data-[state=open]:` → `data-[open]:`, all `data-[state=closed]:` → `data-[closed]:`. Preserve `forwardRef`, `displayName`, `inset` prop on `DropdownMenuItem`, and all exported names (`DropdownMenu`, `DropdownMenuTrigger`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuSeparator`).

- [x] T010 [P] [US1] Migrate `frontend/src/components/ui/dialog.tsx`: replace `import * as DialogPrimitive from "@radix-ui/react-dialog"` with `import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"`. Map: `DialogPrimitive.Root` → `DialogPrimitive.Root`, `DialogPrimitive.Trigger` → `DialogPrimitive.Trigger`, `DialogPrimitive.Portal` → `DialogPrimitive.Portal`, `DialogPrimitive.Close` → `DialogPrimitive.Close`, `DialogPrimitive.Overlay` → `DialogPrimitive.Backdrop`, `DialogPrimitive.Content` → `DialogPrimitive.Popup`, `DialogPrimitive.Title` → `DialogPrimitive.Title`, `DialogPrimitive.Description` → `DialogPrimitive.Description`. Update all Tailwind classes: `data-[state=open]:` → `data-[open]:`, `data-[state=closed]:` → `data-[closed]:`. Preserve `forwardRef`, `displayName` for all sub-components, Lucide `X` icon, and all exported names (`Dialog`, `DialogPortal`, `DialogOverlay`, `DialogTrigger`, `DialogClose`, `DialogContent`, `DialogHeader`, `DialogFooter`, `DialogTitle`, `DialogDescription`).

### Complex Component

- [x] T011 [US1] Migrate `frontend/src/components/ui/select.tsx`: replace `import * as SelectPrimitive from "@radix-ui/react-select"` with `import { Select as SelectPrimitive } from "@base-ui/react/select"`. Map: `SelectPrimitive.Root` → `SelectPrimitive.Root`, `SelectPrimitive.Group` → `SelectPrimitive.Group`, `SelectPrimitive.Value` → `SelectPrimitive.Value`, `SelectPrimitive.Trigger` → `SelectPrimitive.Trigger`, `SelectPrimitive.Icon` (with `asChild`) → `SelectPrimitive.Icon` (with `render` prop), `SelectPrimitive.Portal` → `SelectPrimitive.Portal`, `SelectPrimitive.Content` → `SelectPrimitive.Positioner` wrapping `SelectPrimitive.Popup`, `SelectPrimitive.Viewport` → `SelectPrimitive.List`, `SelectPrimitive.ScrollUpButton` → `SelectPrimitive.ScrollUpArrow`, `SelectPrimitive.ScrollDownButton` → `SelectPrimitive.ScrollDownArrow`, `SelectPrimitive.Label` → `SelectPrimitive.GroupLabel`, `SelectPrimitive.Item` → `SelectPrimitive.Item`, `SelectPrimitive.ItemIndicator` → `SelectPrimitive.ItemIndicator`, `SelectPrimitive.ItemText` → `SelectPrimitive.ItemText`, `SelectPrimitive.Separator` → `SelectPrimitive.Separator`. Replace CSS variable `--radix-select-trigger-height` → use Positioner anchor sizing, `--radix-select-trigger-width` → use Positioner anchor sizing. Update Tailwind: all `data-[state=open]:` → `data-[open]:`, `data-[state=closed]:` → `data-[closed]:`. Preserve `forwardRef`, `displayName`, `position` prop handling, Lucide icons, and all exported names (`Select`, `SelectGroup`, `SelectValue`, `SelectTrigger`, `SelectContent`, `SelectLabel`, `SelectItem`, `SelectSeparator`, `SelectScrollUpButton`, `SelectScrollDownButton`).

### Consuming File Update

- [x] T012 [US2] Update `frontend/src/pages/deployments/DeploymentDetailPage.tsx` line 706: change `group-data-[state=open]:rotate-90` to `group-data-[panel-open]:rotate-90` per research decision R9 (Base UI Collapsible uses `data-panel-open` on trigger elements).

**Checkpoint**: All 8 components migrated. Application should render and behave identically to pre-migration state. All interactive behavior (US1), visual styling (US2), and accessibility (US3) preserved.

---

## Phase 4: User Story 4 — Existing Tests Pass (Priority: P2)

**Goal**: Verify all existing frontend tests pass after migration, fixing any DOM query or attribute selector issues.

**Independent Test**: Run `cd frontend && pnpm test` and confirm 100% pass rate.

- [x] T013 [US4] Run `cd frontend && pnpm test` and catalog any failures. For each failure, determine if it's caused by changed data attributes (e.g., `[data-state="open"]` → `[data-open]`) or changed DOM structure. Document findings.
- [x] T014 [US4] Fix any test failures by updating DOM queries and attribute selectors in test files under `frontend/src/`. Changes must be limited to test infrastructure (attribute selectors, DOM queries) — do not change test assertions or behavioral expectations per FR-009.
- [x] T015 [US4] Run `cd frontend && pnpm test` and confirm all tests pass.

**Checkpoint**: Full test suite green. US4 acceptance criteria met.

---

## Phase 5: User Story 5 — Radix Fully Removed (Priority: P2)

**Goal**: Confirm zero Radix UI references remain anywhere in the codebase.

**Independent Test**: Search for `@radix-ui` across the entire frontend directory and `package.json` — zero results expected.

- [x] T016 [US5] Verify no `@radix-ui` imports remain: search all files under `frontend/src/` for `@radix-ui` and `radix` references. Also check `frontend/package.json` and `frontend/pnpm-lock.yaml`. If any references found, remove them.
- [x] T017 [US5] Verify `@base-ui/react` is listed in `frontend/package.json` dependencies.

**Checkpoint**: Clean dependency tree. US5 acceptance criteria met.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification across all success criteria

- [x] T018 [P] Run TypeScript type check: `cd frontend && pnpm tsc --noEmit` — fix any type errors
- [x] T019 [P] Run linter: `cd frontend && pnpm lint` — fix any lint errors
- [x] T020 Build and measure bundle size: `cd frontend && pnpm build` — compare output size to T001 baseline. Verify increase is less than 5% per SC-006.
- [x] T021 Final manual verification: open the application and exercise all interactive components (dialog, dropdown menu, select, checkbox, collapsible) to confirm behavior, styling, and keyboard navigation match pre-migration state.

**Checkpoint**: All success criteria (SC-001 through SC-006) verified. Migration complete.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on T002 (packages installed)
- **Component Migration (Phase 3)**: Depends on T003 (Slot utility). T004–T008 can all run in parallel. T009–T010 can run in parallel. T011 can run in parallel with T009/T010 but is the most complex. T012 depends on T006 (collapsible migration).
- **Test Verification (Phase 4)**: Depends on Phase 3 completion (all components migrated)
- **Dependency Cleanup (Phase 5)**: Depends on Phase 3 completion
- **Polish (Phase 6)**: Depends on Phases 4 and 5

### User Story Independence

Since US1, US2, and US3 are all achieved simultaneously through component migration:

- **US1+US2+US3 (Phase 3)**: Core migration — the MVP. Can stop here for a functional application.
- **US4 (Phase 4)**: Independent verification — can run immediately after Phase 3.
- **US5 (Phase 5)**: Independent verification — can run in parallel with Phase 4.

### Parallel Opportunities

```text
Phase 1: T001 ─── T002 (sequential — T002 needs baseline from T001)

Phase 2: T003 (single task)

Phase 3: T004 ─┬─ T005 ─┬─ T006 ─┬─ T007 (all parallel — different files)
               │         │         │
               T008 ─────┤         T012 (depends on T006)
                         │
               T009 ─┬── T010 (parallel — different files)
                     │
                     T011 (can parallel with T009/T010)

Phase 4: T013 → T014 → T015 (sequential)

Phase 5: T016 ─── T017 (parallel with Phase 4)

Phase 6: T018 ─┬─ T019 (parallel)
               │
               T020 → T021 (sequential — build then verify)
```

---

## Implementation Strategy

### MVP First (Phase 1 + 2 + 3)

1. Complete Phase 1: Swap dependencies
2. Complete Phase 2: Create Slot utility
3. Complete Phase 3: Migrate all 8 components + 1 consuming file update
4. **STOP and VALIDATE**: Manually test all interactive components
5. Application is fully functional with Base UI

### Full Delivery

1. Phases 1–3 → MVP functional
2. Phase 4 → Test suite verified green
3. Phase 5 → Dependency tree clean
4. Phase 6 → Type check, lint, bundle size, final sign-off

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks in the same phase
- All component migrations preserve the public API (exported names, prop types) — consuming files need zero import changes
- The one consuming file change (T012) is a Tailwind class update, not an import/API change
- Component migration order (trivial → simple → medium → complex) follows quickstart.md recommendation
- Each component migration task includes the full mapping from plan.md for self-contained executability
