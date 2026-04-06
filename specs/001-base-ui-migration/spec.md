# Feature Specification: Migrate Frontend from Radix UI to Base UI

**Feature Branch**: `001-base-ui-migration`  
**Created**: 2026-04-05  
**Status**: Draft  
**Input**: User description: "refactor the frontend to use Base UI instead of Radix"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Interactive Components Work Identically After Migration (Priority: P1)

A user interacts with all UI components (dialogs, dropdown menus, selects, checkboxes, collapsible sections) and experiences the same behavior and appearance as before the migration. No functional regression is introduced.

**Why this priority**: This is the core value of the migration — the component library swap must be invisible to end users. Any regression in interactive component behavior would directly impact usability.

**Independent Test**: Can be fully tested by exercising every interactive component (open a dialog, select an option from a dropdown, toggle a checkbox, expand a collapsible section, use a select input) and verifying the behavior matches the current Radix-based implementation.

**Acceptance Scenarios**:

1. **Given** a page with a dialog trigger, **When** the user clicks the trigger, **Then** the dialog opens with the same overlay, content, title, description, and close behavior as before.
2. **Given** a dropdown menu trigger, **When** the user clicks it, **Then** a menu appears with the correct items, separators, and keyboard navigation support.
3. **Given** a select input, **When** the user opens it and selects an option, **Then** the selected value displays correctly and the selection is captured by the form.
4. **Given** a checkbox, **When** the user toggles it, **Then** the checked/unchecked state changes with the correct visual indicator.
5. **Given** a collapsible section, **When** the user clicks the trigger, **Then** the content expands and collapses smoothly.

---

### User Story 2 - Visual Consistency Is Preserved (Priority: P1)

A user navigates the application and sees no visual differences in component styling — spacing, colors, typography, borders, hover states, focus rings, and animations all remain consistent with the current design.

**Why this priority**: Equal to Story 1 because visual regressions are immediately noticeable and erode user trust. The migration must be a zero-visual-change operation.

**Independent Test**: Can be tested by comparing screenshots of every page before and after migration, confirming pixel-level consistency for all component states (default, hover, focus, active, disabled).

**Acceptance Scenarios**:

1. **Given** any page in the application, **When** the user views it after migration, **Then** all components appear visually identical to the pre-migration version.
2. **Given** a component in its hover or focus state, **When** the user interacts with it, **Then** the visual feedback (hover highlight, focus ring) matches the pre-migration behavior.
3. **Given** a disabled component, **When** the user views it, **Then** it displays the same disabled styling as before.

---

### User Story 3 - Keyboard and Screen Reader Accessibility Is Maintained (Priority: P1)

A user relying on keyboard navigation or a screen reader can interact with all components with the same level of accessibility as before. ARIA attributes, focus management, and keyboard shortcuts remain functional.

**Why this priority**: Accessibility is non-negotiable. Both Radix and Base UI are headless accessibility-focused libraries, but the migration must verify no ARIA roles, labels, or keyboard interactions are lost in translation.

**Independent Test**: Can be tested by navigating every interactive component using only the keyboard (Tab, Enter, Space, Escape, Arrow keys) and verifying screen reader announcements with a tool like VoiceOver or NVDA.

**Acceptance Scenarios**:

1. **Given** a dialog, **When** it opens, **Then** focus moves to the dialog content and pressing Escape closes it — matching pre-migration behavior.
2. **Given** a dropdown menu, **When** navigated with arrow keys, **Then** items are highlighted sequentially and Enter selects the focused item.
3. **Given** a select input, **When** navigated with keyboard, **Then** the options list opens, arrow keys move between options, and Enter confirms selection.
4. **Given** a checkbox, **When** focused and Space is pressed, **Then** the checked state toggles with an appropriate screen reader announcement.

---

### User Story 4 - Existing Tests Pass After Migration (Priority: P2)

