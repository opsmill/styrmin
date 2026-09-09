---
name: e2e-troubleshoot
description: Run a specific E2E test with `--pdb`, investigate failures while pytest is paused, apply targeted fixes, and re-run up to five iterations.
argument-hint: A test identifier — file path, file::function, or a test function name
compatibility: Requires the Styrmin repo, vcluster, kubectl, uv, and the E2E pytest fixtures.
metadata:
  source: AGENTS.md E2E debugging policy
---

# E2E Test Troubleshooter

## Introduction

Run a specific E2E test with `--pdb`, and if it fails, investigate the failure while pytest is paused with the vcluster, port-forwards, SDK clients, and fixtures still alive. Apply a fix and re-run. Repeat up to 5 iterations. Always produce a summary at the end.

## Arguments

<arguments> $ARGUMENTS </arguments>

**Required:** A test identifier — file path, `file::function`, or a test function name.

Examples:

- `test_deploy_app`
- `test_ingress_controller.py::test_traefik_routes_traffic`
- `backend/tests/e2e/test_deploy_semaphore.py`

---

## State

Maintain these variables throughout:

```text
iteration = 0
max_iterations = 5
test_resolved = false
investigation_log = []   # Append to this after every iteration
```

---

## Phase 0: Resolve Test Target

1. **Verify the working directory is the repo root:**

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   test -f CLAUDE.md && test -d backend && test -d frontend
   ```

2. **Resolve the argument to a concrete pytest node ID.** The user may provide a partial name. Search for it:

   ```bash
   find backend/tests/e2e -name "*.py" -not -name "__*" | xargs grep -l "def <argument>"
   ```

   Or if the argument is already a file path, use it directly.

   The final target must be a valid pytest node ID, e.g.:

   ```text
   backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app
   ```

   If ambiguous (multiple matches), list them and ask the user which one to run.

3. **Read the test file and its fixtures** to understand what the test does. Read:

   - The test function itself.
   - The fixtures it depends on (trace through `backend/tests/e2e/conftest.py` and `backend/tests/conftest.py`).

   Build a mental model of:

   - What infrastructure the test requires (vcluster, chart-server, git-server, styrmin deployment).
   - What the test deploys (which driver, which version).
   - What the test asserts (HTTP endpoints, Kubernetes resource states, API responses).
   - What namespace the deployed application will live in (pattern: `styrmin-{deployment_id}`).

   Report this analysis to the user before proceeding.

---

## Phase 1: Run the Test

Increment `iteration` by 1.

```bash
E2E_PDB_LOG=/tmp/e2e-pdb.log scripts/e2e-pdb.sh <test_node_id> --tb=long
```

The wrapper keeps pdb's stdin from hitting EOF on failure, which would otherwise exit pytest and tear the cluster down before Phase 2 can look at it, and cleans up after itself if the run is interrupted. Do **not** substitute `sleep infinity | uv run pytest …`: `sleep` never writes, so it never takes SIGPIPE when pytest exits and the command hangs forever even on a pass. See `AGENTS.md` (Debugging E2E Tests) for the full rationale.

**Capture the full output.** Parse `/tmp/e2e-pdb.log` for:

- `PASSED` / `FAILED` / `ERROR`.
- The traceback if failed.
- The active kubeconfig path. If the test is paused in pdb, find it with:

  ```bash
  ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1
  ```

**If the test passed:** set `test_resolved = true`, go to Phase 4.

**If the test failed and pytest is paused in pdb:** keep the pytest process running, record the failure in `investigation_log`, and proceed to Phase 2 from a separate shell. Do not kill pytest until after diagnostics are collected.

---

## Phase 2: Investigate

The pytest process is still alive and paused at the failure. Use that exact live state. The goal is to understand WHY the test failed, not just WHAT failed. The traceback tells you the symptom; kubectl and logs tell you the cause.

### Step 2a: Classify the failure

Read the traceback and classify it:

| Failure Type | Symptoms | Investigation Path |
|---|---|---|
| **Fixture setup error** | Error in `conftest.py` during setup | Check if prerequisite services exist, check Docker, check vcluster connectivity |
| **Deployment timeout** | `deployment did not reach ready state` | Check Prefect flows, task-worker logs, agent-operator logs, HelmRelease status |
| **HTTP timeout** | `did not return 200 after Xs` | Check pod readiness, port-forward, container logs, service endpoints |
| **Assertion error** | `assert X == Y` | Compare expected vs actual, query the API, check the resource state |
| **Kubernetes error** | `ApiException`, `404`, `409` | Check if the resource/namespace exists, check RBAC, check CRDs |

### Step 2b: Collect diagnostics from the live cluster

Use the kubeconfig discovered in Phase 1. Set it for all kubectl commands:

```bash
export KUBECONFIG=<path_from_phase_1>
```

**Always collect these:**

1. **Namespaces:**

   ```bash
   kubectl get namespaces | grep styrmin
   ```

2. **Pods in relevant namespace(s):**

   ```bash
   kubectl get pods -n <namespace> -o wide
   ```

3. **Events (sorted by time):**

   ```bash
   kubectl get events -n <namespace> --sort-by=.lastTimestamp | tail -30
   ```

**Collect based on failure type:**

- **Deployment timeout:**

  ```bash
  kubectl get helmreleases -n <namespace> -o yaml
  kubectl logs -n styrmin deploy/styrmin-server --tail=100
  kubectl logs -n styrmin deploy/styrmin-task-worker --tail=100
  kubectl logs -n styrmin deploy/styrmin-agent-operator --tail=100
  ```

- **HTTP timeout (app not responding):**

  ```bash
  kubectl get pods -n <namespace>
  kubectl describe pod -n <namespace> <pod_name>
  kubectl logs -n <namespace> <pod_name> --all-containers --tail=100
  kubectl get svc -n <namespace>
  kubectl get endpoints -n <namespace>
  ```

- **HelmRelease stuck:**

  ```bash
  kubectl get helmreleases -A -o yaml
  kubectl get helmcharts -A
  kubectl logs -n styrmin deploy/helm-controller --tail=100
  kubectl logs -n styrmin deploy/source-controller --tail=100
  ```

### Step 2c: Analyze

Correlate the traceback with the cluster state. Identify the root cause. Record it in `investigation_log`:

```text
investigation_log.append({
    iteration: <n>,
    failure: "<one-line summary of what failed>",
    root_cause: "<what was found in the cluster/logs>",
    fix: "<what is planned to change>"
})
```

---

## Phase 3: Fix and Retry

Apply the minimal fix. Don't refactor, don't improve, don't clean up — just fix the failing test or the code it exercises. If the fix involves backend Python code, the Styrmin server inside the cluster will NOT auto-reload — a rebuild and redeploy may be needed. Try fixes that don't require that first (test code changes, timing adjustments, fixture issues).

1. **Stop the paused pytest run after diagnostics are complete.** Kill the whole pytest process group so teardown can proceed or, if necessary, force-stop the run:

   ```bash
   pkill -f "pytest .*backend/tests/e2e"
   ```

2. **Apply the fix.** Edit the relevant file(s).

3. **Run the linter:**

   ```bash
   uv run invoke format lint
   ```

   Fix any lint errors before proceeding.

4. **Ensure the test cluster is gone.** The next iteration should create a fresh one. This is mandatory — never leave a stale cluster running between iterations.

   ```bash
   vcluster delete <cluster_name> --driver=docker
   ```

   Verify it is gone:

   ```bash
   vcluster list 2>/dev/null
   ```

5. **If backend code was changed** (`backend/styrmin_backend/`), rebuild the Docker image so the next test run picks up the changes:

   ```bash
   docker compose build
   ```

6. **Check iteration count.** If `iteration >= max_iterations`: go to Phase 4.

7. **Go back to Phase 1** (run the test again).

---

## Phase 4: Final Cleanup and Summary Report

**Before writing the summary**, ensure no paused pytest process or test cluster is still running:

```bash
pkill -f "pytest .*backend/tests/e2e" 2>/dev/null || true
```

```bash
vcluster list 2>/dev/null | grep pytest
```

If any `pytest-*` cluster exists, delete it:

```bash
vcluster delete <cluster_name> --driver=docker
```

**Always produce this report, whether the test passed or not.**

### Format

```markdown
## E2E Troubleshoot Summary

