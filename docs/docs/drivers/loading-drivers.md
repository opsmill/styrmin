---
title: Loading a Driver
sidebar_position: 2
description: Load an Application Driver into Styrmin from a local directory or a git repository (public or private).
---

## Loading a Driver

Before you can deploy an application, Styrmin needs to register an
**Application Driver Version** for it. A driver on disk is inert — loading
it parses the spec, validates the chart reference, and inserts a row in
the database that deployments can pin to.

There are two ways to load a driver:

| Source | Use it when… |
|--------|--------------|
| **Local directory** | The driver is mounted into the Styrmin server container (the bundled examples, drivers you're iterating on locally, or anything you ship in your own image). |
| **Git repository** | The driver lives in a git repo — public or private — and you want Styrmin to fetch it directly. Each load creates a new version pinned to the requested branch's tip. |

Both paths produce the same end result: a new Application Driver Version
in the database that a Deployment can reference.

### From a local directory

The Styrmin server reads the driver from a path **inside its own
container**, not from your laptop. The bundled examples are baked into the
official image at `/styrmin/drivers/<name>`, so the most common command is
just:

```shell
uv run styrminctl drivers load-local-version /styrmin/drivers/infrahub
uv run styrminctl drivers load-local-version /styrmin/drivers/semaphore
```

To load a driver you've authored, mount the directory into the server
container at a stable path and point `load-local-version` at it. The
local-demo Helm values mount everything under `driver/examples/` at
`/styrmin/drivers/`; production installs typically either bake drivers
into a custom image or mount a PVC.

Under the hood this calls the `loadLocalApplicationDriverVersion` GraphQL
mutation with the in-container path.

### From a git repository

```shell
uv run styrminctl drivers load-version \
  https://github.com/your-org/styrmin-drivers.git \
  main
```

The repository must contain a `driver.styrmin.yml` at its root. Each load
creates a new Application Driver Version pinned to the commit at the tip
of the requested branch — re-running the command after pushing to the
branch produces a new version, so older deployments keep working until you
deliberately upgrade them.

Under the hood this calls the `loadApplicationDriverVersionFromGithub`
GraphQL mutation with the repository URL and branch.

#### Private repositories

For private GitHub repositories, the Styrmin server needs a token with
read access. Configure it once when installing Styrmin, alongside the
agent-source repository it pulls from to bootstrap the agent:

```shell
# Token used to clone driver repositories
STYRMIN_DRIVER_TOKEN=<github-token>

# Token + branch + URL used to fetch the agent source code
STYRMIN_AGENT_SOURCE_TOKEN=<github-token>
STYRMIN_AGENT_SOURCE_BRANCH=develop
STYRMIN_AGENT_SOURCE_REPOSITORY=https://github.com/your-org/styrmin.git
```

In the bundled Helm chart, `STYRMIN_DRIVER_TOKEN` and
`STYRMIN_AGENT_SOURCE_TOKEN` are read from Kubernetes Secrets that the
deployment templates already mount; the easiest path is to create the
Secret in the `styrmin` namespace before `helm upgrade --install`. The
`STYRMIN_AGENT_SOURCE_*` settings live in a ConfigMap and are typically
set through Helm values (`styrmin.agentSource.repository` /
`styrmin.agentSource.branch`).

Once those are in place, `uv run styrminctl drivers load-version` works
against the private repo with no extra flags on the client side — the
token is held by the server.

### After loading

Browse the loaded drivers from the **Drivers** view in the UI, or query
the `applicationDrivers` field through the GraphQL API. Versions are
immutable once loaded — to "update" a driver, load a new version and
upgrade the deployments that pin the old one.

### Where to put your own drivers

The reference repository ships several example drivers under
[`driver/examples/`](https://github.com/opsmill/styrmin/tree/develop/driver/examples)
(`infrahub`, `semaphore`, `slurpit`). They're a good starting point
for writing your own.

For your own drivers, the typical layouts are:

- **Inside the Styrmin repo** — drop them under `driver/examples/<name>/`
  and they'll be picked up by the demo image automatically. Best for
  prototyping against the local demo.
- **In a dedicated git repository** — recommended for production use.
  Versioned, reviewable, and Styrmin can pin deployments to a specific
  commit per branch load.
- **In your own container image** — fork or extend the Styrmin server
  image, copy your driver directories into `/styrmin/drivers/`, and use
  `load-local-version` against the baked-in paths.

See [Creating a Driver](./creating-a-driver.md) for the authoring
walkthrough, and the
[Driver overview in the main repository](https://github.com/opsmill/styrmin/blob/develop/driver/DRIVERS.md)
for the authoritative, version-controlled description of the driver
format.

### Next steps

- [**The Context**](./context.md) — what your driver templates and
  actions receive at runtime.
- [**Creating a Driver**](./creating-a-driver.md) — write your own
  driver from scratch.
