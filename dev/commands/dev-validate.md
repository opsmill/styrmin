# Dev Environment Validation

## Introduction

Autonomously spin up the full Styrmin dev environment, run tests, deploy a Semaphore application, and verify everything works end-to-end — including browser-based frontend validation. This command is idempotent: it detects what is already running and skips completed steps.

## Arguments

<arguments> #$ARGUMENTS </arguments>

**Supported arguments:**

- _(no args)_ — Full run: tests, environment setup, deploy Semaphore, verify everything including frontend
- `skip-cluster` — Skip vCluster creation (assume Kubernetes cluster already exists)
- `skip-deploy` — Skip Semaphore deployment (only verify existing environment)
- `skip-tests` — Skip unit and frontend tests
- `frontend-only` — Only run frontend browser verification (assumes environment is up with a deployment)

---

## Phase 0: Prerequisites

<thinking>
Fail fast if required tools are missing. No point starting a 5-minute setup if docker isn't installed.
</thinking>

1. **Verify working directory is the repo root.** The shell may start in a subdirectory (e.g., `frontend/`). Always assert the root first:
   ```bash
   cd "$(git rev-parse --show-toplevel)"
   test -f CLAUDE.md && test -d backend && test -d frontend
   ```
   If the assertion fails, STOP — you are not in the Styrmin repo.

2. Check that all required CLI tools are installed:
   ```bash
   command -v docker && command -v vcluster && command -v helm && command -v kubectl && command -v uv && command -v curl && command -v pnpm
   ```
3. Verify Docker daemon is running:
   ```bash
   docker info > /dev/null 2>&1
   ```
4. Verify Python virtual environment exists:
   ```bash
   test -d .venv
   ```
   If `.venv` does not exist, run:
   ```bash
   uv sync --all-groups --all-packages
   ```
5. Verify frontend dependencies are installed:
   ```bash
   test -d frontend/node_modules
   ```
   If missing, run:
   ```bash
   cd frontend && pnpm install
   ```

**If any tool is missing or Docker is not running — STOP and tell the user exactly what to install or start.**

### Invoke task runner reference

All project automation is through Invoke tasks, run via `uv run invoke <task>`. To see available tasks:
```bash
uv run invoke --list
```

Key tasks used in this command:
| Task | Purpose |
|------|---------|
| `invoke test` | Run backend pytest suite |
| `invoke dev.build` | Build Docker Compose images |
| `invoke dev.start` | Start Docker Compose services |
| `invoke dev.restart` | Stop, rebuild volumes, and restart all services. **Wipes the SQLite database** — you must re-run `invoke dev.bootstrap` after every restart. |
| `invoke dev.stop` | Stop services without touching volumes |
| `invoke dev.bootstrap` | Create `local` cluster, `local` environment, and load the infrahub driver |
| `invoke cluster.create` | Create the vCluster (Docker driver) |
| `invoke cluster.connect` | Export kubeconfig and set kubectl context |
| `invoke cluster.init` | Install CRDs via Helm |

> **Important:** `dev.restart` recreates Docker volumes, which destroys the SQLite database. Every restart cycle requires re-running `dev.bootstrap` and reloading any drivers before you can deploy again. If you only changed backend Python code, you do **not** need to restart — the FastAPI dev server auto-reloads from the mounted `backend/` volume. Only rebuild (`dev.build` + `dev.restart`) when Dockerfile, pyproject.toml, or frontend build artifacts change.

---

## Phase 1: Unit & Frontend Tests

**Skip this phase if `skip-tests` or `frontend-only` argument was provided.**

<thinking>
Run tests early. If the code is broken, there's no point spinning up infrastructure. But don't hard-fail — the live environment might still work even if some tests are flaky.
</thinking>

1. Run backend tests:
   ```bash
   uv run invoke test
   ```
   Record: total passed, total failed, total errors.

2. Run frontend tests:
   ```bash
   cd frontend && pnpm test
   ```
   Record: total passed, total failed.

3. **Report results to the user.** On failures: list which tests failed but **continue** to the next phase. Say something like: "X backend tests failed, Y frontend tests failed. Continuing with environment validation — these failures may or may not affect the live deployment."

---

## Phase 2: Environment Assessment

<thinking>
Before creating or starting anything, check what's already running. This makes the command idempotent — running it twice doesn't break anything.
</thinking>

**Skip to Phase 8 if `frontend-only` argument was provided.**

