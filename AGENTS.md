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
- `python_sdk/` – Async Python client SDK - see [python_sdk/AGENTS.md](python_sdk/AGENTS.md)
- `dev/` – Internal developer documentation - see [dev/README.md](dev/README.md)

## Commands

### Setup

```bash
uv sync                       # Install Python dependencies (root + all workspace members + dev group)
cd frontend && pnpm install   # Install frontend dependencies (required before `uv run invoke generate`)
```

> **Note:** `uv run invoke generate` regenerates both Python SDK types **and** frontend TypeScript types. Without `frontend/node_modules/`, the frontend codegen step fails with `sh: graphql-codegen: command not found`. Run `pnpm install` once after cloning the repo.

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

## Debugging E2E Tests

**Always run E2E tests in `backend/tests/e2e/` with `--pdb`.** Re-running the suite just to attach a debugger after a failure wastes minutes per iteration; every E2E run should start paused-ready so that if something fails the session is already frozen at the failure line with the vcluster, port-forwards, SDK clients, and test fixtures still alive. If the test passes, `--pdb` costs nothing.

```bash
uv run pytest backend/tests/e2e/<node_id> -v -s --pdb
```

While paused, open a second shell and introspect the cluster directly:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get pods -A
kubectl logs -n styrmin-<deployment-id> <pod> --all-containers
```

**When running via a non-interactive shell (background job, agent tool, CI), prefix the command with `sleep infinity |`** so pdb's stdin stays open instead of immediately hitting EOF and exiting (which tears the cluster down):

```bash
sleep infinity | uv run pytest backend/tests/e2e/<node_id> -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

Pytest stays paused indefinitely on failure. Inspect with `kubectl` from a separate shell, then kill the whole process group (`pkill -f pytest` or kill the job) once you're done — pdb can't receive commands over the dummy stdin.

Use `.agents/skills/e2e-troubleshoot/SKILL.md` for the structured multi-iteration variant of this `--pdb` workflow.

`--reruns` from ``pytest-rerunfailures`` is incompatible with ``--pdb``, which is why the plugin and its auto-retry markers were removed in bce37c1. Do not reintroduce them.

### Dual-entrypoint scope — mark `api_only` when there's no UI flow

E2E tests run twice by default: once as `[api-chromium]` (driver = SDK) and once as `[ui-chromium]` (driver = Playwright). Each variant adds ~20 minutes of CI time, so running both should be a deliberate choice tied to actually exercising the UI.

**Use `@pytest.mark.api_only(reason=...)`** when the test only consumes the SDK / GraphQL / Kubernetes APIs and does not drive a UI flow — for example, reading pod statuses, asserting on cluster state, or seeding data through the SDK with no page navigation. These tests would behave identically under `[ui-chromium]` (the SDK call path is the same), so the second variant burns CI time without adding coverage.

```python
@pytest.mark.api_only(
    reason="Reads pod statuses through the SDK; no UI flow exercised — "
    "the [ui-chromium] variant would just re-run the same SDK call.",
)
@pytest.mark.ci
async def test_<name>(...):
    ...
```

**Use `@pytest.mark.ui_only(reason=...)`** for the inverse — tests that assert on UI-specific behaviour (rendering, click flows, accessibility) that has no SDK equivalent.

**Heuristic for whether a test is `api_only`:** if every action you take in the test goes through `client.X.Y()`, `kubectl`, or `kr8s`, and the test never calls `scenario_driver.create_deployment` / `upgrade_deployment` / `create_backup` / `start_components` / etc. (the dual-entrypoint methods), it's an `api_only` candidate. Tests that *do* call those methods exercise both the UI and API code paths and should run under both variants.

### UI-variant troubleshooting — use the Playwright MCP server

When diagnosing a failure in a `[ui-chromium]` scenario, **always** drive the investigation through the Playwright MCP server rather than adding screenshot/HTML-dump instrumentation to the page object. The MCP server lets you navigate, evaluate, inspect element accessibility trees, and run arbitrary Playwright calls interactively — no round-trip through a 3-minute pytest fixture for each diagnostic iteration, and no throwaway debug code leaking into the test suite.

