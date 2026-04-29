# Research: TanStack Form Migration

**Feature Branch**: `001-tanstack-form-migration`
**Date**: 2026-04-03

## R1: TanStack Form API Equivalents for React Hook Form Patterns

**Decision**: Use `@tanstack/react-form` with `@tanstack/zod-form-adapter` for Zod integration.

**Rationale**: TanStack Form provides direct equivalents for every RHF pattern used in the project:

| RHF Pattern | TanStack Form Equivalent | Notes |
|-------------|--------------------------|-------|
| `useForm()` | `useForm()` | Same hook name, different options shape |
| `register()` | `<form.Field>` component | Declarative field binding via render prop |
| `Controller` | `<form.Field>` component | Same component handles both simple and controlled inputs |
| `watch()` | `form.useStore(selector)` | Subscribe to specific field values reactively |
| `setValue()` | `form.setFieldValue(name, value)` | Imperative field value setting |
| `handleSubmit()` | `form.handleSubmit` | Passed to `<form onSubmit={...}>` |
| `formState.errors` | `field.state.meta.errors` | Per-field error access within `<form.Field>` render prop |
| `formState.isSubmitting` | `form.useStore(s => s.isSubmitting)` | Reactive subscription to submission state |
| `reset()` | `form.reset()` | Resets to default values |
| `zodResolver()` | `validatorAdapter: zodValidator()` | Form-level option, or per-field `validators` |

**Alternatives considered**:
- Keep React Hook Form: rejected because the project is standardizing on TanStack ecosystem (Router already migrated, Query adopted)
- Formik: rejected, less TypeScript-first, larger bundle, declining ecosystem momentum

## R2: Radix UI Controlled Component Integration

**Decision**: Use `<form.Field>` render prop to pass `value` and `onChange` to Radix UI controlled components (Select, Checkbox).

**Rationale**: TanStack Form's `<form.Field>` provides `field.state.value` and `field.handleChange` in its render prop, which map directly to Radix UI's `value` and `onValueChange`/`onCheckedChange` props. This is functionally identical to RHF's `Controller` pattern but with a unified API.

**Pattern**:
```tsx
<form.Field name="clusterId" validators={{ onChange: z.string().min(1) }}>
  {(field) => (
    <Select value={field.state.value} onValueChange={field.handleChange}>
      {/* ... */}
    </Select>
  )}
</form.Field>
```

**Alternatives considered**:
- Custom wrapper components around Radix UI: rejected, adds unnecessary abstraction layer

## R3: Conditional Field Rendering (watch → useStore)

**Decision**: Replace `watch()` calls with `form.useStore()` selectors for conditional field rendering.

**Rationale**: RHF's `watch("fieldName")` is used in 3 forms (DeployFormPage, CreateClusterDialog, CreateEnvironmentDialog) to show/hide conditional sections. TanStack Form's `form.useStore(s => s.values.fieldName)` provides the same reactive subscription with better type safety.

**Pattern**:
```tsx
const dedicatedIngressEnabled = form.useStore(
  (s) => s.values.dedicated_ingress_enabled
);
// Then conditionally render:
{dedicatedIngressEnabled && <IngressFields />}
```

**Alternatives considered**:
- `form.subscribe()` with manual state: rejected, useStore is simpler and React-native

## R4: Dynamic Parameter Fields in DeployFormPage

**Decision**: Use `useState` for dynamic parameters (current pattern) since they are managed outside the form schema.

**Rationale**: The DeployFormPage currently manages dynamic driver parameters via `useState` + `dynamicParams` object, separate from the RHF form state. These parameters are not part of the Zod schema — they are collected independently and merged into the mutation payload at submission time. This pattern can remain unchanged since it doesn't depend on React Hook Form. Only the 3 schema-managed fields (name, applicationDriverVersionId, applicationVersion) need to migrate to TanStack Form.

**Alternatives considered**:
- Migrate dynamic params into TanStack Form's field array: possible but adds complexity for no user-facing benefit — current approach works and is cleaner for variable-shape data

## R5: Zod `.refine()` Cross-Field Validation

**Decision**: Use TanStack Form's `onSubmit` validator with the full Zod schema including `.refine()`.

**Rationale**: CreateClusterDialog uses Zod `.refine()` for cross-field validation (storage class required when storage is enabled). TanStack Form's `@tanstack/zod-form-adapter` supports passing a full Zod schema with refinements at the form level via `validators: { onSubmit: zodSchema }`. Individual field validators can still use simple Zod types for instant feedback.

**Alternatives considered**:
- Convert `.refine()` to custom form-level `onSubmit` validator function: rejected, keeping Zod refinements is more maintainable and consistent

## R6: Form Reset on Dialog Close

**Decision**: Call `form.reset()` in the dialog's `onOpenChange` handler, same as current pattern.

**Rationale**: Four forms (CreateBSL, BSLDetail, CreateCluster, CreateEnvironment) use `reset()` when their dialog closes. TanStack Form's `form.reset()` works identically — it restores default values and clears error state. The dialog close handler pattern remains unchanged.

## R7: Dependencies to Install

**Decision**: Install `@tanstack/react-form` and `@tanstack/zod-form-adapter`.

**Rationale**: These are the minimum required packages. `@tanstack/react-form` provides the React bindings. `@tanstack/zod-form-adapter` bridges Zod schemas with TanStack Form's validator API. Both are maintained by the TanStack team and follow the same versioning/release cadence as Router and Query already in the project.

**Packages**:
- `@tanstack/react-form` — core form library for React
- `@tanstack/zod-form-adapter` — Zod integration adapter

**Packages to remove** (after migration complete):
- `react-hook-form`
- `@hookform/resolvers`

## R8: Existing Test Coverage

**Decision**: No form-specific tests exist; migration does not need to update form tests.

**Rationale**: The research found zero test files for any of the 6 form components. Existing tests cover utility components (ErrorState, LoadingState, StatusBadge, etc.) but not forms. The migration will not break any existing tests. New form tests could be added as a separate initiative but are out of scope for this migration (spec says "update form-related tests as needed" — none exist to update).

## R9: Form Submission Pattern Compatibility

**Decision**: No changes needed to GraphQL mutation hooks or query invalidation patterns.

**Rationale**: All forms use TanStack React Query mutation hooks (`useXxxMutation().mutateAsync()`) for submission, followed by `queryClient.invalidateQueries()`. This pattern is independent of the form library — it only consumes the form values object. The `onSubmit` handler in TanStack Form receives the form values in the same shape, so mutation calls remain identical.
