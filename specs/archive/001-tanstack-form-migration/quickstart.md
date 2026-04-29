# Quickstart: TanStack Form Migration

**Feature Branch**: `001-tanstack-form-migration`

## Prerequisites

- Node 22+, pnpm
- Frontend dev environment running (`cd frontend && pnpm dev`)

## Setup

```bash
cd frontend
pnpm add @tanstack/react-form @tanstack/zod-form-adapter
```

## Migration Pattern Reference

### Before (React Hook Form)

```tsx
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  clusterId: z.string().min(1, "Cluster is required"),
  enabled: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function MyForm() {
  const { register, handleSubmit, control, watch, reset, formState: { errors, isSubmitting } } =
    useForm<FormValues>({
      resolver: zodResolver(schema),
      defaultValues: { name: "", clusterId: "", enabled: false },
    });

  const enabled = watch("enabled");

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <Input {...register("name")} />
      {errors.name && <span>{errors.name.message}</span>}

      <Controller
        name="clusterId"
        control={control}
        render={({ field }) => (
          <Select value={field.value} onValueChange={field.onChange}>...</Select>
        )}
      />

      <Controller
        name="enabled"
        control={control}
        render={({ field }) => (
          <Checkbox checked={field.value} onCheckedChange={field.onChange} />
        )}
      />

      {enabled && <ConditionalSection />}

      <Button type="submit" disabled={isSubmitting}>Submit</Button>
    </form>
  );
}
```

### After (TanStack Form)

```tsx
import { useForm } from "@tanstack/react-form";
import { zodValidator } from "@tanstack/zod-form-adapter";
import { z } from "zod";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  clusterId: z.string().min(1, "Cluster is required"),
  enabled: z.boolean(),
});

function MyForm() {
  const form = useForm({
    defaultValues: { name: "", clusterId: "", enabled: false },
    validatorAdapter: zodValidator(),
    validators: {
      onSubmit: schema,
    },
    onSubmit: async ({ value }) => {
      await onSubmit(value);
    },
  });

  const enabled = form.useStore((s) => s.values.enabled);
  const isSubmitting = form.useStore((s) => s.isSubmitting);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        form.handleSubmit();
      }}
    >
      <form.Field name="name" validators={{ onChange: z.string().min(1, "Name is required") }}>
        {(field) => (
          <>
            <Input
              value={field.state.value}
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
            />
            {field.state.meta.errors.length > 0 && (
              <span>{field.state.meta.errors[0]}</span>
            )}
          </>
        )}
      </form.Field>

      <form.Field name="clusterId" validators={{ onChange: z.string().min(1, "Cluster is required") }}>
        {(field) => (
          <Select value={field.state.value} onValueChange={field.handleChange}>
            ...
          </Select>
        )}
      </form.Field>

      <form.Field name="enabled">
        {(field) => (
          <Checkbox
            checked={field.state.value}
            onCheckedChange={field.handleChange}
          />
        )}
      </form.Field>

      {enabled && <ConditionalSection />}

      <Button type="submit" disabled={isSubmitting}>Submit</Button>
    </form>
  );
}
```

## Key Differences Summary

| Concept | RHF | TanStack Form |
|---------|-----|---------------|
| Field binding | `register()` / `Controller` | `<form.Field>` render prop |
| Field value | `field.value` | `field.state.value` |
| Field change | `field.onChange` | `field.handleChange` |
| Watch fields | `watch("name")` | `form.useStore(s => s.values.name)` |
| Set field | `setValue("name", val)` | `form.setFieldValue("name", val)` |
| Errors | `errors.name.message` | `field.state.meta.errors[0]` |
| Is submitting | `formState.isSubmitting` | `form.useStore(s => s.isSubmitting)` |
| Reset | `reset()` | `form.reset()` |
| Submit handler | `handleSubmit(fn)` on form | `form.handleSubmit()` + `onSubmit` in options |
| Validation | `zodResolver(schema)` | `validatorAdapter: zodValidator()` + `validators` |

## Migration Order

1. `AddDriverPage.tsx` — simplest, 1-3 fields, establishes pattern
2. `CreateBackupStorageLocationDialog.tsx` — 6 fields, dialog pattern
3. `BackupStorageLocationDetailPage.tsx` — partial form in dialog
4. `DeployFormPage.tsx` — dynamic fields, watch, setValue
5. `CreateClusterDialog.tsx` — conditional sections, cross-field validation
6. `CreateEnvironmentDialog.tsx` — conditional sections, query-loaded options

## Verification

After each form migration:

```bash
cd frontend
pnpm tsc --noEmit          # Type check
pnpm test                   # Run tests
pnpm dev                    # Manual verification
```

After all forms migrated:

```bash
cd frontend
pnpm remove react-hook-form @hookform/resolvers
pnpm tsc --noEmit
pnpm test
pnpm build
```
