# Styrmin Constitution

## Core Principles

### I. Declarative State Reconciliation

All deployments are managed through desired-state vs current-state reconciliation. The system computes diffs between Deployment (desired) and Instance (current) objects, then generates remediation workflows (create, update, delete). State changes MUST be idempotent — re-running reconciliation on a converged system produces no side effects.

### II. Driver-Based Deployment

Applications are deployed through versioned Application Drivers that declaratively define helm charts, values templates, components, and custom actions. Drivers MUST be self-contained and independently versionable. All deployment behavior flows from the driver specification — no ad-hoc deployment logic outside drivers.

### III. Layered Architecture

Code MUST follow the layered architecture: GraphQL API → Service Layer → Repository Layer → Database. Cross-layer calls MUST go through the service layer. The UnitOfWork pattern coordinates transactions. Async workflows go through Prefect orchestration with callback-driven state updates.

### IV. Type Safety and Typed Errors

Python type hints are mandatory (enforced by mypy with `disallow_untyped_defs`). GraphQL error handling uses exception-based patterns: service functions raise `ServiceError` subclasses (with `error_code` and `default_message`), and the `StructuredErrorExtension` middleware enriches GraphQL errors with machine-readable `extensions.code` and metadata. Union types MUST NOT be used for error handling. Domain models, database models, and context models are separate concerns — never mix persistence with business logic.

### V. Test-First Development

Tests are required for all new functionality. The project uses three test tiers: unit tests (service/repository logic), integration tests (contract testing), and end-to-end tests (real Kind cluster with FluxCD, Prefect, and supporting services). E2E tests MUST run against real infrastructure, not mocks.

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

**Version**: 1.0.0 | **Ratified**: 2026-03-14 | **Last Amended**: 2026-03-14
