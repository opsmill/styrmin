# Developer Documentation

Internal documentation for contributors. For user-facing docs, see `/docs/`.

## Quick Navigation

| I want to... | Go to |
|--------------|-------|
| Understand the architecture | `knowledge/` |
| Follow coding standards | `guidelines/` |
| Learn why we made a decision | `adr/` |
| Complete a specific task | `guides/` |
| See what's being built | `../specs/` |
| Use agent workflows | `../.agents/skills/` and `../.agents/commands/` |

## Directory Guide

- **specs/**: Approved designs at repo root (`../specs/`). Living during development, then archived.
- **guidelines/**: Prescriptive rules. How code should be written.
  - `backend/` - Python backend standards
- **knowledge/**: Descriptive reference. How the system works.
  - `backend/` - Backend architecture and patterns
- **guides/**: Step-by-step procedures for specific tasks.
- **adr/**: Architecture Decision Records. Why we chose what we chose.
- **prompts/**: Prompt templates for common thinking tasks. Currently empty.

Agent workflows live at the repo root under `.agents/skills/` and `.agents/commands/`.

## Document Lifecycle

```text
explorations/ → specs/ → knowledge/ or guidelines/
   (rough)     (approved)      (stable)
```

Mark deprecated docs clearly. Don't delete—update with pointers to replacements.

## Current Guidelines

- [backend/python.md](guidelines/backend/python.md) - Python coding standards, tooling, patterns
- [frontend/routing.md](guidelines/frontend/routing.md) - TanStack Router conventions: `$param` syntax, type registration, navigation
- [frontend/data-fetching.md](guidelines/frontend/data-fetching.md) - TanStack Query + GraphQL codegen: invalidation, polling, conditional fetch
- [frontend/forms.md](guidelines/frontend/forms.md) - TanStack Form + Zod: field bindings, subscriptions, dynamic fields
- [frontend/ui-primitives.md](guidelines/frontend/ui-primitives.md) - Base UI wrapper layer, data-attribute selectors, polymorphic Button
- [cyclopts.md](guidelines/cyclopts.md) - Cyclopts CLI conventions: parameters, validators, type aliases, lazy loading
- [markdown.md](guidelines/markdown.md) - Markdown conventions and document structure

## Current ADRs

- [adr-001-migrate-cli-typer-to-cyclopts.md](adr/adr-001-migrate-cli-typer-to-cyclopts.md) - Migrate styrminctl from Typer to Cyclopts for performance, native async, and framework unification
- [adr-002-consolidate-driver-single-yaml.md](adr/adr-002-consolidate-driver-single-yaml.md) - Consolidate driver declarative config into single driver.styrmin.yml
- [adr-003-alembic-database-migrations.md](adr/adr-003-alembic-database-migrations.md) - Adopt Alembic for versioned database migration management
- [adr-004-shared-async-event-loop-kopf-prefect.md](adr/adr-004-shared-async-event-loop-kopf-prefect.md) - Shared async event loop for kopf operator and Prefect agent
- [adr-005-leader-election-kopf-peering.md](adr/adr-005-leader-election-kopf-peering.md) - Priority-based leader election via kopf peering
- [adr-006-embed-context-in-deployment-crd.md](adr/adr-006-embed-context-in-deployment-crd.md) - Embed GlobalContext in StyrminDeployment CRD for autonomous reconciliation
- [adr-007-ordered-phase-deployment-sub-handlers.md](adr/adr-007-ordered-phase-deployment-sub-handlers.md) - Ordered phase-based deployment via kopf sub-handlers
- [adr-008-prefect-crd-intent-declaration.md](adr/adr-008-prefect-crd-intent-declaration.md) - Prefect flows declare intent via CRD instead of direct resource management
- [adr-009-consolidate-typechecker-on-ty.md](adr/adr-009-consolidate-typechecker-on-ty.md) - Consolidate type checking on ty, removing mypy
- [adr-010-migrate-frontend-router-to-tanstack.md](adr/adr-010-migrate-frontend-router-to-tanstack.md) - Migrate frontend routing from React Router to TanStack Router (code-based)
- [adr-011-replace-urql-with-tanstack-query.md](adr/adr-011-replace-urql-with-tanstack-query.md) - Replace urql with TanStack Query for GraphQL data fetching
- [adr-012-migrate-forms-to-tanstack-form.md](adr/adr-012-migrate-forms-to-tanstack-form.md) - Migrate frontend forms from React Hook Form to TanStack Form
- [adr-013-migrate-ui-primitives-to-base-ui.md](adr/adr-013-migrate-ui-primitives-to-base-ui.md) - Migrate frontend UI primitives from Radix UI to Base UI
- [adr-014-pod-status-records-observed-state-not-declared-state.md](adr/adr-014-pod-status-records-observed-state-not-declared-state.md) - Pod-status records observed runtime state, not declared component intent
- [adr-014-pre-commit-hooks-via-prek.md](adr/adr-014-pre-commit-hooks-via-prek.md) - Pre-commit hooks via prek
- [adr-015-deployment-soft-delete-tombstoning.md](adr/adr-015-deployment-soft-delete-tombstoning.md) - Soft-delete tombstoning with the agent status reporter as the sole writer of `Deployment.deleted_at`
- [adr-016-forensic-cr-retention-janitor.md](adr/adr-016-forensic-cr-retention-janitor.md) - Forensic-retention CR janitor: TTL-gated reaping of `phase: Deleted` CRs, never reaps `Deleting`-stuck ones
- [adr-017-tombstone-visibility-conflation.md](adr/adr-017-tombstone-visibility-conflation.md) - Tombstoned-record visibility: `NOT_FOUND` conflation on writes + opt-in `includeDeleted` filter on reads
- [adr-018-scoped-tombstone-aware-name-uniqueness.md](adr/adr-018-scoped-tombstone-aware-name-uniqueness.md) - Per-environment, tombstone-aware deployment name uniqueness via partial unique index
- [adr-019-deployment-env-vars.md](adr/adr-019-deployment-env-vars.md) - Deployment env vars — free-form, three-scope, post-render injected (post-render injection layer later superseded by ADR-021)
- [adr-020-environment-config-fanout.md](adr/adr-020-environment-config-fanout.md) - Environment-config update — typed `UpdateEnvironmentInput`, per-deployment fanout, clean replace
- [adr-021-driver-env-var-consumption.md](adr/adr-021-driver-env-var-consumption.md) - Driver-side env var consumption via the values template, replacing platform post-render injection
- [adr-022-schema-walking-input-propagation-tests.md](adr/adr-022-schema-walking-input-propagation-tests.md) - Schema-walking propagation tests for Strawberry input completeness against Pydantic config models
- [adr-023-frontend-value-transform-boundary.md](adr/adr-023-frontend-value-transform-boundary.md) - Frontend value-transform layer at the GraphQL submit boundary for full-replacement inputs
- [adr-024-authentication-and-sessions.md](adr/adr-024-authentication-and-sessions.md) - Opaque server-side session tokens with dual transport (HttpOnly cookie + bearer header), 30-day absolute / 7-day idle lifetime, argon2id passwords
- [adr-025-authorization-model.md](adr/adr-025-authorization-model.md) - Three-tier role-based authorization (`READ_ONLY` / `READ_WRITE` / `ADMIN`) with default-deny `RequiresAuthentication` extension and per-resolver `RequiresRole`
- [adr-026-typed-update-deployment-input.md](adr/adr-026-typed-update-deployment-input.md) - Typed `UpdateDeploymentInput` — list-shaped named-dict fields with typed duplicate detection, `parameters`-merge asymmetry, shared leaf inputs under `config/inputs.py`

## Current Knowledge

- [architecture.md](knowledge/architecture.md) - High-level system architecture: server↔agent topology, declarative state, context model. Companion to the constitution.

Backend (server) architecture documentation in [knowledge/backend/](knowledge/backend/):

- [overview.md](knowledge/backend/overview.md) - Architecture overview, directory structure, request flow
- [api.md](knowledge/backend/api.md) - GraphQL API (public and internal), types, response patterns
- [data-models.md](knowledge/backend/data-models.md) - Database, domain, and context models
- [services.md](knowledge/backend/services.md) - Service layer, unit of work, business logic
- [reconciliation.md](knowledge/backend/reconciliation.md) - Reconciliation engine, diff computation, remediation strategies
- [hooks-and-actions.md](knowledge/backend/hooks-and-actions.md) - Hook system, driver actions, setup/upgrade hooks
- [orchestration-flows.md](knowledge/backend/orchestration-flows.md) - Prefect orchestration flows, callbacks, execution patterns (the agent runs the Prefect worker that executes these flows)
- [backup-restore.md](knowledge/backend/backup-restore.md) - Backup/restore system, Velero integration, strategies
- [e2e-testing.md](knowledge/backend/e2e-testing.md) - E2E testing architecture, vcluster setup, fixture graph
- [dead-code.md](knowledge/backend/dead-code.md) - Remaining dead code and cleanup tracking

Agent (in-cluster) architecture documentation in [knowledge/agent/](knowledge/agent/):

- [overview.md](knowledge/agent/overview.md) - Agent process layout, where Prefect lives, Kubernetes resource builders, status reporter
- [operator.md](knowledge/agent/operator.md) - Kopf operator, StyrminDeployment CRD, phase-based deployment, drift reconciliation

Frontend architecture documentation in [knowledge/frontend/](knowledge/frontend/):

- [routing.md](knowledge/frontend/routing.md) - TanStack Router architecture, route tree, type registration, lazy routes
- [data-fetching.md](knowledge/frontend/data-fetching.md) - TanStack Query + codegen pipeline, fetcher, cache invalidation, polling
- [forms.md](knowledge/frontend/forms.md) - TanStack Form architecture, Zod integration, field bindings, dynamic fields
- [ui-primitives.md](knowledge/frontend/ui-primitives.md) - Base UI wrapper layer, Slot utility, data-attribute conventions

## Current Guides

- [database-migrations.md](guides/database-migrations.md) - Alembic migration workflow: creating, applying, and rolling back migrations
- [graphql-propagation-tests.md](guides/graphql-propagation-tests.md) - How to write the unit test that proves a GraphQL field is wired through every layer to the database
- [local-demo.md](guides/local-demo.md) - Local vCluster demo lifecycle
- [pod-scheduling.md](guides/pod-scheduling.md) - Pod scheduling configuration reference
- [session-retrospectives.md](guides/session-retrospectives.md) - End-of-session workflow for turning agent friction into approved context-management improvements
- [users-and-groups.md](guides/users-and-groups.md) - Operator guide to users, groups, roles, the bootstrap admin, the Settings → Access UI, lockout recovery, and v1 limitations