Check each component and record its state:

1. **vCluster:** Does a `styrmin` cluster already exist?
   ```bash
   vcluster list 2>/dev/null
   ```
   Look for a cluster named `styrmin` in the output. Record: `cluster_exists = true/false`.

2. **Docker Compose services:** Are they running?
   ```bash
   docker compose ps --format json 2>/dev/null
   ```
   Check if `server`, `task-manager`, `task-worker`, `agent-operator` are listed and running. Record: `services_running = true/false`.

3. **Backend health:**
   ```bash
   curl -sf http://localhost:8000/health 2>/dev/null
   ```
   Record: `backend_healthy = true/false`.

4. **Prefect health:**
   ```bash
   curl -sf http://localhost:4200/api/health 2>/dev/null
   ```
   Record: `prefect_healthy = true/false`.

Report what was found: "Cluster: running, Services: running, Backend: healthy, Prefect: healthy" (or the actual state).

---

## Phase 3: Cluster Setup

**Skip this phase if `skip-cluster` argument was provided or `cluster_exists = true`.**

<thinking>
Create the vCluster, connect to it, and install the required CRDs. If the cluster already exists, just ensure we're connected.
</thinking>

1. If `cluster_exists = false`:
   ```bash
   uv run invoke cluster.create
   ```
   Wait for it to complete. This can take 30-60 seconds.

   ```bash
   uv run invoke cluster.connect
   ```

   ```bash
   uv run invoke cluster.init
   ```

2. If `cluster_exists = true` but we need to ensure connectivity:
   ```bash
   uv run invoke cluster.connect
   ```

3. Verify the cluster is ready:
   ```bash
   kubectl get nodes
   kubectl get namespaces
   ```
   Both commands should succeed. If they fail, report the error and stop.

---

## Phase 4: Services Startup

**Skip this phase if `services_running = true` AND `backend_healthy = true` AND `prefect_healthy = true`.**

<thinking>
Build the Docker image and start services. Then poll health endpoints until they're ready. This is where most of the startup time is spent.
</thinking>

1. If services are not running at all:
   ```bash
   uv run invoke dev.build
   uv run invoke dev.start
   ```

2. **Poll health endpoints.** Check every 5 seconds for up to 120 seconds (24 attempts):

   Backend health:
   ```bash
   curl -sf http://localhost:8000/health
   ```
   Expected response: `{"status": "healthy"}`

   Prefect health:
   ```bash
   curl -sf http://localhost:4200/api/health
   ```
   Expected: HTTP 200.

   Report progress every 30 seconds: "Waiting for services... 30s/120s"

3. **If timeout is reached** without both being healthy:
   - Dump the last 100 lines of logs for each service:
     ```bash
     docker compose logs --tail=100 server
     docker compose logs --tail=100 task-manager
     docker compose logs --tail=100 task-worker
     docker compose logs --tail=100 agent-operator
     ```
   - Report the failure and **STOP** — downstream phases cannot work without healthy services.

4. **Scan container logs for errors** (informational, do not stop on errors):
   ```bash
   docker compose logs --tail=50 server 2>&1 | grep -iE "error|exception|traceback"
   docker compose logs --tail=50 task-worker 2>&1 | grep -iE "error|exception|traceback"
   docker compose logs --tail=50 agent-operator 2>&1 | grep -iE "error|exception|traceback"
   ```
   Report any errors found, with the service name and the error line. Continue regardless.

---

## Phase 5: Bootstrap

<thinking>
Check if Styrmin entities (cluster, environment, driver) already exist. If they do, skip bootstrap. If not, run it. The bootstrap task creates a "local" cluster, "local" environment, and loads the infrahub driver.
</thinking>

1. Query for existing clusters:
   ```bash
   curl -sf http://localhost:8000/graphql -H "Content-Type: application/json" -d '{"query":"{ clusters { id name } }"}'
   ```

2. Query for existing environments:
   ```bash
   curl -sf http://localhost:8000/graphql -H "Content-Type: application/json" -d '{"query":"{ environments { id name } }"}'
   ```

3. **If clusters or environments are empty** (no data returned), run bootstrap:
   ```bash
   uv run invoke dev.bootstrap
   ```
   This creates:
   - A cluster named `local`
   - An environment named `local` linked to that cluster
   - Loads the infrahub driver version from `/styrmin/drivers/infrahub`

