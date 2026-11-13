---
title: styrminctl CLI
sidebar_position: 3
description: Reference for every command, flag, and exit code in the styrminctl CLI.
---

## `styrminctl` CLI

:::info Partial reference — the full command tree is not generated yet

The sections below are written manually and are correct for the commands
they cover. They document what `--help` does not show, such as
identifier precedence and exit codes. They do not cover every command
yet; the full reference will be generated from the Cyclopts command tree
at build time.

For the commands not covered here, read the CLI help:

```bash
styrminctl --help
styrminctl <command> --help
```

The source code is under
[`cli/`](https://github.com/opsmill/styrmin/tree/develop/cli).

:::

### Scope

`styrminctl` is the command-line client for Styrmin, built with Cyclopts.
It calls the GraphQL API and does not connect to the database or the
agent.

Its top-level command groups are `clusters`, `environments`,
`deployments`, `drivers`, `backups`, `env-backups`, `env-clones`,
`backup-locations`, `tasks`, `auth`, and `telemetry`. `login`, `logout`,
and `whoami` are also top-level commands, as short forms of their `auth`
subcommands. Every other command, such as restoring a backup or upgrading
a deployment's version, is a subcommand of one of these groups.

When the reference is generated, this page will document, for each
command:

- Every group, subcommand, and flag
- Output formats (`--output text|json|yaml`)
- Exit codes
- Authentication and configuration (where the CLI reads the server URL
  and the token)

### Generation source

- **Schema**: the Cyclopts command tree in
  [`cli/src/`](https://github.com/opsmill/styrmin/tree/develop/cli/src)
- **Build step**: not defined yet; it will read the Cyclopts command
  tree and write one Markdown section per command into this file

### `clusters update` — change a cluster's config

`styrminctl clusters update` replaces the config of an existing cluster
and redeploys the deployments that take a changed value. You keep every
deployment and environment of the cluster. The command requires the
administrator role.

```text
styrminctl clusters update [NAME] [--id UUID] --config JSON|@FILE [--dry-run]
```

- `NAME`: the name of the cluster.
- `--id`: the UUID of the cluster. Pass either a name or `--id`, not
  both.
- `--config`: required. The whole cluster config, as inline JSON or as
  `@path/to/file.json`.
- `--dry-run`: check the config and list the deployments that the
  update would redeploy, without saving anything.

```bash
styrminctl clusters get default --json > cluster.json
# edit cluster.json
styrminctl clusters update default --config @cluster.json --dry-run
styrminctl clusters update default --config @cluster.json
```

The same update is available as the `updateCluster` GraphQL mutation
(with `dryRun: true` for the check), as `clusters.update()` in the
Python SDK, and from the **Edit** button on the cluster detail page,
which the page shows only to administrators. The edit dialog lists the
changed values and the deployments that will be redeployed before it
saves. It keeps the values it does not show: the database size, the
backup retention, and the dedicated ingress service
annotations and load balancer IP. When you turn the
dedicated ingress off, the annotations and the load balancer IP are
removed with it.

#### From the Python SDK

`clusters.update()` takes the config as a dict, like
`clusters.create()`. Read the stored config, change one value, and send
it back:

```python
from styrmin_sdk import StyrminClient

async with StyrminClient(server_address="https://styrmin.example") as client:
    cluster = await client.clusters.get(cluster_name="default")
    config = {**cluster.config, "fqdn_suffix": "apps.example.com"}

    preview = await client.clusters.update(config, cluster_name="default", dry_run=True)
    print([d.deployment_name for d in preview.redeployed])

    result = await client.clusters.update(config, cluster_name="default")
    for failed in result.failed_to_start:
        print("not started:", failed.environment_name, failed.deployment_name)
```

The SDK accepts the stored values that `get()` returns, such as
`"external_url_scheme": "http"`, and refuses an unknown key at any depth
with a `ValueError` before it sends anything.

#### The file holds the whole config

The config you submit replaces the stored config. A key that you leave
out is removed from the cluster, except `ingress_class` and
`runtime_class`, which get `traefik` and `default`, as with
`clusters create`. For example, a file without `dedicated_ingress` turns
the dedicated ingress off, and a file without `fqdn_suffix` removes the
FQDN suffix.

The file uses the same keys as `clusters create --config`, in
snake_case. camelCase keys, the GraphQL spelling, are accepted too. The
command refuses a key that it does not know, at any depth, before it
sends anything to the server, so that a misspelled key cannot remove a
value:

```text
Error: Unknown config key(s): fqdn_sufix, dedicated_ingress.servce
```

A cluster config does not take `scheduling`, because no pod gets a
cluster's scheduling value. The key is refused whatever its value,
including `null` and `{}`: `clusters update` refuses it as unknown, and
`clusters create` and the `createCluster` mutation refuse it with
`VALIDATION_ERROR`. Set `scheduling` on the environment or the
deployment instead.

To start from the stored config, run
`styrminctl clusters get <name> --json`. It prints only the config, as
JSON, and `clusters update` accepts that JSON as it is, including
values such as `"external_url_scheme": "http"`. Without `--json`, the
command prints a table whose `config` column truncates long values, so do
not copy the config from the table.

Two updates are not merged: the update saved last replaces the other. A
file that you saved before another administrator's update reverts that
update, so read the stored config with `clusters get --json` immediately
before you edit it. The edit dialog warns you when the config changed after you opened
it.

The update is refused, and nothing is saved, in these cases:

- The config does not pass validation (`VALIDATION_ERROR`).
- An environment clone is in progress in the cluster: it is still
  capturing the backup of an environment of the cluster, or it is still
  building its new environment in the cluster. The error names the
  environment; submit the config again when the clone has finished.
  Environment backups and restores in progress do not block the update.
- You do not have the administrator role.

#### Which deployments are redeployed

For each deployment, Styrmin computes the config that the deployment
resolves to now: the cluster config, then its environment's config, then
its own config, where the most specific value wins. When this config differs
from the one that the deployment's active instance was deployed with,
Styrmin redeploys the deployment at its current application version and
driver version. As a result:

- A deployment in an environment that sets the changed value itself is
  not redeployed.
- Submitting the stored config again redeploys only the deployments
  that are not at the config they resolve to, whatever the cause. For
  example, it redeploys a deployment whose redeploy could not be started
  during an earlier update. It also redeploys a dedicated ingress
  controller whose `dedicated_ingress` values differ from the values
  that its environment resolves to, for example after an environment
  update changed the environment's own `dedicated_ingress` values. It
  does not redeploy a `RUNNING` controller whose values match.
- Deleted deployments and deployments that are being deleted are not
  redeployed. A deployment with a restore in progress is skipped; submit
  the config again after the restore has ended.
- A deployment where the environment and the deployment both set
  `required` node affinity terms, rendered before
  [#486](https://github.com/opsmill/styrmin/issues/486), is not at the
  config it resolves to: Styrmin now combines these terms. The next
  cluster update redeploys it, even when the update changes an unrelated
  value. See
  [When running deployments get the combined terms](../concepts-and-architecture/node-affinity.md#when-running-deployments-get-the-combined-terms).
- When `dedicated_ingress` changes, the applications of an environment
  that takes the cluster's value move onto the environment's ingress
  controller only once the controller is ready, and the controller is
  removed only after the applications have moved off it. See
  [Changing the dedicated ingress on the cluster](../concepts-and-architecture/ingress-and-networking.md#changing-the-dedicated-ingress-on-the-cluster).

#### What the command prints

After the update, the command lists, by environment:

- the deployments that are being redeployed, each with the ID of its
  `update_instance` task. To follow one, run
  `styrminctl tasks get <task-id>`.
- the deployments that wait for their environment's dedicated ingress
  controller. They are redeployed when the controller runs with the new
  values.
- the deployments that are not redeployed because a restore is in
  progress.
- the dedicated ingress controllers that the update creates, redeploys
  or removes.
- the deployments whose redeploy could not start, and the environments
  that could not be evaluated, for example because the environment's
  stored config no longer passes validation.

The config is saved even when some redeploys could not start, so a
successful command does not mean that every redeploy started. When the
command lists deployments or environments that could not start, run the
same command again: it retries only the deployments that are not at
their config.

Styrmin starts the redeploys, environment by environment, before it
returns a response. The command waits up to 10 minutes. If it times out, the
server can still be saving the config and starting the redeploys: check
the config with `clusters get --json` before you run the command again.

The server log has one `cluster_config_updated` line per update, with
the ID of the administrator who submitted it and the previous and new
value of each top-level key that changed. It also has one
`cluster_config_fanout` line, with the number of deployments evaluated,
redeployed, skipped and failed, and one
`cluster_config_fanout_environment_error` line for each environment that
could not be evaluated. Styrmin cancels the changes that it recorded for
that environment and still evaluates the other environments.

#### Reverting an update

To revert an update, submit the previous file again. Styrmin redeploys
the deployments whose config changes back. Keep a copy of the file
before you edit it, or save the output of
`styrminctl clusters get <name> --json` first. Styrmin does not keep a
history of cluster configs
([#447](https://github.com/opsmill/styrmin/issues/447)); the
`cluster_config_updated` server log line contains the previous values.

#### Storage class change on a `StatefulSet`

Kubernetes refuses any change to the volume claim templates of an
existing `StatefulSet`, and an application driver can write the storage
class there (the Infrahub example drivers do). When you change
`standard_storage` or `fast_storage`, the redeploy of such a deployment
fails and the deployment becomes `FAILED`. Its existing volumes keep
their storage class. Styrmin makes the new instance active before the
rollout runs, so submitting the same config again does not retry the
redeploy. To recover, do one of the following:

- Submit the config with the previous storage class again. Styrmin
  redeploys the deployment with the storage class of its volumes.
- Delete the deployment and deploy it again. The new deployment gets
  volumes with the new storage class. The data in the old volumes is
  not moved.

### `env-backups` — environment-level backup and restore

The `env-backups` group backs up and restores a whole environment. One
command backs up every eligible deployment of an environment, and one
command restores them. An environment backup (also called a snapshot)
contains one **constituent backup** per eligible deployment: an ordinary
backup of that deployment, which belongs to the environment backup. An
environment restore runs one constituent restore per constituent backup.
See [Backing up a whole
environment](../concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment).

Backups of one deployment stay in the `backups` group, because the
`backups` commands act on one deployment or one instance, and the
`env-backups` commands act on an environment:

- `backups restore <BACKUP_ID>` takes the backup id alone and restores
  the backup into the deployment it was taken of, in that deployment's
  namespace. You do not choose the deployment or the namespace.
- `backups list` and `backups restore --last` act on a deployment's
  backup history: the backups of every instance the deployment has had.
  `backups list` takes the deployment by name or by `--id`, and
  `backups restore --last` takes it with `--target-deployment` or
  `--target-deployment-id`. See [Backup history of a
  deployment](../concepts-and-architecture/backups-and-restores.md#backup-history-of-a-deployment).
- `--target-deployment`, `--target-deployment-id`,
  `--target-instance-id` and `--environment` work only with
  `backups restore --last`. They select the backups from which the
  command picks the newest completed backup, and the backup is restored
  into the deployment it was taken of. `backups restore` refuses a backup
  id combined with one of these options before it contacts the server,
  and exits with status 1.
- `backups restore --last` skips backups whose expiry date has passed.
  When the backup it selects was taken of an earlier instance, or at
  another application version, it shows the backup's application
  version and the deployment's current one, and asks for confirmation.
  `--yes` skips the question. Without a terminal, the command refuses
  the restore unless you pass `--yes`.
- `backups restore --last` can restore into a deployment that has no
  active instance, as the server can.
- `--instance-id` on `backups list` and `--target-instance-id` on
  `backups restore --last` act on one instance only.

The group has seven commands:

| Command | What it does |
|---------|--------------|
| `env-backups create [ENVIRONMENT]` | Back up every eligible deployment of an environment in one operation. |
| `env-backups get <ENVIRONMENT_BACKUP_ID>` | Show one environment backup, with the result of each constituent backup. |
| `env-backups list [ENVIRONMENT]` | List the environment backups of an environment, newest first. |
| `env-backups restore <ENVIRONMENT_BACKUP_ID>` | Restore an environment backup into the deployments it was taken of. Requires the administrator role. |
| `env-backups restore-get <ENVIRONMENT_RESTORE_ID>` | Show one environment restore, with the skipped deployments and their reasons. A redeploy that the restore could not start is not listed ([#520](https://github.com/opsmill/styrmin/issues/520)). |
| `env-backups restore-list <ENVIRONMENT_BACKUP_ID>` | List the restores of an environment backup, newest first. |
| `env-backups delete <ENVIRONMENT_BACKUP_ID>` | Delete an environment backup, its constituent backups, and their restores. |

#### Targeting an environment

`create` and `list` take the environment as a positional name, or as a
UUID with `--id`. Passing both, or neither, is an error. Styrmin looks up
a name within a cluster, so pass `--cluster <name>` (default `default`)
or `--cluster-id <uuid>` when you have more than one cluster registered.

`--cluster-id` combined with a named `--cluster` other than `default` is
an error. `--cluster-id` with the default `--cluster default` is
accepted, because the CLI cannot tell a default value from a value you
typed. `--cluster-id` then takes precedence: the CLI sends the name
lookup with the cluster id and no cluster name.

```bash
styrminctl env-backups create production --name before-upgrade
styrminctl env-backups list production
styrminctl env-backups list --id <environment-uuid>
```

The other commands take the UUID of an environment backup or of an
environment restore.

#### `create` options

| Option | Default | Purpose |
|--------|---------|---------|
| `--name` | generated | Name of the environment backup. Defaults to `styrmin-envbackup-<uuid>`. |
| `--wait` | off | Wait until every constituent backup reaches a final state. |
| `--max-wait` | `600` | Seconds to wait, with `--wait`. |
| `--interval` | `5` | Poll interval in seconds, with `--wait`. |

`create` prints the status of the environment backup and a count of its
constituent backups in `ok/failed/total` form, then one line per
constituent backup, with its failure reason when it has one. `ok` counts
the constituent backups that **completed**, and `failed` counts the
deployments that got no backup. A constituent backup that is still
running, or that was deleted since, appears only in `total`. To check
that every eligible deployment has a backup, compare `total` with the
number of eligible deployments; the status does not show it.

#### `restore` options

| Option | Default | Purpose |
|--------|---------|---------|
| `--wait` | off | Wait until every constituent restore reaches a final state. |
| `--max-wait` | `900` | Seconds to wait, with `--wait`. |
| `--interval` | `5` | Poll interval in seconds, with `--wait`. |

`restore` prints the restored constituent backups and each skipped one,
with its deployment name and reason, before it waits. The list of skipped
deployments is complete when the command returns: the server selects the
deployments to skip when it receives the request.

#### Exit codes

`create` and `restore` exit with a **non-zero code on `PARTIAL` and on
`FAILED`**, with or without `--wait`. You can restore a `PARTIAL`
environment backup, but it does not include every deployment that you
asked to back up or restore. The exit code is the only machine-readable
sign of this, so a CI job that treats the command as successful does not
detect the missing deployments.

Styrmin computes the status from the constituent backups on every read,
so the status can already be `PARTIAL` or `FAILED` when the command
returns. For example, a backup in which every deployment already had a
backup running, or a restore in which every deployment was skipped, has
nothing to wait for. In that case the command prints the result and exits
with a non-zero code without polling. Without `--wait`, a command whose
constituent backups or restores are still running exits with code 0 when
the server accepts the operation.

**A `--wait` that times out also exits with code 1.** The CLI does not
report the timeout as a separate error: it prints the last status it read
(`PENDING` or `IN_PROGRESS`) and exits with a non-zero code. The
constituent backups or restores keep running. Increase `--max-wait`
instead of treating that exit code as a failed backup.

:::note `delete` works in any status

`env-backups delete` works whatever the status of the environment backup,
including while its constituent backups are still running. Use it when a
constituent backup never started and the environment stays blocked:
deleting the environment backup lets you start new environment-level
operations.

:::

### `env-clones` — clone an environment

The `env-clones` group copies a running environment into a **new**
environment on the same cluster, from a new environment backup of the
source, and tracks the operation. For how the selection and the config
override work, and what a clone is not isolated from, see [Cloning an
environment](../concepts-and-architecture/backups-and-restores.md#cloning-an-environment).

The group has three commands:

| Command | What it does |
|---------|--------------|
| `env-clones create [ENVIRONMENT] --name <new-name>` | Clone an environment into a new one. Requires the administrator role. |
| `env-clones get <ENVIRONMENT_CLONE_ID>` | Show one clone: its status, the result for each deployment, and the events of the operation. |
| `env-clones list [ENVIRONMENT]` | List the clones taken **of** an environment, newest first. |

`create` and `list` take the source environment in the same way as
`env-backups`: a positional name, or a UUID with `--id`, looked up within
`--cluster` (default `default`) or `--cluster-id`. Passing both a name
and `--id`, or neither, is an error.

`list` lists the clones of a **source** environment. An environment
created by a clone is listed under its source environment, not under
itself: run `env-clones list` on the **source** environment, or
`env-clones get <id>` on the clone record. To find the clone that created
an environment, read the `Environment.clonedFrom` field in the UI or the
GraphQL API; no `styrminctl` command reads it.

#### `create` options

| Option | Default | Purpose |
|--------|---------|---------|
| `--name` | *required* | Name of the new environment to create. |
| `--deployment` | all eligible | A source deployment to include, by **name or UUID**. Repeat for several. Omit to include every eligible deployment. |
| `--config-override` | none | JSON `UpdateEnvironmentInput` merged over the captured config, inline or `@path/to/file.json`. camelCase or snake_case keys. |
| `--clear-config-field` | none | A captured config field to remove before the merge, by **snake_case** field name. Repeat for several. |
| `--wait` | off | Wait until the clone reaches a final state. |
| `--max-wait` | `1800` | Seconds to wait, with `--wait`. A clone takes a backup, creates the environment and restores the data, so the default is longer than for `env-backups`. |
| `--interval` | `5` | Poll interval in seconds, with `--wait`. |

`--deployment` accepts deployment **names**, looked up in the source
environment, and UUIDs. The CLI rejects a name that matches no deployment
of the source before it sends the mutation.

Omitting `--deployment` and passing an **empty** selection are different
requests. Omit it to clone every eligible deployment. Pass
`--empty-deployment`, which Cyclopts generates, to clone no application:
the clone copies only the environment's configuration and ends in
`COMPLETED` once the new environment exists. `env-clones get` shows which
one you asked for: `all eligible` or `none (configuration only)`.

When the environment's config has an affinity term that names a
deployment, an empty selection is rejected with `VALIDATION_ERROR`,
because the clone copies no deployment. The error message names each
such deployment and the path of every term that names it. Add
`--clear-config-field scheduling`, or give a `scheduling` that names no
deployment in `--config-override`.

`--config-override` is an `UpdateEnvironmentInput` payload, so `envVars`
is a list of `{name, value}` entries, not a map. camelCase keys
(`backupTtl`, `fqdnSuffix`) are the GraphQL spelling and always work;
the CLI also accepts the snake_case forms. `--clear-config-field` takes
**only** snake_case names, because the CLI checks them against the field
names of the config, not against the input type.

`create` prints the clone's id, its status, the source name, and a
`cloned/skipped/failed/total` deployment count, then one line per source
deployment with its result and reason, then the events of the
operation.

```bash
# Everything eligible, wait for it
styrminctl env-clones create production --name prod-rehearsal --wait

# Two deployments by name, with the outbound integration removed and
# safe environment variables merged in
styrminctl env-clones create production \
  --name prod-rehearsal \
  --deployment api \
  --deployment worker \
  --clear-config-field external_dns_endpoints_type \
  --config-override '{"envVars": [{"name": "EMAIL_MODE", "value": "disabled"}]}'

# Override from a file, source addressed by UUID
styrminctl env-clones create --id <environment-uuid> \
  --name prod-rehearsal \
  --config-override @rehearsal-config.json

# Configuration only — create the environment, bring no applications
styrminctl env-clones create production --name prod-config-only --empty-deployment
```

To follow the clone afterwards:

```bash
styrminctl env-clones list production
styrminctl env-clones get <environment-clone-id>
```

#### Exit codes

`create` exits with **0 on `COMPLETED`**, and with **1 on `PARTIAL` and
on `FAILED`**. On `PARTIAL`, it also prints a warning, because the clone
does not include every deployment you selected.

Styrmin computes the status on every read. The first status, which the
mutation returns, is never final: it is `PENDING`, or `IN_PROGRESS` once
anything has been recorded, including a deployment skipped at the start.
A configuration-only clone, or a clone whose deployments were all
skipped, also shows `IN_PROGRESS` until its environment exists. A final
status therefore comes only from polling: `create` reads it with
`--wait`, and `get` shows it afterwards.

Without `--wait`, `create` exits with 0 when the server accepts the
clone, even if the clone is still running. As with `env-backups`, a
`--wait` that reaches `--max-wait` also exits with 1: the CLI prints the
last status it read and stops waiting. The clone keeps running. Increase
`--max-wait` instead of treating that exit code as a failed clone.

:::note There is no `env-clones delete`

To discard a clone, delete the **environment it created**
(`styrminctl environments delete <name>`). This works in any state, and
you can then clone again under the same name. If the clone stopped
before its environment was created, delete its environment backup with
`env-backups delete <id>` instead. See [Discarding a
clone](../concepts-and-architecture/backups-and-restores.md#discarding-a-clone).

:::

### `deployments apply` is idempotent

`styrminctl deployments apply -f <manifest>` is declarative: the CLI
sends the full desired state on every run, and the server compares it
with the stored state. Applying an unchanged manifest again changes
nothing: Styrmin creates no new instance and starts no reconciliation
task, and the deployment keeps its active instance and status. The
command still exits with code 0.

The command reports the result for each deployment in a run:

- `created <name>`: Styrmin created a new deployment.
- `updated <name>`: the desired state was different, and Styrmin started
  a reconciliation.
- `unchanged <name>`: the resolved desired state already matched the
  stored state; Styrmin did nothing.
- `failed <name>: <reason>`: the apply failed for that deployment. When
  the server rejected the manifest, the line ends with the server's error
  code, for example `[COMPONENT_CONTAINER_NOT_DECLARED]`, and nothing on
  the deployment changed. When the server refused the update and returned
  a failed task, the reason is `task <task-id> failed: <message>`, and the
  deployment keeps its application version. See
  [A declared action has no registered flow](../drivers/loading-drivers.md#a-declared-action-has-no-registered-flow)
  for an example.

A run ends with a summary line counting each outcome, for example:

```text
2 created, 1 updated, 3 unchanged, 0 failed
```

A run in which every deployment is `unchanged` exits with code 0, so you
can run `apply` repeatedly, for example from a CI job. A run with at least
one `failed` result exits with code 1.

For an existing deployment, `apply` sends the manifest's config,
parameters and version in one request. The config replaces the whole stored
config: a key that the stored config has and the manifest's `spec.config` omits
is cleared, for example the `services` overrides, when `spec.config` has other
keys. An omitted or empty `spec.config` is the exception: it keeps the stored
config. `spec.parameters` is merged on top of the stored parameters, not
replaced. This needs a Styrmin server with
[#388](https://github.com/opsmill/styrmin/issues/388): against an older
server, every update fails with a message that says to upgrade the
server. Upgrade the server before or together with `styrminctl` and the
SDK.

:::note Re-applying a failed deployment

An apply that changes nothing does not retry a `FAILED` deployment.
`apply` compares the desired state with the stored state, not with the
health of the deployment, so a failed deployment whose manifest did not
change stays failed.

:::

:::note Rebuilt image under an unchanged version

`apply` compares the *resolved desired state*, which depends on the
application version and the driver version, not on the content of the
image. An application image that you rebuild and push again under the
**same** version, with an unchanged config, gives the same instance, so
`apply` does not redeploy it. Change the version to redeploy.

:::

### Failure reasons of `deployments apply --wait`

With `--wait`, `apply` prints `submitted <name>` when it submits a
change, then `running <name>` or `failed <name>: <reason>` when the
deployment reaches a final state. When the server refuses the change
and returns a failed task, `apply` prints only the line
`failed <name>: task <task-id> failed: <message>` and does not wait,
because the deployment did not change. For an upgrade, `apply` prints
`running` only after the upgrade task and the tasks that its driver hook
started have finished (see
[Status reporting](../concepts-and-architecture/status-reporting.md)).
When the deployment state becomes `FAILED`, the reason names the failed
step, in the form
`step "<step name>" failed: <error>`. `apply` looks for it in the steps of
the task that the apply started, then in the tasks that the task's hook
steps started, nearest first. When it finds no failed step, the reason
is `deployment reconciliation failed (status: <status>)`.

`--wait` stops after `--max-wait` seconds (600 by default) with the
reason `wait timeout`. The operator fails a HelmRelease that is not ready
after its readiness timeout (270 seconds by default), which counts from the
start of the rollout, after the flow and its hooks. When the hooks of a
deployment take longer than about 5 minutes, raise `--max-wait`, or the
wait can end with `wait timeout` instead of the failed step. Read the steps
with `styrminctl tasks get <task-id>`; `styrminctl tasks list` shows the
type and deployment of each task.

### `deployments get` — the Components table

`styrminctl deployments get <deployment-id>` prints the deployment's
fields, then a "Components" table with the columns `id`, `name`,
`enabled` and `replicas`. The `replicas` column shows the count that
Styrmin applies to the component and where it comes from (see
[Replica overrides](../concepts-and-architecture/replica-overrides.md#order-of-precedence)):

| Component | `replicas` cell |
|-----------|-----------------|
| A replica override of 3 applies | `3 (override)` |
| A driver default of 2, no override | `2 (driver default)` |
| A singleton component without an override | `1 (driver default, singleton)` |
| A singleton component with an override of 1 | `1 (override, singleton)` |
| Neither an override nor a driver default | `chart` |
| A stored override of 3 that does not apply on a declared component | the cell followed by `, override 3 not applied` |
| A stopped component | the cell followed by `, stopped: 0 pods`, for example `3 (override), stopped: 0 pods` |

A replica override on a component that the deployment's driver version
no longer declares gets its own row, with `-` in the `id` and `enabled`
columns and the cell `3 (override, not applied: no longer declared)`.

The `chart` cell has no number, because Styrmin does not read the count
that the chart renders.

### `deployments update-version`

`styrminctl deployments update-version <deployment-id> <version>` moves a
deployment to an application version. The deployment is bound to the
newest loaded driver version that supports that version, or to
`--driver-version-id`.

`--config` takes a JSON `UpdateDeploymentInput` payload, inline or as
`@<file>`, the same payload as `deployments update`. It is written with
the version and checked against the target driver version, and one task
reconciles both. `--config` needs a Styrmin server with
[#388](https://github.com/opsmill/styrmin/issues/388);
`update-version` without `--config` works with older servers too.

When the server refuses the version change before it writes anything,
the request returns a failed task. The command then prints
`Error: task <task-id> failed: <message>` and exits with code 1, and the
deployment keeps its application version and driver version. For
example, the server refuses an upgrade to a driver version that declares
an upgrade action with no registered flow: see
[A declared action has no registered flow](../drivers/loading-drivers.md#a-declared-action-has-no-registered-flow).

When the command changes the deployment's driver version and the target
driver version no longer declares a parameter that the deployment sets,
Styrmin drops the value if it equals the parameter's default in the
current driver version. Any other value fails the command with
`RETIRED_PARAMETER_VALUE` before any task starts. `deployments apply`
follows the same rule. See
[Change a deployment's driver version](../drivers/changing-driver-versions.md)
and
[Migrate the infrahub replica parameters](../drivers/migrating-replica-parameters.md).

### `deployments scale` — set the replica count of one component

`styrminctl deployments scale <deployment-id> <component> <count>` sets
the [replica override](../concepts-and-architecture/replica-overrides.md)
of one component. `--clear` instead of a count removes the override, and
the driver default or the chart's count applies again:

```shell
uv run styrminctl deployments scale <deployment-id> task-worker 4
uv run styrminctl deployments scale <deployment-id> task-worker --clear
```

The command keeps every other override of the deployment: it reads the
stored component blocks and sends them back with only that component's
count changed. `deployments update --config` with `components` instead
replaces every stored component block. A change that another user writes
between the read and the update is overwritten.

The server rejects a count below 1 with `INVALID_REPLICA_COUNT`, a count
above the server's maximum (`STYRMIN_MAX_REPLICA_COUNT`, 20 by default)
with `REPLICA_COUNT_ABOVE_MAXIMUM`, and a count above 1 on a singleton
component with `SINGLETON_REPLICA_OVERRIDE`. The command exits with code 1
and prints the error. When the count does not change, it prints
`Deployment already up to date; no changes applied.`

### `tasks get` — a task's steps

`styrminctl tasks get <task-id>` prints three parts:

1. A "Task" table with the columns `id`, `type`, `status`, `result`,
   `message` and `deploymentId`. `status` shows only the state of the
   Prefect flow run; `result` is the task result, calculated from the steps and the
   `status` of the task and of the tasks its hook steps started
   (`RUNNING`, `FAILED`, `SUCCEEDED` or `SUPERSEDED`).
2. A "Steps" table with one row per step, in start order with pending
   steps last: `step` (the step's name), `status`, `duration` (`running`
   while the step runs), `attempts` and `error`. The `error` column contains
   the error of each failed attempt as `attempt <n>: <message>`, oldest
   first, then FluxCD's current reason for the HelmRelease step, then the
   last line of a failed command's output as `output: <line>`, one per
   line. A task without steps prints "No steps recorded for this task."
   instead.
3. A "Started tasks" table with the `id`, `type` and `result` of each
   task that the task's hook steps started. It is printed only when there
   is one.

The full output of a failed command is on the deployment page.

### Manifest `spec.config` format

`spec.config` accepts the same typed configuration whether `apply` creates
or updates a deployment. Environment variables, for the deployment and for
each component, are written as a **list of `{name, value}` entries**, not as
a key/value map:

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/my-driver
  version: "1.2.3"
  environment: production
  config:
    env_vars:
      - name: MY_ENV
        value: value01
    components:
      - name: server
        env_vars:
          - name: LOG_LEVEL
            value: debug
        image: "registry.example/acme/app-patched:{{ app.version }}"
        replicas: 3
  parameters:
    storage_size: 10
```

`spec.parameters` stays a `{name: value}` map.

`spec.config.service_name_overrides` gives a service of the deployment another
name than the one its driver declares. It is a list of `{driver_service_name,
override_name}` entries, as in
[`examples/deployments/semaphore.yml`](https://github.com/opsmill/styrmin/blob/develop/examples/deployments/semaphore.yml).
A service name is unique within an environment, so a second deployment of a
driver that declares the same service name, such as
[`generic-app`](../drivers/generic-app.md#several-deployments-in-one-environment),
needs an override when `apply` creates it. An entry that is not a
`{driver_service_name, override_name}` pair fails before `apply` creates or updates
anything.

`services` lists the
[service ingress override](../concepts-and-architecture/service-ingress-overrides.md)
of each external service, as a list of `{name, ingress_class, fqdn_suffix}`
rows, as `components` is a list. `name` is the service name that the driver
declares. A row sets an ingress class, an FQDN suffix, or both, for that service
only. Removing a row clears the override on the next apply, with the same
`components: []` exception as for `image`: write `services: []` to clear the
last override when nothing else stays in `spec.config`. An ingress class must be
a Kubernetes object name, and a suffix must be a DNS name; an invalid value
fails with `VALIDATION_ERROR`. A service that the driver version does not
declare fails with `UNKNOWN_SERVICE_INGRESS_OVERRIDE`, a service that it declares
`internal`, or `external` with kind `tcp` or `udp`, fails with `SERVICE_INGRESS_NOT_BUILT`, two rows for one service fail
with `DUPLICATE_SERVICE_NAME`, and a change to a driver version that removes the
service, declares it `internal`, or gives it kind `tcp` or `udp`, while the
override is stored and the manifest keeps it, fails with `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`. `apply` checks each row before it sends the request. A key other than `name`,
`ingress_class` and `fqdn_suffix` (or `ingressClass` and `fqdnSuffix`), a row
without a name, a row that sets neither field, and a row that is not a mapping
fail the manifest with an error that names the service and the key. In a
`create` or `update` command, `--config` takes the GraphQL input, which the
server checks.

`components[].image` is the component's
[image override](../concepts-and-architecture/image-overrides.md): one full
reference with an explicit tag or digest, where every `{{ app.version }}`
token becomes the deployment's application version. Quote it, since YAML
reads an unquoted `{` as a map. Removing the key clears the override on the
next apply, unless that leaves `spec.config` empty: an omitted or empty
`spec.config` keeps the stored configuration, so write `components: []` to
clear the last override. A reference that is not a valid image reference,
has no tag or digest, contains another template expression, or becomes
invalid once
`{{ app.version }}` is replaced by the application version fails with
`INVALID_IMAGE_REFERENCE`;
a component the driver version does not declare fails with
`UNKNOWN_COMPONENT_IMAGE_OVERRIDE`.

`components[].replicas` is the component's
[replica override](../concepts-and-architecture/replica-overrides.md): a
whole number from 1 to 2147483647 that Styrmin sets on `spec.replicas` of
the component's `Deployment` and `StatefulSet` workloads. It needs no
component container. Removing the key clears the override on the next
apply, with the same `components: []` exception as for `image`; the
component then runs the driver default or the chart's count. A value that
is not a whole number, such as `true` or `"3"`, fails before `apply` sends
anything. A count below 1 fails with `INVALID_REPLICA_COUNT`, a new or
changed count above the server's maximum (`STYRMIN_MAX_REPLICA_COUNT`, 20
by default) fails with `REPLICA_COUNT_ABOVE_MAXIMUM`, a count above 1 on a
singleton component fails with `SINGLETON_REPLICA_OVERRIDE`, and a new or
changed count on a component the driver version does not declare fails
with `UNKNOWN_COMPONENT_REPLICA_OVERRIDE`.

Adding or changing per-component `env_vars`, `image`, `command` or `args` on a
component whose driver version declares no component container fails with
`COMPONENT_CONTAINER_NOT_DECLARED`. A manifest has no driver version field:
`apply` writes `spec.config` together with the version change, and runs these
checks against `spec.version` and the newest loaded driver version that
supports it (see
[Selecting a driver version](../drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading)),
whatever versions the deployment was on before. The error names the driver
version and application version it checked. A rejected apply changes nothing on
the deployment.

Component config on a component that this driver version does not declare is
rejected even when it is unchanged, with one exception: a block that contains
only `replicas`, sent with the stored value unchanged, is accepted, stored and
not applied. When a driver version removes or renames a component, remove its
block from the manifest in the same change that changes `spec.version`. Unchanged
`env_vars`, `image`, `command` or `args` on a component that the driver version
declares without a component container are accepted, stored and not applied.
`apply` prints a warning on stderr for each such component. The warning names
the kinds of override and the two ways to fix it:

```text
updated my-app
warning: my-app: env var and args overrides are stored on worker but not applied: the driver version declares no component container for worker. Remove them from the manifest, or load a driver version that declares components.worker.container and apply again
0 created, 1 updated, 0 unchanged, 0 failed
```

A replica override needs no component container, so it gets its own warning,
which names the component that the driver version does not declare:

```text
warning: my-app: replica override is stored on legacy but not applied: the driver version does not declare legacy. Remove it from the manifest, or load a driver version that declares components.legacy and apply again
```

The SDK returns these components as `ApplyOutcome.inapplicable_components`, and
the kinds of override per component (`env_vars`, `image`, `command`, `args`,
`replicas`) as `ApplyOutcome.inapplicable_overrides`.

`apply` reads these lists back from the server after the update is written.
When that read fails, for example against a server of an earlier release,
`apply` still succeeds and prints a warning with the error instead, because it
cannot list the overrides that are not applied. The SDK sets
`ApplyOutcome.applicability_check_error`.
See [Migrate env vars to component containers](../drivers/migrating-env-vars.md)
and
[Migrate command and args overrides to component containers](../drivers/migrating-container-overrides.md).

When a manifest changes an existing deployment's application version,
`styrminctl deployments apply` prints a warning on stderr for each
deployment whose image overrides have no `{{ app.version }}` token, since
those components keep their pinned image after the upgrade:

```text
updated my-app
warning: my-app: pinned image override on server will not follow version 1.3.0 (no {{ app.version }} token)
0 created, 1 updated, 0 unchanged, 0 failed
```

The warning does not change the exit code, and `apply` never prompts. With
`--wait`, it is printed once, when the change is submitted. `apply` reads only
the config, so it lists every override without the token, including one on a
component whose override does not currently apply. The SDK returns the same
components as `ApplyOutcome.pinned_image_components`, with
`ApplyOutcome.target_version` set on an `updated` outcome that changes the
version.

When a manifest sets `spec.config` keys and no `services`, `apply` replaces the
whole stored config, so the stored service ingress overrides are cleared. The
command prints a warning on stderr that names each service whose override is
cleared. The exit code is unchanged. The SDK returns the names as
`ApplyOutcome.dropped_service_overrides`.

```text
updated my-app
warning: my-app: the stored ingress override of service web is cleared: spec.config has keys and no services. Add web to spec.config.services to keep it
0 created, 1 updated, 0 unchanged, 0 failed
```

:::note Overrides in the apply that changes the version

Every component override (`env_vars`, `command`, `args`, `image`, `replicas`)
is checked against the target driver version, so you can set all of them in
the apply that changes `spec.version`. The driver's upgrade action can start before the new
values reach the component's workload, so the action primitives take the
`image` override and the `env_vars` from the new configuration: a Job that the
action builds from the component's image and env runs with them. One
exception: an env var that the same apply removes still reaches that Job,
because it is still in the workload. To keep it out of the upgrade, remove it
in an earlier apply that keeps `spec.version`.

:::

### `drivers load-version` — load a driver version from git

`styrminctl drivers load-version REPOSITORY-URL BRANCH` loads an
application driver version from a git repository. The server clones the
repository, records the commit at the tip of the branch, and reads the
driver from the driver directory. The command needs the `ADMIN` role.

| Argument or option | Default | Purpose |
|--------------------|---------|---------|
| `REPOSITORY-URL` | required | Git repository URL of the driver. |
| `BRANCH` | required | Git branch to load from. |
| `--driver-directory PATH` | the repository root | The directory of the repository that contains `driver.styrmin.yml`, relative to the repository root. |

```shell
uv run styrminctl drivers load-version \
  https://github.com/your-org/styrmin-drivers.git main \
  --driver-directory drivers/infrahub
```

The command prints the loaded driver version, then its component
configs, actions and Helm chart. Load warnings, if any, follow the
`Success:` line:

```text
Success: Application driver version '<version>@<short commit>' loaded (id: <driver version id>)
  Driver ID: <driver id>
  Supported versions: <supported application versions>
  Commit SHA: <40-character commit SHA>
  Driver directory: drivers/infrahub
```

The `Driver directory:` line is printed only for a driver version loaded
from a driver directory. A load from the repository root prints no such
line. `./drivers/infrahub/`, `drivers//infrahub` and `drivers/./infrahub`
load the same driver directory as `drivers/infrahub`, and an empty value
or `.` loads from the repository root.

The server refuses these values before it clones the repository:

- an absolute path, such as `/etc`;
- a path with a `..` segment, such as `../other`;
- a path with a backslash, such as `drivers\infrahub`;
- a path with `{` or `}`;
- a value with a control character, such as a NUL character or a tab;
- a path longer than 255 characters once it is stored.

The server also refuses the load when the driver directory is a symlink
to a path outside the repository, when its `driver.styrmin.yml`,
`values.j2.yml` or `actions.py` is a symlink to a path outside the driver
directory, or when one of them cannot be followed, such as a symlink
loop. These checks apply to loads from the repository root too.

`--driver-directory` needs a Styrmin server that accepts a driver
directory. Against an older server, the command prints `Error:` and a
message that asks you to upgrade the server. Without
`--driver-directory`, the command works against older servers too.

When the server refuses the load or the load fails, the command prints
`Error:` and the server's message, and exits with code 1. When the driver
directory does not exist, is not a directory, or contains no
`driver.styrmin.yml`, the message names the driver directory, the
repository, the branch and the commit:

```text
Error: Driver directory 'drivers/missing' does not exist in repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567).
```

See [Load a driver](../drivers/loading-drivers.md#from-a-git-repository)
for the SDK, GraphQL and UI equivalents, and for how the actions of a
driver version loaded from a driver directory run.

### Related pages

- [Install Styrmin on a local vCluster](../installation/vcluster-local.md):
  an install that logs in with `styrminctl login` and creates the first
  records with the CLI.
