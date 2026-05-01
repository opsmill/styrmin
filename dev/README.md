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

## Current Knowledge

Backend architecture documentation in [knowledge/backend/](knowledge/backend/):

- [overview.md](knowledge/backend/overview.md) - Architecture overview, directory structure, request flow
- [api.md](knowledge/backend/api.md) - GraphQL API (public and internal), types, response patterns
- [data-models.md](knowledge/backend/data-models.md) - Database, domain, and context models
- [services.md](knowledge/backend/services.md) - Service layer, unit of work, business logic
- [reconciliation.md](knowledge/backend/reconciliation.md) - Reconciliation engine, diff computation, remediation strategies
- [hooks-and-actions.md](knowledge/backend/hooks-and-actions.md) - Hook system, driver actions, setup/upgrade hooks
- [orchestration-flows.md](knowledge/backend/orchestration-flows.md) - Prefect orchestration flows, callbacks, execution patterns
- [agent.md](knowledge/backend/agent.md) - Kubernetes agent, resource builders, FluxCD integration
- [operator.md](knowledge/backend/operator.md) - Kopf operator, StyrminDeployment CRD, phase-based deployment, drift reconciliation
- [backup-restore.md](knowledge/backend/backup-restore.md) - Backup/restore system, Velero integration, strategies
- [e2e-testing.md](knowledge/backend/e2e-testing.md) - E2E testing architecture, Kind cluster setup, fixture graph
- [dead-code.md](knowledge/backend/dead-code.md) - Remaining dead code and cleanup tracking

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
