# Feature Specification: Migrate Frontend Forms to TanStack Form

**Feature Branch**: `001-tanstack-form-migration`
**Created**: 2026-04-03
**Status**: Extracted
**Input**: GitHub Issue #54 — Refactor frontend forms from React Hook Form to TanStack Form

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Simple Form Migration (Priority: P1)

A developer migrates the simplest form (Add Driver, 1-3 fields) from React Hook Form to TanStack Form, establishing the migration pattern and validating that TanStack Form integrates correctly with the existing Zod validation schemas and GraphQL mutation flow.

**Why this priority**: Establishes the foundational migration pattern with the lowest-risk form. All subsequent migrations build on conventions proven here.

**Independent Test**: Can be fully tested by navigating to the Add Driver page, filling in the form fields, submitting the form, and confirming the driver is created via GraphQL. Delivers a proven migration pattern and one fully migrated form.

**Acceptance Scenarios**:

1. **Given** a user is on the Add Driver page, **When** they fill in all required fields and submit, **Then** the driver is created successfully and the user receives confirmation feedback identical to the current behavior
2. **Given** a user submits the Add Driver form with invalid input, **When** validation runs, **Then** the same Zod-based validation errors are displayed inline next to the relevant fields
3. **Given** a user submits the Add Driver form, **When** the submission is in progress, **Then** the submit button shows a loading state and prevents double submission

---

### User Story 2 - Medium-Complexity Dialog Form Migration (Priority: P2)

A developer migrates the medium-complexity dialog forms (Create Backup Storage Location and Backup Storage Location Detail) to TanStack Form, validating that form-in-dialog patterns and 6-field forms with various input types work correctly.

**Why this priority**: Validates the migration pattern works within dialog components and with a moderate number of fields, covering Radix UI controlled components (Select, Checkbox) integrated with TanStack Form.

**Independent Test**: Can be tested by opening the Create Backup Storage Location dialog, filling in all 6 fields including controlled components, submitting, and verifying the storage location is created. Also test the detail page edit form for save/reset behavior.

**Acceptance Scenarios**:

1. **Given** a user opens the Create Backup Storage Location dialog, **When** they fill in all fields including Radix UI Select and Checkbox components and submit, **Then** the backup storage location is created and the dialog closes
2. **Given** a user is on the Backup Storage Location Detail page, **When** they modify fields and save, **Then** changes are persisted; **When** they click reset, **Then** the form reverts to the last saved state
3. **Given** a user opens the dialog and submits with missing required fields, **When** validation triggers, **Then** error messages appear next to the correct fields without dismissing the dialog

---

### User Story 3 - High-Complexity Form Migration (Priority: P3)

A developer migrates the three high-complexity forms (Deploy Form, Create Cluster, Create Environment) to TanStack Form, handling dynamic fields, conditional rendering, and 8+ field forms with conditional sections.

**Why this priority**: These are the most complex forms and carry the highest migration risk. They require dynamic field arrays, conditional section visibility, and complex interdependencies between fields. Completing these proves the migration is viable for the entire application.

**Independent Test**: Can be tested by exercising each form's full workflow: for Deploy Form, test dynamic parameter fields that appear based on the selected driver; for Create Cluster and Create Environment, test conditional sections that show/hide based on selected options. Verify all field interactions, validation, and successful submission.

**Acceptance Scenarios**:

1. **Given** a user is on the Deploy Form page, **When** they select a driver that has dynamic parameters, **Then** the parameter fields render dynamically and correctly bind to the form state
2. **Given** a user is creating a cluster with conditional sections, **When** they toggle options that show/hide sections, **Then** the conditional fields appear/disappear and their values are correctly included/excluded from submission
3. **Given** a user is creating an environment with 8+ fields, **When** they submit the form with a mix of valid and invalid fields, **Then** validation errors appear only on the invalid fields and the form does not submit until all errors are resolved

---

### User Story 4 - Dependency Cleanup (Priority: P4)

After all 6 forms are migrated, the old dependencies (`react-hook-form` and `@hookform/resolvers`) are removed from the project, and all form-related tests are updated to work with TanStack Form.

