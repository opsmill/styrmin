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

Every driver-version label in the UI, CLI, and SDK is rendered as
`<version>@<short>`, where `<short>` is the first 7 hex chars of the
**provenance fingerprint** — the content hash for local drivers, the
resolved git commit SHA for git drivers. Detail surfaces show the full
64-char content hash (or 40-char SHA) next to a copy-to-clipboard
control. The corresponding GraphQL fields on `ApplicationDriverVersion`
are `contentHash` (populated for `sourceType == "local"`) and
`sourceCommitSha` (populated for `sourceType == "git"`); exactly one is
non-null per row.

### Reloading a local driver while you iterate

You do **not** need to bump `spec.version` in `driver.styrmin.yml` to
record a change. Re-running `drivers load-local-version` against the
same path:

- creates a new Application Driver Version row when the bytes of
  `driver.styrmin.yml`, the values template, or `actions.py` have
  changed (the three files that feed the content hash);
- is a no-op when those three files are byte-identical to the existing
  row — any number of repeated loads produces a single row.

Edits to other files in the driver directory (`README.md`, examples,
screenshots) are invisible to the fingerprint and never produce a new
row.

For git-sourced drivers, the fingerprint is the resolved commit SHA on
the requested branch — loading the same `repo@branch@commit` twice is a
no-op; loading after a new commit lands creates a new row.

See [`dev/guides/driver-iteration.md`](https://github.com/opsmill/styrmin/blob/develop/dev/guides/driver-iteration.md)
for the full iteration-loop reference.

### Selecting a driver version when deploying or upgrading

Several loaded driver versions can support the same application version
(their `supported_versions` specifiers overlap) — for example after
loading a bugfixed build of a driver whose range did not change. Styrmin
resolves which one a deployment binds to with a deterministic
**latest-wins** rule:

1. the driver version with the highest *parseable* `spec.version` wins
   (compared as versions, so `"10"` beats `"9"`); unparseable version
   strings rank below all parseable ones;
2. ties — including same-`version` rebuilds with different fingerprints —
   are broken by load time, most recent first;
3. any remaining tie falls back to the row id, so the order is total.

The rule applies on **initial deploy** and on **every upgrade**. An
upgrade always re-resolves the binding, so re-running an upgrade at the
deployment's *current* application version is the canonical way to move
it onto a newly loaded driver build:

```shell
# load the fresh build, then re-apply the same application version
uv run styrminctl drivers load-version https://github.com/your-org/styrmin-drivers.git main
uv run styrminctl deployments update-version <deployment-id> 1.6.0
```

To bypass latest-wins and pin a specific build, pass its driver-version
UUID (shown as `Driver version ID` in `deployments get`, or via the
`applicationDriver.versions` GraphQL field):

```shell
uv run styrminctl deployments update-version <deployment-id> 1.6.0 \
  --driver-version-id <uuid>

uv run styrminctl deployments create infrahub 1.6.0 my-env \
  --driver-version-id <uuid>
```

The pinned version must belong to the deployment's driver and its
`supported_versions` must cover the requested application version —
cross-driver moves are rejected. The UI's **Upgrade** dialog exposes the
same choice through a driver-version picker that defaults to
**Latest (auto)**. The pin applies to that call only: a later upgrade
without an explicit pin re-resolves to the latest matching build again.

### Where to put your own drivers

The reference repository ships several example drivers under
[`driver/examples/`](https://github.com/opsmill/styrmin/tree/develop/driver/examples)
(`infrahub`, `infrahub-mcp`, `semaphore`, `slurpit`). They're a good
starting point for writing your own.

The `infrahub` example declares two services: `infrahub` (the Infrahub
API and web UI on port 8000) and `task-manager` (the Prefect UI on port
4200, with the Prefect API under `/api`). Both get a service-discovery
Service in the deployment's namespace, so other applications in the
environment reach them by short DNS name (`infrahub`, `task-manager`).
Both are also exposed through the per-environment ingress: the driver's
`values.j2.yml` enables each chart's own Ingress and sets its host to
the computed FQDNs from the template context — the Infrahub server on
`{{ services.infrahub.primary_fqdn }}` and the Prefect UI on
`{{ services['task-manager'].human_readable_fqdn }}` (the
service-scoped name, since `primary_fqdn` is app-scoped and identical
for every service of a deployment).

Because the Prefect UI is a single-page app whose browser-side code
calls the Prefect API directly (at `PREFECT_UI_API_URL`, defaulting to
`http://localhost:4200/api`), the driver also sets the subchart's
`server.uiConfig.prefectUiApiUrl` to the externally reachable API URL —
built in the template from the same `human_readable_fqdn` plus
`instance.config.external_url_scheme` / `external_url_port`, mirroring
how Styrmin computes user-facing service URLs. Without it, the UI loads
but reports "Can't connect to Server API at `http://localhost:4200/api`".

The `infrahub-mcp` example exposes an existing Infrahub instance to AI
agents over the Model Context Protocol in token-passthrough auth mode.
Its `infrahub_address` parameter is accepted as a free-form string and
is **not** URL-validated — connection failures surface at agent-query
time, not at deploy time.

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
