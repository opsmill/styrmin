# Research: Migrate Frontend from Radix UI to Base UI

**Branch**: `001-base-ui-migration` | **Date**: 2026-04-05

## Research Tasks

### R1: Base UI Component Coverage for Radix Primitives

**Decision**: All 8 Radix UI primitives in use have direct Base UI equivalents.

**Rationale**: Base UI was co-created by the Radix UI co-founder (Colm Tuite) and former MUI team members. It was designed as a spiritual successor covering the same headless component space. Component mapping confirmed through official Base UI documentation (base-ui.com).

**Alternatives considered**:
- **Keep Radix UI**: No migration needed, but user explicitly requested Base UI.
- **React Aria (Adobe)**: Another headless library, but hooks-based rather than compound-component based — would require larger architectural changes.
- **Ark UI**: Compound-component library from Chakra team, but smaller community and less mature.

### R2: Data Attribute Convention Differences

**Decision**: Migrate from Radix's `data-state="value"` string attributes to Base UI's boolean `data-*` presence attributes.

**Rationale**: Base UI uses a simpler attribute model — `data-open` is present when open, absent when closed (vs. Radix's `data-state="open"`). This is a CSS selector-level change affecting Tailwind utility classes.

**Mapping**:
| Radix | Base UI | CSS Selector Change |
|-------|---------|---------------------|
| `data-state="open"` | `data-open` | `data-[state=open]:` → `data-[open]:` |
| `data-state="closed"` | `data-closed` | `data-[state=closed]:` → `data-[closed]:` |
| `data-state="checked"` | `data-checked` | `data-[state=checked]:` → `data-[checked]:` |
| `data-state="unchecked"` | `data-unchecked` | `data-[state=unchecked]:` → `data-[unchecked]:` |

**Impact**: 4 UI wrapper files + 1 consuming file (`DeploymentDetailPage.tsx`) use `data-[state=` selectors.

**Alternatives considered**:
- Adding custom `data-state` attributes to Base UI components via wrapper props — rejected as fragile and fighting the library's conventions.

### R3: Replacing Radix Slot/asChild Pattern

**Decision**: Implement a minimal `Slot` utility component (~15 lines) that merges props and refs onto a child element, preserving the `asChild` public API on the Button component.

**Rationale**: The Button component's `asChild` prop is used by consuming files to render buttons as links or other elements. Changing this API would violate FR-011 (zero changes to consuming files). Base UI's `render` prop is built into Base UI components but the Button wrapper is a custom CVA component, not a Base UI primitive. A minimal Slot implementation is straightforward in React 19 where `ref` is a regular prop.

**Implementation sketch**:
```tsx
function Slot({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) {
  const child = React.Children.only(children) as React.ReactElement;
  return React.cloneElement(child, { ...props, ...child.props,
    className: cn(props.className as string, child.props.className),
  });
}
```

**Alternatives considered**:
- **Deprecate `asChild` and use `render` prop**: Would break consuming files — violates FR-011.
- **Import Slot from a third-party package**: Adds an unnecessary dependency for ~15 lines of code.
- **Use `@radix-ui/react-slot` alone**: Would keep a Radix dependency — violates FR-007.

### R4: Dialog Architecture Differences

**Decision**: Map `Dialog.Overlay` → `Dialog.Backdrop`, `Dialog.Content` → `Dialog.Popup`. Keep `DialogPortal`, `DialogClose`, `DialogTrigger` wrappers pointing to their Base UI equivalents.

**Rationale**: Base UI renames Overlay to Backdrop and Content to Popup. The Portal and Close components have direct equivalents. The `DialogContent` wrapper currently auto-includes the overlay — this pattern can be preserved by composing `Dialog.Backdrop` + `Dialog.Popup` inside the wrapper.

**Alternatives considered**: None — the mapping is straightforward.

### R5: Menu Architecture (Replacing DropdownMenu)

**Decision**: Map `DropdownMenu.*` → `Menu.*` with an added `Menu.Positioner` wrapper between `Menu.Portal` and `Menu.Popup`.

**Rationale**: Base UI's Menu requires an explicit `Positioner` component for positioning the popup relative to the trigger. Radix handles this internally. The public API of the wrapper components (`DropdownMenu`, `DropdownMenuTrigger`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuSeparator`) remains unchanged.

**Key difference**: `sideOffset` prop becomes CSS/style on the Positioner rather than a direct prop.

**Alternatives considered**: None — direct mapping with minor structural addition.

### R6: Select Architecture Differences

**Decision**: Map `Select.Content` → `Select.Positioner` + `Select.Popup`, `Select.Viewport` → `Select.List`, scroll buttons → scroll arrows. Replace `--radix-select-trigger-*` CSS variables with Base UI's anchor sizing approach.

**Rationale**: Base UI's Select follows the same Positioner pattern as Menu. The scroll indicators are renamed from "Button" to "Arrow". The CSS variable for trigger dimensions changes from `--radix-select-trigger-height/width` to anchor-based sizing via the Positioner.

**Alternatives considered**: None — direct mapping with naming changes.

### R7: Label Component Migration

**Decision**: Replace Radix `Label.Root` with a native HTML `<label>` element, preserving the CVA variants and `forwardRef` wrapper.

**Rationale**: The Radix Label component is essentially a styled `<label>` with minimal added behavior. Base UI's `Field.Label` is designed for use within `Field.Root` context, which is more than what the current Label wrapper needs. A native `<label>` with the existing CVA styling is the simplest and most correct replacement.

**Alternatives considered**:
- **Use Base UI `Field.Label`**: Requires wrapping in `Field.Root` context — too much ceremony for a standalone label.
- **Keep Radix Label**: Would keep a dependency — violates FR-007.

### R8: Bundle Size Impact

**Decision**: The migration is expected to be bundle-size neutral or slightly favorable.

**Rationale**: Base UI ships as a single tree-shakable package. Per-component sizes are often smaller (e.g., Dialog is ~30% smaller gzipped). Removing 8 separate Radix packages reduces package resolution overhead. The full Base UI bundle is ~464 KB vs Radix's ~444 KB, but with tree-shaking only used components are included.

**Alternatives considered**: N/A — measurement will be verified post-migration as part of SC-006.

### R9: Collapsible Data Attribute for Consuming Files

**Decision**: The `group-data-[state=open]:rotate-90` class in `DeploymentDetailPage.tsx` must change to `group-data-[panel-open]:rotate-90`.

**Rationale**: Base UI's Collapsible uses `data-panel-open` on the trigger element (not `data-state="open"`). Since this selector is in a consuming file (not in the UI wrapper), this is the one exception to FR-011's "zero changes to consuming files" requirement. However, it is a Tailwind class change (not an import/API change), which is acceptable per the spec's edge case note about data-attribute conventions.

**Alternatives considered**:
- Adding a custom `data-state` attribute to the Collapsible wrapper — rejected as fragile.

### R10: forwardRef in React 19

**Decision**: Maintain existing `forwardRef` patterns for now; do not refactor to React 19 function-component refs.

**Rationale**: While React 19 supports `ref` as a regular prop, removing `forwardRef` is a separate refactoring concern outside the scope of this migration. The existing `forwardRef` wrappers work correctly with React 19 and Base UI. Scope creep would risk introducing unrelated changes.

**Alternatives considered**:
- Refactoring all components to drop `forwardRef` — rejected as out of scope per the spec's focus on library swap only.
