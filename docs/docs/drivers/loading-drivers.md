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
| **Git repository** | The driver lives in a git repo — public or private — at its root or in a driver directory, and you want Styrmin to fetch it directly. Each load creates a new version pinned to the requested branch's tip. |

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

A load from git takes the repository URL, the branch and, optionally, the
driver directory: the folder of the repository that holds the driver's
`driver.styrmin.yml`, `values.j2.yml` and `actions.py`, given as a path
relative to the repository root. Without a driver directory, Styrmin
reads the driver from the repository root:

```shell
uv run styrminctl drivers load-version \
  https://github.com/your-org/styrmin-drivers.git \
  main
```

Styrmin clones the whole repository, records the commit at the tip of the
branch, and reads `driver.styrmin.yml` from the driver directory, or from
the repository root when no driver directory is given. A load fails when
that folder holds no `driver.styrmin.yml`.

The CLI calls the `loadRemoteApplicationDriverVersion` GraphQL mutation
with the `repositoryUrl`, `branch` and `driverDirectory` arguments. The
mutation needs the `ADMIN` role.

#### Loading a driver from a driver directory

A repository can hold several drivers, each in its own driver directory,
for example `drivers/infrahub/` and `drivers/semaphore/`. To load one of
them, give its driver directory:

```shell
uv run styrminctl drivers load-version \
  https://github.com/your-org/styrmin-drivers.git \
  main \
  --driver-directory drivers/infrahub
```