**Why this priority**: Cleanup is the final step that locks in the migration. Until old dependencies are removed, the migration is incomplete and the codebase has dual form libraries.

**Independent Test**: Can be verified by removing `react-hook-form` and `@hookform/resolvers` from `package.json`, running the full test suite, and confirming zero imports of the old libraries remain in the codebase.

**Acceptance Scenarios**:

1. **Given** all 6 forms have been migrated, **When** `react-hook-form` and `@hookform/resolvers` are removed from `package.json`, **Then** the application builds without errors and all tests pass
2. **Given** the migration is complete, **When** searching the codebase for `react-hook-form` or `@hookform/resolvers` imports, **Then** zero results are found

---

### Edge Cases

- What happens when a form field receives a server-side validation error (e.g., duplicate name) after submission? Error must still be displayed to the user.
- How does the Deploy Form handle dynamically adding/removing parameter fields when the driver selection changes mid-edit?
- What happens when a dialog form is closed while a submission is in progress? The mutation should still complete, but the UI should handle the unmount gracefully.
- What happens when a user navigates away from a form with unsaved changes? Current behavior should be preserved (no regression).
- How are form values handled when conditional sections are hidden — are they cleared or retained?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All 6 identified form components MUST be migrated from React Hook Form to TanStack Form while preserving identical user-facing behavior
- **FR-002**: All existing Zod validation schemas MUST be retained and integrated with TanStack Form via the `@tanstack/zod-form-adapter`
- **FR-003**: All Radix UI controlled components (Select, Checkbox, etc.) MUST work correctly with TanStack Form's field binding
- **FR-004**: Conditional field rendering (currently implemented via `watch()`) MUST produce equivalent behavior using TanStack Form's subscription model
- **FR-005**: Dynamic parameter fields in the Deploy Form MUST continue to support runtime addition and removal based on driver selection
- **FR-006**: Form error display, loading/submitting states, and reset behavior MUST be preserved across all 6 forms
- **FR-007**: All form submissions MUST continue to trigger the correct GraphQL mutations with properly shaped payloads
- **FR-008**: The `react-hook-form` and `@hookform/resolvers` packages MUST be removed from `package.json` after migration is complete
- **FR-009**: All existing frontend tests MUST pass after migration, with form-related tests updated to use TanStack Form patterns
- **FR-010**: Forms MUST prevent double submission during in-flight requests (current behavior preservation)

### Key Entities

- **Form Component**: A React component that collects user input, validates it against a Zod schema, and submits the data via a GraphQL mutation. Each form has fields, validation rules, and submission handlers.
- **Form Field**: An individual input within a form, which may be a simple text input, a controlled Radix UI component (Select, Checkbox), or a dynamically generated field based on external data.
- **Validation Schema**: A Zod schema that defines the shape and constraints of form data, shared between the form library and submission logic.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 6 form components use TanStack Form exclusively — zero references to React Hook Form APIs remain in the codebase
- **SC-002**: 100% of existing frontend tests pass after migration with no skipped form-related tests
- **SC-003**: Zero regressions in form submission workflows — every form that previously submitted data to the backend continues to do so correctly
- **SC-004**: Users experience no change in form behavior — validation messages, loading states, error displays, and reset functionality work identically to the pre-migration state
- **SC-005**: The frontend bundle does not increase in size as a result of the migration (net dependency change is neutral or negative)
- **SC-006**: Consistent use of TanStack Form APIs across all 6 form components — no mixed patterns or one-off workarounds

## Assumptions

- TanStack Form's `@tanstack/zod-form-adapter` supports all Zod 4 validation patterns currently used in the project
- TanStack Form provides equivalent functionality for all React Hook Form patterns in use: `useForm`, `register`, `Controller`, `watch`, `setValue`, `handleSubmit`, `formState`, and `reset()`
- The Radix UI component library is compatible with TanStack Form's field binding approach without requiring wrapper components
- The migration is a 1:1 behavioral replacement — no new form features or UX changes are introduced as part of this work
- Existing GraphQL mutation payloads and their shapes remain unchanged; only the form library producing them changes
