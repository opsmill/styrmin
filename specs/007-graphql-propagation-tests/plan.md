# Implementation Plan: GraphQL ↔ Database Propagation Test Coverage

**Branch**: `007-graphql-propagation-tests` | **Date**: 2026-05-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-graphql-propagation-tests/spec.md`

## Summary

Close the Constitution §V coverage gap on the GraphQL → service → repository → database propagation contract. Take an inventory of every query, mutation, output field, input type, and resolver argument under `backend/styrmin_backend/api/schema/`, classify each row as covered / uncovered, and add HTTP-driven propagation tests (using the existing `client` + `session` fixtures from `backend/tests/functional/test_api.py`) for every gap. External systems (Prefect, Kubernetes, helm, git/HTTP) are faked at the existing service boundaries; the GraphQL, service, and repository layers run for real against an in-memory SQLite session.

## Technical Context

**Language/Version**: Python 3.11+ (project standard, enforced by `uv`)
**Primary Dependencies**: pytest, pytest-asyncio, httpx (`AsyncClient` with `ASGITransport`), SQLModel + sqlalchemy (`AsyncSession`, `aiosqlite`, `StaticPool`), Strawberry GraphQL, FastAPI/Starlette, fast_depends (for service-layer dependency overrides)
**Storage**: In-memory SQLite (`sqlite+aiosqlite://`) per test, via the existing `session_fixture` in `backend/tests/functional/test_api.py`. Production uses Postgres but propagation tests target the SQL contract, not the dialect.
**Testing**: pytest with `pytest-asyncio` (mode = auto). Tests run under `uv run invoke test` or directly via `uv run pytest backend/tests/...`. No new test frameworks are introduced.
**Target Platform**: Backend test suite (Linux/macOS dev machines, CI). Tests must pass under the same toolchain as the rest of `backend/`.
**Project Type**: Web service (Python backend `backend/` + React frontend `frontend/`). This feature touches only the backend test tier.
**Performance Goals**: Each new test must complete in under 1 second on a developer laptop. The full backend test suite must remain under its existing wall-clock budget; no new long-lived fixtures.
**Constraints**: No GraphQL schema changes. No service or repository behavior changes. Tests must not depend on Kubernetes, Prefect, helm, git remotes, or the network. `uv run invoke format lint` must pass before each commit; pre-commit hooks must not be bypassed.
**Scale/Scope**: ~25 queries + ~27 mutations + their input types and output object scalars. Estimated 60–90 new test functions split across 12–15 domain modules.

## Constitution Check

The constitution at `.specify/memory/constitution.md` (v1.2.0) is the *driver* of this feature, not a constraint to navigate around. Cross-checking each principle:

- **I. Declarative State Reconciliation** — Not applicable; tests do not change reconciliation behavior.
- **II. Driver-Based Deployment** — Not applicable; tests do not introduce ad-hoc deployment logic.
- **III. Layered Architecture** — Honored: tests drive the GraphQL boundary and exercise the real service + repository + DB stack. No cross-layer shortcuts.
- **IV. Type Safety and Typed Errors** — Honored: new tests use the existing typed `ServiceError` / `StructuredErrorExtension` paths via the GraphQL HTTP endpoint. No union-type error handling introduced.
- **V. Test-First Development** — This feature *is* the closure of §V's GraphQL ↔ Database propagation rule. New tests follow `dev/guides/graphql-propagation-tests.md`. No production code changes; this feature does not introduce a new user-visible flow, so the §V "E2E for new features" gate does not apply (the matrix verdict is part of the deliverable, and existing E2E coverage of the affected paths is not regressed).
- **VI. Format and Lint Before Commit** — Honored. `uv run invoke format lint` runs in pre-commit and CI.

**Constitution Check verdict: PASS.** No violations to track in the Complexity table.

### Governance Gate Cross-Check

The constitution flags five categories that need explicit discussion before implementation. None apply here:

