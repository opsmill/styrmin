# Feature Specification: GraphQL ↔ Database Propagation Test Coverage

**Feature Branch**: `007-graphql-propagation-tests`
**Created**: 2026-05-01
**Status**: Extracted
**Input**: User description: "I would like to develop the unit tests for the GraphQL API as defined by the GraphQL-to-database propagation tests as defined by the constitution. I think today we have very low coverage for that. The goal is to analyze the code and understand which tests we need to add. The focus here is really about those propagation tests."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Audit current propagation coverage and identify gaps (Priority: P1)

A backend maintainer needs a clear, evidence-based picture of which GraphQL operations and fields are currently exercised by Constitution §V propagation tests and which are not, so the team can target test work where it actually matters and stop relying on a vague sense that "coverage is low".

**Why this priority**: Without a coverage map, the team will either re-test what is already covered or skip what isn't. The map is the foundation that every subsequent test author depends on, and it also makes future regressions visible (a new schema element with no row in the map is a flag).

**Independent Test**: A reviewer can read the resulting coverage matrix, cross-check a sample of rows against the schema and the test files, and confirm the matrix accurately reports which GraphQL elements have propagation coverage today.

**Acceptance Scenarios**:

1. **Given** the current `backend/styrmin_backend/api/schema/` source, **When** the audit is run, **Then** every GraphQL query, mutation, output field, input type, and resolver argument defined under that path appears in the matrix with a clear "covered / not covered" verdict and a pointer to the covering test (if any).
2. **Given** the matrix, **When** a maintainer scans it, **Then** the gaps are grouped by domain (Cluster, Environment, Deployment, Backup, BackupSchedule, BackupStorageLocation, ApplicationDriver, Restore, Task, Pod statuses, Callbacks, Components, Jobs, Deployment timeline, Service FQDN, etc.) so test work can be parcelled out per domain.
3. **Given** the matrix, **When** a future schema change lands, **Then** the matrix structure makes it obvious whether the change introduces a new uncovered row.

---

### User Story 2 - Add propagation tests for write paths (mutations and write arguments) (Priority: P1)

A backend developer needs every mutation and every write-side argument under `backend/styrmin_backend/api/schema/mutation.py` to have a unit test that drives the GraphQL endpoint, then reads persisted state back through the real repository or the database session, asserting the value reached the database.

**Why this priority**: Writes are where "field added to schema but never wired to the repository" regressions hide. These regressions silently accept data and lose it, and they are exactly what Constitution §V was added to prevent. Writes are higher priority than reads because a broken write corrupts state, while a broken read is usually obvious.

**Independent Test**: For any mutation in scope, the new test can be run on its own with `uv run pytest backend/tests/unit/api/...` (or `backend/tests/functional/...` if HTTP-driven), it boots an in-memory SQLite session via the existing `client`/`session` fixtures, calls the mutation with representative inputs, and the assertion that fails when the resolver-to-repository wiring is removed is the database read-back, not the resolver return value.

**Acceptance Scenarios**:

1. **Given** a mutation that takes input arguments, **When** the test executes the mutation with a representative payload, **Then** the test reads the row back through the real repository / DB session and asserts each persisted field matches the input.
2. **Given** an input type with multiple fields, **When** the test exercises it, **Then** every field of the input type appears in the assertion (either by direct read-back or by a follow-up query that surfaces the field), and removing the field from the resolver-to-service wiring causes the test to fail.
3. **Given** a mutation that triggers a side-effect outside the layered architecture (Kubernetes, Prefect, helm, external HTTP), **When** the test runs, **Then** that side-effect is faked at the boundary while the service and repository layers remain real, per `dev/guides/graphql-propagation-tests.md`.

---

### User Story 3 - Add propagation tests for read paths (queries and output fields) (Priority: P2)

A backend developer needs every query and every output field exposed under `backend/styrmin_backend/api/schema/query.py` (and types referenced from it) to have a unit test that seeds state through the real repository, executes the query, and asserts the resolver projects the persisted state correctly.

**Why this priority**: Reads matter, but a misprojected read is generally caught earlier than a silent write loss (the UI or SDK consumer notices). Reads are still in scope because Constitution §V is explicit about both directions, and read coverage is what catches "field was renamed in the model but not in the resolver" regressions.

**Independent Test**: For any query in scope, the new test can be run on its own, it seeds a database row through the real repository, executes the query, and the assertion targets the resolver's projected value of every output field — not just `id`.

**Acceptance Scenarios**:

