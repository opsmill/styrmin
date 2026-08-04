# E2E Testing

## Overview

End-to-end tests validate the complete deployment pipeline: from an API call (or a UI flow) that requests a deployment, through the orchestration engine, all the way to a running application on Kubernetes with reachable HTTP endpoints. The tests run against a real (local) Kubernetes cluster with all Styrmin components deployed via Helm.

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         vCluster (Docker driver)                     │
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐ │
│  │ Chart Server │   │  Git Server  │   │    Styrmin (Helm)        │ │
│  │  (HTTP)      │   │ (git-daemon) │   │  ┌────────┐ ┌────────┐  │ │
│  │  :8080       │   │  :9418       │   │  │ Server │ │ Agent  │  │ │
│  └──────┬───────┘   └──────┬───────┘   │  └───┬────┘ └───┬────┘  │ │
│         │                  │           │      │          │        │ │
│         │    Helm chart    │  Driver   │      │  Prefect │FluxCD  │ │
│         │    repository    │  source   │      │          │        │ │
│         │                  │           │  ┌───▼────┐ ┌───▼──────┐ │ │
│         └──────────────────┘           │  │Prefect │ │  Helm    │ │ │
│                                        │  │Server  │ │Controller│ │ │
│                                        │  └────────┘ └──────────┘ │ │
│                                        └──────────────────────────┘ │
│                                                                      │
│  ┌────────────────────────────────────────┐                         │
│  │  Deployed Application                  │                         │
│  │  namespace: styrmin-{deployment_id}    │                         │
│  └────────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │ port-forward (kr8s)                      │ port-forward / Playwright
         │                                          │
┌────────┴──────────────────────────────────────────┴─────────────────┐
│                         Test Runner (pytest)                         │
│                                                                      │
│  ScenarioDriver (api or ui mode):                                    │
│   - api: drives the SDK (StyrminClient)                              │
│   - ui:  drives the frontend via Playwright                          │
└──────────────────────────────────────────────────────────────────────┘
```

Tests live under `backend/tests/e2e/` and are marked with the markers below.

## Markers

Defined in the root `pyproject.toml` under `[tool.pytest.ini_options]`:

| Marker | Meaning |
|--------|---------|
| `e2e` | End-to-end tests requiring a vCluster and external dependencies |
| `ci` | E2E tests included in the CI pipeline |
| `api_only(reason)` | Scenario runs only through the API entrypoint; the `[ui]` variant is skipped with the given reason |
| `ui_only(reason)` | Scenario runs only through the UI entrypoint; the `[api]` variant is skipped with the given reason |

The dual-entrypoint design is the reason every E2E scenario runs **twice by default** in CI — once as `[api-chromium]` (driver = SDK) and once as `[ui-chromium]` (driver = Playwright). Use `api_only` / `ui_only` to opt out of one variant when the same code path would be exercised redundantly. See `backend/tests/AGENTS.md` for the full rationale.

<!-- Extracted from specs/011-env-config-input-hardening on 2026-05-10 -->

#### `api_only` audit discipline

A test that calls **any** dual-entrypoint method on `scenario_driver`
(`create_deployment` / `update_deployment` / `update_environment_via_form` /
`set_environment_backup_ttl` / `upgrade_deployment` / `create_backup` /
`start_components` / `stop_components` / `run_job` / `delete_*`) MUST run
under both variants — these methods
exercise both the UI form and the API code path, and the parametrisation
**is** the parity check. Marking such a test `api_only` short-circuits half
the coverage and was the source of the marker drift cleaned up in spec 011.

`api_only` is reserved for tests that genuinely have no UI surface — pure
GraphQL reads (e.g. `client.X.Y()` SDK calls), `kubectl`/`kr8s`
introspection, or assertions on backend-only state. Each retained marker
carries an inline `reason=` explaining why the UI variant would add no
coverage.

When adding a new dual-entrypoint method, add it to **both** drivers
(`api_driver.py` and `ui_driver.py`) with the same signature — that's the
shape of the protocol and the lever the parametrisation uses. Adding the
method to only `ui_driver.py` (or wrapping the test in `api_only` because
the API side is missing) re-introduces the same drift class.

#### Peer-deployment service-name overrides

The platform enforces **service-name uniqueness within an environment**.
A driver that declares `services: [{ name: "simple-app", … }]` registers
one `DeployedService` per deployment with that resolved name. A second
deployment using the same driver in the same environment errors with
`ServiceNameConflictError: Service name 'simple-app' already exists in
environment` at fixture-setup time, before the test body even runs.

When a fixture creates **multiple deployments using the same driver in a
shared environment** (the scenario behind `test_pod_scheduling`,
`test_deployment_env_vars`, `test_environment_update`), every peer past
the first MUST pass `service_name_overrides` to rename its services:

```python
deployment = await driver.create_deployment(
    driver="simple-app",
    version="0.1.0",
    environment_id=shared_env["environment_id"],
    name="env-update-b",
    service_name_overrides=[
        {"driverServiceName": "simple-app", "overrideName": "simple-app-b"},
    ],
)
```

The conftest's session-scoped `scenario_environment` docstring documents
the same rule for tests that share the session-wide env (e.g.
`test_service_discovery`, `test_upgrade_simple_app`,
`test_backup_and_restore_lifecycle`). The same applies for
**module-scoped** envs created inside individual test files.

A first deployment never needs the override — only peers do.

`pytest-rerunfailures` is intentionally not in the dependency set — it is incompatible with `--pdb` (the project's standard E2E debugging workflow); see `dev/CLAUDE.md` (Debugging E2E Tests).

## Test Environment

### vCluster (not Kind)

E2E tests use [vCluster](https://www.vcluster.com/) with the Docker driver to create a disposable virtual Kubernetes cluster per session. The session fixture creates and tears down the cluster:

```python
# backend/tests/conftest.py
@pytest.fixture(scope="session")
async def vcluster(request, tmp_path_factory):
    cluster_name = f"pytest-{uuid.uuid4()}"
    kubeconfig_path = str(tmp_path_factory.mktemp("vcluster") / "kubeconfig")
    # vcluster create <name> --driver=docker
    # vcluster connect <name> --print --driver=docker  -> kubeconfig
    ...
    yield {"api": api, "cluster_name": cluster_name, "kubeconfig_path": kubeconfig_path}
    # finalizer: vcluster delete <name> --driver=docker
