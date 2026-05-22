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

Tests are required for all new functionality. The project uses three test tiers: unit tests (service/repository logic), integration tests (contract testing), and end-to-end tests (disposable per-session vCluster on Docker with FluxCD, Prefect, and supporting services — see `dev/knowledge/backend/e2e-testing.md` for the fixture graph). E2E tests MUST run against real infrastructure, not mocks.

**New features MUST ship with an E2E test that covers the user-visible flow end-to-end, and that E2E test MUST be executed and observed to pass before the feature is considered complete.** Deferring E2E coverage to a follow-up, gating it behind "we'll add it later", or relying on unit/integration tests alone is not acceptable for net-new functionality. The test — or an existing one extended to cover the new behaviour — is part of the feature's definition of done.

**Local PASS evidence is required (NON-NEGOTIABLE).** A new or modified E2E test is not "done" until it has been observed to PASS locally at least once. Marker-clean / lint-clean / type-clean is not the same as green — a test that has only ever run as `SKIPPED`, or has never been executed against a real cluster, does not count. Workflows that declare a spec done (manual or automated, including `speckit.implement` and `speckit.auto.implement`) MUST record for each new/modified E2E test: (a) the pytest node ID, (b) the exact pytest command, (c) the ISO 8601 wall-clock timestamp of the passing run, (d) the cluster identifier (e.g. `vcluster<N>` fixture id + kubeconfig path under `/tmp/pytest-of-*/pytest-*/`), and (e) the verbatim `PASSED ...` line from pytest output. If the evidence cannot be produced, the test is not done — escalate rather than mark the spec complete. Rationale: incident from PR #209 (issue #216), where three latent bugs in a never-executed E2E test surfaced sequentially in CI because marker-clean was treated as done.

For bug fixes and small changes (refactors, doc updates, config tweaks, internal behaviour that is already exercised end-to-end), writing a new E2E test is not always proportionate. In those cases the implementer MUST ask for confirmation before skipping E2E coverage, describing what existing tests already cover the affected path; the reviewer's explicit approval is what authorises skipping, not the implementer's own judgment.

**GraphQL ↔ Database Propagation Tests (NON-NEGOTIABLE).** Every GraphQL field, argument, input type, and mutation under `backend/styrmin_backend/api/schema/` MUST be covered by a unit test that asserts full-stack propagation through the real service and repository layers — value reaches the database for writes, database state is projected to the resolver for reads. A schema change is not "done" until the propagation test passes. Procedure: `dev/guides/graphql-propagation-tests.md`.

### VI. Format and Lint Before Commit

`uv run invoke format lint` MUST pass before any commit. Line length is 120 characters. Ruff handles formatting and linting. This is non-negotiable and applies to all contributions.

### VII. Documentation Accuracy (NON-NEGOTIABLE)

The Styrmin documentation is a load-bearing artefact, not a side-effect of shipping code. Two surfaces MUST stay accurate with every change that touches them:

1. **The public documentation site (`docs/`).** User-visible behaviour — CLI commands, GraphQL surface, driver format, install / quickstart / how-it-works content, architecture diagrams, default values, screenshots — MUST match the implementation. If a change renames a field, alters a command, changes a default, removes a feature, or shifts an architectural fact described in `docs/`, the corresponding page MUST be updated in the same change. Adding new user-visible behaviour MUST include new or extended `docs/` content covering it.

2. **The internal developer documentation.** Architecture changes get reflected in [`dev/knowledge/`](knowledge/); new operational procedures get a [`dev/guides/`](guides/) entry; non-trivial decisions get an ADR in [`dev/adr/`](adr/); new, renamed, or retired domain concepts update [`CONTEXT.md`](../CONTEXT.md) in the same change.

A spec, feature, bug fix, or refactor is not "done" until the documentation describing it has been brought into alignment with the new state. Doc drift discovered after the fact is treated as a bug against the change that caused it.

**Guardrails:**

- "I'll update the docs later" is not acceptable. Either update them in the same change, or scope the change so it does not touch documented surface area.
- Speckit workflows (`/speckit.implement`, `/speckit.auto.implement`, `/speckit.tasks`, etc.) MUST include documentation tasks where applicable; reviewers MUST treat a missing doc update as a blocking issue, not a nit.
- If you remove a feature, remove the docs describing it in the same change.
- If a page is stale because it was never accurate to begin with, file a separate doc-bug; don't propagate the inaccuracy.
- An ADR-level architecture change (e.g. a new core principle, a new component, a topology change) MUST update [`dev/knowledge/architecture.md`](knowledge/architecture.md) and any affected `docs/how-it-works/` page in the same change.

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

**Version**: 1.4.0 | **Ratified**: 2026-03-14 | **Last Amended**: 2026-05-22
