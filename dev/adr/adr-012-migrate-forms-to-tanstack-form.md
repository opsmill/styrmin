## ADR-012: Migrate Frontend Forms from React Hook Form to TanStack Form

**Status**: Accepted
**Date**: 2026-04-26
**Source**: specs/archive/001-tanstack-form-migration/research.md (R1–R9)

## Context

The frontend used React Hook Form (RHF) with `@hookform/resolvers/zod` for six forms ranging from one field (Add Driver) to 8+ fields with conditional sections (Create Cluster, Create Environment, Deploy Form). Each form mixed RHF idioms (`register`, `Controller`, `watch`, `setValue`, `formState`) with controlled UI primitives (Radix Select, Checkbox) wrapped in `Controller`. Validation was Zod-driven via `zodResolver`.

After ADR-010 (TanStack Router) and ADR-011 (TanStack Query), the only non-TanStack data primitive left in the frontend was the form library. Standardizing on TanStack Form completes the ecosystem alignment, gives forms first-class TypeScript inference comparable to Router/Query, and removes one of two competing reactive subscription patterns from the codebase.

## Decision

Migrate all six forms to `@tanstack/react-form`, preserving every existing Zod schema verbatim. TanStack Form 1.28+ accepts Zod schemas directly via Standard Schema, so **no adapter package is needed** (`@tanstack/zod-form-adapter` is not a dependency).

1. Replace `useForm({ resolver: zodResolver(schema) })` with `useForm({ validators: { onSubmit: schema } })` — the Zod schema is passed straight in.
2. Replace both `register("name")` and `<Controller name="..." render={...}/>` with a single `<form.Field name="...">{(field) => ...}</form.Field>` render-prop pattern. Controlled UI primitives bind via `value={field.state.value}` + `onChange={field.handleChange}` (or the primitive's equivalent — `onValueChange`, `onCheckedChange`).
3. Replace `watch("fieldName")` with the standalone `useStore(form.store, (s) => s.values.fieldName)` (imported from `@tanstack/react-form`) for conditional rendering.
4. Replace `formState.isSubmitting` reads with `useStore(form.store, (s) => s.isSubmitting)`.
5. Keep the Deploy Form's **dynamic driver-parameter fields outside the form schema** — they remain plain `useState` because their shape is data-driven and merging them into the mutation payload at submit time is simpler than modeling them as a TanStack Form field array.
6. For cross-field validation (e.g. CreateClusterDialog: "storage class required when storage is enabled"), keep Zod `.refine()` and pass the full schema as the form-level `onSubmit` validator; do not rewrite refinements as imperative validator functions.
7. `form.reset()` in `onOpenChange` preserves the existing dialog-close behavior verbatim.
8. Remove `react-hook-form` and `@hookform/resolvers`.

## Consequences

**Easier:**

- One field-binding primitive (`<form.Field>`) replaces the RHF `register` vs `Controller` split — no more deciding which to reach for based on whether the input is uncontrolled or controlled.
- Reactive subscriptions go through the standalone `useStore(form.store, selector)` API, with selector-driven re-render scoping.
- The frontend now uses TanStack across routing, data fetching, and forms — one mental model, one set of release notes to track.

**Harder:**

- Field bindings are render-prop based, which is more verbose than RHF's `{...register("name")}` for trivial inputs. Acceptable trade-off for unifying simple and controlled inputs under one API.
- TanStack Form is a younger library than RHF; some niche RHF features (e.g., `useFieldArray` ergonomics) have less community material to lean on. Deploy Form's dynamic params sidestep this by staying in `useState` (see decision item 5).
- No existing form tests covered any of the six forms before migration, so the test suite did not validate behavior end-to-end during the swap. New form-level tests are still owed (tracked separately, not as part of this migration).

## Alternatives Considered

- **Stay on React Hook Form**: Mature and battle-tested. Rejected because the only remaining argument for it was inertia — every other reason had been outweighed by ecosystem alignment and the unified `<form.Field>` model.
- **Formik**: Considered for completeness; rejected for declining ecosystem momentum, weaker TypeScript-first design, and larger bundle.
- **Convert Zod `.refine()` to imperative `onSubmit` validators**: Rejected — refinements coexist cleanly with `validators.onSubmit: schema`, and rewriting them would lose the schema's role as single source of truth for shape *and* invariants.
- **Migrate the Deploy Form's dynamic params into a TanStack Form field array**: Rejected — modeling variable-shape, runtime-discovered parameters as schema-managed fields adds complexity for no user-facing benefit.
