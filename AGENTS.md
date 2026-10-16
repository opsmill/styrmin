# Styrmin

Styrmin is a **deployment orchestration platform** that manages application deployments on Kubernetes clusters. It provides a declarative approach to deploying applications through "Application Drivers" - versioned deployment specifications that define how applications should be deployed, configured, and managed.

## Read before exploring

- **[`CONTEXT.md`](CONTEXT.md)** at the repo root — the project glossary. Defines the canonical name for every domain concept (cluster, environment, deployment, instance, driver, context, agent, operator, …) and the synonyms to avoid. Use these terms verbatim in code, schema, specs, ADRs, commit messages, and conversation. If a concept is missing or drifts from how the code actually uses it, update CONTEXT.md in the same change.
- **[`dev/constitution.md`](dev/constitution.md)** — the prescriptive non-negotiable principles (declarative reconciliation, driver-based deployment, layered architecture, typed errors, E2E definition-of-done, propagation tests, documentation accuracy).
- **[`dev/knowledge/architecture.md`](dev/knowledge/architecture.md)** — the descriptive companion explaining how the principles are realised today.
- **[`dev/adr/`](dev/adr/)** — read ADRs that touch the area you're about to work in.

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
- `docs/` – User-facing documentation site (Docusaurus)
- `dev/` – Internal developer documentation - see [dev/README.md](dev/README.md)
- `scripts/` – Developer scripts, such as `e2e-pdb.sh`, which runs an E2E test with `--pdb` from a non-interactive shell

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

### Prerequisites (read this before claiming an E2E is blocked)

E2E tests in `backend/tests/e2e/` are **self-bootstrapping**. The session-scoped `vcluster` fixture in `conftest.py` creates a disposable virtual Kubernetes cluster per pytest session (via vCluster on Docker) and tears it down on exit. There is **no host cluster, no kind, no k3d, no minikube** involved.

- **Required on PATH**: `vcluster` and `docker` (or any OCI-compatible runtime accessible to `vcluster create --driver=docker`). That's it.
- **You do NOT need to pre-run `uv run invoke dev`.** That command (or the `dev-validate` skill) brings up the long-running dev stack for *interactive* development and manual exploration — frontend hot-reload against a real backend. It is **separate from the test stack** and not a test prerequisite; the E2E fixtures ignore it and create their own ephemeral cluster.
- **A failing E2E is almost never "blocked by missing infrastructure".** The fixture handles cluster lifecycle. Before recording an E2E as `❌ blocked`, **verify the alleged missing dependency by reading `backend/tests/e2e/conftest.py`** — most claimed blockers (k3d, kind, port not listening, no running backend) are imaginary. Genuine blockers reduce to: docker daemon down, `vcluster` binary missing from PATH, lockfile out of sync, host disk full. Confirm one of those before deferring the task.

See `dev/knowledge/backend/e2e-testing.md` for the full fixture graph, scope rules, and debugging workflow.

### Running with `--pdb`

**Always run E2E tests in `backend/tests/e2e/` with `--pdb`.** On failure the session freezes at the failure line with the vcluster, port-forwards, SDK clients, and fixtures still alive — no re-run needed to attach a debugger. If the test passes, `--pdb` costs nothing.

```bash
uv run pytest backend/tests/e2e/<node_id> -v -s --pdb
```

