# Styrmin Constitution

## Core Principles

### I. Declarative State Reconciliation

All deployments are managed through desired-state vs current-state reconciliation. The system computes diffs between Deployment (desired) and Instance (current) objects, then generates remediation workflows (create, update, delete). State changes MUST be idempotent — re-running reconciliation on a converged system produces no side effects.

### II. Driver-Based Deployment

Applications are deployed through versioned Application Drivers that declaratively define helm charts, values templates, components, and custom actions. Drivers MUST be self-contained and independently versionable. All deployment behavior flows from the driver specification — no ad-hoc deployment logic outside drivers.

### III. Layered Architecture

Code MUST follow the layered architecture: GraphQL API → Service Layer → Repository Layer → Database. Cross-layer calls MUST go through the service layer. The UnitOfWork pattern coordinates transactions. Async workflows go through Prefect orchestration with callback-driven state updates.

### IV. Type Safety and Typed Errors

Python type hints are mandatory (enforced by ty, Astral's type checker). GraphQL error handling uses exception-based patterns: service functions raise `ServiceError` subclasses (with `error_code` and `default_message`), and the `StructuredErrorExtension` middleware enriches GraphQL errors with machine-readable `extensions.code` and metadata. Union types MUST NOT be used for error handling. Domain models, database models, and context models are separate concerns — never mix persistence with business logic.

### V. Test-First Development

Tests are required for all new functionality. The project uses three test tiers: unit tests (service/repository logic), integration tests (contract testing), and end-to-end tests (real vcluster with FluxCD, Prefect, and supporting services). E2E tests MUST run against real infrastructure, not mocks.

**New features MUST ship with an E2E test that covers the user-visible flow end-to-end, and that E2E test MUST be executed and observed to pass before the feature is considered complete.** Deferring E2E coverage to a follow-up, gating it behind "we'll add it later", or relying on unit/integration tests alone is not acceptable for net-new functionality. The test — or an existing one extended to cover the new behaviour — is part of the feature's definition of done.

For bug fixes and small changes (refactors, doc updates, config tweaks, internal behaviour that is already exercised end-to-end), writing a new E2E test is not always proportionate. In those cases the implementer MUST ask for confirmation before skipping E2E coverage, describing what existing tests already cover the affected path; the reviewer's explicit approval is what authorises skipping, not the implementer's own judgment.

**GraphQL ↔ Database Propagation Tests (NON-NEGOTIABLE).** Every GraphQL field, argument, input type, and mutation under `backend/styrmin_backend/api/schema/` MUST be covered by a unit test that asserts full-stack propagation through the real service and repository layers — value reaches the database for writes, database state is projected to the resolver for reads. A schema change is not "done" until the propagation test passes. Procedure: `dev/guides/graphql-propagation-tests.md`.

### VI. Format and Lint Before Commit

`uv run invoke format lint` MUST pass before any commit. Line length is 120 characters. Ruff handles formatting and linting. This is non-negotiable and applies to all contributions.

## Governance Gates

Changes to these areas require explicit discussion before implementation:

- Database schema or migration changes
- GraphQL schema modifications
- New dependencies
- CI/CD workflow changes
- Authentication/authorization changes

## Boundaries

### Never

- Commit secrets, API keys, or credentials
- Edit generated files manually
- Skip linting in CI
- Force push to `stable` or `develop`
- Execute the script `update-agent-context.sh` — agent context files are maintained manually or through other workflows

## Governance

This constitution defines the non-negotiable principles for the Styrmin project. All specifications, plans, and implementations MUST be validated against these principles. Amendments require updating this file, incrementing the version, and propagating changes to dependent templates.

**Version**: 1.2.0 | **Ratified**: 2026-03-14 | **Last Amended**: 2026-05-01
