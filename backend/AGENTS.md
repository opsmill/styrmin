# Backend

Python backend for Styrmin: GraphQL API, service layer, repositories, database models, Prefect workflows, Kubernetes agent tasks, and operator logic.

## Tech Stack

- **API:** FastAPI, Strawberry GraphQL
- **Models:** SQLModel, Pydantic
- **Workflows:** Prefect
- **Kubernetes:** kr8s, kopf, FluxCD HelmRelease resources
- **Tooling:** uv, ruff, ty, pytest

## Commands

Run from the repository root unless noted otherwise.

```bash
uv run invoke test
uv run invoke format
uv run invoke lint
uv run invoke validate-graphql
```

For E2E tests in `backend/tests/e2e/`, follow the root `AGENTS.md` debugging policy and run with `--pdb`:

```bash
uv run pytest backend/tests/e2e/<node_id> -v -s --pdb
```

## Context Map

| Area | Read |
|------|------|
| Backend architecture | `dev/knowledge/backend/overview.md` |
| GraphQL API | `dev/knowledge/backend/api.md` |
| Data models | `dev/knowledge/backend/data-models.md` |
| Services and Unit of Work | `dev/knowledge/backend/services.md` |
| Reconciliation | `dev/knowledge/backend/reconciliation.md` |
| Hooks and user actions | `dev/knowledge/backend/hooks-and-actions.md` |
| Prefect orchestration | `dev/knowledge/backend/orchestration-flows.md` |
| Kubernetes agent | `dev/knowledge/backend/agent.md` |
| Kopf operator | `dev/knowledge/backend/operator.md` |
| Backup and restore | `dev/knowledge/backend/backup-restore.md` |
| E2E test architecture | `dev/knowledge/backend/e2e-testing.md` |
| Python style | `dev/guidelines/backend/python.md` |
| Database migrations | `dev/guides/database-migrations.md` |

## Backend Rules

- Keep GraphQL operations in dedicated `.graphql` files; do not inline GraphQL strings in Python.
- After GraphQL schema or query changes, regenerate `schema.graphql` and SDK types:

  ```bash
  uv run styrmin export graphql-schema schema.graphql
  uv run invoke generate
  ```

- Ask before database schema or migration changes.
- When changing SQLModel database models, create and review an Alembic migration.
- Use module-level async service functions with `uow: UnitOfWork`; do not introduce service classes unless the architecture changes explicitly.
- Use `ServiceError` subclasses for service-layer failures.
- Use `loguru` with brace-style placeholders.
- Do not edit generated files manually.
