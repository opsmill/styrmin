<!-- Extracted from specs/001-tanstack-form-migration on 2026-04-26 -->

## Frontend Forms Guidelines

Conventions for authoring forms with TanStack Form. See [knowledge/frontend/forms.md](../../knowledge/frontend/forms.md) for the architectural overview and [ADR-012](../../adr/adr-012-migrate-forms-to-tanstack-form.md) for context.

### Validation

- Every form has a Zod schema as the **single source of truth** for shape and constraints.
- Pass the full schema directly to `validators.onSubmit` — TanStack Form (1.28+) accepts Standard Schema, so Zod schemas work without an adapter. Do not add `@tanstack/zod-form-adapter` and do not pass `validatorAdapter`; if you see those in old documentation, it is stale.
- Per-field `validators.onChange` may use simpler standalone Zod types for instant feedback, but the form-level `onSubmit` validator must include any `.refine()` invariants.

### Field Bindings

- Use `<form.Field>` with the render-prop pattern for **every** field — uncontrolled inputs and controlled UI primitives alike. Do not split fields between two binding APIs the way React Hook Form forced (`register` vs `Controller`).
- For controlled UI primitives, wire `value={field.state.value}` and the primitive's onChange equivalent (`onValueChange`, `onCheckedChange`, etc.) to `field.handleChange`.

### Reactive Subscriptions

- Use the standalone `useStore` from `@tanstack/react-form`, applied to `form.store`, for any value that drives conditional rendering or derived UI. Keep selectors narrow so re-renders are scoped.

  ```tsx
  import { useStore } from "@tanstack/react-form";

  const isSubmitting = useStore(form.store, (s) => s.isSubmitting);
  const showAdvanced = useStore(form.store, (s) => s.values.advancedEnabled);
  ```

- Do not reintroduce a `watch` helper on top of `useStore`; the selector pattern is the convention.

### Dynamic / Variable-Shape Fields

- If a form has fields whose **shape** is determined at runtime (e.g. driver-defined parameters discovered after a remote query), keep them in plain `useState` and merge them into the mutation payload at submit time. Do not force them into a TanStack Form field array — the schema should describe only what is statically known.
- If a form has a list of items with a **fixed** field shape, model that as a TanStack Form field array.

### Submission

- `onSubmit` lives on `useForm({ ... onSubmit })` and receives `{ value }`. Call the GraphQL mutation hook from there, then invalidate via the patterns in [data-fetching guidelines](./data-fetching.md).
- Forms must prevent double-submission while a request is in flight. Disable the submit button on `useStore(form.store, (s) => s.isSubmitting)`; do not wire ad-hoc `useState` flags.

### Dialog Forms

- For forms inside dialogs, call `form.reset()` from the dialog's `onOpenChange` when transitioning to closed. This restores defaults and clears errors and matches the long-standing UX expectation that closing a dialog discards in-flight edits.

### Tests

- New form components should ship with at least one happy-path test using `customRender` from `src/test/utils.tsx`. The previous codebase had no form-level tests; that is a debt to close, not a precedent to copy.