```

`VCLUSTER_DIR` may be set to point at a vCluster config directory; the fixture passes it via `--config` to both `create`, `connect`, and `delete`.

The cluster is created with a unique name (`pytest-{uuid}`) and a temporary kubeconfig in `tmp_path_factory`. A finalizer deletes it after the session, regardless of test outcome (and may be skipped by passing `--keep-vcluster` for post-mortem debugging).

### Fixture scopes

Most cluster, image, and platform fixtures are session-scoped so the expensive setup happens only once. The notable exceptions:

- `_dump_k8s_logs_on_failure` is **function-scoped** and `autouse` — it dumps pod logs after every failing test (see Debugging below).
- `scenario_driver` is **function-scoped** so each test gets a fresh driver. It inherits its mode (`api` vs `ui`) from the session-scoped `driver_mode` fixture.

### Where the wall-clock actually goes

Shared fixture bootstrap is **not** the bottleneck. Measured on the
`general` / `api` shard (32 CPU host, warm Docker cache), the whole
session-scoped setup — vcluster, `docker compose build`, the Helm
install, chart/git servers, CSI driver, cluster/env/BSL/driver — costs
**~76s**, about 4% of the run. Everything else is the per-test
deployment lifecycle.

The dominant cost is the **operator reconcile tick**. The kopf timer in
`operator/handlers/styrmin_deployment.py` is the only path that advances
a deployment past `phase: CreatingHelmRelease`: phase 3
(Services → Ready → `displayState: Running`) and the terminal
`phase: Deleted` both happen on a tick. HelmRelease status changes are
never watched — only `on.create` / `on.delete` handlers exist. At the
60s production default (with `initial_delay` equal to it), every create,
upgrade and delete slept ~60s *after* Kubernetes had finished:

```
10:23:45  Phase 1 complete, HelmRelease created
10:23:57  InstallSucceeded          <- app is up, 12s in
10:24:45  reached Ready state       <- +48s of pure tick latency
```

`backend/tests/e2e/fixtures/styrmin-values.yaml` therefore pins
`STYRMIN_OPERATOR_RECONCILE_INTERVAL: "5"` through the agent subchart's
`agent.extraEnv`. That one value took the shard from **1940s to 924s
(−52%)** with identical pass/skip counts. If a shard suddenly doubles in
duration, check this value reached the agent pod before looking anywhere
else.

**Two plausible fixture optimisations that do *not* pay** — both were
measured and rejected, so don't re-derive them:

1. *"Share one environment across the `apply` scenarios instead of a
   fresh one per test, to avoid N dedicated-ingress boots."*
   `_ensure_ingress_controller` (`services/deployment.py`) dispatches the
   internal Traefik deployment and returns immediately — it never blocks
   on it, so the ingress install overlaps the application install and
   costs ~0 wall clock. Proof: `deployed_simple_app` (env already has
   Traefik) takes **40.4s**; `typed_input_deployment` (brand-new env, so
   it also boots Traefik) takes **40.5s**. Worse, sharing the env would
   force each test to delete its deployment and wait for the tombstone
   before the next could claim the `simple-app` service name — namespace
   finalisers make that far more expensive than the boot it saves.
2. *"Point `typed_input_environment` at the session `scenario_environment_id`."*
   Same reasoning — the environment itself is cheap; only deployments
   cost time.

What *is* still expensive is irreducible: each deploy is ~40s and each
full delete-to-tombstone is ~25-60s (namespace finalisers), so the way
to speed a shard up further is to **reduce the number of
deploy/upgrade/delete cycles**, not to reshuffle environment fixtures.
That is what the read-only tier in
[`e2e-deployment-sharing.md`](../../guides/e2e-deployment-sharing.md)
is for.

## Dual-entrypoint architecture

Every E2E scenario can be driven through either the SDK or the UI without changing the test code. The driver protocol lives in `tests/e2e/drivers/protocol.py`:

```python
class ScenarioDriver(Protocol):
    async def create_deployment(...) -> Deployment: ...
    async def upgrade_deployment(...) -> ...: ...
    async def create_backup(...) -> ...: ...
    async def start_components(...) -> ...: ...
    # ... etc
