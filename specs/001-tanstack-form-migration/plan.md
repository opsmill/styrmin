# Implementation Plan: TanStack Form Migration

**Branch**: `001-tanstack-form-migration` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-tanstack-form-migration/spec.md`

## Summary

Migrate all 6 frontend form components from React Hook Form (v7) to TanStack Form, preserving identical user-facing behavior. The migration follows a complexity-ordered approach: simple forms first to establish patterns, then medium-complexity dialog forms, then high-complexity forms with dynamic/conditional fields. Zod validation schemas are retained via `@tanstack/zod-form-adapter`. After all forms are migrated, `react-hook-form` and `@hookform/resolvers` are removed.

## Technical Context

**Language/Version**: TypeScript 5.9.3, Node 22
**Primary Dependencies**: React 19.2.4, `@tanstack/react-form` (new), `@tanstack/zod-form-adapter` (new), Zod 4.3.6, Radix UI, `@tanstack/react-query` v5
**Storage**: N/A (frontend-only, data via GraphQL API at `/graphql`)
**Testing**: Vitest + React Testing Library
**Target Platform**: Web (SPA served by Vite 8.0.1)
**Project Type**: Web application (frontend-only change)
**Performance Goals**: No increase in bundle size; no degradation in form interaction responsiveness
**Constraints**: Zero regressions in form behavior; all 6 forms must migrate before old deps are removed
**Scale/Scope**: 6 form components across 6 files, ~1500 lines of form-related code

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | Backend-only principle, no deployment logic changes |
| II. Driver-Based Deployment | N/A | No driver specification changes |
| III. Layered Architecture | PASS | Frontend-only change, does not affect backend layers |
| IV. Type Safety and Typed Errors | PASS | TanStack Form is TypeScript-first; type safety preserved or improved |
| V. Test-First Development | PASS | Existing tests must pass; no form tests exist to break |
| VI. Format and Lint Before Commit | PASS | ESLint + Prettier enforced as usual |

**Governance Gates**:

| Gate | Status | Notes |
|------|--------|-------|
| New dependencies | FLAGGED | Adding `@tanstack/react-form` and `@tanstack/zod-form-adapter`; removing `react-hook-form` and `@hookform/resolvers`. Net change: swap 2 deps for 2 deps in same ecosystem. |
| GraphQL schema modifications | N/A | No schema changes |
| Database schema changes | N/A | Frontend-only |
| CI/CD workflow changes | N/A | No pipeline changes |
| Auth changes | N/A | No auth changes |

**Post-Phase 1 Re-check**: All gates pass. The new dependencies are from the TanStack ecosystem already adopted in the project (Router, Query). The dependency swap is a net-neutral change.

## Project Structure

### Documentation (this feature)

```text
specs/001-tanstack-form-migration/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: API mapping and migration patterns
├── data-model.md        # Phase 1: Form data schemas (preserved as-is)
├── quickstart.md        # Phase 1: Migration pattern reference
├── contracts/           # Phase 1: GraphQL mutation contracts (unchanged)
│   └── README.md
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── pages/
│   │   ├── drivers/
│   │   │   └── AddDriverPage.tsx              # Form 1: simple (P1)
│   │   ├── backup-storage-locations/
│   │   │   ├── CreateBackupStorageLocationDialog.tsx  # Form 2: medium (P2)
│   │   │   └── BackupStorageLocationDetailPage.tsx    # Form 3: medium (P2)
│   │   ├── deployments/
│   │   │   └── DeployFormPage.tsx              # Form 4: high (P3)
│   │   ├── settings/
│   │   │   └── CreateClusterDialog.tsx         # Form 5: high (P3)
│   │   └── environments/
│   │       └── CreateEnvironmentDialog.tsx     # Form 6: high (P3)
│   ├── components/ui/
│   │   ├── input.tsx       # forwardRef input wrapper (may need minor update)
│   │   ├── checkbox.tsx    # Radix Checkbox (no changes needed)
│   │   ├── select.tsx      # Radix Select (no changes needed)
│   │   ├── dialog.tsx      # Radix Dialog (no changes needed)
│   │   └── label.tsx       # Radix Label (no changes needed)
│   ├── generated/
│   │   └── graphql.ts      # Auto-generated mutation hooks (no changes)
│   └── lib/
│       ├── graphql-fetcher.ts  # Fetch wrapper (no changes)
│       └── query-client.ts     # React Query config (no changes)
├── package.json            # Dependency swap happens here
└── codegen.ts              # GraphQL codegen config (no changes)
```

**Structure Decision**: This migration modifies 6 existing page-level form components in-place and updates `package.json` dependencies. No new files, directories, or architectural patterns are introduced. The UI component library (`components/ui/`) requires no changes — TanStack Form's `<form.Field>` render prop provides `value`/`handleChange` that map directly to existing Radix UI component props.

## Complexity Tracking

No constitution violations to justify. This is a straightforward library swap within the existing frontend architecture.
