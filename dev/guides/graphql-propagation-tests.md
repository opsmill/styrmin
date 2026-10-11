# Writing GraphQL Propagation Tests

## Overview

Per Constitution §V, every GraphQL field, argument, input type, and mutation
exposed under `backend/styrmin_backend/api/schema/` MUST be covered by a unit
test that asserts full-stack propagation across the layered architecture
(Principle III: GraphQL API → Service Layer → Repository Layer → Database).

A propagation test proves that a value entered at the resolver boundary
actually reaches the database (for writes) and, conversely, that database
state is correctly projected to the resolver output (for reads). It is the
test that catches "field added to schema but never wired to the repository"
regressions.

A schema change is **not "done"** until the propagation test exists, exercises
the new path, and passes.

## What to Assert

### Writes (mutations and write arguments)

1. Drive the resolver with the input value (via the GraphQL HTTP endpoint or
   by calling the resolver directly with a real `info.context`).
2. Read the persisted state back through the **real repository** (or directly
   from the database session).
3. Assert the value is present in the database.

Asserting only on the resolver's return value is not sufficient — the test
must prove the value reached the database.

### Reads (queries and output fields)

1. Seed state through the real repository.
2. Execute the query.
3. Assert the resolver projects the persisted state correctly.

## What to Use

- **Real service functions** — the actual `async def` services from
  `backend/styrmin_backend/services/`.
- **Real repository implementations** — the `SQLModel*Repository` classes
  used in production, not the fakes in `tests/unit/services/fakes.py`. Fake
  repos are appropriate for service-logic tests but defeat the purpose of a
  propagation test.
- **A real database session** — typically the in-memory SQLite fixture used
  by the functional API tests (see `backend/tests/functional/test_api.py`
  for the `session` and `client` fixtures).
- **Fakes only for systems outside the layered architecture** — Kubernetes,
  Prefect, helm, external HTTP services may be faked.

## Test Location

Place propagation tests under `backend/tests/functional/graphql/`. The
package is dedicated to Constitution §V coverage and ships a `conftest.py`
with `session`, `client`, and `prefect_manager_mock` fixtures, a
`seeds.py` module with helpers for building minimum-viable persisted
graphs, and a `graphql/` directory for the operation files (see next
section).

Resolver-direct tests under `backend/tests/unit/api/` are acceptable when
there is a documented reason to bypass the Strawberry transport, but they
are the exception. Default to the HTTP-driven recipes below.

## GraphQL operation files (no inline strings)

Every GraphQL operation used by a propagation test MUST live in its own
`.graphql` file and be loaded via the `load_query` helper. Inline GraphQL
strings inside a test module are not allowed — they bypass
`uv run invoke validate-graphql`, which means a schema change could remove a
field and the test would still pass against the dead string until somebody
notices at runtime.

- **Location**: `backend/tests/functional/graphql/operations/<operation>.graphql`
- **One operation per file**, named with the GraphQL operation (e.g.
  `query GetCluster {...}`, never anonymous `query {...}`).
- **File naming**: snake_case derived from the operation name (e.g.
  `GetClusterByName` → `get_cluster_by_name.graphql`).
- **Loading**: import `load_query` from
  `backend.tests.functional.graphql._queries` (or, inside the package,
  `from ._queries import load_query`) and call it with the file stem:

  ```python
  from ._queries import load_query

  response = await client.post(
      "/graphql",
      json={
          "query": load_query("create_cluster"),
          "variables": {...},
      },
  )
  ```

`uv run invoke validate-graphql` discovers every `.graphql` file under the
repository (excluding `.venv`, `node_modules`, and `specs/`) and validates
it against `schema.graphql`. The propagation `graphql/` directory is
covered automatically — no extra wiring needed. CI runs the same task,
so a schema change that breaks any operation file fails the build before
the test ever runs.

## Recipe: HTTP-driven propagation test (write)

`backend/tests/functional/graphql/operations/create_cluster.graphql`:

```graphql
mutation CreateCluster($name: String!, $config: JSON) {
    createCluster(name: $name, config: $config) {
        id
        name
        config
    }
}
```

`backend/tests/functional/graphql/test_cluster.py`:

```python
from ._queries import load_query


@pytest.mark.asyncio
async def test_create_cluster_persists_name(
    client: AsyncClient, session: AsyncSession
):
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_cluster"),
            "variables": {"name": "my-cluster"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    cluster_id = payload["data"]["createCluster"]["id"]

    # Read back through the real repository / DB session — proves the value
    # reached the database, not just the resolver.
    db_cluster = await session.get(Cluster, UUID(cluster_id))
    assert db_cluster is not None
    assert db_cluster.name == "my-cluster"
```

The `session` and `client` fixtures come from
`backend/tests/functional/graphql/conftest.py` and wire the in-memory
SQLite engine through the `get_session` dependency override.

## Recipe: HTTP-driven propagation test (read)

`backend/tests/functional/graphql/operations/get_cluster.graphql`:

```graphql
query GetCluster($clusterId: UUID!) {
    cluster(clusterId: $clusterId) {
        id
        name
    }
}
```

```python
@pytest.mark.asyncio
async def test_get_cluster_projects_db_state(
    client: AsyncClient, session: AsyncSession
):
    seeded = Cluster(name="seeded-cluster")
    session.add(seeded)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_cluster"),
            "variables": {"clusterId": str(seeded.id)},
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]["cluster"]
    assert data["name"] == "seeded-cluster"
```

## Recipe: Resolver-level test with a real UoW

When the field under test is a nested resolver, you can also drive the
resolver function directly, passing a real `info.context["uow"]` backed by
the test session. Prefer the HTTP-driven recipes above unless there's a
specific reason to bypass the GraphQL transport.

## Skipping

Never skip the propagation test for a new or modified schema element. If you
believe an existing propagation test already covers the change, name the
test explicitly in the PR description and request reviewer confirmation —
don't decide on your own.

## Common mistakes

- **Inlining the GraphQL string in the test module.** The string bypasses
  `validate-graphql`. Move it to
  `backend/tests/functional/graphql/operations/<name>.graphql` and load
  with `load_query("<name>")`.
- **Anonymous operation names.** Every operation must be named
  (`query GetCluster`, `mutation CreateCluster`) — anonymous operations
  break the `validate-graphql` discovery.
- **Asserting only on the GraphQL response.** Read back through
  `session.get(...)`. The resolver may have correctly returned the value
  while never persisting it — that's the regression §V exists to catch.
<!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 -->
- **Asserting only `extensions.code == "VALIDATION_ERROR"`.** graphql-core's own
  request-validation errors (a wrong variable type, a missing required
  argument) use the same code. Also assert the service's message and
  `path`, so the test proves the service rule fired. Example:
  `backend/tests/functional/graphql/test_backup_history_propagation.py`
  checks `"Provide exactly one of deployment_id or instance_id"` and
  `path == ["backups"]`.

## See Also

- Constitution Principle V (`.specify/memory/constitution.md`)
- Existing functional API tests: `backend/tests/functional/test_api.py`
- Python testing conventions: `dev/guidelines/backend/python.md`
