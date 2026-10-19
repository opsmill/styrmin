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
| **Local directory** | The driver is at a path in the Styrmin server container, and in the agent pod when it declares actions (the bundled examples, drivers you're iterating on locally, or anything you ship in your own image). |
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

To load a driver you wrote, put it at a stable path in the server
container and give that path to `load-local-version`. When the driver
declares actions, the Styrmin agent must hold the driver at the same path
(see
[Actions of a driver loaded from a local directory](#actions-of-a-driver-loaded-from-a-local-directory)).
The Styrmin Helm charts have no value that mounts a volume of drivers
into the server or the agent. In a Helm install, build an image `FROM`
the Styrmin image with your drivers copied into `/styrmin/drivers/`, and
run the server and the agent with it. The local demo
builds the Styrmin image from the working tree, so it holds everything
under `driver/examples/` at `/styrmin/drivers/`. The `docker compose`
dev stack mounts `driver/examples/` at `/styrmin/drivers/` into the
server container and the agent container.

Under the hood this calls the `loadLocalApplicationDriverVersion` GraphQL
mutation with the in-container path.

#### Actions of a driver loaded from a local directory

When a driver that declares actions is loaded from a local directory,
Styrmin registers one Prefect flow for each action, as it does for a
driver loaded from git. Each action runs the `actions.py` at the path you
gave to `load-local-version`, with that path as its working directory, so
`actions.py` can import modules next to it, such as a `helpers.py`.

The Styrmin agent runs each action as a process in the agent pod, and
reads the driver from the same path as the server. The agent pod must
therefore hold the driver files at that path, in the agent's image or on
a volume mounted at that path. In a standard install, the server and the
agent run the same Styrmin image, which holds the bundled drivers at
`/styrmin/drivers/<name>`, so the bundled drivers need no other setup. A
driver that only the server container holds is not in the agent pod, and
its actions fail with the
[error for missing driver files](#the-driver-files-are-not-at-the-path).

If the agent runs an image of your own, build it `FROM` the Styrmin image
of the server's release and copy the driver to the same path as on the
server. The image then holds the driver and the `styrmin_backend` package
that checks the driver files before each action runs.

An action's `image:` field has no effect today, for a driver loaded from
a local directory or from git: the agent runs every action as a process
in its own pod, not in a container of that image. A follow-up issue
records this.

When the driver declares actions, Styrmin refuses a path that contains
`{` or `}`. Prefect fills in `{{ ... }}` templates in the path before the
action checks the driver files, so such a path could write a value of the
action's environment, such as the action's API token, into the error of
the check. A driver without actions loads from such a path. The refusal
reads:

```text
Driver path '/srv/drivers/{{ name }}' is refused: it contains '{' or '}', and the driver declares actions. Prefect fills in '{{ ... }}' templates in the path before the action checks the driver files. Load the driver from a path without '{' or '}'.
```

#### Check of the driver files before an action runs

Before an action of a driver loaded from a local directory runs, Styrmin
checks the files at the path in the agent pod:

1. The path is a folder that holds `driver.styrmin.yml` and `actions.py`.
2. The provenance fingerprint of `driver.styrmin.yml`, the values template
   and `actions.py` at the path equals the provenance fingerprint that the
   driver version was loaded with.

When the check fails, the action does not import or run `actions.py`, and
the hook step and the task fail with one of the errors below. A change to
any of the three files, also to the values template only, makes the check
fail for every driver version loaded from the path before the change.

#### Errors when an action of a driver version cannot run

Each error appears on the failed hook step, such as "Run the setup
pre-hook", on the deployment page and in `styrminctl tasks get` (see
[Steps of a hook](../concepts-and-architecture/hooks-and-actions.md#steps-of-a-hook)).
The two errors of the check appear inside an error that starts with
`RuntimeError: Deployment flow run <id> crashed:` and ends with Prefect's
state message in parentheses. The logs of the action's flow run in
Prefect show the same error.

The two errors of the check name an image after the path:

- `the image <name>`: the action's `image:` when it sets one, otherwise
  the default image of the work pool `user-work-pool`. In a standard
  install, that default is the Styrmin image of the server's release,
  which the agent also runs.
- `the default image of the work pool user-work-pool`, or
  `the image of this action's Job`: the check could not read the image
  from Prefect.

In every case, the action ran in the agent pod and not in a container of
the named image. To fix the error, change the files at the path in the
agent pod, or load the driver again, as described for each error.

##### The driver files are not at the path

```text
The driver files are not at /srv/drivers/my-app in the image registry.opsmill.io/opsmill/styrmin:latest: /srv/drivers/my-app not found. An action's image must hold the driver at the same path as the Styrmin server. Add the driver to the image at /srv/drivers/my-app, or load the driver from a path that the image holds.
```

The path, `driver.styrmin.yml` or `actions.py` is not in the agent pod.
The error names the missing path or files. To fix it, do one of the
following:

- Put the driver at the path in the agent pod: rebuild the image that the
  agent runs with the driver at that path, or mount a volume at that path
  into the agent pod.
- Load the driver from a path that the agent pod holds, and use the new
  driver version.

##### The driver files at the path are not the files of the driver version

```text
The driver files at /styrmin/drivers/my-app in the image registry.opsmill.io/opsmill/styrmin:latest are not the files of this driver version: their provenance fingerprint is e9f0a1b, and the driver version was loaded with a1b2c3d. The files changed after the driver was loaded. Rebuild the image with the files you loaded and load the driver again, or load the driver again from /styrmin/drivers/my-app and use the new driver version.
```

The files at the path in the agent pod changed after the driver version
was loaded. This happens when:

- someone edited `driver.styrmin.yml`, the values template or `actions.py`
  at the path;
- a Styrmin upgrade installed an image with a newer bundled driver at the
  same path;
- the image that the agent runs was built before an edit of the files that
  the server loaded.

To fix it, do one of the following:

- To use the files that are now at the path, load the driver again from
  the path. The load creates a new driver version. Create or upgrade the
  deployment with it; pass `--driver-version-id` to pin it (see
  [Selecting a driver version](#selecting-a-driver-version-when-deploying-or-upgrading)).
- To use the driver version you loaded, rebuild the image that the agent
  runs with the files you loaded, and load the driver again.

After a Styrmin upgrade that ships a newer bundled driver, load the
bundled drivers again. A create or an upgrade that uses a driver version
loaded before the Styrmin upgrade fails with this error when one of that
version's actions runs.

##### A declared action has no registered flow

```text
Driver version my-app 1.0.0@a1b2c3d declares the action upgrade for the upgrade hook, mode core, but no flow is registered for it, so the hook cannot run. Load the driver again to register its actions: styrminctl drivers load-local-version /styrmin/drivers/my-app. Then request the change again; a deployment whose creation failed must be deleted and created again. If the driver's files or commit changed since it was loaded, the load creates a new driver version; use that version instead.
```

This error applies to driver versions loaded from git and from a local
directory. The driver version declares an action, and Prefect holds no
flow for it, for example because the driver version was loaded by a
Styrmin release that did not register the actions of local drivers, or
because its Prefect deployments were deleted. The hook step fails; the
hook is never skipped. The message gives the command that loads the
driver again: `load-local-version` with the path, or `load-version` with
the repository, the branch and the driver directory.

An upgrade request finds this error before it changes the deployment. It
returns a failed task whose "Run the upgrade hook" step holds the error,
and the deployment keeps its application version and driver version.
`styrminctl deployments update-version` and `styrminctl deployments apply`
print the task id and the error and exit with code 1:

```text
failed my-app: task <task-id> failed: Driver version my-app 1.0.0@a1b2c3d declares the action upgrade for the upgrade hook, mode core, but no flow is registered for it, ...
```

`apply --wait` reports the failure at once and does not wait for the
deployment. In the SDK, `client.deployments.apply` returns an outcome
with `action="failed"`, the task id as `task_id` and the same reason as
`failure_reason`. `client.deployments.update_version` returns the failed
task, with the error as its `message`, and does not raise.

To fix it:

1. Run the command in the message. The load registers the missing actions.
   When the driver's files or commit changed since the driver version was
   loaded, the load creates a new driver version instead; use that version.
2. Request the change again. For an upgrade, send the same request. For a
   create that failed, delete the deployment and create it again.

#### Loading a driver again registers its missing actions

Each load of a driver that declares actions, from git or from a local
directory, registers the actions whose hook and mode have no registered
flow, also when the load returns an existing driver version. Styrmin
decides that a flow is missing with the same lookup that hooks use, so it
leaves the flows that hooks already find as they are. A load with nothing
to register makes no change in Prefect.

#### When an action's check fails during an upgrade

The upgrade writes the new application version to the deployment's
`StyrminDeployment` before it runs the upgrade actions, so the cluster can
roll out the new application version although the upgrade action did not
run. The task fails, and the new version stays the deployment's active
version, as after any failed upgrade. Then:

- a second request for the same application version and the same driver
  version starts no task;
- a request for the same application version with another driver version,
  such as the one you get when you load the driver again, runs as an
  update: Styrmin applies the new driver version and runs no upgrade
  action.

Styrmin cannot run the upgrade action of that application version again;
only a change to another application version runs an upgrade action. A
follow-up issue records this. To avoid the case, load the target driver
version right before you request an upgrade, so its files at the path are
the files the check expects.

#### Logs of a crashed action are shown on its hook step

When the flow run of an action crashes, for example because the check of
the driver files failed, the error of its hook step holds the first log
line of level `ERROR` of that flow run, cut to 4,000 characters. Every
signed-in user who can read the task can read this error, so actions must
not write secrets to their logs.

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
    print(version.driver_directory)  # drivers/infrahub
```

A refused or failed load raises `OperationFailedError` with the server's
message. A load with a driver directory needs a Styrmin server that
accepts the `driverDirectory` argument; an older server makes the SDK
raise `IncompatibleServerError`, and `styrminctl` prints it as an error.
A load without a driver directory works against older servers too.

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
    driverDirectory
  }
}
```

In the UI, open the Drivers page, select "Load driver", and on the
"Git repository" tab fill in "Repository URL", "Branch" and
"Driver directory (optional)". Leave the driver directory empty to load
from the repository root. While the server clones the repository, the
button reads "Cloning repository…". When the server refuses the load, the
drawer keeps the values you entered and shows the server's message: under
the "Driver directory" field when the message is about the driver
directory, and at the top of the drawer otherwise. The drawer refuses the
web address of a folder or a file, such as
`https://github.com/your-org/styrmin-drivers/tree/main/drivers/infrahub`
or a GitLab `/-/tree/` link, before it calls the server, and names the
repository URL to enter instead; enter the folder as the driver
directory.

The `driverDirectory` field of the application driver version returns
the driver directory, or null for a load from the repository root and for
a local driver version. The `sourcePath` field holds the same value for a
git driver version, but holds the folder on the server for a local one.
The Overview tab of the driver version shows the driver directory in a
"Driver directory" row after the "Source" row, and the Source cell of the
drivers list shows it after the repository and branch, as
`<repository> @ <branch> · drivers/infrahub`. A driver version loaded
from the repository root has no "Driver directory" row and no driver
directory in its Source cell.

Styrmin stores every way of writing the same folder in one form, so a
reload at the same commit returns the existing driver version:
`./drivers/infrahub/`, `drivers//infrahub` and `drivers/./infrahub` are
stored as `drivers/infrahub`. An empty value, `.` and `./` load from the
repository root, the same as a load without a driver directory.

#### Refused driver directories and error messages

Styrmin refuses these values before it clones the repository:

- an absolute path, such as `/etc` or `/drivers/infrahub`;
- a path with a `..` segment, such as `../other` or `drivers/../../etc`;
- a path with a backslash, such as `drivers\infrahub`;
- a path with `{` or `}`, such as `drivers/{{ name }}`, because the
  Prefect step that sets the working directory of the actions fills in
  `{{ ... }}` templates;
- a value with a control character, such as a NUL character, a tab or a
  line break;
- a path longer than 255 characters once it is stored.

The error message names the value as you entered it, with control
characters written as escapes such as `\x00`, and the rule, for example:

```text
Driver directory '../other' is refused: it contains a '..' segment. Give a path relative to the repository root, such as 'drivers/infrahub'.
```

After the clone, and before it reads any file, Styrmin refuses the load
when:

- the driver directory is a symlink, or is inside a symlink, to a path
  outside the repository. The message names the part of the path that is
  the symlink;
- the driver directory's `driver.styrmin.yml`, `values.j2.yml` or
  `actions.py` is a symlink to a path outside the driver directory, also
  when that path is another folder of the repository. For a load from the
  repository root, the driver directory is the whole repository;
- the driver directory or one of these files cannot be followed, such as
  a symlink loop. The message names the path in the repository and the
  reason, such as `Too many levels of symbolic links`.

A symlink to a path inside the driver directory is accepted. These checks
also apply to loads from the repository root, for example:

```text
'values.j2.yml' in repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567) is a symlink to a path outside the repository.
'drivers/infrahub/actions.py' in repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567) is a symlink to a path outside driver directory 'drivers/infrahub'.
```

When the driver directory does not exist, is not a folder, or holds no
`driver.styrmin.yml`, the message names the driver directory, the
repository, the branch and the commit, for example:

```text
Driver directory 'drivers/missing' does not exist in repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567).
No driver.styrmin.yml in driver directory 'drivers/infrahub' of repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567).
```

Messages show every URL without the user info that follows `scheme://`,
such as `user:token@`. An address without a scheme, such as
`git@github.com:your-org/styrmin-drivers.git`, keeps its `git@`.

#### Actions run from the driver directory

Each action of a driver version loaded from a driver directory runs with
the driver directory as its working directory: the action clones the
repository at the recorded commit into a temporary folder in the agent
pod, then changes to the driver directory.
`actions.py` can import modules from the driver directory, such as a
`helpers.py` next to it with `import helpers`, but not modules from other
folders of the repository. Packages installed in the agent's image, such
as `prefect` and `styrmin_backend`, import as before. Put code that
several drivers share into each driver directory, or install it in the
image that the agent runs.

The load does not import `actions.py`, so an import that fails, such as
`import shared` for a module outside the driver directory, shows only when
an action runs: the step of the hook that runs the action fails with the
action's error, on the deployment page and in `styrminctl tasks get` (see
[Steps of a hook](../concepts-and-architecture/hooks-and-actions.md#steps-of-a-hook)),
and the logs of the action's flow run in Prefect show the import error.

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
two driver versions, also when their drivers have the same name. Each
driver version runs the actions of its own driver directory. The deploy
form, the Upgrade dialog and the version picker of the driver page label
each one `<version>@<short commit> · <driver directory>`, and the search
of the version picker matches the driver directory.

Drivers with the same name are one application driver, whatever their
driver directory. The latest-wins rule that binds a deployment does not
look at the driver directory, so an upgrade with "Latest (auto)" can move
a deployment from `drivers/a` to `drivers/b` when `drivers/b` holds the
newest matching version. The Upgrade dialog warns about this while
"Latest (auto)" is selected and the driver's versions come from more than
one driver directory. To keep a deployment in one driver directory, give
each driver directory its own driver name in `metadata.name`, or pin the
driver version with `--driver-version-id` (see
[Selecting a driver version](#selecting-a-driver-version-when-deploying-or-upgrading)).

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
non-null per row. The UI pickers add the driver directory to the
label of a version loaded from one, as in `1.0.0@0123456 · drivers/infrahub`.

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
  row — any number of repeated loads produces a single row;
- registers the declared actions that have no registered flow, also when
  it returns the existing row (see
  [Loading a driver again registers its missing actions](#loading-a-driver-again-registers-its-missing-actions)).

Edits to other files in the driver directory (`README.md`, examples,
screenshots) are invisible to the fingerprint and never produce a new
row.

After you edit `driver.styrmin.yml`, the values template or `actions.py`,
the driver versions loaded from the path before the edit no longer pass
the [check of the driver files](#check-of-the-driver-files-before-an-action-runs):
their actions fail with the fingerprint error. Load the driver again and
create or upgrade your deployments with the new driver version. The
agent reads the files from the same path as the server: on the
`docker compose` dev stack, both containers mount `driver/examples/`, so
the agent reads your edit without an image build; in a Helm install, the
server and the agent read the driver from their image, so rebuild the
image and roll out the server and the agent before you load the driver
again.

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
Latest-wins does not look at the driver directory: see
[A new commit to the repository creates a new driver version](#a-new-commit-to-the-repository-creates-a-new-driver-version)
for drivers with the same name in several driver directories.

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
  `load-local-version` against the baked-in paths. Run the server and the
  agent with that image, because the agent runs the driver's actions from
  the same paths.

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
