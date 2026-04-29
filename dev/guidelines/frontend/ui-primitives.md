<!-- Extracted from specs/001-base-ui-migration on 2026-04-26 -->

## Frontend UI Primitives Guidelines

Conventions for adding and consuming headless UI components built on Base UI. See [knowledge/frontend/ui-primitives.md](../../knowledge/frontend/ui-primitives.md) for the architectural overview and [ADR-013](../../adr/adr-013-migrate-ui-primitives-to-base-ui.md) for context.

### Wrapper Layer is the Boundary

- Consuming components import only from `frontend/src/components/ui/`. They must never import from `@base-ui/react` directly. This keeps the primitive choice swappable and ensures every consumer benefits from the wrapper layer's CVA + Tailwind styling.
- Add new primitive wrappers under `components/ui/` and export them through the existing index (or follow whatever pattern is established for the wrapper family you are adding to).

### Library Choice

- New primitives must build on Base UI (`@base-ui/react`). Do not pull a Radix package back in, even for a single missing primitive — if Base UI does not cover something, raise it before reaching for an alternative library.

### `forwardRef` and `displayName`

- Every wrapper uses `forwardRef` and assigns `displayName`. Do not drop these even though React 19 supports refs as regular props — that refactor is a separate, project-wide concern.

### Polymorphic Rendering (`asChild`)

- The `Button` wrapper exposes `asChild`, backed by `frontend/src/components/ui/slot.tsx` (~30 LOC, a `forwardRef` wrapper around `React.isValidElement` + `cloneElement`). Do not import `@radix-ui/react-slot` or any other slot package. If a richer composition story is ever needed, extend the local `Slot`.

### Data Attribute Conventions

Base UI exposes state via boolean presence attributes. Tailwind selectors must use the boolean form:

| Use this | Not this (Radix-era) |
|----------|----------------------|
| `data-[open]:` / `data-[closed]:` | `data-[state=open]:` / `data-[state=closed]:` |
| `data-[checked]:` / `data-[unchecked]:` | `data-[state=checked]:` / `data-[state=unchecked]:` |
| `data-[panel-open]:` (Collapsible) | `data-[state=open]:` |

- Any `data-[state=...]:` selector in new code is a bug.
- The Collapsible trigger uses `data-panel-open` (not `data-open`); double-check the Base UI docs for the correct attribute when adding selectors for a new primitive.

### Menu and Select Composition

- Both `Menu` and `Select` require an explicit `Positioner` between `Portal` and `Popup`. Do not skip the Positioner — without it, popups do not anchor correctly.
- Pass positioning props (`sideOffset`, alignment) on the `Positioner`, not on the `Popup`.

### Label

- Use the `Label` wrapper, which renders a native `<label>` with the project's CVA variants. Do not introduce `Field.Root` + `Field.Label` for simple labels — the ceremony adds nothing for a styled label.

### Tests

- Do not assert on `data-state="..."` in tests. Match against the new boolean attributes (`data-open`, `data-checked`, etc.) or, preferably, against accessible roles and names — those are what users and screen readers see.
