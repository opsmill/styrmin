# Python Coding Guidelines

## Tooling

- **Linter & Formatter:** ruff (all rules enabled via `select = ["ALL"]`, with selective ignores)
- **Type Checker:** ty (Astral's type checker, configured in `[tool.ty]` in `pyproject.toml`)
- **Line Length:** 120 characters (hard limit), 150 for pycodestyle
- **Quote Style:** Double quotes
- **Complexity:** Max cyclomatic complexity of 10

Run before committing:

```bash
uv run invoke format lint
```

## Type Hints

All public functions must have complete type annotations (enforced by ty).

- Use `X | Y` syntax instead of `Union[X, Y]`
- Use `X | None` instead of `Optional[X]`
- Prefer `Sequence[T]` over `list[T]` for read-only return types
- Use `TYPE_CHECKING` blocks to avoid circular imports:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from styrmin_backend.db.models import Cluster
```

Tests are exempt from strict typing enforcement.

## Import Ordering

Managed by ruff isort. Standard order:

1. `from __future__ import annotations`
2. Standard library imports
3. Third-party imports
4. Local application imports
5. `TYPE_CHECKING` block (at the end of imports)

## Logging

Use **loguru**, not the standard `logging` module:

```python
from loguru import logger

logger.info("Processing deployment_id={}", deployment_id)
logger.debug("Context resolved: cluster={} env={}", cluster.name, env.name)
```

Use brace-style placeholders `{}` (not f-strings or `%`-formatting) in log messages for structured logging.

## Service Layer

Services are **module-level async functions**, not classes:

```python
async def create_cluster(name: str, config: dict | None, uow: UnitOfWork) -> Cluster:
    async with uow:
        cluster = Cluster(name=name, config=config)
        await uow.clusters.add(cluster)
        await uow.commit()
        return cluster
```

Conventions:

- Every service function takes `uow: UnitOfWork` as a parameter
- Use `async with uow:` context manager for transaction scope
- Call `await uow.commit()` explicitly to persist changes
- Naming: action verbs (`get_`, `create_`, `update_`, `delete_`, `deploy_`, `refresh_`)

## Repository Pattern

Repositories use abstract base classes with concrete SQLModel implementations:

```python
class ClusterRepository(BaseRepository[Cluster], ABC):
    @abstractmethod
    async def get_by_name(self, name: str) -> Cluster | None:
        raise NotImplementedError()

class SQLModelClusterRepository(BaseSQLModelRepository[Cluster], ClusterRepository):
    model_class = Cluster

    async def get_by_name(self, name: str) -> Cluster | None:
        statement = select(self.model_class).where(self.model_class.name == name)
        result = await self.session.exec(statement)
        return result.first()
```

Use `_eager_load_options()` for relationships to prevent N+1 queries.

## Error Handling

Custom exceptions inherit from `ServiceError` with `error_code` and `default_message`:

```python
class DeploymentNotFoundError(ServiceError):
    error_code = "NOT_FOUND"
    default_message = "Deployment not found"
```

Raise with exception chaining:

```python
raise InvalidContextError() from e
```

## Database Models (SQLModel)

- Inherit from `StyrminModel` (provides `id`, `created_on`, `updated_on`)
- Use `table=True` for database-backed models
- JSON columns: `Field(sa_column=Column(JSON))`
- Relationships: `Relationship(back_populates="...")`

## Domain Models (Pydantic)

- Use `BaseModel` for domain objects
- Use `PrivateAttr` for internal state
- Provide `@classmethod create()` factory methods
- Use `@property` for computed fields

## GraphQL (Strawberry)

- Types use `@strawberry.type` decorator
- Convert from DB models via `@classmethod from_instance()`
- Hide internal fields with `strawberry.Private[T]`
- Inject context via `info: strawberry.Info` parameter
- All GraphQL operations must be in `.graphql` files (see CLAUDE.md)

### Nested Resolvers

<!-- Extracted from specs/001-graphql-nested-resolvers on 2026-04-01 -->

When adding a nested object field to a GraphQL type, choose the resolver pattern based on whether the relationship is already eager-loaded:

- **Async UoW resolver** (preferred for new fields): Fetch via `info.context["uow"]`. Only executes when the field is requested. Use when the repository does not eager-load the relationship.
- **Sync resolver**: Access `self.instance.relationship` directly. Use only when the repository already eager-loads the relationship via `selectinload`.

**Nullability**: Match the resolver return type to the FK nullability in the database model. Non-nullable FK → non-nullable return. Nullable FK → nullable return.

**Error handling**: Non-nullable resolvers must raise an exception (e.g., `ValueError`) if the entity is not found — this surfaces as a GraphQL field error. Nullable resolvers return `None` when the FK is null (skip the DB query).

```python
# Async UoW resolver (non-nullable)
@strawberry.field
async def environment(self, info: strawberry.Info) -> Environment:
    uow = info.context["uow"]
    entity = await uow.environments.get(self.instance.environment_id)
    if entity is None:
        msg = f"Environment {self.instance.environment_id} not found"
        raise ValueError(msg)
    return Environment.from_instance(entity)

# Async UoW resolver (nullable)
@strawberry.field
async def deployment(self, info: strawberry.Info) -> Deployment | None:
    if self.instance.deployment_id is None:
        return None
    uow = info.context["uow"]
    entity = await uow.deployments.get(self.instance.deployment_id)
    return Deployment.from_instance(entity) if entity else None

# Sync resolver (relationship already eager-loaded)
@strawberry.field
def application_driver(self) -> ApplicationDriver:
    return ApplicationDriver.from_instance(self.instance.application_driver)
```

**Circular imports**: Use `strawberry.lazy()` with `Annotated` only when circular imports actually occur. Prefer standard imports when possible.

## Prefect Flows & Tasks

- `@task` for individual async operations
- `@flow` for multi-step orchestration
- Use `flow_run_name` / `task_run_name` for readable Prefect UI entries
- Only top-level wrapper flows register callbacks; inner flows do not

## Invoke Tasks

When a task does not use `context`, suppress with `# noqa: ARG001`:

```python
@task
def my_task(context: Context) -> None:  # noqa: ARG001
    ...
```

## Testing

- pytest with pytest-asyncio (`asyncio_mode = "auto"`)
- Fake repositories for unit tests (see `tests/unit/services/fakes.py`)
- `fast_depends.dependency_provider` for dependency overrides in tests
- Test naming: `test_<function>_<scenario>`
- `assert` statements allowed in tests (S101 ignored)
- Type hints optional in test files

### GraphQL ↔ Database Propagation Tests

Per Constitution §V, every GraphQL field, argument, input type, and mutation
under `backend/styrmin_backend/api/schema/` MUST be covered by a unit test that
asserts full-stack propagation across the layered architecture (Principle III).
This is non-negotiable: a schema change is not "done" until the propagation
test exists and passes.

**What to assert:**

- **Mutations / write arguments**: drive the resolver with the input value and
  read the persisted state back through the real repository (or directly from
  the database session). Asserting only on the resolver's return value is not
  sufficient — the test must prove the value reached the database.
- **Queries / output fields**: seed state through the real repository, execute
  the query, and assert the resolver projects the persisted state correctly.

**What to use:**

- Real service functions and real repository implementations (the same
  `SQLModel*Repository` classes used in production).
- A real database session (the test database fixture), not fake repos. Fake
  repositories from `tests/unit/services/fakes.py` are appropriate for service
  logic tests, but propagation tests specifically exercise the repository
  ↔ database edge and therefore require the real implementation.
- Fakes/stubs are allowed only for systems outside the layered architecture
  (Kubernetes, Prefect, helm, external HTTP services).

**When to skip:** never, for a new or modified schema element. If you believe
an existing propagation test already covers the change, name it explicitly in
the PR description and request reviewer confirmation — don't decide on your
own.
