# Styrmin

Styrmin is a **deployment orchestration platform** that manages application deployments on Kubernetes clusters. It provides a declarative approach to deploying applications through "Application Drivers" - versioned deployment specifications that define how applications should be deployed, configured, and managed.

## Tech Stack

- **Backend:** Python, GraphQL with Strawberry, Pydantic, SQLModel, Prefect
- **Frontend:** React 19, TypeScript, Vite, urql, Tailwind CSS, Base UI
- **Linting:** ruff, ty (type checking); ESLint, Prettier (frontend)
- **Testing:** pytest (backend); Vitest, React Testing Library (frontend)
- **Package Managers:** uv (Python), pnpm (frontend)
- **Task Runner:** Invoke

## File Structure

- `backend/` – Python backend (GraphQL, core logic) - see [backend/AGENTS.md](backend/AGENTS.md)
- `frontend/` – React frontend (SPA) - see [frontend/AGENTS.md](frontend/AGENTS.md)
- `dev/` – Internal developer documentation - see [dev/README.md](dev/README.md)

## Commands

### Setup

```bash
uv sync --all-groups --all-packages   # Install Python dependencies add all packages are installed
```

### Testing

```bash
uv run invoke test       # Backend tests
cd frontend && pnpm test # Frontend tests
```

### Linting & Formatting

```bash
uv run invoke format           # Format all Python code
uv run invoke lint             # Lint all Python code
```

**Important:** `ruff` and `ty` are the authoritative tools for detecting Python syntax errors, style violations, and type issues. Do not attempt to identify Python syntax errors by reading the code — run `uv run invoke format lint` instead and rely on the tool output.

### GraphQL Schema

```bash
uv run styrmin export graphql-schema schema.graphql  # Regenerate schema.graphql
uv run invoke generate                                # Regenerate SDK types from queries
```

When modifying GraphQL queries or mutations (in `backend/styrmin_backend/api/schema/`), you **must**:

1. Regenerate `schema.graphql` at the repo root
2. Regenerate SDK types with `uv run invoke generate`

Both steps are required because the generated Pydantic models in `python_sdk/src/styrmin_sdk/graphql/_generated/` are derived from the schema and the `.graphql` query files. CI will fail if either is out of date.

### Build

TODO

## GraphQL Queries

All GraphQL operations (queries and mutations) **must** be placed in dedicated `.graphql` files. Inline GraphQL strings in Python code are **not allowed**.

### Directory Conventions

- **SDK operations:** `python_sdk/src/styrmin_sdk/graphql/`
- **Dev task operations:** `tasks/graphql/`

### Rules

- One operation per `.graphql` file
- File naming: snake_case derived from the GraphQL operation name (e.g., `GetCluster` → `get_cluster.graphql`)
- Load queries using the `load_query()` utility, never as inline strings
- Validate with `uv run invoke validate-graphql` before committing

### Adding a New Query

1. Create `<operation_name>.graphql` in the appropriate directory (every operation **must** have a name, e.g., `query GetCluster`, not anonymous `query {`)
2. Use `load_query("<operation_name>")` to load it in Python code
3. Run `uv run invoke validate-graphql` to verify it passes schema validation
4. Run `uv run invoke generate` to regenerate SDK Pydantic types

## Invoke Tasks

When an Invoke task does not use the `context` parameter, suppress the lint error with `# noqa: ARG001` on the function signature rather than renaming the parameter (e.g., `_context`). Example:

```python
@task
def my_task(context: Context) -> None:  # noqa: ARG001
```

## Coding Standards

- Python: `dev/guidelines/backend/python.md`
- Markdown: `dev/guidelines/markdown.md`

## Boundaries

### Always Do

- Run formatters before committing (`uv run invoke format lint`)
- Regenerate `schema.graphql` after any GraphQL schema change (`uv run styrmin export graphql-schema schema.graphql`)
- Regenerate SDK types after any GraphQL schema or query change (`uv run invoke generate`)
- Write tests for new functionality
- Use type hints for Python (backend)

### Ask First

- Database schema or migration changes
- GraphQL schema modifications
- New dependencies
- CI/CD workflow changes
- Authentication/authorization changes

### Never Do

- Commit secrets, API keys, or credentials
- Edit generated files manually
- Skip linting in CI
- Force push to `stable` or `develop`

## Navigation

| Question | Location |
|----------|----------|
| How does the system work? | `dev/knowledge/` |
| How do I do X? | `dev/guides/` |
| Why was this decided? | `dev/adr/` |
| What are we building? | `dev/specs/` |
| How should I write code? | `dev/guidelines/` |
| What commands are available? | `.agents/commands/` |

## Component Maps

- Backend: `backend/AGENTS.md`
- Frontend: `frontend/AGENTS.md`
- Drivers: `driver/DRIVERS.md`
