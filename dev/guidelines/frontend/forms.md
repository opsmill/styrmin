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

<!-- Extracted from specs/011-env-config-input-hardening on 2026-05-10 -->

### Value-transform boundary for full-replacement inputs

When a form submits a typed GraphQL input built from **persisted** JSON
state — i.e. a full-replacement mutation that round-trips fields the
operator may not have edited — every field whose persisted shape differs
from its GraphQL input shape MUST be transformed at the submit boundary,
not casted with `as`. The canonical case: persisted Pydantic enums
round-trip as raw strings (`"https"`, `"NodeExternalIP"`); the GraphQL
input requires the enum literal (`HTTPS`, `NODE_EXTERNAL_IP`).

Use a typed helper with an explicit declarative mapping table per enum:

```typescript
const EXTERNAL_URL_SCHEME_MAP: Record<string, ExternalUrlScheme> = {
    "http": ExternalUrlScheme.HTTP,
    "https": ExternalUrlScheme.HTTPS,
};

function transformEnumValue<E extends string>(
    field: string,
    value: unknown,
    mapping: Record<string, E>,
): E | null {
    if (value == null) return null;
    if (typeof value !== "string") {
        throw new Error(`Field ${field}: expected string, got ${typeof value}`);
    }
    const transformed = mapping[value];
    if (transformed === undefined) {
        throw new Error(
            `Field ${field}: unrecognised value "${value}". ` +
            `Expected one of: ${Object.keys(mapping).join(", ")}`,
        );
    }
    return transformed;
}
```

Used inside `buildFullReplacementInput` (or the equivalent submit-shape
builder for the form):

```typescript
externalUrlScheme: transformEnumValue(
    "externalUrlScheme",
    config.external_url_scheme,
    EXTERNAL_URL_SCHEME_MAP,
),
```

**Throw on unrecognised values** — never silently submit `null` or pass a
TypeScript-only `as` cast. The form's existing error-display path catches
the throw and surfaces an actionable message to the operator. Silent
corruption of a persisted field on every save is the bug class this
discipline prevents (spec 011/US2).

The mappings are **maintained by hand** next to the form, matched to the
Pydantic source of truth. Drift is surfaced at code-review time when a
new enum value lands; codegen-generated mapping tables were rejected in
[ADR-023](../../adr/adr-023-frontend-value-transform-boundary.md) — the
manual table is clearer for the small cardinalities involved.

The pattern generalises beyond enums: any persisted-vs-GraphQL shape
divergence (date strings, partial objects, JSON-encoded payloads) belongs
at the same boundary with the same throw-on-unknown discipline.

### Dialog Forms

- For forms inside dialogs, call `form.reset()` from the dialog's `onOpenChange` when transitioning to closed. This restores defaults and clears errors and matches the long-standing UX expectation that closing a dialog discards in-flight edits.

### Tests

- New form components should ship with at least one happy-path test using `customRender` from `src/test/utils.tsx`. The previous codebase had no form-level tests; that is a debt to close, not a precedent to copy.
