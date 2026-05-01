# Propagation Test Contract

Every test added under `backend/tests/functional/propagation/` MUST satisfy this contract. A test that fails any clause is not a valid propagation test for purposes of the Constitution §V verdict in `coverage-matrix.md`.

## C1. Drives the GraphQL boundary

The test issues a request through the same boundary a real client would. Acceptable forms:

- `await client.post("/graphql", json={"query": ..., "variables": ...})` (preferred).
- A direct call to a Strawberry resolver passing a real `info.context["uow"]` constructed against the test session — only when the field under test is a nested resolver and the parent query path is already covered by another propagation test.

A test that calls a *service function* directly does **not** satisfy C1.

## C2. Real layered architecture

The full chain `GraphQL resolver → service function → repository → DB session` runs unmodified during the test. The test MUST NOT:

- Substitute `tests/unit/services/fakes.py::FakeUnitOfWork` for the real UoW.
- Substitute `Fake*Repository` instances for the real `SQLModel*Repository`.
- Patch the resolver itself.
- Patch the service function.
- Patch the repository class or any of its methods.

## C3. Real database session

The DB-side state observed at assertion time MUST come from the same session the resolver wrote to (the `session` fixture in `backend/tests/functional/test_api.py`, bound through the FastAPI `get_session` dependency override). Acceptable read-back forms:

- `await session.get(<DBModel>, <id>)`.
- A direct query through `session.exec(select(<DBModel>)...)`.
- Instantiating a real repository against `session` and calling its method.

A test that asserts only on the resolver's GraphQL response payload does **not** satisfy C3 — that is the regression Constitution §V exists to catch.

## C4. Boundary fakes only

External systems may be faked **only** at the system boundary the service crosses to reach them:

| External system | Fake at                                                            | How                                                                                                       |
|-----------------|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| Prefect         | `styrmin_backend.workflows.dependency.get_manager`                 | `dependency_provider.override(get_manager.__wrapped__, get_fake_manager)` returning `Mock(spec=PrefectManager)` (see `prefect_manager_mock` fixture) |
| Kubernetes      | `kubernetes_asyncio` client constructors at the call site          | `mocker.patch(...)` with `AsyncMock`                                                                       |
| helm            | `subprocess` / helm-CLI call sites in `services/applications.py`   | `mocker.patch(...)`                                                                                        |
| git / HTTP      | The loader function entry point (`load_application_driver_from_git_repository` etc.) | `mocker.patch(...)` returning a fixture-built `ApplicationDriverVersion` model                            |

If a propagation test patches the resolver, service, repository, or `session`, that patch is a C2/C3 violation, not a boundary fake.

## C5. Asserts every relevant scalar

For **writes**, the test asserts every scalar field of the input type / mutation argument set against the corresponding column on the persisted row. If a field is computed/server-set (timestamps, status enums, derived ids), the test asserts it is populated and has the expected shape.

For **reads**, the test asserts every scalar output field of the type under test against the seeded row's value. Asserting only `id` is **not** sufficient.

## C6. Filter arguments are exercised meaningfully

For queries with filter arguments (e.g. `backups(instanceId, status)`, `podStatuses(deploymentId, environmentId, clusterId)`), the test seeds at least one matching row **and** at least one non-matching row, then asserts the resolver returns only the matching set. This proves the argument was actually consumed by the repository.

## C7. Independent, isolated, fast

- The test is independently runnable: `uv run pytest backend/tests/functional/propagation/<module>::<test>` passes in isolation.
- The test does not depend on order, on other tests' fixtures, or on session-scoped state.
- The test completes in under 1 second on a developer laptop.
- The test does not touch the network, Kubernetes, Prefect, helm, git, or any subprocess.

## C8. Mocking depth limits

`prefect_manager_mock.run_action` may be asserted against only when the parameters dict surfaces a propagated input that does not appear in any DB write. Otherwise prefer the DB read-back assertion. A test SHOULD NOT add `run_action.assert_called_with(...)` purely as a smoke-check; that's not what propagation tests prove.

## C9. Error paths

Negative-path tests (e.g. "internal deployment cannot be updated") follow the same C1–C7 rules but assert the typed error response in the GraphQL `errors` array (with `extensions.code`) and the absence of any DB write.

## C10. Lint and format

`uv run invoke format lint` MUST pass. Pre-commit hooks MUST NOT be bypassed.
