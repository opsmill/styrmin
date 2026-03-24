# E2E Testing

## Overview

End-to-end tests validate the complete deployment pipeline: from an API call that requests a deployment, through the orchestration engine, all the way to a running application on Kubernetes with reachable HTTP endpoints. The tests run against a real (local) Kubernetes cluster with all Styrmin components deployed via Helm.

```text
┌──────────────────────────────────────────────────────────────────────┐
│                        Kind Cluster                                  │
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
│  │  Deployed Application (simple-app)     │                         │
│  │  namespace: styrmin-{deployment_id}    │                         │
│  │  ┌──────────┐  ┌────────────────────┐  │                         │
│  │  │ FastAPI  │  │   PostgreSQL       │  │                         │
│  │  │  :8000   │  │                    │  │                         │
│  │  └──────────┘  └────────────────────┘  │                         │
│  └────────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │ port-forward (kr8s)                      │ port-forward
         │                                          │
┌────────┴──────────────────────────────────────────┴─────────────────┐
│                         Test Runner (pytest)                         │
│                                                                      │
│  1. Create resources via StyrminClient (Python SDK)                  │
│  2. Trigger deployment                                               │
│  3. Poll deployment status until "deployed"                          │
│  4. Port-forward to deployed service                                 │
│  5. Verify HTTP endpoints (/health, /count)                          │
└──────────────────────────────────────────────────────────────────────┘
```

Tests are marked with `@pytest.mark.e2e` and live under `backend/tests/e2e/`.

## Test Environment