**Test:** `<test_node_id>`
**Result:** FIXED after N iterations / NOT FIXED after 5 iterations
**Branch:** `<current git branch>`

### Investigation Log

#### Iteration 1
- **Failure:** <what failed>
- **Root cause:** <what was found>
- **Fix applied:** <what was changed and why>
- **Files modified:** <list of files>

#### Iteration 2
...

### Cluster Diagnostics Collected
- <List key findings from kubectl: pod states, events, log excerpts>
- <Include anything that would help a human continue debugging>

### Files Changed
| File | Change |
|------|--------|
| `path/to/file.py` | Description of change |

### Current State
- Cluster: deleted (must always be cleaned up)
- Uncommitted changes: <yes/no — run `git diff --stat`>

### Recommendations
<If NOT FIXED: what to investigate next, what hypotheses remain untested>
<If FIXED: any follow-up items, related tests to run, potential regressions>
```

---

## Important Guidelines

- **Do not skip the investigation.** Don't guess at fixes without looking at the cluster state. Pytest is paused at the failure so the exact failing state is available — use it.
- **One fix per iteration.** Don't stack multiple speculative fixes. Apply one targeted change and re-run.
- **Record everything.** The summary is the most valuable output of this skill. A human or future agent should be able to read it and understand exactly what happened.
- **Don't fight the test framework.** If the test expects a specific behavior and the code doesn't provide it, fix the code. If the test has a wrong assertion, fix the test. But be sure which one is wrong before changing either.
- **Always clean up the run.** Kill paused pytest after investigation, delete any leftover test cluster before retrying, and clean up after the final iteration regardless of outcome. There must never be a test cluster left running when the skill finishes.