4. **If entities already exist**, report what was found and skip. Record the environment ID from the query response — you will need it for the deployment phase.

---

## Phase 6: Deploy Semaphore

**Skip this phase if `skip-deploy` argument was provided.**

<thinking>
This is the core sanity check. Load the Semaphore example driver, deploy it, and wait for it to become healthy. Use curl with GraphQL — the same pattern as dev.bootstrap and the E2E tests.
</thinking>

### Step 6a: Load the Semaphore driver

The Semaphore driver is bundled in the Docker image at `/styrmin/drivers/semaphore` (mounted from `driver/examples/semaphore/`).

```bash
curl -sf http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation LoadLocalApplicationDriverVersion($path: String!) { loadLocalApplicationDriverVersion(path: $path) { id version } }","variables":{"path":"/styrmin/drivers/semaphore"}}'
```

Verify the response contains a valid `id` and `version`. If it fails, report the error and stop.

### Step 6b: Deploy Semaphore

The deploy mutation requires both `environmentName` and `clusterName`. Omitting `clusterName` will return: `"Either cluster_id or cluster_name is required"`.

```bash
curl -sf http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation Deploy($driver: String!, $version: String, $environmentName: String, $clusterName: String, $name: String) { deploy(driver: $driver, version: $version, environmentName: $environmentName, clusterName: $clusterName, name: $name) { id type status message deploymentId } }","variables":{"driver":"semaphore","version":"2.16.47","environmentName":"local","clusterName":"local","name":"semaphore-validate"}}'
```

Capture the `deploymentId` from the response. If the mutation returns an error (e.g., name already taken), report it. If a deployment named `semaphore-validate` already exists, that's fine — skip to polling its status.

### Step 6c: Poll deployment status

Poll every 10 seconds for up to 300 seconds (30 attempts):

```bash
curl -sf http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"query GetDeployment($deploymentId: UUID!) { deployment(deploymentId: $deploymentId) { id name status applicationVersion applicationInstance { id status } components { name enabled } } }","variables":{"deploymentId":"<DEPLOYMENT_ID>"}}'
```

Replace `<DEPLOYMENT_ID>` with the actual deployment ID captured in step 6b.

**Success condition:** `status` is `"deployed"` or `"active"`.

Report progress every 30 seconds: "Deployment status: in_progress... 60s/300s"

**If timeout is reached:**
- Report the current deployment status
- Dump diagnostic info:
  ```bash
  docker compose logs --tail=100 task-worker
  docker compose logs --tail=100 agent-operator
  ```
- List pods and events in the deployment namespace. The namespace follows the pattern `styrmin-<name>` where name is the deployment name:
  ```bash
  kubectl get pods -A | grep styrmin
  kubectl get events -A --sort-by=.lastTimestamp | grep styrmin | tail -20
  ```
- **STOP** — the deployment failed.

---

## Phase 7: Verify Kubernetes Resources

<thinking>
The deployment is reported as successful by the API. Now verify the actual Kubernetes resources are healthy — pods running, services created, HelmRelease reconciled.
</thinking>

1. **Find the deployment namespace.** Query the deployment to get the instance namespace, or look for namespaces:
   ```bash
   kubectl get namespaces | grep styrmin
   ```
   The Semaphore deployment namespace will match the pattern based on the deployment name/ID.

2. **Check pods:**
   ```bash
   kubectl get pods -n <namespace>
   ```
   All pods should be `Running` with all containers ready (e.g., `1/1`). Report any pods in `CrashLoopBackOff`, `Pending`, or `Error` state.

3. **Check services:**
   ```bash
   kubectl get svc -n <namespace>
   ```
   Should show the Semaphore service on port 3000.

4. **Check HelmRelease:**
   ```bash
   kubectl get helmrelease -n <namespace>
   ```
   Status should show `Ready`.

5. **Port-forward and health-check Semaphore:**
   ```bash
   kubectl port-forward -n <namespace> svc/styrmin-semaphore 3000:3000 &
   PF_PID=$!
   sleep 3
   curl -sf http://localhost:3000/api/ping
   PING_EXIT=$?
   kill $PF_PID 2>/dev/null
   ```
   If curl returns HTTP 200, the Semaphore application is alive and serving requests.

   **Note:** If the port-forward or health check fails, this is not necessarily a blocker — it may take time for the application to fully start. Report the result but continue.

---

## Phase 8: Frontend Browser Validation