1. **Given** a query that returns a typed object, **When** the test executes it after seeding, **Then** every scalar output field of the type is asserted against the seeded value, and a future change that drops a field from the resolver causes the test to fail.
2. **Given** a query with arguments (filtering, lookup by id, by name, status filter), **When** the test exercises each argument, **Then** the seeded set is filtered correctly and the assertion proves the argument was actually consumed by the repository (different inputs yield different result sets).
3. **Given** a nested resolver (e.g. `Deployment.environment`, `BackupSchedule.deployment`), **When** the test executes the parent query asking for the nested field, **Then** the nested object is resolved against real persisted state and asserted on its scalar fields.

---

### User Story 4 - Document the propagation test pattern as a repeatable recipe (Priority: P3)

A future contributor (or AI agent) needs the test pattern, fixture wiring, and "what to assert" rules to be discoverable and self-explanatory enough that adding a propagation test alongside any new GraphQL change feels like a 5-minute task, not a research project.

**Why this priority**: The propagation test rule already exists in the constitution and `dev/guides/graphql-propagation-tests.md`, but the existing in-repo examples are sparse. Reducing the friction of authoring the test is what makes Constitution §V hold under future schema changes.

**Independent Test**: A new contributor (or agent) can read the resulting recipe and one in-repo example, then write a propagation test for an unfamiliar mutation in under 30 minutes without asking clarifying questions.

**Acceptance Scenarios**:

1. **Given** the new tests landing in this feature, **When** a contributor opens any one of them, **Then** the test follows a single, consistent shape (HTTP-driven where transport matters, resolver-driven only where there is a documented reason) and uses shared fixtures rather than ad-hoc setup.
2. **Given** the existing guide at `dev/guides/graphql-propagation-tests.md`, **When** the work in this feature lands, **Then** the guide either remains accurate or is updated so its recipes match the patterns now used in `backend/tests/unit/api/`.

---

### Edge Cases

- A GraphQL field is computed (no direct DB column) — for example, derived totals, status enums computed from related rows. The propagation test asserts the projection is correct given seeded inputs, not that it maps to a single column.
- A mutation is a no-op or has been deprecated but still present in the schema. The audit lists it; the implementer either tests it or marks it as intentionally untested with a one-line justification in the matrix.
- A mutation triggers asynchronous workflows (Prefect, Kubernetes reconciliation). The propagation test asserts the synchronous DB write that the mutation is responsible for, and fakes the async system at its boundary; downstream behavior is covered by E2E, not by propagation tests.
- A field exists only as a relay between layers (e.g. an alias or backward-compat field). The audit still lists it; the test asserts the alias resolves to the same persisted value as the canonical field.
- Authorization-gated fields. The test runs under the existing test auth context; authorization-specific behavior is out of scope here and stays in dedicated authz tests.
- Generated/server-set fields (timestamps, UUIDs, status enums set by the service). The test asserts these are populated and have the expected shape, not specific values.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The work MUST produce a coverage matrix enumerating every query, mutation, output field, input type, and resolver argument exposed under `backend/styrmin_backend/api/schema/`, each row mapped to either an existing covering test (file + test name) or marked as a gap.
- **FR-002**: The matrix MUST be checked into the spec directory (`specs/007-graphql-propagation-tests/`) so it can be reviewed alongside the spec and serve as the task-generation input.
- **FR-003**: Every gap identified in the matrix that falls under "mutation or write argument" MUST be closed by a new propagation test in the same feature, OR explicitly excluded with a documented justification (e.g. "covered by existing test X", "deprecated, scheduled for removal in feature Y").
- **FR-004**: Read-side gaps (queries and output fields) MUST be closed wherever doing so does not require duplicating coverage that already exists in the functional API tests; otherwise the existing coverage MUST be cited in the matrix and accepted as sufficient.
- **FR-005**: New tests MUST live under `backend/tests/unit/api/` (or `backend/tests/functional/` when HTTP-driven coverage is the most natural fit), MUST use the existing in-memory SQLite session fixtures, and MUST exercise the real `SQLModel*Repository` implementations and real service functions — not the fakes in `tests/unit/services/fakes.py`.
- **FR-006**: New tests MUST drive the GraphQL boundary (HTTP endpoint or `info.context`-passing direct resolver call) rather than calling services directly, so the test exercises the full GraphQL → service → repository → DB chain.
- **FR-007**: Each write test MUST assert the persisted value by reading it back through the real repository or DB session, not solely from the resolver return value.
- **FR-008**: Each read test MUST assert the resolver-projected value of each scalar output field of the type under test, after seeding via the real repository.
- **FR-009**: Systems outside the layered architecture (Kubernetes client, Prefect client, helm, external HTTP services) MUST be faked at their boundaries; the layered architecture itself (GraphQL, service, repository, DB) MUST remain real.
- **FR-010**: GraphQL queries used by the new tests MUST live in `.graphql` files under the appropriate test-helper or SDK location consistent with project conventions, OR be defined inline in the test module if the project's existing functional test pattern does so; the chosen pattern MUST match what `backend/tests/functional/test_api.py` already uses to avoid divergence.
- **FR-011**: After this feature lands, every GraphQL element under `backend/styrmin_backend/api/schema/` MUST either have a propagation test or appear in the matrix with a written exclusion reason that a reviewer signed off on.
- **FR-012**: The full backend test suite (`uv run invoke test`) MUST pass on the feature branch, and `uv run invoke format lint` MUST pass before any commit.
- **FR-013**: The work MUST NOT modify the GraphQL schema itself, MUST NOT change service or repository behavior, and MUST NOT change production code paths beyond what is strictly required to make a missing field testable (e.g. exposing a previously-hidden read path on an existing repository so a test can assert state). Any such change MUST be flagged in the matrix as a "production change required" row and confirmed before being made.

