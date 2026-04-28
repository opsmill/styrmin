## ADR-013: Migrate Frontend UI Primitives from Radix UI to Base UI

**Status**: Accepted
**Date**: 2026-04-26
**Source**: specs/archive/001-base-ui-migration/research.md (R1–R10)

## Context

The frontend's `components/ui/` wrapper layer (Button, Checkbox, Collapsible, Dialog, DropdownMenu, Label, Select, Separator) was built on eight separate `@radix-ui/react-*` packages plus `@radix-ui/react-slot` for the Button's `asChild` polymorphic-render pattern. CVA + Tailwind handled all styling; consuming components imported only from the wrapper layer (23 files), so the underlying primitive library was already encapsulated.

Base UI is maintained by the original Radix co-founder (Colm Tuite) together with former MUI engineers and was designed as the long-term successor to Radix's headless primitives. It ships as a single tree-shakable package, simplifies the data-attribute model, and aligns the project on a smaller dependency footprint.

## Decision

Replace all Radix primitives in the wrapper layer with `@base-ui/react` equivalents while keeping the wrapper layer's public API unchanged:

1. **Component mapping** (within `components/ui/`):
   - `Dialog`: `Overlay` → `Backdrop`, `Content` → `Popup`. `Portal`, `Close`, `Trigger` retain wrapper names pointing at Base UI equivalents.
   - `DropdownMenu` → Base UI `Menu` with an explicit `Menu.Positioner` between `Menu.Portal` and `Menu.Popup` (Base UI requires explicit positioning; Radix did this implicitly). `sideOffset` becomes a Positioner style/prop.
   - `Select`: `Content` → `Positioner` + `Popup`, `Viewport` → `List`, scroll *Buttons* → scroll *Arrows*. CSS variables for trigger sizing change from `--radix-select-trigger-*` to Base UI's anchor-sizing approach.
   - `Checkbox`, `Collapsible`, `Separator`: direct API mappings.
   - `Label`: replace Radix `Label.Root` with a native `<label>` element (preserving the existing CVA + `forwardRef` wrapper) — Base UI's `Field.Label` requires a `Field.Root` context that adds ceremony for what is effectively a styled label.
2. **Polymorphic Button (`asChild`)**: implement an in-house `Slot` utility (~30 lines in `components/ui/slot.tsx`) — a `forwardRef` wrapper that uses `React.isValidElement` + `cloneElement` to merge props, refs, and `className` onto the child. Do **not** import `@radix-ui/react-slot`; do not add `react-slot` libraries; do not change Button's public API. This satisfies the constraint that consuming files require zero changes.
3. **Data attribute conventions**: Tailwind selectors must move from Radix's string-valued `data-state="open"` model to Base UI's boolean presence model:
   - `data-[state=open]:` → `data-[open]:`
   - `data-[state=closed]:` → `data-[closed]:`
   - `data-[state=checked]:` → `data-[checked]:`
   - `data-[state=unchecked]:` → `data-[unchecked]:`
   - Collapsible trigger: `data-[state=open]` → `data-[panel-open]` (Base UI's specific name on the trigger). This is the **one** consuming-file change required (in `DeploymentDetailPage.tsx`).
4. **`forwardRef` + `displayName`**: retained as-is on every wrapper. React 19's regular-prop ref support is real, but converting wrappers is a separate concern and out of scope for a primitive swap.
5. Remove all eight `@radix-ui/*` packages; add `@base-ui/react`.

## Consequences

**Easier:**

- Single dependency (`@base-ui/react`) replaces eight `@radix-ui/*` packages — fewer version-skew opportunities, simpler upgrades.
- Boolean data attributes (`data-open`) are simpler to reason about in Tailwind selectors than Radix's `data-state="..."` strings.
- Future primitives stay on Base UI; the wrapper layer is now the single chokepoint for primitive choices, and the `Slot` utility keeps polymorphic-render under the project's own control.

**Harder:**

- Base UI requires an explicit `Positioner` for menus and selects; the wrapper layer absorbs this structural change but contributors writing new primitives must remember it.
- The in-house `Slot` is intentionally minimal — it does not implement every edge case `@radix-ui/react-slot` covers (e.g., complex children, asChild on asChild). If a consumer needs richer composition, the wrapper layer must extend `Slot`, not reach for a third-party slot package.
- One Tailwind selector in `DeploymentDetailPage.tsx` (`group-data-[state=open]` → `group-data-[panel-open]`) breaks the "zero consuming-file changes" goal. Documented as a known one-off; future Collapsible consumers must use `data-panel-open`.
- The native `<label>` Label loses any future Base UI Field-context features; if those are wanted later, the wrapper must opt into `Field.Root`.

## Alternatives Considered

- **Stay on Radix UI**: Functionally equivalent with no migration cost. Rejected because the user explicitly requested Base UI and the consolidation benefits (one package, simpler attributes, successor library) compound over time.
- **React Aria (Adobe)**: Hooks-based rather than compound-component based; would force a much larger architectural change in the wrapper layer.
- **Ark UI**: Compound-component library from the Chakra team; smaller community and less mature than Base UI.
- **Use `@radix-ui/react-slot` for the Button's `asChild`**: Would leave one Radix dependency in `package.json`, undermining the migration's clean-removal goal.
- **Drop `forwardRef` while migrating** (since React 19 supports refs as regular props): Rejected as scope creep; doing both at once muddies the diff and risks regressions unrelated to the primitive swap.
