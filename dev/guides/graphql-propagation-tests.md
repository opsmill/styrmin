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

Place propagation tests under `backend/tests/unit/api/` (or
`backend/tests/functional/` if the test drives the GraphQL HTTP endpoint
end-to-end against an in-memory database). The existing functional API tests
in `backend/tests/functional/test_api.py` are good reference points: they
boot the ASGI app with an SQLite session and POST GraphQL queries against
it.

## Recipe: HTTP-driven propagation test (write)

```python
@pytest.mark.asyncio
async def test_create_cluster_persists_name(client: AsyncClient, session: AsyncSession):
    response = await client.post(
        "/graphql",
        json={
            "query": create_cluster_query,
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

Reuse the `session` and `client` fixtures from
`backend/tests/functional/test_api.py` (or the equivalent in your test
module). They wire the in-memory SQLite engine through the
`get_session` dependency override.

## Recipe: HTTP-driven propagation test (read)

```python
@pytest.mark.asyncio
async def test_get_cluster_projects_db_state(client: AsyncClient, session: AsyncSession):
    seeded = Cluster(name="seeded-cluster")
    session.add(seeded)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": get_cluster_query,
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

## See Also

- Constitution Principle V (`.specify/memory/constitution.md`)
- Existing functional API tests: `backend/tests/functional/test_api.py`
- Python testing conventions: `dev/guidelines/backend/python.md`
