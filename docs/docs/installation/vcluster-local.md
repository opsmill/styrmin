---
title: Local laptop (vcluster)
sidebar_position: 4
description: Deploy Styrmin on your local laptop using vcluster, step by step — the manual version of `uv run invoke start`.
---

## Local laptop with vcluster

This guide walks through deploying Styrmin to a
[vCluster](https://www.vcluster.com/) on your laptop, the same way the
`uv run invoke start` command does — but unpacked into individual steps
so you can see what each piece is for, swap parts out, or debug a stuck
state.

By the end you'll have:

- a Docker-backed vCluster named `styrmin` running on your machine,
- [Traefik](https://traefik.io/) acting as the cluster's ingress controller,
- an in-cluster [Garage](https://garagehq.deuxfleurs.fr/) for S3-compatible
  Velero backups,
- Styrmin (server + agent + Prefect + Postgres) installed via the
  bundled Helm chart,
- one **Cluster**, one **Environment**, one **Backup Storage Location**,
  and the bundled **Application Driver Versions** loaded,
- the UI reachable at `http://styrmin.local.styrmin.io:8080`.

> If you just want the one-command experience, see the
> [Quickstart](../installation/quickstart.md) — it runs every step in
> this guide for you.

### How this compares to `uv run invoke start`

Each section below is one step in `tasks/demo.py::start`. If you ever
get stuck during a manual run, you can pick up by calling the
corresponding invoke task instead — they're independent and idempotent.

| Step | Manual command | Invoke equivalent |
|------|----------------|-------------------|
| 2. Create vCluster | `vcluster create styrmin …` | `uv run invoke cluster.create` |
| 3. Connect kubeconfig | `vcluster connect styrmin …` | `uv run invoke cluster.connect` |
| 4. Install Traefik | `helm upgrade --install traefik …` | `uv run invoke cluster.traefik` |
| 5. Install Garage | `kubectl apply -f dev/local/garage.yaml …` | `uv run invoke cluster.garage` |
| 6. Build the image | `docker build …` | `uv run invoke build` |
| 7. Install Styrmin chart | `helm upgrade --install styrmin …` | (part of `start`) |
| 8. Port-forward Traefik | `kubectl port-forward …` | (part of `start`) |
| 9. Bootstrap entities | `styrminctl …` | `uv run invoke dev.bootstrap` |

### Prerequisites

You need the following on your `PATH`:

- **Docker** — vCluster uses the `docker` driver by default
- **`kubectl`**
- **`helm`** ≥ 3.x
- **`vcluster`** CLI ([install instructions](https://www.vcluster.com/docs/getting-started/setup))
- **`uv`** ([install instructions](https://docs.astral.sh/uv/getting-started/installation/))

You also need a free TCP port **`8080`** on your host — the Traefik
port-forward binds there. (Port 80 is privileged, hence the offset.)

> **No `/etc/hosts` edits required.** The wildcard zone
> `*.local.styrmin.io` resolves to `127.0.0.1`, so
> `http://styrmin.local.styrmin.io:8080` works straight away.

### 1. Clone and install the toolchain

```shell
git clone https://github.com/opsmill/styrmin.git
cd styrmin
uv sync
```

`uv sync` installs the root project plus the backend, SDK, CLI workspace
packages and the dev dependency group (which provides `invoke` and
`styrminctl`).

### 2. Create the vCluster

[vCluster](https://www.vcluster.com/) runs a virtual Kubernetes control
plane inside a single pod on a host cluster — but with the `docker`
driver, that "host cluster" is just Docker, so you don't need an
existing Kubernetes to begin with. This is the same path
`uv run invoke cluster.create` takes.

```shell
vcluster create styrmin \
  --upgrade \
  --driver=docker \
  --connect=false
```

- `--driver=docker` runs the vCluster control-plane container directly
  in Docker — no host kubernetes required.
- `--upgrade` makes the command idempotent: re-running it on an existing
  vCluster upgrades it instead of failing.
- `--connect=false` keeps your kubeconfig pointing wherever it already
  was; we'll switch it explicitly in the next step.

`vcluster list` should now show `styrmin` as `Running`.

### 3. Connect your kubeconfig

```shell
vcluster connect styrmin --driver=docker
```

This writes a kubeconfig entry for the vCluster and switches your
current context to it. Confirm with:

```shell
kubectl get nodes
kubectl config current-context
```

You should see one node (the vCluster's synthetic node).

> **Tip:** every subsequent `kubectl` and `helm` command in this guide
> targets _the vCluster_, not your host's normal cluster. If you have
> other clusters configured, double-check `kubectl config
> current-context` before each step.

### 4. Install Traefik (ingress controller)

Styrmin's frontend is reached over HTTP through a Kubernetes `Ingress`,
so the cluster needs an ingress controller. Traefik is what the demo
uses; any ingress controller would work, but the Helm values and
hostnames in this guide assume Traefik.

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

Two things to note:

- **`service.type=ClusterIP`** (not `LoadBalancer`). The vCluster does
  not have a working cloud `LoadBalancer` provider, so we expose Traefik
  via a port-forward later instead of relying on an external IP. Using
  `ClusterIP` keeps the flow identical across Linux and macOS.
- **`dev/local/traefik-values.yaml`** sets a small resource request and
  enables `publishedService` so Ingress objects know which Service they
  resolve through.

### 5. Install Garage (backup storage)

Velero — Styrmin's backup engine — needs an S3-compatible object store.
For local use we run Garage inside the same namespace.

```shell
kubectl apply -f dev/local/garage.yaml -n styrmin
kubectl rollout status deployment/garage -n styrmin --timeout=120s
```

The manifest creates a `ConfigMap` (Garage's config plus a bootstrap
script), a single-replica `Deployment`, and a `Service` exposing the S3
API on port `3900` and the admin API on port `3903`.

A fresh Garage node stores nothing until a cluster layout is assigned, so
the pod runs a second container that waits for the admin API, assigns the
layout, then creates the `velero` bucket and the access key for it. The
pod only reports ready once that has finished — `kubectl rollout status`
returning means the bucket is there.

The access key is `GKdeadbeefdeadbeefdeadbeef` with secret
`deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef` (used
by Velero and by the Backup Storage Location you'll create in step 9).
They are fixed demo values — pick your own for anything long-lived.

### 6. Build the Styrmin container image

`helm/styrmin` references `styrmin:latest` by default
([dev/local/demo-values.yaml](https://github.com/opsmill/styrmin/blob/develop/dev/local/demo-values.yaml)).
Build it locally:

```shell
uv run invoke build
```

Under the hood this runs:

1. `docker build` of the agent image (used by both server and agent),
2. `helm dependency update helm/agent`,
3. `helm dependency update helm/styrmin`.

Because the vCluster uses the host's Docker daemon for pulls, the image
is immediately reachable as `styrmin:latest` — no registry push needed.

> Skip this step if you've built the image before and your code hasn't
> changed. The `start` task only rebuilds when the image is missing or
> when you pass `--build-image`.

### 7. Install Styrmin via Helm

```shell
helm upgrade --install styrmin helm/styrmin \
  -n styrmin --create-namespace \
  -f dev/local/demo-values.yaml \
  --wait --timeout 10m
```

`dev/local/demo-values.yaml` is the demo-flavoured values file. The
parts worth knowing:

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
  backupsEnabled: false        # Garage is wired up by the BSL in step 9 instead
```

Confirm the server is up:

```shell
kubectl rollout status deployment/styrmin-server -n styrmin --timeout=300s
```

### 8. Port-forward Traefik

Because Traefik is a `ClusterIP` service, you need to forward a host
port to reach it. The demo uses `8080`:

```shell
kubectl port-forward svc/traefik 8080:80 -n styrmin
```

Leave that running in its own terminal (or background it with `&` and
record the PID — that's exactly what `invoke start` does to a PID file
under `.vcluster/`).

You should now be able to reach the UI at:

```text
http://styrmin.local.styrmin.io:8080
```

### 9. Bootstrap the platform

The cluster has Styrmin _running_ but no records in its database yet.
The bootstrap step uses `styrminctl` to create the Cluster, Environment,
Backup Storage Location, and to load the bundled Application Driver
Versions.

#### 9a. Log in

```shell
export STYRMIN_SERVER_ADDRESS=http://styrmin.local.styrmin.io:8080
uv run styrminctl login --username admin
```

(The seeded admin credentials come from `styrmin.adminUsername` /
`styrmin.adminPassword` in `dev/local/demo-values.yaml`. If you changed
them there, change them here too.)

#### 9b. Create the Cluster record

The `external_url_*` fields tell Styrmin how end users reach the
cluster's services — they're what the generated FQDNs are built from.

```shell
uv run styrminctl clusters create local \
  --config '{
        "fqdn_suffix": "local.styrmin.io",
        "external_url_scheme": "http",
        "external_url_port": 8080
      }'
```

Record the returned `id` — referred to as `<CLUSTER_ID>` below.

#### 9c. Create the Environment

```shell
uv run styrminctl environments create local --cluster local -c '{}'
```

Record the returned `id` — referred to as `<ENVIRONMENT_ID>` below.

#### 9d. Create the Backup Storage Location

Point a BSL at the in-cluster Garage from step 5:

```shell
uv run styrminctl backup-locations create local \
  --endpoint http://garage.styrmin.svc:3900 \
  --bucket velero \
  --region garage \
  --access-key-id GKdeadbeefdeadbeefdeadbeef \
  --secret-access-key deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
```

Record the returned `id` — referred to as `<BSL_ID>` below.

#### 9e. Assign the BSL to the Environment

```shell
uv run styrminctl backup-locations assign <ENVIRONMENT_ID> <BSL_ID>
```

#### 9f. Load the bundled drivers

The driver examples are baked into the Styrmin image at
`/styrmin/drivers/`. Load `infrahub` and `semaphore` — these are the
two the `dev.bootstrap` task loads by default:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

Now log into the UI: you should see one cluster (`local`), one
environment (`local`), and two drivers ready to deploy.

### 10. Try it out

From the UI or with `styrminctl`, create a deployment:

```shell
uv run styrminctl deployments create infrahub 1.6.0 <ENVIRONMENT_ID>
```

Watch the reconciliation either by polling:

```shell
uv run styrminctl deployments get <DEPLOYMENT_ID>
```

…or by port-forwarding the Prefect UI in another shell:

```shell
kubectl port-forward svc/prefect-server 4200:4200 -n styrmin
```

Then open [http://localhost:4200](http://localhost:4200).

### Lifecycle

| What you want | Command |
|---------------|---------|
| Pause everything, preserve state | `vcluster pause styrmin --driver=docker` (or `uv run invoke stop`) |
| Resume after pause | `vcluster resume styrmin --driver=docker` then re-run the port-forward |
| Tear it all down | `vcluster delete styrmin --driver=docker` (or `uv run invoke destroy`) |
| Start fresh | `uv run invoke reset` |

The state lives on the vCluster's Docker volume, so a `pause` round-trip
keeps your cluster + environment + drivers + deployments intact.

### Troubleshooting

**`kubectl` is hitting the wrong cluster.** `vcluster connect` switches
your current context, but if you ran `kubectl config use-context …`
since then you're back on your host cluster. Re-run `vcluster connect
styrmin --driver=docker` or `kubectl config use-context vcluster_…`.

**Port 8080 is already in use.** The port-forward command fails fast.
Free the port (whatever else binds it) or change both the
`kubectl port-forward` target and the `external_url_port` you record on
the cluster in step 9b.

**`styrmin:latest` is `ImagePullBackOff`.** Re-run `uv run invoke build`
to rebuild the image. The vCluster reads Docker's image cache directly,
so a successful local build is sufficient — no registry push needed.

**Bootstrap step says "Cluster already exists".** A previous bootstrap
run got that far. The easiest fix is `uv run invoke reset`, which starts
over from a clean vCluster. `styrminctl clusters delete` removes the
existing record only while the cluster has no environments: once the
bootstrap has created one, the delete is refused with an error that
lists them.

**Login fails with "invalid credentials".** Confirm the
`styrmin.adminPassword` in `dev/local/demo-values.yaml` matches the one
you're logging in with. The Helm install seeds it on first run; later
changes to the values file require `helm upgrade` to take effect.

### Next steps

- [**Platform Overview**](../introduction/platform-overview.md) — the
  conceptual model behind cluster, environment, deployment.
- [**What is an Application Driver?**](../concepts-and-architecture/what-is-a-driver.md) —
  the unit of deployment you just loaded.
- [**DigitalOcean**](./digitalocean.md) — when you're ready to move off
  your laptop.