Typical loop:

1. Start a styrmin deployment the test expects (use `uv run pytest ... --pdb` to pause at the exact state, or run the fixtures explicitly).
2. Point the Playwright MCP server at the port-forwarded styrmin URL and reproduce the failing step by step.
3. Use MCP tools (`browser_snapshot`, `browser_evaluate`, `browser_click`, etc.) to inspect DOM, computed styles, `elementFromPoint`, console/network logs.
4. Form a hypothesis, apply the fix in source, re-run the full pytest to validate.

Only fall back to screenshot/HTML dumps inside the page object when the MCP server is genuinely unavailable.

## Coding Standards

- Python: `dev/guidelines/backend/python.md`
- Markdown: `dev/guidelines/markdown.md`

## Boundaries

### Always Do

- Install the pre-commit hooks once after cloning (`uv run invoke pre-commit-install`). Requires `prek` on PATH. Hooks run the project's mandatory checks locally before each commit; see `dev/guides/pre-commit-hooks.md`.
- Run formatters before committing (`uv run invoke format lint`)
- Regenerate `schema.graphql` after any GraphQL schema change (`uv run styrmin export graphql-schema schema.graphql`)
- Regenerate SDK types after any GraphQL schema or query change (`uv run invoke generate`)
- Write tests for new functionality
- Use type hints for Python (backend)
- **For every new feature, ship an E2E test covering the user-visible flow and run it to a pass before declaring the work done.** This applies equally when executing a speckit workflow (``/speckit.implement``, ``/speckit.tasks``, etc.) — the tasks list MUST include E2E coverage and the agent MUST execute it, not defer to a later iteration. E2E is part of the definition of done, not an optional follow-up. See Constitution §V.
- **For every GraphQL schema change (new/modified field, argument, input type, or mutation under `backend/styrmin_backend/api/schema/`), ship a propagation test.** See [`dev/guides/graphql-propagation-tests.md`](dev/guides/graphql-propagation-tests.md) for the full recipe; see Constitution §V for the rule.

### Ask First

- Database schema or migration changes
- GraphQL schema modifications
- New dependencies
- CI/CD workflow changes
- Authentication/authorization changes
- **Skipping E2E coverage for a bug fix, refactor, or small change.** If you believe the existing E2E suite already exercises the affected path (or the change is genuinely too narrow to warrant a new scenario), state which tests cover it and request confirmation before omitting new coverage — don't unilaterally decide the work is "too small".
- **Skipping a GraphQL propagation unit test for a schema change.** If you believe an existing propagation test already covers the new/modified field, name the test and request confirmation; don't decide unilaterally.

### Never Do

- Commit secrets, API keys, or credentials
- Edit generated files manually
- Skip linting in CI
- Force push to `stable` or `develop`

### Bypassing the pre-commit hooks

Use `git commit --no-verify` only for genuine emergencies — e.g., a hook that needs network when the network is down, or a hotfix to `develop`/`stable` from automation that has already run the equivalent checks. Routine "skip lint" commits are not appropriate; fix the violation and commit normally instead. CI's `Pre-Commit Hooks` job runs the same checks regardless, so bypassing locally only delays the failure. See `dev/guides/pre-commit-hooks.md` for the full bypass policy.

## Navigation

| Question | Location |
|----------|----------|
| How does the system work? | `dev/knowledge/` |
| How do I do X? | `dev/guides/` |
| Why was this decided? | `dev/adr/` |
| What are we building? | `specs/` |
| How should I write code? | `dev/guidelines/` |
| What agent workflows are available? | `.agents/skills/` and `.agents/commands/` |

## Component Maps

- Backend: `backend/AGENTS.md`
- Frontend: `frontend/AGENTS.md`
- Python SDK: `python_sdk/AGENTS.md`
- Drivers: `driver/DRIVERS.md`

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/007-graphql-propagation-tests/plan.md`.
<!-- SPECKIT END -->
