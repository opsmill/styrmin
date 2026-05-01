# Phase 0 Research — Propagation Test Coverage

This file resolves all open decisions for the implementation. There are no `NEEDS CLARIFICATION` markers in `spec.md` or `plan.md`; the work below is the up-front design choices and the alternatives we considered.

## R1. Test transport: HTTP-driven vs. resolver-direct

**Decision**: Drive the GraphQL HTTP endpoint via the existing `client` fixture (`AsyncClient` over `ASGITransport(app=app)`) for every propagation test, except for nested-resolver tests where the parent type's `info.context["uow"]` plumbing is the actual integration we want to exercise — in which case the parent query is still the entry point, and the nested field is added to the GraphQL selection set.

**Rationale**: Recipe 1 of `dev/guides/graphql-propagation-tests.md` is HTTP-driven, and it is what catches the realistic regression: "field is in the resolver but the schema dispatch doesn't reach it" or "input type field is dropped between Strawberry input parsing and the service call". A resolver-direct test bypasses the Strawberry input-parsing step, which is exactly where some of the regressions hide (camelCase ↔ snake_case argument mapping, `Optional` defaults, list-of-input parsing). Driving HTTP costs nothing extra given the fixtures already exist.

**Alternatives considered**:

- *Resolver-direct everywhere*. Rejected — bypasses the part of the stack most likely to silently lose a field.
- *Use the production `httpx.AsyncClient` against a running uvicorn*. Rejected — adds boot time, port allocation, and flake without buying anything propagation-test-related.

## R2. Database backend for tests

**Decision**: In-memory SQLite (`sqlite+aiosqlite://`) via the existing `session_fixture`. The fixture already binds `SQLModel.metadata.create_all` and overrides `get_session` for the FastAPI app.

**Rationale**: Production runs Postgres but the propagation contract under test is "the value reached the persistence layer through the real repository implementation". SQLite faithfully exercises that contract for every type used in the schema today. The functional test suite has been on SQLite for the entire lifetime of the project and has not produced false-positives that Postgres would have caught.

**Alternatives considered**:

- *Postgres via `testcontainers`*. Rejected for unit-tier propagation tests — boot cost (~5–10s per session) is incompatible with the per-test fixture lifecycle the existing functional tests rely on, and this feature does not need dialect-specific behavior.

## R3. Faking external systems (Prefect, Kubernetes, helm, git, HTTP)

**Decision**:

- **Prefect**: Override `get_manager` via `fast_depends.dependency_provider.override(get_manager.__wrapped__, get_fake_manager)` returning a `mocker.Mock(spec=PrefectManager)`. This is the established pattern at `backend/tests/unit/services/conftest.py:45–53` and `backend/tests/unit/services/reconciliation/test_remediation.py:42–48`. Reuse it from a new `backend/tests/functional/graphql/conftest.py`.
- **Kubernetes / helm / git / external HTTP**: Mock at the service-boundary call sites the relevant mutation crosses (e.g. `load_application_driver_from_local_directory`, `load_application_driver_from_git_repository`) using `pytest-mock`'s `mocker.patch(...)`. The propagation test asserts the *DB row* the resolver+service committed, so the external call only needs to return a value that lets the service reach its DB write.

**Rationale**: Faking at the boundary preserves Constitution III layering and matches the existing fakes used in `tests/unit/services/`. We do not pull in the unit-services `FakeUnitOfWork` because the whole point of a propagation test is to exercise the *real* repositories, not the fakes.

**Alternatives considered**:

- *Always run the full Prefect flow against a local Prefect server*. Rejected — propagation tests assert DB state, not workflow execution; downstream behavior is E2E's job.
- *Skip mutations that touch external systems*. Rejected — these are exactly the mutations where "value not propagated" regressions are easiest to introduce. Mock the boundary, not the service.

## R4. Where new GraphQL query/mutation strings live

**Decision**: Add new query/mutation strings to `backend/tests/functional/helpers.py` next to the existing `get_cluster_query`, `create_cluster_query`, etc. Tests import them from `helpers`. Do **not** introduce `.graphql` files for tests at this stage — the project's `.graphql`-file rule (CLAUDE.md / AGENTS.md) is scoped to SDK operations under `python_sdk/src/styrmin_sdk/graphql/` and dev-task operations under `tasks/graphql/`, and the existing functional tests already use inline strings in `helpers.py`. Diverging from the established pattern for *test fixtures only* would create churn without buying anything.

**Rationale**: Consistency with the existing pattern is the right default. If the project later adopts `.graphql` files for tests, the strings in `helpers.py` are easy to migrate atomically.

**Alternatives considered**:

- *New `.graphql` files under `backend/tests/functional/graphql/`*. Rejected for now — would require new tooling to load them; not justified by this feature alone. Open as a separate cleanup if desired.

