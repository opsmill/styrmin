# Implementation Plan: Migrate Frontend from Radix UI to Base UI

**Branch**: `001-base-ui-migration` | **Date**: 2026-04-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-base-ui-migration/spec.md`

## Summary

Replace all Radix UI primitive dependencies with Base UI (`@base-ui/react`) across the 8 wrapper components in `frontend/src/components/ui/`. The migration preserves the existing public API (exported component names, props, and composition patterns) so that 23 consuming files require zero changes. Key technical work involves mapping Radix's `asChild`/`Slot` pattern to Base UI's `render` prop, translating `data-[state=*]` Tailwind selectors to Base UI's boolean `data-*` attributes, and handling structural differences like `Dialog.Overlay` → `Dialog.Backdrop` and `DropdownMenu.*` → `Menu.*`.

## Technical Context

**Language/Version**: TypeScript ~5.9.3, React 19.2.4
**Primary Dependencies**: Base UI (`@base-ui/react`), Tailwind CSS 4.2.2, class-variance-authority, Lucide React, tailwind-merge
**Storage**: N/A (frontend-only change)
**Testing**: Vitest 4.1.0, React Testing Library 16.3.2
**Target Platform**: Web (SPA via Vite 8.0.1)
**Project Type**: Web application (frontend only for this feature)
**Performance Goals**: Bundle size must not increase by more than 5% (SC-006)
**Constraints**: Zero changes to consuming component import statements or usage patterns (FR-011)
**Scale/Scope**: 8 UI wrapper components, 23 consuming files, ~6 Tailwind data-attribute selectors to update, 1 CSS variable reference to remap

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Backend concern, not affected |
| II. Driver-Based Deployment | N/A | Backend concern, not affected |
| III. Layered Architecture | N/A | Backend concern, not affected |
| IV. Type Safety and Typed Errors | PASS | TypeScript strict mode preserved; component prop types maintained |
| V. Test-First Development | PASS | Existing tests must pass (FR-009); test updates for DOM query changes acceptable |
| VI. Format and Lint Before Commit | PASS | ESLint + Prettier for frontend; will run before commits |

**Governance Gates:**

| Gate | Triggered? | Action Required |
|------|-----------|----------------|
| New dependencies | YES | Adding `@base-ui/react`, removing 8 `@radix-ui/*` packages — net reduction in dependency count |
| Database schema changes | No | — |
| GraphQL schema changes | No | — |
| CI/CD workflow changes | No | — |
| Auth/authz changes | No | — |

**Gate Resolution**: The dependency change is a swap (8 packages → 1 package), not an addition of new capability. This is the explicit purpose of the feature. **GATE PASSED.**

## Project Structure

### Documentation (this feature)

```text
specs/001-base-ui-migration/
├── plan.md              # This file
├── research.md          # Phase 0: API mapping and migration patterns
├── quickstart.md        # Phase 1: Developer migration guide
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
frontend/
├── package.json                          # Dependency swap: remove @radix-ui/*, add @base-ui/react
├── src/
│   ├── components/
│   │   └── ui/
│   │       ├── button.tsx                # Migrate Slot/asChild → render prop or native approach
│   │       ├── checkbox.tsx              # Migrate CheckboxPrimitive → Checkbox from @base-ui/react/checkbox
│   │       ├── collapsible.tsx           # Migrate CollapsiblePrimitive → Collapsible from @base-ui/react/collapsible
│   │       ├── dialog.tsx                # Migrate DialogPrimitive → Dialog from @base-ui/react/dialog
│   │       ├── dropdown-menu.tsx         # Migrate DropdownMenuPrimitive → Menu from @base-ui/react/menu
│   │       ├── label.tsx                 # Migrate LabelPrimitive → native <label> or Field.Label
│   │       ├── select.tsx               # Migrate SelectPrimitive → Select from @base-ui/react/select
│   │       └── separator.tsx            # Migrate SeparatorPrimitive → Separator from @base-ui/react/separator
│   └── pages/
│       └── deployments/
│           └── DeploymentDetailPage.tsx  # Update data-[state=open] → data-[open] (line 706)
└── tests/                                # Verify all existing tests pass; update DOM queries if needed
```

**Structure Decision**: This is a frontend-only refactor scoped entirely within the existing `frontend/src/components/ui/` directory. No new directories or architectural changes are needed. One consuming file (`DeploymentDetailPage.tsx`) requires a Tailwind class update.

## Complexity Tracking

No constitution violations. No complexity justifications needed.

## Migration Mapping Reference

### Component Mapping

| Current (Radix) | Target (Base UI) | Import Path |
|------------------|------------------|-------------|
| `@radix-ui/react-checkbox` | `Checkbox` | `@base-ui/react/checkbox` |
| `@radix-ui/react-collapsible` | `Collapsible` | `@base-ui/react/collapsible` |
| `@radix-ui/react-dialog` | `Dialog` | `@base-ui/react/dialog` |
| `@radix-ui/react-dropdown-menu` | `Menu` | `@base-ui/react/menu` |
| `@radix-ui/react-label` | Native `<label>` | N/A (plain HTML) |
| `@radix-ui/react-select` | `Select` | `@base-ui/react/select` |
| `@radix-ui/react-separator` | `Separator` | `@base-ui/react/separator` |
| `@radix-ui/react-slot` | `render` prop | N/A (built into Base UI components) |

### Sub-Part Mapping

| Radix | Base UI | Notes |
|-------|---------|-------|
| `Dialog.Overlay` | `Dialog.Backdrop` | Renamed |
| `Dialog.Content` | `Dialog.Popup` | Renamed; positioned inside `Dialog.Portal` |
| `DropdownMenu.Root` | `Menu.Root` | Different namespace |
| `DropdownMenu.Content` | `Menu.Popup` inside `Menu.Positioner` | Needs wrapping `Positioner` |
| `DropdownMenu.Item` | `Menu.Item` | Direct mapping |
| `DropdownMenu.Separator` | `Menu.Separator` | Direct mapping |
| `Select.Content` | `Select.Popup` inside `Select.Positioner` | Needs wrapping `Positioner` |
| `Select.Viewport` | `Select.List` | Renamed |
| `Select.ScrollUpButton` | `Select.ScrollUpArrow` | Renamed |
| `Select.ScrollDownButton` | `Select.ScrollDownArrow` | Renamed |
| `Select.Icon` (with `asChild`) | `Select.Icon` | Direct; use `render` prop instead of `asChild` |
| `Collapsible.CollapsibleTrigger` | `Collapsible.Trigger` | Simplified name |
| `Collapsible.CollapsibleContent` | `Collapsible.Panel` | Renamed |

### Tailwind Data Attribute Mapping

| Current Radix Selector | Base UI Selector | Files Affected |
|------------------------|------------------|----------------|
| `data-[state=open]:` | `data-[open]:` | dialog.tsx, dropdown-menu.tsx, select.tsx, DeploymentDetailPage.tsx |
| `data-[state=closed]:` | `data-[closed]:` | dialog.tsx, dropdown-menu.tsx, select.tsx |
| `data-[state=checked]:` | `data-[checked]:` | checkbox.tsx |
| `group-data-[state=open]:` | `group-data-[panel-open]:` | DeploymentDetailPage.tsx (collapsible trigger context) |

### CSS Variable Mapping

| Current Radix Variable | Base UI Equivalent | File |
|------------------------|--------------------|------|
| `--radix-select-trigger-height` | `--anchor-height` (via Positioner) | select.tsx |
| `--radix-select-trigger-width` | `--anchor-width` (via Positioner) | select.tsx |

### Button `asChild` Migration

The Button component uses `Slot` from `@radix-ui/react-slot` for the `asChild` prop pattern. Since Button is a custom wrapper (not a Base UI component), this needs a standalone solution:

- **Option A**: Keep the `asChild` prop on the Button public API but implement it using Base UI's internal `render` approach or React 19's native ref forwarding without Radix Slot.
- **Option B**: Since React 19 supports `ref` as a regular prop, implement a minimal `Slot`-like component that merges props and refs onto the child element.
- **Recommended**: Option B — a small utility function (< 20 lines) that replicates `Slot` behavior, keeping the `asChild` public API intact for consuming components (satisfying FR-011).
