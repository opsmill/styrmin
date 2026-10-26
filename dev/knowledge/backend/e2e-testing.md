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
| `changes_cluster_config` | The test changes the session cluster's config, which redeploys every deployment of the cluster; the E2E conftest runs these tests first in the session |

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

The hook `run_cluster_config_changes_first` in `backend/tests/e2e/conftest.py`, called from
`pytest_collection_modifyitems`, moves the `changes_cluster_config` tests to the front of the
session and keeps the order within each group. They then run before other tests create shared
deployments. Each such test restores the original config and calls `wait_for_cluster_settled`
(`backend/tests/e2e/helpers/ingress.py`), which waits until no deployment of the cluster, internal
ones included, is pending or deploying. The shard rules for these tests are in
[`e2e-parallelism.md`](../../guides/e2e-parallelism.md#tests-that-change-the-cluster-config).

The E2E vCluster runs no shared ingress controller: no Traefik or NGINX runs besides the dedicated
ingress controllers. `test_cluster_update.py` therefore checks that an application uses the
shared ingress class through the Ingress resource's `spec.ingressClassName`, not over HTTP.

<!-- Extracted from specs/024-ingress-class-post-render on 2026-10-16 -->

The E2E fixture drivers `late-container` and `failing-actions`
(`backend/tests/e2e/fixtures/drivers/`) keep `className: "{{ instance.config.ingress_class }}"`
in their `values.j2.yml` on purpose, although the example drivers dropped that line
([ADR-071](../../adr/0071-ingress-class-set-by-post-render.md)). The session cluster has a
dedicated ingress controller, so the CI tests that deploy these drivers render a template that
still sets the class, which Styrmin must then remove after the chart renders.
`test_apply_sets_env_vars_with_the_version_that_adds_their_container` (`test_deployments_apply.py`)
checks that every Ingress that `late-container` deploys has no `spec.ingressClassName` and has the
annotation `kubernetes.io/ingress.class: traefik`, so it fails when Flux does not apply the removal
patch. Do not remove the class line from these fixtures. The integration fixture
`backend/tests/integration/fixtures/legacy_drivers/simple-app/values.j2.yml` also keeps the line,
for another reason: it is a byte-identical copy of the template from before
[#457](https://github.com/opsmill/styrmin/issues/457), and its README forbids edits.
`test_cluster_update_redeploys_and_moves_dedicated_ingress` and
`test_traffic_routes_through_dedicated_ingress` deploy the `simple-app` example driver, which no
longer sets the class.

The dual-entrypoint design is the reason every E2E scenario runs **twice by default** in CI — once as `[api-chromium]` (driver = SDK) and once as `[ui-chromium]` (driver = Playwright). Use `api_only` / `ui_only` to opt out of one variant when the same code path would be exercised redundantly. See `backend/tests/AGENTS.md` for the full rationale.

<!-- Extracted from specs/011-env-config-input-hardening on 2026-05-10 -->

#### `api_only` audit discipline

A test that calls **any** dual-entrypoint method on `scenario_driver`
(`create_deployment` / `update_deployment` / `update_environment_via_form` /
`set_environment_backup_ttl` / `set_component_env_vars` / `set_component_image` /
`set_component_container_override` / `set_component_replicas` /
`upgrade_deployment` / `pinned_image_components` / `create_backup` /
`list_backups` / `start_components` / `stop_components` / `run_job` /
`create_environment_backup` / `get_environment_backup` / `wait_for_environment_backup` /
`restore_environment_backup` / `wait_for_environment_restore` / `clone_environment` /
`get_environment_clone` / `wait_for_environment_clone` / `delete_*`) MUST run
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

<!-- Extracted from specs/001-env-backup-restore and specs/010-environment-clone on 2026-10-13 -->

The environment backup methods drive the environment detail page's Backups
tab, and the clone methods its Clones tab. Both groups are scoped by an
environment: `create_environment_backup` and `clone_environment` take the
environment id and the UI driver keeps it for the read methods that follow,
which raise `ScenarioActionError` when the driver has no environment yet. The
API driver ignores it, so scenarios need no `driver_mode` branch.

`backend/tests/unit/test_e2e_driver_conformance.py` checks that
`ApiScenarioDriver` and `UiScenarioDriver` implement every method of
`ScenarioDriver`, and that no implementation is a `raise NotImplementedError`
stub. It lives under `tests/unit/`, not `tests/e2e/`, because it needs no
cluster:

- Every test under `tests/e2e/` boots a vCluster, because the autouse fixture
  `_dump_k8s_logs_on_failure` depends on the session-scoped `vcluster` fixture.
- The unit job runs `pytest tests --ignore=tests/e2e` (`tasks/__init__.py`),
  and the CI E2E jobs select tests with `-m "ci and shard_<name>"`. While the
  test lived under `tests/e2e/drivers/` without those markers, no CI job ran it.

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

FluxCD rolls a failed Helm upgrade back at its HelmRelease timeout, and the
rollback removes the failing pods; `test_task_steps.py` asserts that the
failed HelmRelease step lists those pods' reasons, which holds only while the
readiness timeout stays below FluxCD's. For the missing image the reason is
`ImagePullBackOff` or `ErrImagePull`: the kubelet reports `ErrImagePull` for
about 12 s after each pull attempt, and at 210 s the timeout can land in that
window. The E2E values lower both, keeping that order:
`STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT` is 210 s (270 s in production) and
`STYRMIN_OPERATOR_HELM_RELEASE_TIMEOUT` is 240 s (300 s). Every E2E rollout
must be ready within those, or FluxCD rolls it back; the slowest, Infrahub's,
reached `running` in 95 s locally. 150 s / 180 s were measured to pass locally
but were rejected as too close for CI, where the Infrahub cell's duration
varies by up to 1.8×.

The next cost is **Prefect scheduling latency**. The agent runs its own
Prefect `ProcessWorker` (`entrypoint/combined.py`), which polls its work
pool every `PREFECT_WORKER_QUERY_SECONDS` — Prefect's default is 10s —
and a simple-app create chains three agent flow runs (main flow,
pre-hook, post-hook). Each one started ~9s late on average. The same
values file therefore also sets `PREFECT_WORKER_QUERY_SECONDS: "1"` in
`agent.extraEnv`, and `run_deployment_or_fail`
(`agent/tasks/utils.py`) polls sub-flows every 1s instead of Prefect's
5s default. Together they took `general` / `api` from **969s to 727s
(−25%)** and `configuration` / `ui` from **648s to 543s (−16%)**. The
~4s left per flow run is Prefect process start-up, not polling.

Rolling updates that re-render the simple-app **PostgreSQL** pod
(scheduling, env-var and toleration edits) used to stall for exactly
31s: SIGTERM is a Postgres "smart" shutdown, which waits for the app's
open connections (simple-app never closes its pool) until the default
30s grace period kills the pod. The simple-app driver
(`driver/examples/simple-app/values.j2.yml`) now runs
`pg_ctl stop -m fast --no-wait` in a `preStop` hook, which disconnects
clients and checkpoints, so each restart is a clean ~1-2s shutdown.
`--no-wait` matters: Postgres is PID 1, so a waiting `pg_ctl` is killed
with the container and the hook would fail. The grace period (10s) is
only a backstop. With the polling fixes, `configuration` / `ui`
runs in **489s (−25% from 648s)** and `general` / `api` in **711s
(−27% from 969s)**.

The `configuration` shard used to create each module's deployment
serially through the UI deploy form, then wait on the detail page's 10s
refetch. `configuration/conftest.py` now creates all selected modules'
deployments concurrently through the SDK, with any baseline config
seeded at create time instead of by a follow-up update. That took the
shard from **489s to 217s**: the seven deployments cost one deploy of
wall-clock between them.

`general` / `api` was then dominated by the manifest-apply tests: six
`api_only` tests, each deploying fresh simple-apps, were 343s of its 922s
in CI. They now run as their own `apply` shard, where the create / update
/ no-op scenarios are folded into one lifecycle test, leaving four tests
in the shard. The
delete-then-redeploy regression and the service-rename test also reuse
deployments their siblings already pay for. Locally, `general` / `api`
went from **711s to 344s**, and the new `apply` / `api` cell runs in
**296s**.

`general` then grew again with `test_task_steps.py`, whose HelmRelease
failure scenario waits out timeouts rather than doing work, so it took
~460s on every host (CI 1233s for `general` / `api`, 472s of it in that one
test). Measured locally, it spent 55s waiting for the deployment to recover
from the prerequisites scenario (the operator's hardcoded 30 s retry delay),
287s until the step failed (the 270 s readiness timeout), 24s until FluxCD's
rollback (its 5-minute timeout) and a fixed 90s checking that the failure
stays. The module now runs as its own `task_steps` shard, the operator's
retry delay and both timeouts are settings that the E2E values lower
(`STYRMIN_OPERATOR_RETRY_DELAY` 5 s, readiness 210 s, HelmRelease 240 s),
and the check ends 15 s after the operator answers FluxCD's rolled-back
`Ready=True` with `Ready=False RolledBack` (about 16 s after the rollback).
Since the upgrade to helm-controller v1.7.1, FluxCD tries the upgrade again
after the rollback instead, and the check ends when it sees FluxCD start the
next attempt (11 to 15 s after the rollback in local runs, 90 s at most).
Measured locally (four cells at a time), `general` / `api` went from
**1175s to 520s** and `general` / `ui` from **863s to 391s**; the HelmRelease
scenario takes 312s instead of 463s, and the new `task_steps` cells take
**523s** (`api`) and **436s** (`ui`). `backup` / `api` (617s) is now the
slowest cell.

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

What *is* still expensive is irreducible: each deploy is ~30s and each
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
| `BackupRef` | `id`, `name`, `status`, `steps`, `application_version` | `application_version` is set by `list_backups` only: the application version of the instance the backup was taken of. <!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 --> |
| `RestoreRef` | `id`, `status` | |
| `TimelineEntry` | `task_id`, `task_type`, `task_status`, `application_version`, `created_on` | Returned from `get_deployment_timeline`. |

Refer to `tests/e2e/drivers/refs.py` for the canonical definitions; treat that file (not this table) as the source of truth.

## Supporting Services

Three lightweight services are deployed inside the vCluster to simulate the external infrastructure that Styrmin depends on in production.

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
| **How it works** | Alpine with `git-daemon`; the image creates one bare repository per driver (`RUN git init --bare /git/<driver>.git`), and one for `driver-collection` |
| **Cluster address** | `git://git-server.default.svc.cluster.local/<driver>.git`, one repository per driver, and `git://git-server.default.svc.cluster.local/driver-collection.git` |

At setup time, the fixture:

1. Copies each driver source to a temp directory: the examples under `driver/examples/` and the test drivers under `tests/e2e/fixtures/drivers/`
2. Patches `driver.styrmin.yml` to point the Helm chart location at the chart server's cluster-internal URL (drivers that use the chart server's charts). For `simple-app`, it also sets `spec.info.icon` to `https://styrmin-e2e.invalid/simple-app-logo.svg` and adds one "Documentation" link to `https://styrmin-e2e.invalid/docs` (`SIMPLE_APP_LOGO_URL` and `SIMPLE_APP_DOCS_URL` in `conftest.py`); see [Serving external URLs to the UI browser](#serving-external-urls-to-the-ui-browser) <!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->
3. Initializes a git repository using [dulwich](https://www.dulwich.io/) (pure Python git)
4. Port-forwards the git-daemon service and pushes the repo

The test drivers exist only for E2E scenarios. `failing-actions` reuses the simple-app chart, and its upgrade action fails on purpose for some target versions; `test_task_steps.py` uses it to cause the failures of spec 019. `late-container` reuses the simple-app chart without a component container on `server`; `test_deployments_apply.py` pushes its next version, which declares that container, to a branch, and moves a deployment onto it with component env vars in one apply (#388). `hook-job` reuses the simple-app chart with `preUpgradeHookJob.enabled: true`, which turns on the chart's pre-upgrade Helm hook Job, labelled with the server component's identifier label `app.kubernetes.io/name: simple-app`, and a pre-upgrade hook ConfigMap without labels; `test_pod_scheduling.py` uses it to check that the hook Job gets the deployment's scheduling settings and Styrmin's labels, and that the ConfigMap gets Styrmin's labels (#435).

The `driver-collection` repository holds two drivers with actions, each in its own driver directory: `drivers/simple-app/` and `drivers/failing-actions/`. The fixture prepares each one as it prepares the repository of that driver (`_prepare_driver` in `conftest.py`), then adds `collection_helper.py` next to the `actions.py` of `simple-app` and makes that `actions.py` import it (`_import_sibling_module`). The session fixture `styrmin_resources` loads `simple-app` from the driver directory `drivers/simple-app` of `driver-collection` (spec 028), so every session deploys a driver version loaded from a driver directory and runs its actions from that folder; an action that cannot import the module next to it fails, and with it the session deployment. `test_driver_version_reselection.py` checks that the setup actions of that version completed, and loads `drivers/failing-actions` from the same commit to check that each driver keeps its own action deployments. The `simple-app` repository stays: `test_driver_version_reselection.py` and `helpers/drivers.py` push new branches to it and load them from the repository root.

<!-- Extracted from specs/025-helm-v4-defaults on 2026-10-16 -->

The E2E vcluster has one node, so an E2E test cannot check which node a pod runs on. Scheduling tests such as `test_pod_scheduling.py` check the scheduling fields of the pod template (tolerations, node affinity, pod affinity, topology spread, runtime class, resources) and that the pod ran, for example `status.succeeded` of a Job (research R-009 of [spec 025](../../../specs/archive/025-helm-v4-defaults/research.md)).

A new test driver needs two entries: one in the `drivers` map of the `git_server` fixture in `conftest.py` (with `chart_name` when the driver reuses an example chart, so that the fixture points `helm.main.location` at the chart server), and a `RUN git init --bare /git/<driver>.git` line in `tests/e2e/fixtures/git-server/Dockerfile`. Without the second, the fixture's push of that driver fails in setup with `dulwich.errors.GitProtocolError: access denied or repository not exported: /<driver>.git`.

### Telemetry Sink

A standard-library HTTP server that receives the daily telemetry report (spec 020), so the E2E install never sends reports to the OpsMill endpoint.

| Aspect | Detail |
|--------|--------|
| **Purpose** | Receive the report that the `send_telemetry_report` flow sends |
| **Image** | Built at test time from `tests/e2e/fixtures/telemetry-sink/Dockerfile` (`python:3.14-slim`) |
| **How it works** | `POST /report` stores the JSON body in memory, `GET /reports` returns the stored bodies, `GET /healthz` answers 200 |
| **Cluster address** | `http://telemetry-sink.default.svc.cluster.local:8080/report` |

`tests/e2e/fixtures/styrmin-values.yaml` sets `styrmin.telemetry.endpoint` to the cluster address when the chart is installed, before the sink exists. The module-scoped `telemetry_sink` fixture deploys the sink (or reuses it when an earlier module created it), port-forwards to it and yields the local base URL. A test reads the number of stored reports before it starts the flow and compares it after the run.

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
| `telemetry_sink` | module | `vcluster` | Port-forwarded telemetry sink URL |
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
4. Writes the full log of the agent pod (label `app.kubernetes.io/component=agent` in the `styrmin` namespace) to `e2e-logs/<test node id>/<pod>.log`, and the log of the previous container to `<pod>.previous.log` when the agent restarted

The 200-line tail of the agent pod often starts after the failure began, so the operator actions that led to it are only in the full log. In CI, the `Upload agent logs` step of the E2E job uploads `e2e-logs/` as the `e2e-agent-logs-<entrypoint>-<shard>` artifact when the job fails. GitHub keeps it for 7 days. Download it from the run's summary page or with `gh run download <run-id> -n e2e-agent-logs-<entrypoint>-<shard>`.

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

<!-- Extracted from specs/031-recorded-feature-demos on 2026-10-21 -->

### Operations fail with "An internal error occurred" when the host disk is nearly full

The vCluster's node evicts pods when the host's free disk falls below 15% of its size, for example 14.4 GiB on a 96 GB disk. The evicted pods include Velero, Prefect and Garage, and Styrmin operations then fail with "An internal error occurred". On 2026-10-21 this happened in an E2E run and in a recording of the demos, both with the host disk 85% full ([local demo guide](../../guides/local-demo.md#problems-seen-when-recording-the-demos)).

To confirm it, run `kubectl get events -n styrmin | grep Evicted`. Check `df -h /` before a run; `docker system df` shows which images and build cache take the space. Free disk space, wait until `kubectl get pods -n styrmin` shows the evicted pods running again, then run the failed tests again.

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
| [tests/e2e/demos/](backend/tests/e2e/demos/) | Recorded feature demos that reuse the page objects (`uv run invoke record`) |
| [tests/e2e/fixtures/](backend/tests/e2e/fixtures/) | Chart-server, git-server, test drivers, and Helm values |
| [dev/local/garage.yaml](dev/local/garage.yaml) | Single-node Garage (S3 store for Velero); shared with the local demo |
| [tests/e2e/test_deploy_app.py](backend/tests/e2e/test_deploy_app.py) | Canonical end-to-end deploy test |
| [driver/examples/simple-app/](driver/examples/simple-app/) | Test application (FastAPI + PostgreSQL + Helm chart) |
| [python_sdk/](python_sdk/) | Python SDK used by the api driver |
| [tests/e2e/helpers/drivers.py](backend/tests/e2e/helpers/drivers.py) | `kubectl_cp`, `styrmin_pod_name`, `agent_pod_name`: copy driver files into the server pod or the agent pod |
| [tests/e2e/test_local_driver_actions.py](backend/tests/e2e/test_local_driver_actions.py) | Actions of driver versions loaded from a local directory (`ci`, `shard_general`, `api_only`) |

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

## Driver files in the server pod and the agent pod

The server reads a local driver version's files when the driver is loaded. The agent runs each action as a process in the agent pod and reads the files at the same path there, after it checks that they have the driver version's provenance fingerprint. Tests of local driver actions therefore control what each pod holds at a path:

- **The same files in both pods.** The Styrmin image holds the `backend/` tree at `/source/backend` (`docker/Dockerfile`), and the server and the agent both run that image. `test_local_driver_actions.py` loads the `local-actions` test driver from `/source/backend/tests/e2e/fixtures/drivers/local-actions`, so its actions run without a copy. The test driver uses the `simple-app` chart at the fixed chart server URL, and its `pre_setup`, `post_setup` and `upgrade` actions log a marker that the test reads in each action's Prefect flow run logs.
- **Different files in each pod.** The test writes a variant of the driver with its own name (`local-actions-check`) and copies it with `kubectl_cp` into the server pod (`styrmin_pod_name`, container `styrmin-server`) at a path that holds a random part per session, such as `/tmp/local-actions-check-<hex>`. It copies an edited `actions.py` to the same path in the agent pod (`agent_pod_name`, container `agent`), or copies nothing there. The create then fails at `hook:setup:pre` with the fingerprint error or with the missing files error. `kubectl_cp` needs a path that does not exist in the pod yet.
- **A bundled driver.** `test_infrahub_local_driver_actions.py` loads `/styrmin/drivers/infrahub`, creates a deployment and upgrades it from 1.6.0 to 1.7.0. It has no `ci` marker, because it boots a full Infrahub stack, and is run by hand after a change to how actions run.

Every create and version change in these modules pins `driver_version_id`, so the latest-wins rule cannot bind a deployment to another variant of the driver (see [Testing](../../guidelines/backend/python.md#testing)).

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

## Filling and submitting dialogs

Base UI moves focus to a dialog's first focusable element one animation frame after the dialog opens. Playwright's `fill()` focuses its target and then types in a second step, so a fill that runs across that frame types into the newly focused element and leaves its own field empty. The form then fails validation and the dialog never closes (#365). A `fill()` that follows any `click()` inside the dialog is safe, because `click()` waits for the element to be stable over two animation frames.

Page objects use the two helpers in `tests/e2e/pages/_dom.py`:

- `wait_for_dialog_open(dialog)` waits until the dialog is visible and holds focus. Call it after opening a dialog and before its first `fill()`.
- `submit_dialog(dialog, button="Create")` clicks the submit button and waits for the dialog to close. When the dialog stays open, it raises `ScenarioTimeout` with the dialog's text (submit and field errors included), the inputs that fail native validation, and the empty inputs.

## Page objects shared with the recorded demos

The recorded demos in `backend/tests/e2e/demos/` (`uv run invoke record`, see [Recording the demos](../../guides/local-demo.md#recording-the-demos)) perform every recorded Styrmin action through `UiScenarioDriver` and the page objects in `tests/e2e/pages/`, and contain no selector for a Styrmin page. Their setup and cleanup use the SDK and are not recorded. The setup demo is the exception: it records the creation of the cluster, the backup storage location, the driver and the environment in the Styrmin UI. A fix to a page object therefore repairs the E2E tests and the demos in one change (spec 031, SC-004). CI does not run the demos. To catch a frontend change that breaks the methods below, E2E tests call them on deployments that they already create. The `[ui-chromium]` variants of two tests in `test_deployment_image_override.py` call the four `DeploymentDetailPage` methods and compare what each returns with the API, and `test_pods_tab_copy_logs_command` in `test_ui_smoke.py` calls the three `PodsTabPage` methods:

- `test_override_then_clear` calls `show_component_overrides(component="server")` after it sets the image override and after it clears it.
- `test_token_follows_upgrade_and_action_job` calls `read_task_ids()` before the upgrade, then `wait_for_new_task("upgrade_instance", ...)` and `show_timeline_entry(task_id)`. The task ids, the id of the new upgrade task and its steps must equal what the API lists.
- `test_pods_tab_copy_logs_command` calls `expand_section("database")`, `wait_for_running_pods("database", count=1)` and `show_pod(pod_name)` on simple-app's PostgreSQL pod, and checks that the expanded row lists the `postgresql` container.

Any other change that breaks a demo shows only when someone records that demo. The page objects for Infrahub and Semaphore in `tests/e2e/demos/pages/` have no test: a recording of demos 1, 3 and 4 is their only test. No E2E test calls these page-object options and methods, which only the setup demo uses: `SidebarPage.open(label)` in `tests/e2e/pages/sidebar.py`, `DriversListPage.load_local_version(path=...)`, `EnvironmentsListPage.open_card(environment_id=...)`, and `open_page=False` on `SettingsPage.create_cluster`, `BackupStorageLocationsListPage.create`, `EnvironmentsListPage.create_environment` and `EnvironmentDetailPage.assign_bsl`, which start from the page that the demo opened from the sidebar instead of opening it by its address. A recording of the setup demo is their only test. `SettingsPage.create_cluster` also enters the `fast_storage` key of the configuration since the setup demo was added; before, it left fast storage unset. The `styrmin_resources` fixture in `tests/e2e/conftest.py` passes that key, so the `[ui-chromium]` variant now creates its cluster with the same fast storage class as the `[api-chromium]` variant. The page objects for Infrahub and Semaphore and the setup demo's methods are tested only by a recording, which is why the [local demo guide](../../guides/local-demo.md#when-to-record-the-demos-again) gives the command an owner and a schedule. The page objects have this setting, this helper and these methods for the demos:

- Every page-object class that enters text, and `UiScenarioDriver`, take a keyword-only `keystroke_delay_ms: int | None = None`, and a page object or driver that creates another page object passes its value on. The E2E suite keeps the default `None`: the two places in `tests/e2e/conftest.py` that create `UiScenarioDriver` do not pass the argument.
- Page objects enter text with `enter_text(locator, text, *, keystroke_delay_ms)` from `tests/e2e/pages/_dom.py`, not with `fill()`. With `None`, it calls `locator.fill(text)`, as before. With a number, it clears the field with `fill("")` and types the text with `press_sequentially(text, delay=keystroke_delay_ms)`, so the video shows the text appear one key at a time. The setup demo and demo 1 pass 90 ms, and demos 2 to 4 pass 45 ms.
- `DeploymentDetailPage.wait_for_new_task(task_type, *, known_task_ids, timeout)` waits until the Timeline tab lists a task of type `task_type` (a `TaskType` value such as `update_instance` or `upgrade_instance`) whose id is not in `known_task_ids` and whose result is `succeeded`, and returns its id. It raises `ScenarioActionError` when that task fails or is superseded, and `ScenarioTimeout` after `timeout` seconds. A caller reads `known_task_ids` with `read_task_ids()` before it submits the change. `wait_for_deployment_running` is not enough for this, because the deployment header can still show Running before the task starts.
- Two `DeploymentDetailPage` methods scroll an element into view, so that the video shows it:
  - `show_timeline_entry(task_id)` expands the Timeline entry of the task `task_id`, scrolls it to the top of the page and returns the entry as a `TimelineEntry`, with its application version and its steps. The Timeline tab must already be open; the method does not click it. It raises `ScenarioActionError` when the tab shows no entry for the task within 10 s, or when the entry does not expand after a click. Demo 1 uses it to show the upgrade task, because the timeline lists the tasks that the driver's upgrade action starts above the upgrade task, and fails unless the entry shows the step of the upgrade action as succeeded and the `latest` Infrahub version.
  - `show_component_overrides(component=...)` opens the Settings tab, scrolls the component's row of the Component Overrides card to the middle of the page and returns the row's text. Demo 2 uses it after each override.
- Three `PodsTabPage` methods show the pods of one declared component. Demo 2 ends each chapter with them, so the video shows the effect of each override:
  - `expand_section(component)` opens the section of the declared component and scrolls it to the top of the page;
  - `wait_for_running_pods(component, *, count, timeout)` waits until that section lists exactly `count` pods, all `RUNNING`, and returns their names. The tab refreshes every 10 s, so a pod that an update replaced leaves the list;
  - `show_pod(pod_name)` expands the pod's row, scrolls it to the middle of the page and returns its text, which lists each container with its image.

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

## Serving external URLs to the UI browser

A test that checks content which the browser loads from an external URL serves that content
itself with Playwright's `page.route()`, so it does not depend on network access in CI.
`test_driver_logo_description_and_links_render` (`backend/tests/e2e/test_ui_smoke.py`) does this
for the driver logo:

- The `git_server` fixture sets the `simple-app` logo to a URL on the reserved `.invalid` domain
  (RFC 2606), where no real host answers. Without the route the logo cannot load, so the test
  fails clearly instead of passing by accident.
- The route answers with a small SVG that has an explicit `width` and `height`, so the decoded
  image has a `naturalWidth` above zero. The test waits for `data-logo-state="image"` and for
  `img.complete && img.naturalWidth > 0`.
- The test calls `page.unroute()` in a `finally` block, because `session_ui_page` is shared by the
  whole session and a route left on it would change later tests.
- List logos load lazily (`loading="lazy"`), so the test scrolls the driver group into view before
  it checks the logo.