While paused, open a second shell and introspect the cluster directly:

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get pods -A
kubectl logs -n styrmin-<deployment-id> <pod> --all-containers
```

**When running via a non-interactive shell (background job, agent tool)**, pdb's stdin hits EOF the moment the test fails, so pytest exits and the vcluster is torn down before you can look at it. Use the wrapper, from the repository root:

```bash
scripts/e2e-pdb.sh backend/tests/e2e/<node_id>
scripts/e2e-pdb.sh "backend/tests/e2e/test_x.py::test_y[ui-chromium]" --tb=long
```

The wrapper gives pytest a FIFO as stdin that stays open until the run ends, so pdb waits for input instead of reading end of input. When stdin is a terminal, it runs pytest in the foreground instead, so you can type pdb commands; stop that run with Ctrl-C and then `q` at the `(Pdb)` prompt. It passes your arguments to pytest followed by `-v -s --pdb`, writes a combined log, and exits with pytest's own status. Each run writes a new log file, `${TMPDIR:-/tmp}/e2e-pdb-log.XXXXXX`, so concurrent runs on one host do not overwrite each other's log; set `E2E_PDB_LOG` to choose the path yourself. When it starts, it prints its PID, the log path and the stop command on one line of stderr and writes the same line as the first line of the log, for example `e2e-pdb: pid=12345 log=/tmp/e2e-pdb-log.a1B2c3 (stop with: kill 12345)`. If no argument names an existing test file or directory, or if it cannot write the log, it exits with status 2 without starting pytest. When the run ends, it prints the exit status and the log path on stderr, for example `e2e-pdb: exit=1 log=/tmp/e2e-pdb-log.a1B2c3`.

**Do not hand-roll `sleep infinity | uv run pytest …`.** It holds stdin open, but `sleep` never writes, so it never takes SIGPIPE when pytest exits and the shell waits on it forever — the command hangs after the run finishes, **including when the test passes**. A background job started that way never reports completion, and any consumer that buffers rather than streams (`tail`, a pager) discards the output when you finally kill it.

On failure pytest stays paused in pdb. Inspect the cluster with `kubectl` from a second shell. To stop the run, use `kill <pid>` with the PID that the wrapper prints when it starts. pytest leaves pdb and runs its session teardown, which deletes the vcluster (unless you passed `--e2e-keep-cluster`), and the wrapper exits with status 143 and removes its FIFO. The same command stops a run whose test is still running. If the wrapper is killed with SIGKILL instead, the process that holds the FIFO open exits within about a second, pdb reads end of input and pytest starts its teardown; the teardown itself, which deletes the vcluster, can take longer.

Do not kill pytest or `uv` directly: the run ends, but pytest skips its teardown and the vcluster keeps running, so you then have to delete it with `vcluster delete <name> --driver=docker`. Do not `pkill -f pytest`: the pattern matches every pytest on the host, and on a shared dev box or a multi-worktree checkout that kills other people's runs and leaves their vclusters running.

Use `.agents/skills/e2e-troubleshoot/SKILL.md` for the structured multi-iteration variant of this `--pdb` workflow.

`--reruns` from ``pytest-rerunfailures`` is incompatible with ``--pdb``, which is why the plugin and its auto-retry markers were removed in bce37c1. Do not reintroduce them.

The matrix-sharded CI layout (one vcluster per shard) does not change this recipe — each shard runs pytest single-threaded.

### Dual-entrypoint scope — mark `api_only` when there's no UI flow

E2E tests run twice by default: once as `[api-chromium]` (driver = SDK) and once as `[ui-chromium]` (driver = Playwright). Each variant adds ~20 minutes of CI time, so running both should be a deliberate choice tied to actually exercising the UI.

- **`@pytest.mark.api_only(reason=...)`** — the test only consumes the SDK / GraphQL / Kubernetes APIs (e.g. reading pod statuses, asserting on cluster state, seeding via the SDK with no page navigation). It would behave identically under `[ui-chromium]`, so the second variant burns CI time without adding coverage.
- **`@pytest.mark.ui_only(reason=...)`** — the inverse: assertions on UI-specific behaviour (rendering, click flows, accessibility) with no SDK equivalent.

**Heuristic:** a test is an `api_only` candidate when every action goes through `client.X.Y()`, `kubectl`, or `kr8s` and it never calls a dual-entrypoint `scenario_driver` method (`create_deployment` / `upgrade_deployment` / `create_backup` / `start_components` / etc.) — tests that *do* call those exercise both UI and API paths and MUST run under both variants. The full marker table, the dual-entrypoint method list, the `reason=` discipline, and a decorator example live in [`dev/knowledge/backend/e2e-testing.md`](dev/knowledge/backend/e2e-testing.md) (`## Markers`).

