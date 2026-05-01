# Quickstart — Add a Propagation Test

Use this guide when a GraphQL schema change lands and you need to add the matching Constitution §V propagation test, or when working through the gaps in `coverage-matrix.md`.

> **Source of truth**: `dev/guides/graphql-propagation-tests.md` and `contracts/propagation-test-contract.md` (this directory). This page is the *fast* path; consult those files for the full rules.

## 1. Pick a row from the matrix

Open `coverage-matrix.md`. Find a row with verdict `gap` or `partial`. Note its **Element**, **Direction**, and **Planned test**.

## 2. Open the right test module

Tests live under `backend/tests/functional/propagation/test_<domain>_propagation.py`. If the file does not exist yet, create it from this skeleton:

```python
"""Propagation tests for <domain> resolvers.

See specs/007-graphql-propagation-tests/contracts/propagation-test-contract.md.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import <DBModel>

from ._queries import load_query
```

## 3. Add the GraphQL operation as a `.graphql` file

GraphQL operations used by propagation tests **must** live in
`backend/tests/functional/propagation/graphql/<operation_name>.graphql` — never
inline in the test module. Inline strings bypass `uv run invoke validate-graphql`,
which means a schema change can break a test silently.

Create `backend/tests/functional/propagation/graphql/create_widget.graphql`:

```graphql
mutation CreateWidget($name: String!, $config: JSON) {
    createWidget(name: $name, config: $config) {
        id
        name
        config
    }
}
```

Rules:
- One operation per file. Snake_case file stem matches the operation name.
- Operations **must** be named (`mutation CreateWidget`, never anonymous `mutation { ... }`).
- The file is auto-discovered by `validate-graphql` via `rglob`. No registration step is needed.

Confirm the operation validates:

```bash
uv run invoke validate-graphql
```

The relevant line should appear as `OK    backend/tests/functional/propagation/graphql/create_widget.graphql`.

## 4. Write the test

Load the operation via `load_query("<file_stem>")` from the package-local
`_queries` module — never paste GraphQL into the test module.

### Write recipe

```python
@pytest.mark.asyncio
async def test_create_widget_persists_name_and_config(
    client: AsyncClient,
    session: AsyncSession,
):
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("create_widget"),
            "variables": {"name": "my-widget", "config": {"k": "v"}},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload
    widget_id = UUID(payload["data"]["createWidget"]["id"])

    db_row = await session.get(Widget, widget_id)
    assert db_row is not None
    assert db_row.name == "my-widget"
    assert db_row.config == {"k": "v"}
```

### Read recipe

```python
@pytest.mark.asyncio
async def test_widget_projects_all_scalars(
    client: AsyncClient,
    session: AsyncSession,
):
    seeded = Widget(name="seeded", config={"k": "v"})
    session.add(seeded)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("get_widget"),
            "variables": {"widgetId": str(seeded.id)},
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]["widget"]
    assert data["name"] == "seeded"
    assert data["config"] == {"k": "v"}
```

## 5. Workflow-dispatching mutations

If your mutation calls `prefect_manager.run_action(...)`, add the `prefect_manager_mock` fixture (defined in `backend/tests/functional/propagation/conftest.py`) to your test signature. The mock prevents real Prefect calls and lets you optionally assert on the dispatched parameters.

```python
@pytest.mark.asyncio
async def test_create_backup_persists_row(
    client, session, prefect_manager_mock,
):
    # ... mutation call ...
    db_row = await session.get(Backup, backup_id)
    assert db_row is not None
    # Optional: assert prefect_manager_mock.run_action.await_count == 1
```

## 6. Mocking external loaders

For mutations that load from disk / git / HTTP (e.g. `loadLocalApplicationDriverVersion`, `loadRemoteApplicationDriverVersion`), patch at the **service-boundary loader** with `pytest-mock`:

```python
async def test_load_local_driver_persists_rows(
    client, session, mocker,
):
    mocker.patch(
        "styrmin_backend.api.schema.mutation.load_application_driver_from_local_directory",
        new=AsyncMock(return_value=<seeded ApplicationDriverVersion model>),
    )
    # ... HTTP call + DB read-back ...
```

Patch the **import site** (`api.schema.mutation`), not the definition site (`services.applications`), so the resolver picks up the patched callable.

## 7. Run the test

```bash
# Just your new test
uv run pytest backend/tests/functional/propagation/test_<domain>_propagation.py -v

# With pdb on the first failure (use `sleep infinity |` from non-interactive shells)
uv run pytest backend/tests/functional/propagation/test_<domain>_propagation.py -v --pdb

# Full backend suite
uv run invoke test
```

## 8. Verify your test would catch the regression

Temporarily comment out the resolver-to-service wiring (or change one field assignment in the service). Re-run your test. **It must fail.** Restore the code. This step is the single highest-value sanity check that distinguishes a real propagation test from a coincidental pass.

## 9. Format, lint, commit

```bash
uv run invoke format lint
git add backend/tests/functional/propagation/<module>.py backend/tests/functional/helpers.py
git commit -m "test(<domain>): add propagation tests for <element>"
```

Pre-commit hooks must pass. Do not use `--no-verify`.

## 10. Update the matrix

Open `coverage-matrix.md`, find the row(s) you closed, and update **Verdict** from `gap`/`partial` to `covered` and **Existing coverage** to point at your new test (`backend/tests/functional/propagation/<module>.py::<test>`).

---

## Common pitfalls

- **Inlining the GraphQL string in the test.** Bypasses `validate-graphql`. Always extract to `graphql/<name>.graphql` and load via `load_query("<name>")`.
- **Using an anonymous operation.** `query { cluster(...) { id } }` is invalid here — name every operation (`query GetCluster { ... }`) so `validate-graphql` discovers and reports it correctly.
- **Asserting only on the GraphQL response.** Read back through `session.get(...)`. The resolver may have correctly returned the value while never persisting it — that is the exact regression §V is designed to catch.
- **Mocking the repository.** The repository is the layer under test; mocking it deletes the propagation contract.
- **Mocking the service function.** Same as above — the service is what wires the resolver to the repository, so mocking it removes the integration the test exists to verify.
- **Sharing seeded rows across tests.** The `session` fixture is function-scoped; do not try to hoist it. Test isolation is cheap here.
- **Forgetting the `assert "errors" not in payload, payload` guard.** GraphQL returns 200 even when the operation errored. Always assert no errors before reading `data[...]`.
- **Asserting `prefect_manager_mock.run_action` smoke-style.** Only assert on it when its parameters dict surfaces a propagated input that doesn't appear in the DB write.
