# Quickstart: Migrate Frontend from Radix UI to Base UI

**Branch**: `001-base-ui-migration` | **Date**: 2026-04-05

## Prerequisites

- Node.js and pnpm installed
- Frontend dependencies installed (`cd frontend && pnpm install`)
- Existing tests passing (`pnpm test`)

## Migration Overview

This migration replaces 8 `@radix-ui/*` packages with a single `@base-ui/react` package. All changes are scoped to `frontend/src/components/ui/` wrapper components, with one Tailwind class update in a consuming file.

## Step-by-Step

### 1. Install Base UI and remove Radix

```bash
cd frontend
pnpm add @base-ui/react
pnpm remove @radix-ui/react-checkbox @radix-ui/react-collapsible @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-label @radix-ui/react-select @radix-ui/react-separator @radix-ui/react-slot
```

### 2. Migrate each component

Work through one component at a time. For each component:

1. Update the import to use the Base UI equivalent
2. Replace sub-part names per the mapping table in [plan.md](plan.md)
3. Update `data-[state=*]:` Tailwind selectors to `data-[*]:` format
4. Run `pnpm test` after each component to catch regressions early

**Migration order** (simplest to most complex):

| Order | Component | Complexity | Key Changes |
|-------|-----------|------------|-------------|
| 1 | `separator.tsx` | Trivial | Direct 1:1 swap |
| 2 | `label.tsx` | Trivial | Replace with native `<label>` |
| 3 | `collapsible.tsx` | Simple | Rename sub-parts |
| 4 | `button.tsx` | Simple | Replace Radix Slot with minimal Slot utility |
| 5 | `checkbox.tsx` | Simple | Swap primitive + update `data-[state=checked]:` |
| 6 | `dropdown-menu.tsx` | Medium | `DropdownMenu.*` → `Menu.*`, add Positioner |
| 7 | `dialog.tsx` | Medium | Overlay → Backdrop, Content → Popup, update animations |
| 8 | `select.tsx` | Complex | Most sub-parts to remap, CSS variable changes |

### 3. Update consuming file data attributes

After migrating the collapsible component, update the one consuming file:

- `src/pages/deployments/DeploymentDetailPage.tsx` line 706:
  - `group-data-[state=open]:rotate-90` → `group-data-[panel-open]:rotate-90`

### 4. Verify

```bash
# Run tests
pnpm test

# Type check
pnpm tsc --noEmit

# Lint
pnpm lint

# Verify no Radix references remain
grep -r "@radix-ui" src/ package.json
# Should return no results

# Check bundle size (compare before/after)
pnpm build
```

## Key Patterns

### Import pattern

```tsx
// Before (Radix)
import * as DialogPrimitive from "@radix-ui/react-dialog";

// After (Base UI)
import { Dialog } from "@base-ui/react/dialog";
```

### Data attribute selectors

```tsx
// Before (Radix)
"data-[state=open]:animate-in data-[state=closed]:fade-out-0"

// After (Base UI)
"data-[open]:animate-in data-[closed]:fade-out-0"
```

### Positioner pattern (new in Base UI)

```tsx
// Before (Radix) — positioning is internal
<DropdownMenuPrimitive.Portal>
  <DropdownMenuPrimitive.Content sideOffset={4}>
    {children}
  </DropdownMenuPrimitive.Content>
</DropdownMenuPrimitive.Portal>

// After (Base UI) — explicit Positioner
<Menu.Portal>
  <Menu.Positioner sideOffset={4}>
    <Menu.Popup>
      {children}
    </Menu.Popup>
  </Menu.Positioner>
</Menu.Portal>
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Tests fail on `data-state` queries | Update test selectors from `[data-state="open"]` to `[data-open]` |
| Animation classes not applying | Verify `data-[open]:` and `data-[closed]:` selectors replace `data-[state=open]:` |
| Select dropdown wrong size | Replace `--radix-select-trigger-*` CSS vars with Positioner's anchor sizing |
| Button `asChild` broken | Ensure the Slot utility merges props and className correctly |
