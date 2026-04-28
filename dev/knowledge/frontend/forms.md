<!-- Extracted from specs/001-tanstack-form-migration on 2026-04-26 -->

## Frontend Forms

### Overview

The frontend uses **TanStack Form** (`@tanstack/react-form`) for all six form components (Add Driver, Create/Detail BSL, Create Cluster, Create Environment, Deploy Form). Each form follows the same pattern: a Zod schema declares shape and constraints, `<form.Field>` binds inputs to form state, and submission calls a TanStack Query mutation.

TanStack Form 1.28+ accepts Zod schemas directly via Standard Schema. There is **no `@tanstack/zod-form-adapter`** dependency — it isn't needed at this version.

See [ADR-012](../../adr/adr-012-migrate-forms-to-tanstack-form.md) for the migration rationale.

### Hook Setup

```tsx
import { useForm, useStore } from "@tanstack/react-form";

const form = useForm({
  defaultValues: { name: "", endpoint: "" },
  validators: { onSubmit: createBslSchema }, // full Zod schema, including .refine()
  onSubmit: async ({ value }) => {
    await createBsl.mutateAsync(value);
    queryClient.invalidateQueries({ queryKey: useListBslQuery.getKey() });
  },
});
```

### Field Binding

A single `<form.Field>` render-prop component handles **both** uncontrolled inputs and Radix/Base UI controlled primitives. There is no equivalent of RHF's `register` vs `Controller` split.

**Plain input:**

```tsx
<form.Field name="name" validators={{ onChange: z.string().min(1) }}>
  {(field) => (
    <Input
      value={field.state.value}
      onChange={(e) => field.handleChange(e.target.value)}
    />
  )}
</form.Field>
```

**Controlled UI primitive (Select, Checkbox):**

```tsx
<form.Field name="clusterId" validators={{ onChange: z.string().min(1) }}>
  {(field) => (
    <Select value={field.state.value} onValueChange={field.handleChange}>
      {/* options */}
    </Select>
  )}
</form.Field>
```

Per-field errors live at `field.state.meta.errors`.

### Reactive Subscriptions

The standalone `useStore` from `@tanstack/react-form`, applied to `form.store`, replaces RHF's `watch` and `formState` reads. The selector pattern keeps re-render scoping tight.

```tsx
import { useStore } from "@tanstack/react-form";

const isSubmitting = useStore(form.store, (s) => s.isSubmitting);
const dedicatedIngressEnabled = useStore(
  form.store,
  (s) => s.values.dedicated_ingress_enabled,
);

return (
  <>
    {dedicatedIngressEnabled && <IngressFields />}
    <Button disabled={isSubmitting}>Submit</Button>
  </>
);
```

### Cross-Field Validation

Zod `.refine()` works as form-level validation when the full schema is passed via `validators.onSubmit`. Per-field validators continue to use simpler Zod types for instant feedback.

```ts
const createClusterSchema = z
  .object({
    storageEnabled: z.boolean(),
    storageClass: z.string().optional(),
  })
  .refine((d) => !d.storageEnabled || !!d.storageClass, {
    message: "Storage class required when storage is enabled",
    path: ["storageClass"],
  });
```

### Dynamic Fields Outside the Schema

The Deploy Form renders runtime-discovered driver parameters whose shape depends on the selected driver. These are **intentionally not modeled in the form schema** — they live in plain `useState` and are merged into the mutation payload at submit time. The three statically-known fields (`name`, `applicationDriverVersionId`, `applicationVersion`) remain TanStack Form fields.

This split keeps the schema honest (it describes only what is statically known) and avoids modeling variable-shape data as a TanStack Form field array.

### Dialog Reset

Forms inside dialogs call `form.reset()` from the dialog's `onOpenChange` to restore default values and clear errors when the dialog closes.

```tsx
<Dialog onOpenChange={(open) => { if (!open) form.reset(); }}>
```

### Form Tests

No form-specific tests existed before the migration, so none were updated. Tests for utility components (ErrorState, LoadingState, StatusBadge) were unaffected. Adding form-level test coverage is outstanding follow-up work.

### What Was Replaced

| Concept | Before (React Hook Form) | After (TanStack Form) |
|---------|--------------------------|-----------------------|
| Hook | `useForm({ resolver: zodResolver(schema) })` | `useForm({ validators: { onSubmit: schema } })` (Standard Schema, no adapter) |
| Plain field | `{...register("name")}` | `<form.Field>{(field) => ...}</form.Field>` |
| Controlled field | `<Controller name=... render={...}/>` | (same `<form.Field>` — unified) |
| Watch value | `watch("name")` | `useStore(form.store, (s) => s.values.name)` |
| Submitting state | `formState.isSubmitting` | `useStore(form.store, (s) => s.isSubmitting)` |
| Imperative set | `setValue("name", v)` | `form.setFieldValue("name", v)` |
| Reset | `reset()` | `form.reset()` |