**Shard markers (matrix CI):** Every `@pytest.mark.ci` E2E test ALSO carries exactly one bare-name shard marker (`shard_general`, `shard_env`, `shard_compute`, `shard_backup`, `shard_env_backup`, `shard_infrahub`, `shard_configuration`, `shard_apply`, or `shard_task_steps`) that routes it to one of nine CI matrix shards. The authoritative list lives in `backend/tests/e2e/conftest.py` (`_VALID_SHARDS`). See [`dev/guides/e2e-parallelism.md`](dev/guides/e2e-parallelism.md) for the shard scheme and [`dev/guides/e2e-deployment-sharing.md`](dev/guides/e2e-deployment-sharing.md) for the decision tree. The conftest hook `enforce_shard_markers` fails collection if the marker is missing or duplicated.

### UI-variant troubleshooting — use the Playwright MCP server

When diagnosing a failure in a `[ui-chromium]` scenario, **always** drive the investigation through the Playwright MCP server (navigate, evaluate, inspect accessibility trees, run arbitrary Playwright calls interactively) rather than adding screenshot/HTML-dump instrumentation to the page object — it avoids a 3-minute pytest round-trip per iteration and keeps throwaway debug code out of the suite.

Typical loop:

1. Start a styrmin deployment the test expects: run the test with `--pdb` to pause at the exact state (through `scripts/e2e-pdb.sh` from a non-interactive shell), or run the fixtures explicitly.
2. Point the Playwright MCP server at the port-forwarded styrmin URL and reproduce the failing step by step.
3. Use MCP tools (`browser_snapshot`, `browser_evaluate`, `browser_click`, etc.) to inspect DOM, computed styles, `elementFromPoint`, console/network logs.
4. Form a hypothesis, apply the fix in source, re-run the full pytest to validate.

Only fall back to screenshot/HTML dumps inside the page object when the MCP server is genuinely unavailable.

## Coding Standards

- Python: `dev/guidelines/backend/python.md`
- Markdown: `dev/guidelines/markdown.md`
- Helm charts: `dev/guidelines/helm.md`
- Changelog entries: `dev/guidelines/changelog.md`

## Boundaries

### Always Do

- Install the pre-commit hooks once after cloning (`uv run invoke pre-commit-install`). Requires `prek` on PATH. Hooks run the project's mandatory checks locally before each commit; see `dev/guides/pre-commit-hooks.md`.
- Run formatters before committing (`uv run invoke format lint`)
- Regenerate `schema.graphql` after any GraphQL schema change (`uv run styrmin export graphql-schema schema.graphql`)
- Regenerate SDK types after any GraphQL schema or query change (`uv run invoke generate`)
- Write tests for new functionality
- **Record every user-visible change as a towncrier news fragment in `changelog/`** (`uv run towncrier create -c "..." <issue>.<type>.md`, or `+<slug>.<type>.md` with no issue). `CHANGELOG.md` is generated by the release workflow — never edit it by hand. See [`dev/guidelines/changelog.md`](dev/guidelines/changelog.md).
- Use type hints for Python (backend)
- **Ship an Alembic revision with any change to `backend/styrmin_backend/db/models.py`.** The schema is versioned with Alembic (`styrmin db migrate`); `metadata.create_all()` only builds a *fresh* database at startup and in test fixtures, so it will **not** evolve an existing one — an additive column without a revision silently breaks any database that already exists. Generate the revision in the same change: see [ADR-001](dev/adr/0001-alembic-database-migrations.md) and [`dev/guides/database-migrations.md`](dev/guides/database-migrations.md). Tests deliberately bypass migrations, so a green suite is not evidence that a revision is unnecessary.
- **For every new feature, ship an E2E test covering the user-visible flow and run it to a pass before declaring the work done.** This applies equally to speckit workflows (``/speckit.implement``, ``/speckit.tasks``, etc.) — the tasks list MUST include E2E coverage and the agent MUST execute it, not defer it. See Constitution §V.
- **Reuse before you boot: prefer extending an existing E2E over adding a new heavy test node.** When the new coverage is a read-only assertion on a stack an existing test already deploys, add it to that test (or a sibling sharing its session fixture) rather than creating a new node — Constitution §V explicitly allows "an existing one extended". Before depending on a session-scoped heavy fixture, confirm it has an active (non-`skip`ped) consumer: a fixture whose only consumers are skipped is never booted, so a new test becomes its sole consumer and silently pays the full boot cost. See [`dev/guides/e2e-deployment-sharing.md`](dev/guides/e2e-deployment-sharing.md) ("Reuse before you boot").
- **For every GraphQL schema change (new/modified field, argument, input type, or mutation under `backend/styrmin_backend/api/schema/`), ship a propagation test.** See [`dev/guides/graphql-propagation-tests.md`](dev/guides/graphql-propagation-tests.md) for the full recipe; see Constitution §V for the rule.
- **Keep the documentation accurate in the same change.** Any update that touches user-visible behaviour (CLI/SDK/GraphQL surface, driver format, install or quickstart steps, architecture facts described in `docs/how-it-works/`, default values, screenshots) MUST update the corresponding pages under `docs/`. Architecture, operations, decisions, and vocabulary changes update [`dev/knowledge/`](dev/knowledge/), [`dev/guides/`](dev/guides/), [`dev/adr/`](dev/adr/), and [`CONTEXT.md`](CONTEXT.md) respectively. Speckit workflows MUST include documentation tasks where applicable. Constitution §VII (non-negotiable) forbids deferring docs.