E2e tests use [Kind](https://kind.sigs.k8s.io/) (Kubernetes-in-Docker) to create a disposable single-node cluster per test session. Kind was chosen because it runs entirely in Docker, requires no cloud resources, and provides a real Kubernetes API.

The cluster is created with a unique name (`pytest-{uuid}`) and a temporary kubeconfig. A finalizer deletes the cluster after the session completes, regardless of test outcome.

```python
# backend/tests/conftest.py
@pytest.fixture(scope="session")
async def kind_cluster(request, tmp_path_factory):
    cluster_name = f"pytest-{uuid.uuid4()}"
    # kind create cluster --name <name> --kubeconfig <path>
    ...
    yield {"api": api, "cluster_name": cluster_name, "kubeconfig_path": kubeconfig_path}
    # finalizer: kind delete cluster --name <name>
```

All e2e fixtures are **session-scoped** so the expensive cluster setup happens only once.

## Supporting Services

Two lightweight services are deployed inside the Kind cluster to simulate the external infrastructure that Styrmin depends on in production.

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
2. Patches `styrmin_driver.yaml` to point the Helm chart location at the chart server's cluster-internal URL
3. Initializes a git repository using [dulwich](https://www.dulwich.io/) (pure Python git)
4. Port-forwards the git-daemon service and pushes the repo

## Styrmin Deployment

Styrmin itself is deployed into the Kind cluster via its Helm chart, following the same path a real deployment would take.

### Image Preloading

Kind clusters cannot pull images from the internet by default. All dependency images are pre-pulled on the host and loaded into the cluster node using `docker save | kind load image-archive`:

```text
busybox:1.36                                    # task-worker init container
bitnamilegacy/postgresql:17.6.0-debian-12-r4    # database
prefecthq/prefect:3.6.13-python3.11             # Prefect server
prefecthq/prefect:3.6.13-python3.11-kubernetes  # Prefect worker
fluxcd/helm-controller:v1.1.0                   # FluxCD agent subchart
fluxcd/source-controller:v1.4.0                 # FluxCD agent subchart
```

### Helm Installation

The styrmin Docker image is built via `docker compose build`, loaded into Kind, then installed:

```bash
helm upgrade --install styrmin \
  --dependency-update --create-namespace -n styrmin \
  helm/styrmin/ \
  --set image.tag=latest \
  --set image.pullPolicy=Never \
  --set styrmin.driver.token=dummy \
  --set styrmin.agentSource.token=$GITHUB_PAT \
  --wait --timeout 5m
```

The `--wait` flag ensures Helm blocks until all pods are ready. After installation, the fixture port-forwards the `styrmin-server` service and waits for its `/health` endpoint to return 200.

## Test Data Setup

The `styrmin_resources` fixture uses the Python SDK (`styrmin_sdk.StyrminClient`) to create the resources needed for a deployment test:

```text
StyrminClient
  ├── clusters.create("test-cluster", config={...})
  │     fqdn_suffix, ingress_class, runtime_class, storage_class
  │
  ├── environments.create("test-environment", cluster_id=...)
  │     ip_whitelist
  │
  ├── drivers.create("simple-app")
  │
  └── drivers.load_version(git_url, "master")
        Fetches driver spec from git server
```

This mirrors what a user would do through the API: register a cluster, create an environment, register a driver, and load a version from a git repository.

## Test Flow

The main test (`test_deploy_simple_app`) exercises the complete deployment lifecycle:

```text
1. Deploy          client.deployments.create("simple-app", "0.1.0", environment_id)
                   └─ Returns a task with deployment_id

2. Poll            client.deployments.get(deployment_id)
                   └─ Loop until status is "deployed" or "running" (3 min timeout)

3. Discover        kr8s list services in namespace styrmin-{deployment_id}
                   └─ Find the service matching "simple-app"

4. Port-forward    service.portforward(remote_port=8000)
                   └─ Opens local tunnel to the deployed app

5. Verify          GET /health  → 200
                   GET /count   → 200
```

Behind the scenes, the deployment triggers Styrmin's full orchestration pipeline: Prefect workflows render the Helm values, the agent creates a FluxCD HelmRelease, and Flux reconciles it into running pods.

## Fixture Dependency Graph

All fixtures are session-scoped. The dependency chain determines initialization order:

```text
kind_cluster ─────────────────────────────┐
  │                                       │
  ├── styrmin_images                      │
  │     └── styrmin_deployment            │
  │           └── styrmin_resources ──────┤
  │                                       │
  ├── chart_server                        │
  │     └── git_server ───────────────────┤
  │                                       │
  └── simple_app_image                    │
                                          │
                              test_deploy_simple_app
```

| Fixture | Depends on | What it provides |
|---------|-----------|-----------------|
| `kind_cluster` | — | K8s API client, cluster name, kubeconfig path |
| `styrmin_images` | `kind_cluster` | Dependency images loaded into cluster |
| `chart_server` | `kind_cluster` | Cluster-internal chart server URL |
| `git_server` | `kind_cluster`, `chart_server` | Cluster-internal git URL |
| `styrmin_deployment` | `kind_cluster`, `styrmin_images` | Port-forwarded Styrmin server URL |
| `styrmin_resources` | `styrmin_deployment`, `git_server` | Cluster/environment/driver IDs + SDK client |
| `simple_app_image` | `kind_cluster` | simple-app image loaded into cluster |

## Debugging

### Automatic Log Dump on Failure

An autouse fixture (`_dump_k8s_logs_on_failure`) hooks into pytest's test reporting. When a test fails, it automatically:

1. Lists all namespaces matching `styrmin*`
2. For each namespace, prints pod statuses (`kubectl get pods -o wide`)
3. For each pod, prints the last 200 lines of container logs

This runs via a `pytest_runtest_makereport` hook that stores the test result on the item, then the fixture checks `rep_call.failed` in its teardown.

### Manual Investigation

Since the Kind cluster persists for the session, you can interact with it directly if a test is paused or using `--pdb`:

```bash
export KUBECONFIG=/tmp/pytest-xxx/kind0/kubeconfig
kubectl get pods -A
kubectl logs -n styrmin deploy/styrmin-server
kubectl get helmreleases -A
```

## Prerequisites

### System Tools

| Tool | Purpose |
|------|---------|
| `docker` | Build images, run Kind |
| `kind` | Create/manage local K8s clusters |
| `kubectl` | Debug access and log dumping |
| `helm` | Deploy Styrmin into the cluster |

### Running

```bash
cd backend && uv run pytest tests/e2e -v
```

## Key Files

| File | Purpose |
|------|---------|
| [tests/e2e/test_deploy_app.py](backend/tests/e2e/test_deploy_app.py) | Main e2e test |
| [tests/e2e/conftest.py](backend/tests/e2e/conftest.py) | E2e fixtures (chart server, git server, Styrmin deployment) |
| [tests/conftest.py](backend/tests/conftest.py) | Root fixtures (Kind cluster, config loading) |
| [tests/e2e/fixtures/chart-server/](backend/tests/e2e/fixtures/chart-server/) | Chart server Dockerfile and K8s manifests |
| [tests/e2e/fixtures/git-server/](backend/tests/e2e/fixtures/git-server/) | Git server Dockerfile and K8s manifests |
| [driver/examples/simple-app/](driver/examples/simple-app/) | Test application (FastAPI + PostgreSQL + Helm chart) |
| [python_sdk/](python_sdk/) | Python SDK used by tests to interact with Styrmin API |