| Gate                         | Affected? | Notes                                                                                                                                  |
|------------------------------|-----------|----------------------------------------------------------------------------------------------------------------------------------------|
| DB schema / migrations       | No        | Tests use existing `SQLModel.metadata.create_all` against in-memory SQLite. No schema changes ship.                                    |
| GraphQL schema modifications | No        | FR-013: this feature explicitly forbids schema changes. If the audit surfaces a missing field that must be added, it is a flagged row. |
| New dependencies             | No        | All required test deps (pytest-asyncio, httpx, aiosqlite) are already in the project.                                                  |
| CI/CD changes                | No        | Tests slot into the existing backend test job.                                                                                         |
| Authn/authz changes          | No        | Tests run under the existing test auth context; authz behavior is out of scope.                                                        |

## Project Structure

### Documentation (this feature)

```text
specs/007-graphql-propagation-tests/
├── plan.md                  # This file
├── research.md              # Phase 0: fixture/recipe decisions (this command)
├── data-model.md            # Phase 1: coverage matrix shape + propagation test shape
├── coverage-matrix.md       # Phase 1: full inventory (rows) — feeds /speckit-tasks
├── quickstart.md            # Phase 1: how to add a new propagation test
├── contracts/
│   └── propagation-test-contract.md   # Phase 1: what every propagation test must assert
└── tasks.md                 # Phase 2 output (NOT created here; /speckit-tasks generates it)
```

### Source Code (repository root)

This feature only adds files under `backend/tests/`. No production code changes.

```text
backend/
├── styrmin_backend/
│   └── api/schema/
│       ├── query.py        # READ ONLY — surface enumerated, not modified
│       └── mutation.py     # READ ONLY — surface enumerated, not modified
└── tests/
    ├── functional/
    │   ├── test_api.py                              # exists; new write/read tests may extend it
    │   ├── helpers.py                               # exists; new query/mutation strings added here
    │   └── propagation/                             # NEW: dedicated propagation test modules (HTTP-driven)
    │       ├── conftest.py                          # NEW: re-exports session/client + adds prefect/kube fakes
    │       ├── test_cluster_propagation.py          # NEW
    │       ├── test_environment_propagation.py     # NEW
    │       ├── test_deployment_propagation.py      # NEW
    │       ├── test_backup_propagation.py          # NEW
    │       ├── test_backup_schedule_propagation.py # NEW
    │       ├── test_backup_storage_location_propagation.py  # NEW
    │       ├── test_application_driver_propagation.py       # NEW
    │       ├── test_restore_propagation.py         # NEW
    │       ├── test_task_propagation.py            # NEW
    │       ├── test_pod_status_propagation.py      # NEW
    │       ├── test_components_propagation.py      # NEW
    │       ├── test_run_job_propagation.py         # NEW
    │       ├── test_callback_propagation.py        # NEW
    │       ├── test_deployment_timeline_propagation.py  # NEW
    │       └── test_deployment_status_propagation.py    # NEW
    └── unit/
        └── api/                                     # exists; reserved for resolver-direct tests when justified
```

**Structure Decision**: Place propagation tests under `backend/tests/functional/graphql/` rather than `backend/tests/unit/api/`. The decisive factor: `dev/guides/graphql-propagation-tests.md` recipe 1 ("HTTP-driven propagation test") is the canonical shape, and the existing fixtures that wire SQLite through the `get_session` dependency override live in `backend/tests/functional/test_api.py`. Co-locating with those fixtures avoids re-implementing them and keeps a single source of truth for "drive the GraphQL HTTP endpoint against an in-memory DB". The `unit/api/` tree remains available for narrow resolver-direct tests when there is a specific reason to bypass the transport (none planned for this feature).

The split into per-domain modules makes `tasks.md` mappable 1:1 to files (one task group per file), keeps individual files under ~300 lines, and makes parallel work mergeable without contention.

## Complexity Tracking

> No Constitution Check violations. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| —         | —          | —                                    |