```

Two implementations:

| Driver | Module | What it drives |
|--------|--------|----------------|
| `ApiScenarioDriver` | `tests/e2e/drivers/api_driver.py` | The Python SDK (`StyrminClient`) |
| `UiScenarioDriver` | `tests/e2e/drivers/ui_driver.py` | The frontend via Playwright (`Page` + page objects under `tests/e2e/pages/`) |

The session-scoped `driver_mode` fixture is parametrised with `["api", "ui"]`, which is what produces the `[api-chromium]` and `[ui-chromium]` test variants. `session_scenario_driver` constructs the matching driver and wires the SDK client / Playwright page through. Tests consume the function-scoped `scenario_driver` fixture and call `await scenario_driver.create_deployment(...)` without caring about which entrypoint is in use.

### Ref type surface

ScenarioDriver methods return **driver-neutral ref dataclasses**, not SDK models or Playwright Locators. The refs live in `tests/e2e/drivers/refs.py` and intentionally expose a minimal surface — anything beyond what's listed below has to be looked up via the SDK directly (`client.deployments.get(id).name`, etc.). When a test relies on a field that isn't on the ref, it'll fail with a confusing AttributeError; this list is the contract.

| Ref | Fields | Notes |
|---|---|---|
| `ClusterRef` | `id`, `name` | |
| `EnvironmentRef` | `id`, `name`, `cluster_id` | |
| `BSLRef` | `id`, `name` | Backup storage location. |
| `DriverVersionRef` | `id`, `application_driver_id`, `version` | |
| `DeploymentRef` | `id`, `status`, `application_version`, `instance_id` | **No `name`.** Look up via `client.deployments.get(id).name` if you need it. |
| `BackupRef` | `id`, `name`, `status` | |
| `RestoreRef` | `id`, `status` | |
| `TimelineEntry` | `task_id`, `task_type`, `task_status`, `application_version`, `created_on` | Returned from `get_deployment_timeline`. |

Refer to `tests/e2e/drivers/refs.py` for the canonical definitions; treat that file (not this table) as the source of truth.

## Supporting Services

Two lightweight services are deployed inside the vCluster to simulate the external infrastructure that Styrmin depends on in production.

### Chart Server

A minimal HTTP server that hosts a packaged Helm chart repository.

| Aspect | Detail |
|--------|--------|
| **Purpose** | Serve the simple-app Helm chart so FluxCD can fetch it |
| **Image** | Built at test time from `tests/e2e/fixtures/chart-server/Dockerfile` |
| **How it works** | Alpine image with Helm CLI packages the chart, then serves the directory with `python3 -m http.server` |
| **Cluster address** | `http://chart-server.default.svc.cluster.local:8080` |

The Dockerfile copies the simple-app Helm chart from `driver/examples/simple-app/src/helm/`, runs `helm package --dependency-update`, and generates an `index.yaml` so FluxCD treats it as a standard Helm repository.