### Ask First

- Database schema or migration changes
- GraphQL schema modifications
- New dependencies
- CI/CD workflow changes
- Authentication/authorization changes
- **Skipping E2E coverage for a bug fix, refactor, or small change.** If you believe the existing E2E suite already exercises the affected path (or the change is genuinely too narrow to warrant a new scenario), state which tests cover it and request confirmation before omitting new coverage — don't unilaterally decide the work is "too small".
- **Skipping a GraphQL propagation unit test for a schema change.** If you believe an existing propagation test already covers the new/modified field, name the test and request confirmation; don't decide unilaterally.
- **Shipping a change without the matching documentation update.** If you believe an existing page in `docs/`, `dev/knowledge/`, `dev/guides/`, or `CONTEXT.md` already covers the new state, name the page and request confirmation (Constitution §VII).

### Never Do

- Commit secrets, API keys, or credentials
- Edit generated files manually, including `CHANGELOG.md` (towncrier owns it)
- Skip linting in CI
- Force push to `stable` or `develop`
- **Configure resource limits in the Styrmin Helm charts.** `helm/styrmin/` and `helm/agent/` ship `resources.requests` only — never `resources.limits`, in default values, templates, or any committed values overlay (demo, E2E fixtures, CI). CPU limits throttle bursty workloads and memory limits turn a transient spike into an OOM kill, which is how a worker pod dies mid-flow and orphans a flow run (#312). Operators may set limits in their own values files; we do not ship them. Enforced by `backend/tests/unit/test_helm_resource_limits.py`; rationale in [`dev/guidelines/helm.md`](dev/guidelines/helm.md).

### Bypassing the pre-commit hooks

Use `git commit --no-verify` only for genuine emergencies — e.g., a hook that needs network when the network is down, or a hotfix to `develop`/`stable` from automation that has already run the equivalent checks. Routine "skip lint" commits are not appropriate, and CI's `Pre-Commit Hooks` job runs the same checks regardless, so bypassing locally only delays the failure. See `dev/guides/pre-commit-hooks.md` for the full bypass policy.

## Navigation

| Question | Location |
|----------|----------|
| What do we call this concept? | [`CONTEXT.md`](CONTEXT.md) |
| How does the system work? | `dev/knowledge/` |
| How do I do X? | `dev/guides/` |
| How do I manage users, groups, and roles? | `dev/guides/users-and-groups.md` |
| How do I authenticate the CLI? | `cli/README.md#authentication` |
| Why was this decided? | `dev/adr/` |
| What are we building? | `specs/` |
| How should I write code? | `dev/guidelines/` |
| How do I record a change in the changelog? | [`dev/guidelines/changelog.md`](dev/guidelines/changelog.md) |
| What agent workflows are available? | `.agents/skills/` and `.agents/commands/` |

## Component Maps

- Backend: `backend/AGENTS.md`
- Frontend: `frontend/AGENTS.md`
- Python SDK: `python_sdk/AGENTS.md`
- Drivers: `driver/DRIVERS.md`

<!-- SPECKIT START -->
<!-- SPECKIT END -->

## Active Technologies

- TypeScript (Docusaurus config), Markdown/MDX (content), Node.js 22+ + Docusaurus v3, `@easyops-ci/docusaurus-search-local`, pnpm (003-docs-site)
- N/A (static site, no database) (003-docs-site)
- TypeScript 5.9.3, Node 22 + React 19.2.4, `@tanstack/react-form` (new), `@tanstack/zod-form-adapter` (new), Zod 4.3.6, Radix UI, `@tanstack/react-query` v5 (001-tanstack-form-migration)
- Python 3.14+ + Pydantic v2, PyYAML, Jinja2, Prefect (001-consolidate-driver-format)
- Filesystem and Git (driver sources) — no database changes (001-consolidate-driver-format)
- TypeScript 5.9.3, Node 22 + React 19.2.4, TanStack Router 1.168.x (already installed), TanStack Query v5 (new), `@graphql-codegen/typescript-react-query` (new) (001-tanstack-query-migration)
- N/A (frontend-only, data via GraphQL API at `/graphql`) (001-tanstack-query-migration)
- Python 3.14+ + Pydantic v2, ariadne-codegen (build-time), httpx (Transport) (003-sdk-typed-bindings)
- Python 3.14+ + Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Jinja2 (001-cluster-env-capabilities)
- PostgreSQL via SQLModel — new JSON columns on Cluster and Environment tables (001-cluster-env-capabilities)
- TypeScript 5.9.3, React 19.2.4, Node 22 + `@tanstack/react-router` (new), urql 5.0.1, Radix UI, React Hook Form 7, Zod 4 (001-tanstack-router-migration)
- N/A (frontend-only change) (001-tanstack-router-migration)
- Python 3.14+ (backend, SDK, CLI) + Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Cyclopts (CLI), httpx (SDK transport) (001-graphql-name-lookup)
- PostgreSQL via SQLModel/SQLAlchemy (async). Schema changes ship as Alembic revisions per ADR-001; `metadata.create_all()` covers only fresh-database startup and test fixtures. (001-graphql-name-lookup)
- Python 3.14+ (backend), TypeScript 5.9.3 (frontend) + Strawberry GraphQL, SQLModel, Pydantic (backend); React 19, urql, React Hook Form, Zod, Radix UI (frontend) (002-single-cluster-limit)
- PostgreSQL via SQLModel/SQLAlchemy (async) — no schema/migration changes (002-single-cluster-limit)
- Python 3.14+, Strawberry GraphQL, SQLModel, SQLAlchemy (async), Pydantic, Pydantic-settings >=2.12.0 (001-graphql-nested-resolvers, 001-migrate-cli-cyclopts)
- Cyclopts >=3.0.0, Rich >=13.0.0, styrmin-sdk (local) (001-migrate-cli-cyclopts)
- PostgreSQL via SQLModel/SQLAlchemy (no schema changes — relationships already exist) (001-graphql-nested-resolvers)
- Python 3.14+ + Strawberry (GraphQL), Pydantic, SQLModel, Jinja2 (001-service-fqdn-context)
- PostgreSQL via SQLModel — no schema changes required (FQDNs are computed, not stored) (001-service-fqdn-context)
- TypeScript 5.9.3, React 19.2.4, Node 22 + Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI, React Router 7, React Hook Form 7 (058-frontend-testing)

## Recent Changes

- 058-frontend-testing: Added TypeScript 5.9.3, React 19.2.4, Node 22 + Vite 8.0.1, urql 5.0.1 (GraphQL), Radix UI, React Router 7, React Hook Form 7
