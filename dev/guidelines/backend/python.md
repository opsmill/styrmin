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

<!-- Extracted from specs/011-env-config-input-hardening on 2026-05-10 -->

### Validator entry-point type guards

Public validators MUST type-check their inputs at the **entry point**,
before any encoding, size computation, or other downstream work. Non-string
(or otherwise wrong-typed) inputs surface as a typed `ServiceError` with
`error_code` + `error_metadata` — never as a generic `AttributeError` /
`TypeError` raised by a downstream `.encode("utf-8")` or similar:

```python
def validate_env_var_value(name: str, value: str, scope: str | None = None) -> None:
    if not isinstance(value, str):
        raise InvalidEnvVarValueError(
            name=name,
            value_type=type(value).__name__,
            scope=scope,
        )
    # ... existing 64 KiB cap check, encoding, etc. ...
```

The same guard belongs in any dict-level helper that callers can hit
without passing through the per-value validator (defence in depth — see
spec 011/US3 for the regression that motivated the rule).

`bool` is a subclass of `int`, not `str` — `isinstance(value, str)`
correctly rejects `True`/`False`. Coercing wrong-typed values via `str(value)`
is **forbidden**: an operator who passes `1` may have meant `"1"` or may
have intended an integer; a typed error tells them which.

### Schema-walking propagation tests

Every Strawberry input that mirrors a Pydantic config model MUST have a
runtime test that introspects both sides and asserts every Pydantic field
has a corresponding Strawberry input field. The test fails fast with the
missing field name when schema drift introduces a Pydantic field without
its input mirror. See [ADR-022](../../adr/adr-022-schema-walking-input-propagation-tests.md)
for the full pattern and the `EnvironmentConfig` ↔ `UpdateEnvironmentInput`
exemplar at `backend/tests/functional/graphql/test_environment_update_propagation.py`.

The schema walk is fail-on-drift; the existing per-field round-trip tests
are fail-on-regression. Both stay; neither subsumes the other.

### Per-target failure isolation in fanout writes

When a write operation fans out across multiple targets (e.g.
`update_environment` redeploys every deployment in the environment),
wrap each per-target invocation in a `try/except Exception`, record the
failure on the per-target `Task`, log it structured, and continue to the
next target. The mutation succeeds once every iteration has either
dispatched a Task or recorded a failure; per-target failures do **not**
surface in the mutation envelope:

```python
for deployment in deployments:
    try:
        task = await redeploy_for_environment_update(deployment, uow)
    except Exception as exc:  # noqa: BLE001 — surface as a per-target Task
        logger.warning(
            "fanout_redeploy_failed",
            deployment_id=str(deployment.id),
            error=str(exc),
        )
        await record_failed_task(deployment, exc, uow)
        continue
    tasks.append(task)
```

This pattern is what makes a fanout write resilient to per-deployment
chart-render failures, missing drivers, or transient cluster errors —
one bad deployment does not block the rest. The failure surface is
queryable via `Deployment.timeline` after the fact; see [ADR-020 §commit
ordering](../../adr/adr-020-environment-config-fanout.md) for the
durability contract.

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

### Admin & authorization mutations

Rules for any mutation that touches user/group state, admin-conferring rows, or session lifecycle. See [`knowledge/backend/services.md`](../../knowledge/backend/services.md) → "Authorization helpers" for the helper modules and [`knowledge/backend/api.md`](../../knowledge/backend/api.md) → "Admin user/group surface" for the wire contract.

- New mutations that change admin-conferring state (role assignment, group membership, active flag, hard-delete) MUST attach `PermissionExtension([RequiresRole(Role.ADMIN)])`. Do not invent ad-hoc role checks in the resolver body.
- Any operation that could violate the last-admin invariant MUST call through `auth/admin_guards` inside its own transaction, with the admin-conferring rows locked via `SELECT ... FOR UPDATE`. Inline rule re-implementations are forbidden — the four-action matrix (`DEACTIVATE` / `DELETE` / `DEMOTE` / `REMOVE_FROM_ADMIN_GROUP`) lives in one place.
- Membership replacements MUST go through `auth/membership.replace_user_groups` / `replace_group_members`. Do not issue a full `DELETE all → INSERT all` pattern; diff-and-mutate is the only acceptable shape (zero statements on no-change is required).
- Mutations that invalidate sessions (`resetUserPassword`, `updateUser(active=False)`, role downgrade where the new role removes admin) MUST share a single transaction with the originating change. The write order is: mutate the user row → flush (no commit) → delete affected sessions → commit. A failure in the session delete MUST roll back the user-row change.
- Admin mutations MUST emit one Loguru audit line on success, after the transaction commits, in the shape:

  ```python
  logger.info(
      "admin_mutation actor={} action={} target={} changed_fields={}",
      actor_id, action_name, target_id, comma_separated_field_names,
  )
  ```

  Field **names only** — never values. Emit from the service function so it only fires on commit, never from the resolver.
- Password-bearing GraphQL variables MUST be added to the `MASKED_VARIABLE_NAMES` frozenset in `api/logging/mask.py`. Per-mutation ad-hoc masking is forbidden — every password field on the schema goes through that one allow-list. Adding a new password field is a one-line PR change that triggers code review on the import site.

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

## Rendering Kubernetes manifests

### No runtime defaults for optional emitted annotations

For optional operator-config fields that drive an emitted Kubernetes annotation, label, or similar wire artifact, the rendering site MUST emit the key only when the resolved value is not `None`:

```python
if context.instance.config.<field> is not None:
    annotations["<annotation-key>"] = context.instance.config.<field>
```

No defaulting at render time, no defaulting at Pydantic-model time, no defaulting in the builder. `None` propagates from the Pydantic field through `ResolvedConfig` to the renderer, and the renderer treats `None` as "skip this annotation". The downstream controller (external-dns, Traefik, …) applies its own default for absent annotations — the platform does not claim authority over defaults it has no business setting.

**Why:** always-emit-with-a-default rewrites the rendered manifest for every existing deployment on upgrade — even ones that never touched the knob. Code review should flag any `annotations["..."] = ... or "default"` shape. Chart-values templates honour the same rule with `{% if … %}` guards.

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