The command prints `Driver directory: drivers/infrahub` after the commit
SHA. See [`drivers load-version`](../reference/styrminctl.md#drivers-load-version--load-a-driver-version-from-git)
for the full output.

From the Python SDK, pass `driver_directory` to `drivers.load_version`:

```python
from styrmin_sdk import StyrminClient

async with StyrminClient(server_address="https://styrmin.example") as client:
    version = await client.drivers.load_version(
        "https://github.com/your-org/styrmin-drivers.git",
        "main",
        driver_directory="drivers/infrahub",
    )
    print(version.source_path)  # drivers/infrahub
```

A refused or failed load raises `OperationFailedError` with the server's
message.

From the GraphQL API, pass the `driverDirectory` argument:

```graphql
mutation {
  loadRemoteApplicationDriverVersion(
    repositoryUrl: "https://github.com/your-org/styrmin-drivers.git"
    branch: "main"
    driverDirectory: "drivers/infrahub"
  ) {
    id
    sourceCommitSha
    sourcePath
  }
}
```

In the UI, open the Drivers page, select "Load driver", and on the
"Git repository" tab fill in "Repository URL", "Branch" and
"Driver directory". Leave "Driver directory" empty to load from the
repository root. When the server refuses the load, the drawer shows the
server's message and keeps the values you entered.

The application driver version stores the driver directory in its
`sourcePath` field. The Overview tab of the driver version shows it in a
"Driver directory" row after the "Source" row, and the Source cell of the
drivers list shows it after the repository and branch, as
`<repository> @ <branch> · drivers/infrahub`. A driver version loaded
from the repository root has no `sourcePath`, no "Driver directory" row
and no driver directory in its Source cell.

Styrmin stores every way of writing the same folder in one form, so a
reload at the same commit returns the existing driver version:
`./drivers/infrahub/`, `drivers//infrahub` and `drivers/./infrahub` are
stored as `drivers/infrahub`. An empty value, `.` and `./` load from the
repository root, the same as a load without a driver directory.

#### Refused driver directories and error messages

Styrmin refuses these values before it clones the repository:

- an absolute path, such as `/etc`;
- a path with a `..` segment, such as `../other` or `drivers/../../etc`;
- a path with a backslash, such as `drivers\infrahub`;
- a value with a NUL character.

The error message names the value and the rule, for example:

```text
Driver directory '../other' is refused: it contains a '..' segment. Give a path relative to the repository root, such as 'drivers/infrahub'.
```

After the clone, Styrmin refuses the load, and reads no file, when the
driver directory, or its `driver.styrmin.yml`, `values.j2.yml` or
`actions.py`, is a symlink to a path outside the repository. This check
also applies to loads from the repository root. A symlink to a path
inside the repository is accepted. The message names the part of the path
that is a symlink leading outside the repository.

When the driver directory does not exist, is not a folder, or holds no
`driver.styrmin.yml`, the message names the driver directory, the
repository, the branch and the commit, for example:

```text
Driver directory 'drivers/missing' does not exist in repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567).
No driver.styrmin.yml in driver directory 'drivers/infrahub' of repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567).
```

Messages show the repository URL without a username or token.

#### Actions run from the driver directory

Each action of a driver version loaded from a driver directory runs with
the driver directory as its working directory: the action's Job clones
the repository at the recorded commit, then changes to the driver
directory.
`actions.py` can import modules from the driver directory, such as a
`helpers.py` next to it with `import helpers`, but not modules from other
folders of the repository. Packages installed in the action's image, such
as `prefect` and `styrmin_backend`, import as before. Put code that
several drivers share into each driver directory, or install it in the
image that the actions run in.

Actions of a driver version loaded from the repository root run from the
repository root, as before.

#### A new commit to the repository creates a new driver version

The provenance fingerprint of a git driver version is the commit SHA, and
a commit covers the whole repository, not only the driver directory. A
reload after any new commit to the branch
creates a new application driver version, even when the commit changed no
file in the driver directory. Deployments keep the driver version they are
bound to until they are upgraded. An upgrade resolves the driver version
again with the latest-wins rule, so it can bind a deployment to the new
driver version (see
[Selecting a driver version](#selecting-a-driver-version-when-deploying-or-upgrading)).

Two driver directories of one repository, loaded at the same commit, give
two driver versions, also when their drivers have the same name. The
version picker labels both `<version>@<short commit>`; the "Driver
directory" row of the Overview tab tells them apart. Each driver version
runs the actions of its own driver directory.

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

The **Drivers** view offers two layouts, switched from the toolbar:

- **Group by application** — one card per application driver, showing its
  three newest **application driver versions**. Drivers with a longer
  history close with a row reading `N older versions`, which opens the
  driver's detail page where the full history lives. A driver with three
  or fewer loaded versions shows all of them and no such row. Filtering
  suspends the cap: while a filter is active every matching version is
  listed, so a search can never hide its own matches.
- **Flat list** — one row per loaded version across all drivers, newest
  first and uncapped.

On a driver's detail page, the version selector carries a search field,
so a driver with a long history stays reachable without scrolling. The
count beside it states how many versions are loaded in total.

Every driver-version label in the UI, CLI, and SDK is rendered as
`<version>@<short>`, where `<short>` is the first 7 hex chars of the
**provenance fingerprint** — the content hash for local drivers, the
resolved git commit SHA for git drivers. Detail surfaces show the full
64-char content hash (or 40-char SHA) next to a copy-to-clipboard
control. The corresponding GraphQL fields on `ApplicationDriverVersion`
are `contentHash` (populated for `sourceType == "local"`) and
`sourceCommitSha` (populated for `sourceType == "git"`); exactly one is
non-null per row.

### Warnings about spec.info values

A driver loads even when its `spec.info.icon` or a `spec.info.links`
entry is invalid. The load leaves that value out of the driver version
and returns one warning for it, which names the field and says why, for
example:

```text
Warning: spec.info.icon must be an absolute https URL, such as https://example.com/logo.svg (found 'xxxx'). The icon was not stored.
```

`drivers load-version` and `drivers load-local-version` print the
warnings after the success line, the Load driver drawer shows them in a
notification that stays until you close it, and the GraphQL load
mutations return them in `loadWarnings`. Styrmin does not store the
warnings: loading the same file again returns them again. To stop a
warning, fix or remove the value in `driver.styrmin.yml` and load the
driver again. See [Creating a driver](./creating-a-driver.md) for the
accepted values.

A load that fails for another reason lists one line per invalid field,
for example `- spec.version: Field required`.

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
the requested branch — loading the same repository, branch, commit and
driver directory twice is a no-op; loading after a new commit lands
creates a new row.

The recorded commit is also the code a deployment's actions run. Pushing
new commits to the driver's branch does not change what a deployment
executes: its actions keep running the commit shown in `sourceCommitSha`
until you load the new commit and upgrade the deployment onto it. Driver
versions loaded by an earlier Styrmin release keep following the branch tip
until a new commit is loaded.

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
(`generic-app`, `infrahub`, `infrahub-mcp`, `semaphore`, `slurpit`). They're a good
starting point for writing your own.

The `infrahub` example declares two services: `infrahub` (the Infrahub
API and web UI on port 8000) and `task-manager` (the Prefect UI on port
4200, with the Prefect API under `/api`). Both get a service-discovery
Service in the deployment's namespace, so other applications in the
environment reach them by short DNS name (`infrahub`, `task-manager`).
Both are also exposed through the per-environment ingress: the driver's
`values.j2.yml` enables each chart's own Ingress and sets its host to
the computed FQDNs from the template context — the Infrahub server on
`{{ services.infrahub.primary_fqdn }}`, with
`{{ services.infrahub.human_readable_fqdn }}` as an extra host (the
chart's `extraHosts` entries take a `hostname` key), and the Prefect UI on
`{{ services['task-manager'].human_readable_fqdn }}` (the
service-scoped name, since `primary_fqdn` is app-scoped and identical
for every service of a deployment). The `infrahub-enterprise` example
declares the same `task-manager` service and Prefect UI ingress, since it
runs the identical `prefect-server` subchart.

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
  commit per branch load. One repository can hold several drivers, each
  in its own driver directory (see
  [Loading a driver from a driver directory](#loading-a-driver-from-a-driver-directory)).
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