<thinking>
Now verify that the frontend UI correctly displays the environment and deployment. Use Playwright MCP tools if available. The frontend is served by the backend at http://localhost:8000/. The index route shows the environment list, environment detail shows deployments, and deployment detail shows status and components.

Frontend routes:
- / — Environment list (shows "local" environment)
- /environments/<environmentId> — Environment detail (shows deployments)
- /environments/<environmentId>/deployments/<deploymentId> — Deployment detail
</thinking>

### Option A: Playwright MCP Available

If the Playwright MCP tools are available (check for `mcp__playwright__browser_navigate` or similar tools), use them:

1. **Navigate to the app:**
   Use the browser navigate tool to go to `http://localhost:8000/`

2. **Verify the environment list page loads:**
   - Take a screenshot
   - Look for the "local" environment in the page content
   - If the page is empty or shows an error, report it

3. **Click into the "local" environment:**
   - Find and click the "local" environment link/card
   - Wait for the environment detail page to load

4. **Verify the Semaphore deployment appears:**
   - Take a screenshot
   - Look for "semaphore-validate" in the deployment list
   - Verify the deployment status is displayed (should show "deployed" or "active")

5. **Click into the deployment detail:**
   - Find and click the "semaphore-validate" deployment
   - Wait for the deployment detail page to load

6. **Verify deployment details:**
   - Take a screenshot to show the user
   - Verify the status, application version (2.16.47), and components (server, database) are visible

7. **Close the browser** when done.

### Option B: No Playwright MCP (Fallback)

If Playwright MCP tools are NOT available:

1. Verify the frontend HTML is served:
   ```bash
   curl -sf http://localhost:8000/ | head -20
   ```
   Should return HTML containing `<div id="root">` or similar React mount point.

2. Verify the GraphQL API responds to frontend-style queries:
   ```bash
   curl -sf http://localhost:8000/graphql -H "Content-Type: application/json" -d '{"query":"{ environments { id name } }"}'
   ```

3. Report to the user:
   > Frontend HTML is being served correctly and the GraphQL API is responding. For full browser-based UI validation, install the Playwright MCP server. You can manually verify the UI at http://localhost:8000/

---

## Phase 9: Summary Report

Present the final validation report as a table:

```
| Check                  | Status    | Details                              |
|------------------------|-----------|--------------------------------------|
| Backend unit tests     | PASS/FAIL | X passed, Y failed                   |
| Frontend unit tests    | PASS/FAIL | X passed, Y failed                   |
| Docker running         | PASS/FAIL |                                      |
| vCluster ready         | PASS/FAIL |                                      |
| Backend healthy        | PASS/FAIL | /health endpoint                     |
| Prefect healthy        | PASS/FAIL | /api/health endpoint                 |
| Bootstrap complete     | PASS/FAIL | cluster/environment/driver           |
| Semaphore driver loaded| PASS/FAIL | version                              |
| Semaphore deployed     | PASS/FAIL | Status + deployment ID               |
| K8s pods healthy       | PASS/FAIL | Pod count and states                 |
| Semaphore HTTP alive   | PASS/FAIL | /api/ping via port-forward           |
| Frontend UI            | PASS/FAIL | Screenshot or HTTP check             |
| Container log errors   | WARN/PASS | Error count per service              |
```

Use PASS/FAIL/WARN/SKIP for each check. SKIP means the phase was skipped due to arguments.

If everything passed, end with:
> All validation checks passed. The Styrmin dev environment is fully operational.

If there were failures, end with a summary of what failed and suggested next steps for debugging.

---

## Error Recovery Guidelines

Throughout all phases, follow these principles:

- **Be specific in error messages.** Don't just say "deployment failed" — include the status, error message, and relevant logs.
- **Dump diagnostics before stopping.** When a phase fails and you need to stop, always collect logs, pod status, or events first.
- **Don't retry blindly.** If a command fails, check why before retrying. One retry is fine for transient network issues; repeated retries indicate a real problem.
- **Clean up background processes.** If you started a `kubectl port-forward` in the background, make sure to kill it before finishing.

## Expected Outcome

A fully validated dev environment with:
- All unit tests reported (pass or fail)
- Kubernetes cluster running
- All Docker Compose services healthy
- Semaphore application deployed and serving HTTP requests
- Frontend UI verified (with screenshots if Playwright is available)
- A clear summary report showing the status of every check