A developer runs the existing frontend test suite and all tests pass without modification (or with minimal, documented changes to account for the new library's DOM structure).

**Why this priority**: Test suite integrity validates that the migration has not introduced regressions. This is secondary to user-facing behavior but essential for developer confidence.

**Independent Test**: Can be tested by running `pnpm test` in the frontend directory and confirming all tests pass.

**Acceptance Scenarios**:

1. **Given** the existing frontend test suite, **When** tests are executed after migration, **Then** all tests pass.
2. **Given** a test that queries components by role or accessible name, **When** it runs after migration, **Then** it still finds the expected elements.

---

### User Story 5 - Radix UI Dependencies Are Fully Removed (Priority: P2)

A developer inspects the project dependencies and confirms that no Radix UI packages remain in `package.json` or anywhere in the dependency tree. The migration is complete with no lingering legacy dependencies.

**Why this priority**: A clean migration reduces bundle size, eliminates confusion about which library to use for new components, and simplifies dependency management.

**Independent Test**: Can be tested by searching for `@radix-ui` in `package.json`, `pnpm-lock.yaml`, and the entire source tree.

**Acceptance Scenarios**:

1. **Given** the migrated frontend, **When** a developer searches for `@radix-ui` in the codebase, **Then** no results are found.
2. **Given** `package.json`, **When** a developer inspects dependencies, **Then** `@base-ui/react` is present and no `@radix-ui/*` packages remain.

---

### Edge Cases

- What happens if a Base UI component has slightly different default ARIA attributes than its Radix equivalent? The migration must explicitly set attributes to match the existing behavior.
- How does the application handle the transition from Radix's `asChild` pattern to Base UI's `render` prop for the Button component's polymorphic rendering (used for link-style buttons)?
- What happens to components that rely on Radix's `data-state` attributes for Tailwind CSS styling? Base UI uses its own `data-*` attribute conventions and the selectors must be updated.
- What if a Radix component used in the project has no direct 1:1 equivalent in Base UI (e.g., standalone Label)? An alternative approach must be identified and documented.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All interactive UI components (Checkbox, Collapsible, Dialog, Dropdown Menu, Select, Separator) MUST be reimplemented using Base UI equivalents while preserving identical user-facing behavior.
- **FR-002**: The Button component's polymorphic rendering (currently using Radix `Slot` with `asChild`) MUST be migrated to use Base UI's `render` prop or an equivalent mechanism.
- **FR-003**: All Tailwind CSS styling currently applied to components MUST be preserved, including variant styles managed by `class-variance-authority` (CVA).
- **FR-004**: All `data-state` and `data-*` attribute selectors used in Tailwind classes MUST be updated to match Base UI's attribute conventions.
- **FR-005**: The Label component MUST be migrated to use Base UI's `Field.Label` or an equivalent accessible label mechanism.
- **FR-006**: The Dropdown Menu component MUST be migrated to use Base UI's `Menu` component with equivalent trigger, content, item, and separator subcomponents.
- **FR-007**: All Radix UI packages (`@radix-ui/react-checkbox`, `@radix-ui/react-collapsible`, `@radix-ui/react-dialog`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-label`, `@radix-ui/react-select`, `@radix-ui/react-separator`, `@radix-ui/react-slot`) MUST be removed from `package.json` after migration.
- **FR-008**: The `@base-ui/react` package MUST be added as a dependency.
- **FR-009**: All existing frontend tests MUST continue to pass after migration, with test updates limited to necessary changes in DOM queries due to attribute or structure differences.
- **FR-010**: All component `displayName` assignments and `forwardRef` patterns MUST be preserved for debugging and React DevTools compatibility.
- **FR-011**: The 23 consuming files that import from the UI component library MUST NOT require changes to their import statements — the public API of each wrapper component MUST remain unchanged.

### Assumptions

- Base UI provides sufficient component coverage for all Radix primitives currently in use (confirmed via research: all 8 Radix-based components have Base UI equivalents).
- The migration is limited to the `frontend/src/components/ui/` wrapper components; consuming components should not need changes beyond what is necessary to maintain the same public API.
- The existing Tailwind CSS + CVA styling approach is retained; no design system overhaul is included in this scope.
- Performance characteristics of Base UI components are equivalent to or better than Radix equivalents for the usage patterns in this project.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of existing frontend tests pass after migration without functional changes to test assertions (test infrastructure changes like attribute selectors are acceptable).
- **SC-002**: Zero visual regressions detected when comparing pre- and post-migration screenshots of all application pages.
- **SC-003**: Zero legacy component library packages remain in the dependency tree after migration.
- **SC-004**: All interactive components maintain identical keyboard navigation and screen reader behavior as verified by manual accessibility testing.
- **SC-005**: No consuming component files (outside the UI component wrapper layer) require changes to their import statements or component usage patterns.
- **SC-006**: Application bundle size does not increase by more than 5% as a result of the migration.
