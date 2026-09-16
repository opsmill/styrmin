---
title: Quickstart
sidebar_position: 3
description: Bring up the built-in Styrmin demo cluster end-to-end in two commands.
---

## Quickstart

The Styrmin repository ships with a one-command demo that spins up a local
[vCluster](https://www.vcluster.com/), installs Styrmin into it, wires up
Traefik, Garage, and the bundled drivers, and prints the URL to log in. It is
the fastest way to see Styrmin running end-to-end on your own machine.

This guide walks you through:

1. Cloning the repository and installing the toolchain
2. Building the demo image with `uv run invoke build`
3. Starting the demo cluster with `uv run invoke start`
4. Logging in and trying it out
5. Tearing it down again

### Prerequisites

You need the following on your `PATH`:

- **Docker** (the vCluster driver used by the demo is `docker`)
- **`kubectl`**
- **`helm`** ≥ 3.x
- **`vcluster`** CLI ([install instructions](https://www.vcluster.com/docs/getting-started/setup))
- **`uv`** ([install instructions](https://docs.astral.sh/uv/getting-started/installation/))

You also need a free TCP port `8080` on your host — the demo port-forwards
Traefik there.

> **No `/etc/hosts` edits required.** The demo uses the
> `*.local.styrmin.io` wildcard zone, which resolves to `127.0.0.1`. The
> URL `http://styrmin.local.styrmin.io:8080` Just Works.

### 1. Clone the repository

```bash
git clone https://github.com/opsmill/styrmin.git
cd styrmin
```

### 2. Install Python dependencies

The demo workflow is implemented as [Invoke](https://www.pyinvoke.org/)
tasks shipped with the repo. Install the toolchain with `uv`:

```bash
uv sync
```

This installs the root project plus all workspace members (backend, SDK,
CLI) and the `dev` dependency group, which is what provides `invoke`.

### 3. Build the demo image

```bash
uv run invoke build
```

This task does three things:

1. Builds the `styrmin:latest` container image used by both the server and
   the agent.
2. Resolves the Helm dependencies under `helm/agent/`.
3. Resolves the Helm dependencies under `helm/styrmin/`.

You only need to re-run `build` when you change the server/agent code,
their `Dockerfile`s, or their Helm chart dependencies.

### 4. Start the demo cluster

```bash
uv run invoke start
```

`start` is the end-to-end happy path. In order, it:

1. Creates a vCluster named `styrmin-demo` running in Docker.
2. Connects to it and exports a kubeconfig under `.vcluster/`.
3. Installs the [Traefik](https://traefik.io/) ingress controller and
   [Garage](https://garagehq.deuxfleurs.fr/) (the in-cluster S3-compatible
   store used for Velero backups).
4. Installs Styrmin into the cluster via `helm upgrade --install`, using
   the values file at
   [`dev/local/demo-values.yaml`](https://github.com/opsmill/styrmin/blob/develop/dev/local/demo-values.yaml).
5. Port-forwards Traefik to `localhost:8080`.
6. Bootstraps the platform by calling the GraphQL API:
   - creates a **Cluster** named `local`
   - creates an **Environment** named `local` bound to that cluster
   - creates a **Backup Storage Location** pointing at the in-cluster
     Garage and assigns it to the environment
   - loads the bundled **Application Driver Versions**
     ([`driver/examples/infrahub`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/infrahub)
     and
     [`driver/examples/semaphore`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/semaphore))
7. Prints a green summary panel with the URLs and admin credentials.

> If `styrmin:latest` is already present, `start` reuses it. Pass
> `--build-image` to force a rebuild:
>
> ```bash
> uv run invoke start --build-image
> ```

When the command finishes, you should see something like:

```text
╭─ Styrmin demo is ready ───────────────────────────────────────────╮
│  Styrmin UI:     http://styrmin.local.styrmin.io:8080             │
│  GraphQL:        http://styrmin.local.styrmin.io:8080/graphql     │
│  Admin login:    admin / styrmin                                  │
│  Garage S3:      kubectl port-forward svc/garage 3900:3900 …      │
│  Garage creds:   GKdeadbeef… / deadbeef…                          │
│                                                                   │
│  Deployments:                                                     │
│  styrmin-server   1/1   1   1   1m                                │
│  …                                                                │
╰───────────────────────────────────────────────────────────────────╯
```

### 5. Log in and look around

Open [http://styrmin.local.styrmin.io:8080](http://styrmin.local.styrmin.io:8080) and log in with `admin` /
`styrmin` (these come from `dev/local/demo-values.yaml`; change them there
if you want different credentials).

You should see:

- one **Cluster** (`local`), with the agent running and reporting status
- one **Environment** (`local`) bound to that cluster
- two **Application Drivers** (`infrahub` and `semaphore`), each with at
  least one driver version loaded
- no deployments yet — try creating one from the UI to see reconciliation
  in action

To explore the GraphQL API directly, head to
[http://styrmin.local.styrmin.io:8080/graphql](http://styrmin.local.styrmin.io:8080/graphql).

### 6. Pause, resume, or tear down

The demo lifecycle has four convenience commands:

| Command | What it does |
|---------|--------------|
| `uv run invoke start`   | Create + provision everything (idempotent). |
| `uv run invoke stop`    | Pause the vCluster, preserving state. |
| `uv run invoke start`   | (After `stop`) resume by re-running start. |
| `uv run invoke destroy` | Delete the vCluster and all associated data. |
| `uv run invoke reset`   | `destroy` then `start` from scratch. |

`stop` is useful when you want to free up resources without losing your
deployments; `destroy` is the right answer when something is wedged and
you'd rather start clean.

### Troubleshooting

**Port 8080 already in use.** Stop whatever else is listening on it; the
demo always uses `8080` because `80` is privileged.

**`docker image inspect styrmin:latest` returns nothing.** Run
`uv run invoke build` first, or pass `--build-image` to `start`.

**Bootstrap step says "Cluster already exists".** That means a previous
demo run left state behind. `uv run invoke reset` is the simplest way to
start over; alternatively `uv run invoke destroy` and then `start`.

### Next steps

- [**Platform Overview**](../introduction/platform-overview.md) — get the conceptual picture if
  you skipped it.
- [**What is an Application Driver?**](../concepts-and-architecture/what-is-a-driver.md) —
  understand the unit of deployment in Styrmin.
- [**Creating a Driver**](../drivers/creating-a-driver.md) — write your
  own driver and load it into the demo.
