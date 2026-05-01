# Data Model — Propagation Test Coverage

This feature does **not** add or change any persisted entity. The "data" produced by this feature is two artifacts checked into the spec directory plus pytest test functions in `backend/tests/`.

## Entity 1: Coverage Matrix Row

**File**: `coverage-matrix.md` (this directory).
**One row per**: query / mutation / output object scalar field / input type field / resolver argument exposed under `backend/styrmin_backend/api/schema/`.

**Columns** (markdown table):

| Field            | Type                                                                                  | Required | Notes                                                                                                                                  |
|------------------|---------------------------------------------------------------------------------------|----------|----------------------------------------------------------------------------------------------------------------------------------------|
| Domain           | string                                                                                | Yes      | One of: `cluster`, `environment`, `deployment`, `backup`, `backup_schedule`, `backup_storage_location`, `application_driver`, `restore`, `task`, `pod_status`, `components`, `run_job`, `callback`, `deployment_timeline`, `deployment_status`, `service`, `health` |
| Element          | string                                                                                | Yes      | Fully qualified GraphQL element. Examples: `Mutation.createCluster`, `Query.cluster.clusterId (arg)`, `Cluster.config (output field)`, `ServiceNameOverride.driverServiceName (input field)` |
| Schema location  | `path:line`                                                                           | Yes      | E.g. `mutation.py:97`. Pinned at audit time; not maintained.                                                                            |
| Direction        | `write` \| `read` \| `both`                                                            | Yes      | Mutations and write-arg fields are `write`; queries and output fields are `read`; lookup args that exist on both sides are `both`.    |
| Existing coverage| `path::test_name` \| `none`                                                           | Yes      | If a propagation-style test already exists today, cite it.                                                                              |
| Verdict          | `covered` \| `gap` \| `excluded` \| `production-change-required`                       | Yes      | `excluded` MUST carry a `notes` justification reviewed before merge.                                                                    |
| Planned test     | `path::test_name` \| n/a                                                              | Yes      | The test that will close the gap. Becomes the test file/function created in the implement phase.                                        |
| Notes            | string                                                                                | No       | Justifications for `excluded`, fake-boundary callouts, links to related rows.                                                           |

**Row-level invariants**:

- Every row maps to at least one element of `backend/styrmin_backend/api/schema/`.
- A row with verdict `gap` MUST have a non-empty `Planned test`.
- A row with verdict `excluded` MUST cite the existing test or rationale that justifies skipping.
- A row with verdict `production-change-required` MUST be flagged for reviewer sign-off before any production code is touched (FR-013).

## Entity 2: Propagation Test Function

**File**: `backend/tests/functional/graphql/test_<domain>_propagation.py`.
**Shape** (write):

```python
@pytest.mark.asyncio
async def test_<resolver>_propagates_<inputs>(
    client: AsyncClient,
    session: AsyncSession,
    prefect_manager_mock,           # only when the resolver dispatches a workflow
):
    response = await client.post(
        "/graphql",
        json={"query": <mutation_string>, "variables": {...}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload  # propagation tests assert on success path
    new_id = UUID(payload["data"]["<resolver>"]["id"])

    # Read back through the real DB session — proves the value reached the DB
    db_row = await session.get(<DBModel>, new_id)
    assert db_row is not None
    assert db_row.<field_a> == <expected_a>
    assert db_row.<field_b> == <expected_b>
```

**Shape** (read):

```python
@pytest.mark.asyncio
async def test_<query>_projects_<fields>(
    client: AsyncClient, session: AsyncSession,
):
    seeded = <DBModel>(...)
    session.add(seeded)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={"query": <query_string>, "variables": {"<arg>": str(seeded.id)}},
    )
    assert response.status_code == 200
    data = response.json()["data"]["<query>"]
    assert data["<fieldA>"] == seeded.<field_a>
    assert data["<fieldB>"] == seeded.<field_b>
```

**Per-test invariants**:

- Drives `client.post("/graphql", ...)` (HTTP transport).
- Uses the `session` fixture — the same session the app dependency override binds, so the read-back observes the resolver's commit.
- Asserts persisted state via `session.get(...)` or a real-repository call, **not** the resolver return value alone.
- Mocks Prefect/Kubernetes/helm/git/HTTP at the service-boundary call sites only; never replaces the repository.

## Entity 3: Domain Test Module

**File**: `backend/tests/functional/graphql/test_<domain>_propagation.py` (one per `Domain` value above).

**Module invariants**:

- Imports query/mutation strings from `backend/tests/functional/helpers.py` (extending it as needed).
- Defines no fixtures of its own that should live in `conftest.py`.
- Stays under ~300 lines; if a domain blows past that, split by sub-resolver.

## Entity 4: Shared conftest extensions

**File**: `backend/tests/functional/graphql/conftest.py` (new).

**Adds** (only what's not already in `backend/tests/functional/test_api.py`):

- `prefect_manager_mock` fixture (mirroring `tests/unit/services/conftest.py:45`), so propagation tests can assert workflow-dispatch arguments and prevent real Prefect calls.
- Generic Kubernetes / helm / git fakes only if a propagation test needs them; preferred pattern is `mocker.patch(...)` at the call site rather than a session-wide fake.

## Out-of-scope entities

- No new domain models, no new repository classes, no new service functions, no new GraphQL types.
- Existing `tests/unit/services/fakes.py` are **not** used in propagation tests (using fakes here would defeat the propagation contract).