### Key Entities *(include if data involved)*

- **Coverage Matrix**: A structured artifact (markdown table) listing each GraphQL element (query / mutation / output field / input field / argument) with: schema location (file:line), domain, current covering test (or "GAP"), planned covering test, and notes. Lives at `specs/007-graphql-propagation-tests/coverage-matrix.md`.
- **Propagation Test**: A single pytest test function that drives the GraphQL boundary, exercises real service + repository + DB, and asserts persisted-state propagation in one direction (write or read). One test per logical schema element-or-input is the default unit; tests MAY be grouped per resolver where the inputs are tightly coupled.
- **Domain Group**: A logical clustering of schema elements (Cluster, Environment, Deployment, Backup, BackupSchedule, BackupStorageLocation, ApplicationDriver, Restore, Task, Pod statuses, Components, Jobs, Deployment timeline, Service FQDN, Callbacks). Used both to organize the matrix and to parcel implementation work into independently mergeable slices.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of GraphQL elements (queries, mutations, output fields, input fields, arguments) under `backend/styrmin_backend/api/schema/` appear as a row in the coverage matrix with a verdict.
- **SC-002**: 100% of mutations and write arguments under `backend/styrmin_backend/api/schema/mutation.py` either have a new or existing propagation test that asserts DB-side state read-back, or a documented exclusion with reviewer sign-off.
- **SC-003**: At least 80% of read-side schema elements (queries and output fields) have a propagation test, with the remainder explicitly cited as covered by an existing functional test in the matrix.
- **SC-004**: Every newly added propagation test passes when run individually and as part of the full suite via `uv run invoke test`.
- **SC-005**: A regression that removes the resolver-to-service wiring of any covered field causes at least one of the new propagation tests to fail (verified by spot-checking 3 newly added tests with a deliberate temporary regression during implementation).
- **SC-006**: A new contributor reading one of the new tests can describe the propagation test pattern in their own words after 5 minutes — the tests are uniform enough that the pattern is self-evident.
- **SC-007**: No GraphQL schema, service, or repository behavior changes ship as part of this feature; the diff is dominated by `backend/tests/...` additions and matrix documentation.

## Assumptions

- The project already provides reusable `client` and `session` test fixtures wired against an in-memory SQLite session (per `backend/tests/functional/test_api.py`); these will be used or extended rather than reinvented.
- The existing fakes for Kubernetes / Prefect / helm at the boundary of the service layer are sufficient for the propagation tests; if they are not, narrow extensions to those fakes are in scope but full new fake systems are not.
- "Propagation test" is interpreted strictly per `dev/guides/graphql-propagation-tests.md`: read-back through the real repository for writes; seed through the real repository for reads. Tests that only assert on the resolver's own return value do not count as propagation tests for the purpose of the matrix verdict.
- The matrix is a one-shot inventory taken at the time this feature is implemented. It is not maintained as living documentation; future schema changes are expected to add their own propagation test per Constitution §V, not to update this matrix.
- Computed/derived fields and async-triggered side-effects keep their existing test strategy (functional or E2E); the propagation test only asserts the synchronous DB-state portion of the contract.
- E2E tests under `backend/tests/e2e/` are out of scope for this feature; this work targets unit/functional propagation only.
- The project's Python version, test runner, fixtures, and SDK code-generation pipeline remain unchanged by this feature.
