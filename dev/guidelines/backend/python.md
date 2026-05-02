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

### Soft-delete and partial unique indexes

<!-- Extracted from specs/008-deployment-deletion on 2026-05-02 -->

When a column makes a row "tombstoned" (e.g., `deleted_at: datetime | None` set after soft-delete), unique constraints involving that table MUST be expressed as **partial unique indexes** predicated on `deleted_at IS NULL` — not as plain `Field(unique=True)` or `UniqueConstraint(...)`. Otherwise tombstoned rows continue to occupy the name slot and prevent operators from reusing names after deletion.

The pattern uses SQLAlchemy's `Index` in `__table_args__` so the constraint is dialect-portable (Postgres in production, SQLite in unit tests):

```python
from sqlalchemy import Index, text

class Deployment(StyrminModel, table=True):
    __table_args__ = (
        Index(
            "uq_deployment_env_name_active",
            "environment_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    name: str  # do NOT pass unique=True — the partial index above is the gate
    environment_id: UUID = Field(foreign_key="environment.id")
    deleted_at: datetime | None = Field(default=None, index=True)
```

Companion conventions for the surrounding code:

- The DB-level partial index is the **authoritative race-free guard**. Service-layer name-conflict checks are best-effort pre-flights that produce a friendly typed error; they do not replace the index. Wrap the eventual commit and map `sqlalchemy.exc.IntegrityError` to a typed `*ConflictError` so concurrent callers see consistent semantics.
- Repository helpers that resolve names (`get_by_name`, `find_names_with_prefix`) MUST take the relevant scope key (e.g., `environment_id`) as a required parameter and accept an optional `include_deleted: bool = False`. Default behaviour is "active rows in this scope only".
- The migration that introduces the partial index SHOULD include a defensive pre-flight: refuse to apply if any pair of currently-active rows already collide on the index columns. This catches corrupt input before the index is created. See migration `c9d0e1f2a3b4_deployment_name_scoped_uniqueness` for the worked pattern.

Worked example: `Deployment.name` (ADR-018). Rationale: ADR-015 (soft-delete tombstoning).

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
- **GraphQL schema changes require a propagation test** — see
  [`dev/guides/graphql-propagation-tests.md`](../../guides/graphql-propagation-tests.md).
