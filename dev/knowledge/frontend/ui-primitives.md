<!-- Extracted from specs/001-base-ui-migration on 2026-04-26 -->

## Frontend UI Primitives

### Overview

Headless UI primitives are provided by **Base UI** (`@base-ui/react`). All consumption is funneled through a wrapper layer at `frontend/src/components/ui/` that owns the public API: CVA + Tailwind styling, `forwardRef` + `displayName` for DevTools, and minor structural details that consumers should not have to know about.

Consuming components (~23 files) import only from `components/ui/`. They never import from `@base-ui/react` directly.

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

<!-- Extracted from specs/012-deployment-pods-tab on 2026-05-15 -->

### Clipboard hook

`frontend/src/hooks/use-copy-to-clipboard.ts` is the shared wrapper around `navigator.clipboard.writeText`. It exposes:

- `copy(text: string) → Promise<boolean>` — writes the string and returns `true` on success, `false` if the browser rejected the request (denied permission, insecure context, focus loss).
- `copied: boolean` — flips to `true` on a successful write and resets to `false` after 2 s. A second copy inside that window resets the timer.

The hook clears its own timeout on unmount; callers never need to deal with `useEffect` cleanup for the toggle.

### Hand-rolled collapsible-section pattern

For chevron-fronted sections that toggle child content (Pods tab section cards, the per-pod `KubectlCommands` block), the project uses a hand-rolled pattern rather than always reaching for the Base UI `Collapsible` wrapper:

```tsx
const [open, setOpen] = useState(defaultOpen);
return (
  <div data-open={open}>
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      aria-expanded={open}
      aria-label={`${open ? "Collapse" : "Expand"} <thing>`}
    >
      <ChevronRight className={`transition-transform ${open ? "rotate-90" : ""}`} />
      {/* …rest of the header… */}
    </button>
    {open && /* …body… */}
  </div>
);
```

When to use this vs. the Base UI `Collapsible` wrapper:

- **Use `Collapsible`** when you want the animated expand/collapse, the ARIA wiring handled for you, and child content that stays mounted while hidden.
- **Use the hand-rolled pattern** when you want children to actually unmount on collapse (so expensive child render paths don't run until needed) or when you need a `data-open` attribute on the wrapper for downstream selectors / E2E test assertions.
