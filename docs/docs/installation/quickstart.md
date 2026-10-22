---
title: Quickstart
sidebar_position: 3
description: Start the Styrmin demo on a local vCluster with two commands.
---

## Quickstart

The Styrmin repository includes a demo that runs on your machine. One
command creates a local [vCluster](https://www.vcluster.com/), installs
Styrmin, Traefik, Garage, and the bundled drivers, and prints the URL to
log in.

### Prerequisites

You need the following on your `PATH`:

- **Docker** (the demo runs vCluster with its `docker` driver)
- **`kubectl`**
- **`helm`** ≥ 3.x
- **`vcluster`** CLI ([install instructions](https://www.vcluster.com/docs/getting-started/setup))
- **`uv`** ([install instructions](https://docs.astral.sh/uv/getting-started/installation/))

TCP port `8080` must be free on your host: the demo port-forwards
Traefik to it.

> The demo uses the `*.local.styrmin.io` wildcard zone, which resolves
> to `127.0.0.1`, so `http://styrmin.local.styrmin.io:8080` opens the
> demo without changes to `/etc/hosts`.

### 1. Clone the repository

```bash
git clone https://github.com/opsmill/styrmin.git
cd styrmin
```

### 2. Install Python dependencies

The demo runs as [Invoke](https://www.pyinvoke.org/) tasks in the
repository. Install them with `uv`:

```bash
uv sync
```

This installs the root project, the workspace members (backend, SDK,
CLI), and the `dev` dependency group, which includes `invoke`.

### 3. Build the demo image

```bash
uv run invoke build
```

This task:

1. Builds the `styrmin:latest` container image, which the server and
   the agent both run.
2. Resolves the Helm dependencies under `helm/agent/`.
3. Resolves the Helm dependencies under `helm/styrmin/`.

Run `build` again only when you change the server or agent code, their
`Dockerfile`s, or their Helm chart dependencies.

### 4. Start the demo cluster

```bash
uv run invoke start
```

`start` runs these steps in order:

1. Creates a vCluster named `styrmin-demo` in Docker.
2. Connects to it and exports a kubeconfig under `.vcluster/`.
3. Installs the [Traefik](https://traefik.io/) ingress controller and
   [Garage](https://garagehq.deuxfleurs.fr/), the S3-compatible object
   store in the cluster that Velero writes backups to.
4. Installs Styrmin into the cluster with `helm upgrade --install`, using
   the values file at
   [`dev/local/demo-values.yaml`](https://github.com/opsmill/styrmin/blob/develop/dev/local/demo-values.yaml).
5. Port-forwards Traefik to `localhost:8080`.
6. Calls the GraphQL API to create the first records:
   - a **cluster** named `local`
   - an **environment** named `local` in that cluster
   - a **backup storage location** for the Garage store, assigned to
     the environment
   - the bundled **application driver versions**
     ([`driver/examples/infrahub`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/infrahub)
     and
     [`driver/examples/semaphore`](https://github.com/opsmill/styrmin/tree/develop/driver/examples/semaphore))
7. Prints a green summary panel with the URLs and the admin credentials.

> If the `styrmin:latest` image exists, `start` uses it. To build it
> again, pass `--build-image`:
>
> ```bash
> uv run invoke start --build-image
> ```

When the command finishes, it prints a summary like this:

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

### 5. Log in

Open [http://styrmin.local.styrmin.io:8080](http://styrmin.local.styrmin.io:8080) and log in with `admin` /
`styrmin`. These credentials come from `dev/local/demo-values.yaml`;
change them there to use other credentials.

The UI shows:

- one **cluster** (`local`), with the agent running and reporting status
- one **environment** (`local`) in that cluster
- two **application drivers** (`infrahub` and `semaphore`), each with
  at least one driver version loaded
- no deployments. Create one from the UI, and the agent creates its
  Kubernetes resources.

To use the GraphQL API directly, open
[http://styrmin.local.styrmin.io:8080/graphql](http://styrmin.local.styrmin.io:8080/graphql).

### 6. Pause, resume, or delete the demo

| Command | What it does |
|---------|--------------|
| `uv run invoke start`   | Creates and configures everything. Running it again is safe. |
| `uv run invoke stop`    | Pauses the vCluster and keeps its state. |
| `uv run invoke start`   | After `stop`, resumes the vCluster. |
| `uv run invoke destroy` | Deletes the vCluster and all its data. |
| `uv run invoke reset`   | Runs `destroy`, then `start`. |

Use `stop` to free resources on your machine and keep your deployments.
Use `destroy` when the demo does not respond and you want to start again
with no data.

### Troubleshooting

**Port 8080 is already in use.** Stop the process that listens on it.
The demo always uses `8080`, because port `80` is a privileged port.

**`docker image inspect styrmin:latest` returns nothing.** Run
`uv run invoke build` first, or pass `--build-image` to `start`.

**The bootstrap step says "Cluster already exists".** A previous demo
run created the cluster record. Run `uv run invoke reset` to start over,
or run `uv run invoke destroy` and then `uv run invoke start`.

### Next steps

- [**Platform overview**](../introduction/platform-overview.md): the
  components and terms of Styrmin.
- [**What is an application driver?**](../concepts-and-architecture/what-is-a-driver.md):
  the specification that Styrmin uses to deploy each application.
- [**Create a driver**](../drivers/creating-a-driver.md): write your own
  driver and load it into the demo.
