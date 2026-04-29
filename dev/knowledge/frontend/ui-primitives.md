<!-- Extracted from specs/001-base-ui-migration on 2026-04-26 -->

## Frontend UI Primitives

### Overview

Headless UI primitives are provided by **Base UI** (`@base-ui/react`). All consumption is funneled through a wrapper layer at `frontend/src/components/ui/` that owns the public API: CVA + Tailwind styling, `forwardRef` + `displayName` for DevTools, and minor structural details that consumers should not have to know about.

Consuming components (~23 files) import only from `components/ui/`. They never import from `@base-ui/react` directly.

See [ADR-013](../../adr/adr-013-migrate-ui-primitives-to-base-ui.md) for the migration rationale.

### Wrapper Inventory

| Wrapper | Base UI primitive | Notable shape |
|---------|-------------------|---------------|
| `Button` | none (CVA + native `<button>`) | Polymorphic via in-house `Slot` for `asChild` |
| `Checkbox` | `Checkbox` | Direct mapping |
| `Collapsible` | `Collapsible` | Trigger uses `data-panel-open` (not `data-state`) |
| `Dialog` | `Dialog` | `Overlay` → `Backdrop`, `Content` → `Popup` |
| `DropdownMenu` | `Menu` | Adds explicit `Menu.Positioner` between `Portal` and `Popup` |
| `Label` | none (native `<label>`) | Base UI `Field.Label` requires `Field.Root` ceremony — not used |
| `Select` | `Select` | `Content` → `Positioner` + `Popup`, `Viewport` → `List`, scroll Buttons → Arrows |
| `Separator` | `Separator` | Direct mapping |

### The Slot Utility

The `Button` component's `asChild` prop (e.g. to render a button as a router `<Link>`) is backed by `frontend/src/components/ui/slot.tsx` — a small (~30 LOC) `forwardRef` wrapper that uses `React.isValidElement` + `cloneElement` to merge props, refs, and `className` onto a single child element. There is no third-party slot package in the dependency tree.

Behavior worth knowing:

- It expects exactly one valid React element as `children`. In dev (`import.meta.env.DEV`) it logs an error and returns `null` if that contract is violated; in prod it returns `null` silently.
- The `ref` is forwarded onto the cloned child.
- `className` is merged via `cn(...)` (parent first, child last).
- Child props win over parent props on direct collisions (the spread order is `{ ...parentProps, ...childProps, ref, className: cn(...) }`).

If a richer composition story is ever needed, extend `Slot` in the wrapper layer rather than reaching for `@radix-ui/react-slot` or similar.

### Data Attribute Conventions

Base UI exposes state via **boolean presence** attributes, not string values. Tailwind selectors must use the boolean form:

| Concept | Selector |
|---------|----------|
| Open / closed | `data-[open]:` / `data-[closed]:` |
| Checked / unchecked | `data-[checked]:` / `data-[unchecked]:` |
| Collapsible trigger (panel state) | `data-[panel-open]:` |
| Popup placement (Menu, Select) | `data-[side=top\|right\|bottom\|left]:` (string-valued — used to direct slide-in animations) |

Selectors of the form `data-[state=open]:` are the **previous** Radix model and must not appear in new code. The single consuming-file exception lives in `DeploymentDetailPage.tsx` (`group-data-[panel-open]:rotate-90` for the Collapsible chevron).

### Positioner Pattern (Menu, Select)

Base UI requires an explicit `Positioner` component between `Portal` and `Popup`. Radix did this implicitly, so this is the main structural difference contributors will encounter when adding a new menu or select.

```tsx
<Menu.Portal>
  <Menu.Positioner sideOffset={4}>
    <Menu.Popup>
      <Menu.Item>...</Menu.Item>
    </Menu.Popup>
  </Menu.Positioner>
</Menu.Portal>
```

Trigger sizing for `Select` uses Base UI's anchor-sizing approach on the Positioner. The Radix-era `--radix-select-trigger-height` / `--radix-select-trigger-width` CSS variables are gone.

### `forwardRef` and `displayName`

All wrappers retain `forwardRef` and assign `displayName`. React 19 supports refs as regular props, but converting wrappers to drop `forwardRef` is a separate refactor and intentionally out of scope.

### What Was Replaced

| Concept | Before (Radix UI) | After (Base UI) |
|---------|-------------------|-----------------|
| Package | 8 × `@radix-ui/*` | 1 × `@base-ui/react` |
| State attributes | `data-state="open"`, etc. | boolean `data-open`, `data-checked`, `data-panel-open`, ... |
| Polymorphic render | `Slot` from `@radix-ui/react-slot` | in-house `Slot` (~30 LOC) |
| Dialog content | `Dialog.Overlay` + `Dialog.Content` | `Dialog.Backdrop` + `Dialog.Popup` |
| Dropdown | `DropdownMenu.Content` (auto-positioned) | `Menu.Positioner` + `Menu.Popup` |
| Select | `Select.Content` + `Select.Viewport` + scroll Buttons | `Select.Positioner` + `Select.Popup` + `Select.List` + scroll Arrows |
| Label | `@radix-ui/react-label` `Label.Root` | native `<label>` |