### Git Server

A bare git daemon that hosts the application driver source code.

| Aspect | Detail |
|--------|--------|
| **Purpose** | Serve the driver spec so Styrmin can load a driver version |
| **Image** | Built from `tests/e2e/fixtures/git-server/Dockerfile` |
| **How it works** | Alpine with `git-daemon`, initializes a bare repo at `/git/simple-app.git` |
| **Cluster address** | `git://git-server.default.svc.cluster.local/simple-app.git` |

At setup time, the fixture:

1. Copies the driver source from `driver/examples/simple-app/` to a temp directory
2. Patches `driver.styrmin.yml` to point the Helm chart location at the chart server's cluster-internal URL
3. Initializes a git repository using [dulwich](https://www.dulwich.io/) (pure Python git)
4. Port-forwards the git-daemon service and pushes the repo

## Styrmin Deployment

Styrmin itself is deployed into the vCluster via its Helm chart, following the same path a real deployment would take.

The styrmin Docker image is built via `docker compose build` in the test setup, and the chart is installed with values loaded from `tests/e2e/fixtures/styrmin-values.yaml`:

```bash
helm upgrade --install styrmin \
  --dependency-update --create-namespace -n styrmin \
  helm/styrmin/ \
  -f tests/e2e/fixtures/styrmin-values.yaml \
  --wait --timeout 5m
```

After installation, the fixture port-forwards the `styrmin-server` service and waits for its `/health` endpoint to return 200.

## Test Data Setup

The session-scoped `styrmin_resources` fixture uses `session_scenario_driver` to register the cluster, environment, and driver through whichever entrypoint the run is using (SDK or UI):

```text
ScenarioDriver
  ├── create_cluster (config={...})
  │     fqdn_suffix, ingress_class, runtime_class, storage_class
  │
  ├── create_environment (cluster_id=...)
  │     ip_whitelist
  │
  └── load_driver_version (git_url, "master")
        Fetches driver spec from git server
```

This mirrors what a user would do through the API or the UI: register a cluster, create an environment, register a driver, and load a version from a git repository.

## Test Flow

A typical scenario (`test_deploy_app.py`) exercises the complete deployment lifecycle:

```text
1. Deploy          await scenario_driver.create_deployment(
                      app="simple-app", version="0.1.0", environment_id=...)
                   └─ Returns when the deployment is "running"

2. Discover        kr8s list services in namespace styrmin-{deployment_id}
                   └─ Find the service matching "simple-app"

3. Port-forward    service.portforward(remote_port=8000)
                   └─ Opens local tunnel to the deployed app

4. Verify          GET /health  → 200
                   GET /count   → 200
```

Behind the scenes, the deployment triggers Styrmin's full orchestration pipeline: Prefect writes a `StyrminDeployment` CRD, the kopf operator reconciles HelmRelease + supporting resources, and FluxCD installs the chart into running pods.

## Fixture Dependency Graph

The dependency chain determines initialization order:

```text
vcluster ──────────────────────────────────┐
  │                                        │
  ├── chart_server                         │
  │     └── git_server ────────────────┐   │
  │                                    │   │
  ├── styrmin_deployment ──────────────┤   │
  │                                    │   │
  └── _dump_k8s_logs_on_failure        │   │
       (autouse, function-scoped)      │   │
                                       │   │
                              session_scenario_driver
                                       │
                              styrmin_resources
                                       │
                              scenario_driver (function-scoped)
                                       │
                                  test_*
```

| Fixture | Scope | Depends on | What it provides |
|---------|-------|------------|------------------|
| `vcluster` | session | — | K8s API client, cluster name, kubeconfig path |
| `chart_server` | session | `vcluster` | Cluster-internal chart server URL |
| `git_server` | session | `vcluster`, `chart_server` | Cluster-internal git URL |
| `styrmin_deployment` | session | `vcluster` | Port-forwarded Styrmin server URL |
| `driver_mode` | session | — (parametrised) | "api" or "ui" |
| `session_ui_page` | session | `driver_mode`, `styrmin_deployment` | Playwright Page (in ui mode), else None |
| `session_scenario_driver` | session | `driver_mode`, `styrmin_deployment`, `session_ui_page` | `(ScenarioDriver, StyrminClient)` |
| `styrmin_resources` | session | `session_scenario_driver`, `git_server` | Cluster/environment/driver IDs |
| `scenario_driver` | function | `styrmin_resources` | Per-test ScenarioDriver |
| `_dump_k8s_logs_on_failure` | function (autouse) | `vcluster` | Auto-logging on failure |

## Debugging

### Always run with `--pdb`

The project standard is to run E2E tests with `--pdb`. See `dev/CLAUDE.md` (Debugging E2E Tests) for the full workflow, including the `sleep infinity |` trick for non-interactive shells.

### Automatic Log Dump on Failure

The autouse function-scoped `_dump_k8s_logs_on_failure` fixture hooks into pytest's test reporting. When a test fails, it automatically:

1. Lists all namespaces matching `styrmin*`
2. For each namespace, prints pod statuses (`kubectl get pods -o wide`)
3. For each pod, prints the last 200 lines of container logs

This runs via a `pytest_runtest_makereport` hook that stores the test result on the item, then the fixture checks `rep_call.failed` in its teardown.

### Manual Investigation

Since the vCluster persists for the session, you can interact with it directly if a test is paused (e.g. via `--pdb`):

```bash
export KUBECONFIG=$(ls /tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig | tail -1)
kubectl get pods -A
kubectl logs -n styrmin deploy/styrmin-server
kubectl get styrmindeployments -A
kubectl get helmreleases -A
```

### UI-variant troubleshooting

When diagnosing a `[ui-chromium]` failure, drive the investigation through the Playwright MCP server rather than adding screenshot/HTML-dump instrumentation to the page object — see `dev/CLAUDE.md` for the full loop.

## Prerequisites

| Tool | Purpose |
|------|---------|
| `docker` | Build images, run vCluster |
| `vcluster` | Create/manage vClusters |
| `kubectl` | Debug access and log dumping |
| `helm` | Deploy Styrmin into the cluster |

## Running

```bash
cd backend && uv run pytest tests/e2e -v
```

Or, for a single scenario in both variants:

```bash
cd backend && uv run pytest tests/e2e/test_deploy_app.py -v
# Produces: test_deploy_app.py::test_deploy[api-chromium]
#           test_deploy_app.py::test_deploy[ui-chromium]
```

For debugging, prefer `-v -s --pdb` (see `dev/CLAUDE.md`).

## Key Files

| File | Purpose |
|------|---------|
| [tests/conftest.py](backend/tests/conftest.py) | Root fixtures (`vcluster`, config loading, log-dump hook) |
| [tests/e2e/conftest.py](backend/tests/e2e/conftest.py) | E2E fixtures (chart server, git server, Styrmin deployment, dual-entrypoint driver wiring) |
| [tests/e2e/drivers/protocol.py](backend/tests/e2e/drivers/protocol.py) | `ScenarioDriver` Protocol |
| [tests/e2e/drivers/api_driver.py](backend/tests/e2e/drivers/api_driver.py) | `ApiScenarioDriver` (SDK driver) |
| [tests/e2e/drivers/ui_driver.py](backend/tests/e2e/drivers/ui_driver.py) | `UiScenarioDriver` (Playwright driver) |
| [tests/e2e/pages/](backend/tests/e2e/pages/) | Playwright page objects (deploy form, deployment detail, etc.) |
| [tests/e2e/fixtures/](backend/tests/e2e/fixtures/) | Chart-server, git-server, MinIO, and Helm values |
| [tests/e2e/test_deploy_app.py](backend/tests/e2e/test_deploy_app.py) | Canonical end-to-end deploy test |
| [driver/examples/simple-app/](driver/examples/simple-app/) | Test application (FastAPI + PostgreSQL + Helm chart) |
| [python_sdk/](python_sdk/) | Python SDK used by the api driver |

<!-- Extracted from specs/012-deployment-pods-tab on 2026-05-15 -->

## Testing clipboard interactions

Chromium denies clipboard reads by default. A test that asserts on clipboard contents (e.g. verifying a "Copy" button wrote the expected string) must explicitly grant the permission on the browser context before driving the button:

```python
await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
```

Then read with:

```python
text = await page.evaluate("() => navigator.clipboard.readText()")
```

Permissions are scoped to the context (not the page), so the grant survives across navigations within the same test. Page objects that depend on clipboard reads should expose a `grant_clipboard_permissions()` method and call it once at the start of the test rather than per-action — see `tests/e2e/pages/pods_tab.py` for the canonical example.

The Copy button itself does not need the grant — `writeText` is allowed by default. The grant is only required to read the clipboard back for an assertion.
