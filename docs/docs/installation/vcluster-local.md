---
title: Install Styrmin on a local vCluster
sidebar_label: Local laptop (vCluster)
sidebar_position: 4
description: Install Styrmin on a vCluster on your laptop, one step at a time — the manual version of `uv run invoke start`.
---

## Install Styrmin on a local vCluster

This guide installs Styrmin on a [vCluster](https://www.vcluster.com/) on
your laptop, with the same steps as the `uv run invoke start` command,
run one at a time. Use it to see what each step does, to replace a
component, or to find the step that fails.

By the end, you have:

- a vCluster named `styrmin` that runs in Docker on your machine,
- [Traefik](https://traefik.io/) as the cluster's ingress controller,
- a [Garage](https://garagehq.deuxfleurs.fr/) object store in the
  cluster, for S3-compatible Velero backups,
- Styrmin (server, agent, Prefect, PostgreSQL) installed from the Helm
  chart in the repository,
- one **cluster**, one **environment**, one **backup storage location**,
  and the bundled **application driver versions** loaded,
- the UI at `http://styrmin.local.styrmin.io:8080`.

> To run every step with one command, see the
> [Quickstart](../installation/quickstart.md).

### How this compares to `uv run invoke start`

Each section below is one step of `tasks/demo.py::start`. If a manual
step fails, run the matching invoke task instead. Each task is
independent and idempotent.

| Step | Manual command | Invoke equivalent |
|------|----------------|-------------------|
| 2. Create vCluster | `vcluster create styrmin …` | `uv run invoke cluster.create` |
| 3. Connect kubeconfig | `vcluster connect styrmin …` | `uv run invoke cluster.connect` |
| 4. Install Traefik | `helm upgrade --install traefik …` | `uv run invoke cluster.traefik` |
| 5. Install Garage | `kubectl apply -f dev/local/garage.yaml …` | `uv run invoke cluster.garage` |
| 6. Build the image | `docker build …` | `uv run invoke build` |
| 7. Install Styrmin chart | `helm upgrade --install styrmin …` | (part of `start`) |
| 8. Port-forward Traefik | `kubectl port-forward …` | (part of `start`) |
| 9. Create the first records | `styrminctl …` | `uv run invoke dev.bootstrap` |

### Prerequisites

You need the following on your `PATH`:

- **Docker**: this guide runs vCluster with its `docker` driver
- **`kubectl`**
- **`helm`** ≥ 3.x
- **`vcluster`** CLI ([install instructions](https://www.vcluster.com/docs/getting-started/setup))
- **`uv`** ([install instructions](https://docs.astral.sh/uv/getting-started/installation/))

TCP port **`8080`** must be free on your host: the Traefik port-forward
listens on it. The guide does not use port `80`, because it is a
privileged port.

> The wildcard zone `*.local.styrmin.io` resolves to `127.0.0.1`, so
> `http://styrmin.local.styrmin.io:8080` opens the UI without changes
> to `/etc/hosts`.

### 1. Clone and install the toolchain

```shell
git clone https://github.com/opsmill/styrmin.git
cd styrmin
uv sync
```

`uv sync` installs the root project, the backend, SDK, and CLI workspace
packages, and the `dev` dependency group, which includes `invoke` and
`styrminctl`.

### 2. Create the vCluster

[vCluster](https://www.vcluster.com/) runs a virtual Kubernetes control
plane in a pod on a host cluster. With the `docker` driver, Docker is
the host, so you do not need an existing Kubernetes cluster.
`uv run invoke cluster.create` runs the same command.

```shell
vcluster create styrmin \
  --upgrade \
  --driver=docker \
  --connect=false
```

- `--driver=docker` runs the vCluster control-plane container in Docker,
  without a host Kubernetes cluster.
- `--upgrade` makes the command idempotent: on an existing vCluster, it
  upgrades the vCluster instead of failing.
- `--connect=false` leaves your kubeconfig unchanged. The next step
  switches it.

`vcluster list` now shows `styrmin` as `Running`.

### 3. Connect your kubeconfig

```shell
vcluster connect styrmin --driver=docker
```

This writes a kubeconfig entry for the vCluster and switches your
current context to it. Check the result:

```shell
kubectl get nodes
kubectl config current-context
```

The output lists one node, the vCluster's synthetic node.

> **Tip:** every later `kubectl` and `helm` command in this guide runs
> against the vCluster, not your usual cluster. If you have other
> clusters configured, check `kubectl config current-context` before
> each step.

### 4. Install Traefik (ingress controller)

The Styrmin frontend is served over HTTP through a Kubernetes `Ingress`,
so the cluster needs an ingress controller. The demo uses Traefik.
Another ingress controller also works, but the Helm values and hostnames
in this guide are for Traefik.

```shell
helm repo add traefik https://helm.traefik.io/traefik
helm repo update traefik
helm upgrade --install traefik traefik/traefik \
  -n styrmin --create-namespace \
  -f dev/local/traefik-values.yaml \
  --set service.type=ClusterIP \
  --take-ownership \
  --wait --timeout 5m
```

Note:

- **`service.type=ClusterIP`**, not `LoadBalancer`. The vCluster has no
  cloud provider for `LoadBalancer` Services, so step 8 exposes Traefik
  with a port-forward instead of an external IP. With `ClusterIP`, the
  steps are the same on Linux and macOS.
- **`dev/local/traefik-values.yaml`** sets a small resource request and
  enables `publishedService`, so Traefik writes the address of its
  Service in the status of each `Ingress`.

### 5. Install Garage (backup storage)

Styrmin runs backups with Velero, which needs an S3-compatible object
store. For a local install, run Garage in the same namespace:

```shell
kubectl apply -f dev/local/garage.yaml -n styrmin
kubectl rollout status deployment/garage -n styrmin --timeout=120s
```

The manifest creates a `ConfigMap` (Garage's configuration and a setup
script), a `Deployment` with one replica, and a `Service` that exposes
the S3 API on port `3900` and the admin API on port `3903`.

A new Garage node stores no data until it has a cluster layout. The pod
runs a second container that waits for the admin API, assigns the
layout, and creates the `velero` bucket and its access key. The pod
reports ready only after that, so when `kubectl rollout status`
returns, the bucket exists.

The access key is `GKdeadbeefdeadbeefdeadbeef` with secret
`deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef`.
Velero uses it, and so does the backup storage location you create in
step 9. These are fixed demo values: use your own keys for an
installation that you keep.

### 6. Build the Styrmin container image

The demo values file
([dev/local/demo-values.yaml](https://github.com/opsmill/styrmin/blob/develop/dev/local/demo-values.yaml))
sets the image to `styrmin:latest`. Build it locally:

```shell
uv run invoke build
```

The task runs:

1. `docker build` of the image that the server and the agent both run,
2. `helm dependency update helm/agent`,
3. `helm dependency update helm/styrmin`.

The vCluster pulls images through the host's Docker daemon, so it can
use `styrmin:latest` right away, without a push to a registry.

> Skip this step if you built the image before and your code has not
> changed. The `start` task builds the image only when it is missing or
> when you pass `--build-image`.

### 7. Install Styrmin with Helm

```shell
helm upgrade --install styrmin helm/styrmin \
  -n styrmin --create-namespace \
  -f dev/local/demo-values.yaml \
  --wait --timeout 10m
```

`dev/local/demo-values.yaml` contains the values for the demo. The
relevant settings:

```yaml
image:
  repository: styrmin
  tag: latest
  pullPolicy: IfNotPresent

# The agent subchart defaults its tag to the released appVersion, so the
# locally-built tag has to be pinned there too.
styrmin-agent:
  image:
    tag: latest
    pullPolicy: IfNotPresent

ingress:
  enabled: true
  className: traefik
  hosts:
    - host: styrmin.local.styrmin.io
      paths:
        - path: /
          pathType: Prefix

styrmin:
  adminUsername: admin
  adminPassword: styrmin
  sessionCookieSecure: false   # demo is plain HTTP; cookies would be dropped otherwise
  telemetry:
    enabled: false             # the local demo sends no telemetry reports

velero:
  backupsEnabled: false        # the BSL of step 9 points Velero to Garage instead
```

Check that the server is running:

```shell
kubectl rollout status deployment/styrmin-server -n styrmin --timeout=300s
```

### 8. Port-forward Traefik

Traefik has a `ClusterIP` Service, so you forward a host port to reach
it. The demo uses `8080`:

```shell
kubectl port-forward svc/traefik 8080:80 -n styrmin
```

Keep it running in its own terminal, or run it in the background with
`&` and record its PID. `invoke start` writes the PID to a file under
`.vcluster/`.

The UI is now available at:

```text
http://styrmin.local.styrmin.io:8080
```

### 9. Create the first records

Styrmin runs, but its database has no records yet. This step uses
`styrminctl` to create the cluster, the environment, and the backup
storage location, and to load the bundled application driver versions.

#### 9a. Log in

```shell
export STYRMIN_SERVER_ADDRESS=http://styrmin.local.styrmin.io:8080
uv run styrminctl login --username admin
```

The admin credentials come from `styrmin.adminUsername` and
`styrmin.adminPassword` in `dev/local/demo-values.yaml`. If you changed
them there, use the new values here.

#### 9b. Create the cluster record

The `external_url_*` fields set how users reach the cluster's services.
Styrmin builds the URLs of the services from them and from
`fqdn_suffix`.

```shell
uv run styrminctl clusters create local \
  --config '{
        "fqdn_suffix": "local.styrmin.io",
        "external_url_scheme": "http",
        "external_url_port": 8080
      }'
```

Record the returned `id`, referred to as `<CLUSTER_ID>` below.

#### 9c. Create the environment

```shell
uv run styrminctl environments create local --cluster local -c '{}'
```

Record the returned `id`, referred to as `<ENVIRONMENT_ID>` below.

#### 9d. Create the backup storage location

Create a backup storage location (BSL) for the Garage store from step 5:

```shell
uv run styrminctl backup-locations create local \
  --endpoint http://garage.styrmin.svc:3900 \
  --bucket velero \
  --region garage \
  --access-key-id GKdeadbeefdeadbeefdeadbeef \
  --secret-access-key deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
```

Record the returned `id`, referred to as `<BSL_ID>` below.

#### 9e. Assign the BSL to the environment

```shell
uv run styrminctl backup-locations assign <ENVIRONMENT_ID> <BSL_ID>
```

#### 9f. Load the bundled drivers

The Styrmin image includes the example drivers at `/styrmin/drivers/`.
Load `infrahub` and `semaphore`, the two drivers that the `dev.bootstrap`
task loads by default:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

Log in to the UI. It shows one cluster (`local`), one environment
(`local`), and two drivers.

### 10. Deploy an application

From the UI or with `styrminctl`, create a deployment:

```shell
uv run styrminctl deployments create infrahub 1.6.0 <ENVIRONMENT_ID>
```

Follow the deployment with `styrminctl`:

```shell
uv run styrminctl deployments get <DEPLOYMENT_ID>
```

Or port-forward the Prefect UI in another shell:

```shell
kubectl port-forward svc/prefect-server 4200:4200 -n styrmin
```

Then open [http://localhost:4200](http://localhost:4200).

### Lifecycle

| What you want | Command |
|---------------|---------|
| Pause everything and keep the state | `vcluster pause styrmin --driver=docker` (or `uv run invoke stop`) |
| Resume after a pause | `vcluster resume styrmin --driver=docker`, then run the port-forward again |
| Delete everything | `vcluster delete styrmin --driver=docker` (or `uv run invoke destroy`) |
| Start again with no data | `uv run invoke reset` |

The vCluster stores its state on a Docker volume, so `pause` and
`resume` keep the cluster, environment, drivers, and deployments.

### Troubleshooting

**`kubectl` connects to the wrong cluster.** `vcluster connect` switches
your current context. If you ran `kubectl config use-context …` after
it, `kubectl` uses your host cluster again. Run
`vcluster connect styrmin --driver=docker` or
`kubectl config use-context vcluster_…` again.

**Port 8080 is already in use.** The port-forward command fails
immediately. Stop the process that listens on the port, or change both
the `kubectl port-forward` port and the `external_url_port` that you set
on the cluster in step 9b.

**The `styrmin:latest` pod is in `ImagePullBackOff`.** Run
`uv run invoke build` again to build the image. The vCluster reads the
images of the host's Docker daemon, so a local build is enough, without
a push to a registry.

**The bootstrap step says "Cluster already exists".** A previous
bootstrap run created the cluster record. Run `uv run invoke reset` to
start over with a new vCluster. `styrminctl clusters delete` removes the
existing record only while the cluster has no environments: after the
bootstrap has created one, Styrmin refuses the delete with an error
that lists them.

**Login fails with "invalid credentials".** Check that
`styrmin.adminPassword` in `dev/local/demo-values.yaml` matches the
password you enter. The Helm install sets the password on the first
install. After you change it in the values file, run `helm upgrade` to
apply it.

### Next steps

- [**Platform overview**](../introduction/platform-overview.md): the
  components and terms of Styrmin.
- [**What is an application driver?**](../concepts-and-architecture/what-is-a-driver.md):
  the specification that Styrmin uses to deploy each application.
- [**Install Styrmin on DigitalOcean**](./digitalocean.md): install
  Styrmin on a managed Kubernetes cluster.