## R5. Granularity: one test per field vs. one test per resolver

**Decision**: One propagation test *per logical resolver write or read*, asserting all of that resolver's input/output scalar fields in a single test. Rationale: input-type round-tripping is the regression target, and inputs come bundled per resolver. A per-field test multiplies the surface 5–10× without adding regression-detection power. When a resolver has *meaningfully different paths* (e.g. `update_backup_storage_location` accepts every field as `Optional` and treats credential fields specially), split per-path.

**Rationale**: Constitution §V mandates that every field is *covered*, not that every field gets its own test function. The matrix verdict (Coverage Matrix in `data-model.md`) is what enforces the per-field guarantee; the test count is an implementation detail.

**Alternatives considered**:

- *One test per field*. Rejected — explosion in test count without a regression-detection win.
- *One test per type*. Rejected — too coarse; failure messages would be hard to localize.

## R6. Async fixtures and event-loop scope

**Decision**: Reuse the existing pytest-asyncio configuration and the `session`/`client` fixtures verbatim. They are function-scoped, which gives test isolation per assertion. Do not introduce session-scoped or class-scoped fixtures.

**Rationale**: Per-test isolation costs <100ms (SQLite + ASGI app boot is cheap) and prevents test order dependencies, which are the typical failure mode when fixtures get hoisted to a broader scope.

## R7. Handling resolvers that hard-code workflow side-effects

**Decision**: For resolvers that submit a Prefect workflow before returning (e.g. `create_backup`, `create_restore`, `assign_backup_storage_location`, `unassign_backup_storage_location`, `update_backup_storage_location`), the propagation test:

1. Fakes the Prefect manager (R3).
2. Asserts the *database write the resolver is responsible for* (the `Backup`, `Restore`, or `Environment.backup_storage_location_id` row) by reading it back through `session.get(...)` or the real repository.
3. Optionally asserts the `prefect_manager_mock.run_action` call shape, but only when the *parameters dict* surfaces a propagated input (e.g. `bucket`, `region`) that is not visible in the DB write itself.

**Rationale**: Constitution §V is about value reaching the database. Workflow dispatch is downstream of that and is owned by E2E.

## R8. Handling computed and projected fields

**Decision**: For fields that are computed at projection time (`DeployedService.primary_fqdn`, `DeploymentTimelineEntry.*`, `Cluster.environments` count, etc.), seed the inputs that drive the computation through the real repository, run the query, and assert the projected output. Do not assert against a single column.

**Rationale**: The contract under test is "given persisted state X, the resolver projects Y". That's the same propagation contract, just with a non-trivial projection.

## R9. Tests for read-side filter arguments

**Decision**: For queries with filter arguments (e.g. `backups(instance_id, status)`, `pod_statuses(deployment_id, environment_id, cluster_id)`), seed *two* rows — one matching, one not — and assert the resolver returns only the matching row. This proves the argument was actually consumed.

**Rationale**: The cheapest assertion that distinguishes "resolver receives the argument" from "resolver ignores the argument and returns everything".

## R10. Pre-commit and CI

**Decision**: All new code must pass `uv run invoke format lint` before commit. The existing pre-commit config runs ruff format, ruff check, ty type-check, yamllint, rumdl markdown lint, and `validate-graphql`. None of these need extension for this feature.

**Rationale**: Constitution §VI is non-negotiable.

## R11. Coverage Matrix as the source of truth for `tasks.md`

**Decision**: The coverage matrix at `coverage-matrix.md` is the *direct input* to `tasks.md`. Every "GAP" row in the matrix produces a task; every "covered" row produces a verification task ("confirm test X actually asserts DB read-back, not just resolver return"). The matrix is checked into the spec dir and frozen at the time `/speckit-tasks` runs.

**Rationale**: Without a single canonical inventory, the work expands or contracts based on whoever is implementing it. The matrix freezes the scope.

## R12. Frontend / SDK regeneration

**Decision**: No frontend changes, no SDK regeneration. The schema does not change.

## R13. Out-of-scope items recorded for follow-up

The following are explicitly out of scope for this feature and should be tracked separately if desired:

- Migrating existing functional API tests in `backend/tests/functional/test_api.py` into the new `propagation/` directory layout. Out of scope — those tests already work; rearranging them is churn.
- Introducing `.graphql` files for test fixtures. Out of scope (R4).
- Postgres-dialect propagation testing. Out of scope (R2).
- Authorization-gated field coverage. Out of scope (spec Edge Cases).
- The deprecated/no-op `Deployment.internal` path that triggers the resolver to return `None`. The propagation test seeds a non-internal deployment; internal-deployment exclusion is asserted in existing functional tests and in the matrix as covered.
