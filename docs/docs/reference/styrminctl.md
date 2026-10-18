---
title: styrminctl CLI
sidebar_position: 3
description: Reference for every command, flag, and exit code in the styrminctl CLI.
---

## `styrminctl` CLI

:::info Partial reference — the full command tree is still to be auto-generated

The sections below are hand-written and **authoritative for the commands
they cover**: they document the behaviour `--help` cannot carry, such as
identifier precedence and exit codes. They are not a complete
command-by-command reference yet — that will be generated from the
Cyclopts command tree at build time.

For anything not covered here, the CLI itself is the source:

```bash
styrminctl --help
styrminctl <command> --help
```

Plus the source tree under
[`cli/`](https://github.com/opsmill/styrmin/tree/develop/cli).

:::

### Scope

`styrminctl` is the Cyclopts-based command-line client for Styrmin.
It's a thin wrapper over the GraphQL API — it never talks to the
database or the agent directly.

Its top-level command groups are `clusters`, `environments`,
`deployments`, `drivers`, `backups`, `env-backups`, `env-clones`,
`backup-locations`, `tasks`, `auth`, and `telemetry`. `login`, `logout`, and `whoami` are
also registered at the top level as shorthands for their `auth`
sub-commands. Everything else — restoring a backup, upgrading a
deployment's version — is a sub-command inside one of those groups, not a
group of its own.

Once auto-generation lands, this page will document, command by command:

- Every group, sub-command, and flag
- Output formats (`--output text|json|yaml`)
- Exit codes
- Authentication and configuration (where the CLI looks for a
  server URL and a token)

### Auto-generation source

- **Schema**: the Cyclopts command tree in
  [`cli/src/`](https://github.com/opsmill/styrmin/tree/develop/cli/src)
- **Build step**: TBD — walk the Cyclopts tree, emit one Markdown
  section per command, write it into this file

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
command prints a table whose `config` column cuts long values, so do not
copy the config from the table.

Two updates are not merged: the update saved last wins. A file that you
saved before another administrator's update reverts that update, so read
the stored config with `clusters get --json` immediately before you edit
it. The edit dialog warns you when the config changed after you opened
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
its own config, where the deepest value wins. When this config differs
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
  `update_instance` task. Follow one with
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

Styrmin starts the redeploys before it answers, environment by
environment. The command waits up to 10 minutes. If it times out, the
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
`cluster_config_updated` server log line holds the previous values.

#### Storage class change on a StatefulSet

Kubernetes refuses any change to the volume claim templates of an
existing StatefulSet, and an application driver can write the storage
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

The `env-backups` group covers whole-environment snapshots: one command
backs up every eligible deployment in an environment, and one restores
them. Per-deployment backups stay in the `backups` group. The two groups
are separate because the `backups` commands target one deployment or one
instance, and the `env-backups` commands target an environment:

- `backups list` and `backups restore --last` work on a deployment's
  backup history: the backups of every instance the deployment has had.
  `backups list` takes the deployment by name or by `--id`, and
  `backups restore --last` takes it with `--target-deployment` or
  `--target-deployment-id`. See [Backup history of a
  deployment](../concepts-and-architecture/backups-and-restores.md#backup-history-of-a-deployment).
- `backups restore --last` skips backups whose expiry date has passed.
  When the backup it chooses was taken of an earlier instance, it shows
  the backup's application version and the deployment's current one,
  and asks for confirmation. `--yes` skips the question, and without a
  terminal the command refuses unless you pass `--yes`.
- `--instance-id` on `backups list` and `--target-instance-id` on
  `backups restore` work on one instance only.

For the semantics behind the `env-backups` commands, read [Backups and
restores](../concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment).

Seven commands:

| Command | What it does |
|---------|--------------|
| `env-backups create [ENVIRONMENT]` | Create a coordinated backup of an environment. |
| `env-backups get <ENVIRONMENT_BACKUP_ID>` | Show one snapshot, including per-constituent outcomes. |
| `env-backups list [ENVIRONMENT]` | List an environment's snapshots, newest first. |
| `env-backups restore <ENVIRONMENT_BACKUP_ID>` | Restore a snapshot in place. Requires the administrator role. |
| `env-backups restore-get <ENVIRONMENT_RESTORE_ID>` | Show one restore, including skipped constituents and their reasons. A redeploy that the restore could not start is not listed ([#520](https://github.com/opsmill/styrmin/issues/520)). |
| `env-backups restore-list <ENVIRONMENT_BACKUP_ID>` | List the restores performed from a snapshot, newest first. |
| `env-backups delete <ENVIRONMENT_BACKUP_ID>` | Delete a snapshot, its constituent backups, and their restores. |

#### Targeting an environment

`create` and `list` take the environment as a positional name, or as a
UUID with `--id`. Passing both — or neither — is an error. A name is
resolved within a cluster, so pass `--cluster <name>` (defaults to
`default`) or `--cluster-id <uuid>` when you have more than one cluster
registered.

`--cluster-id` combined with an explicitly named, non-default `--cluster`
is an error. `--cluster-id` alongside the default `--cluster default` is
accepted — the CLI cannot tell a defaulted value from a typed one — and
`--cluster-id` wins: the name lookup is sent with the cluster id and no
cluster name.

```bash
styrminctl env-backups create production --name before-upgrade
styrminctl env-backups list production
styrminctl env-backups list --id <environment-uuid>
```

Every other command takes a snapshot or restore UUID directly.

#### `create` options

| Option | Default | Purpose |
|--------|---------|---------|
| `--name` | generated | Snapshot name. Defaults to `styrmin-envbackup-<uuid>`. |
| `--wait` | off | Block until every constituent backup reaches a terminal state. |
| `--max-wait` | `600` | Seconds to wait, with `--wait`. |
| `--interval` | `5` | Poll interval in seconds, with `--wait`. |

`create` prints the snapshot's derived status and a constituent count in
`ok/failed/total` form, then one line per constituent with its own
failure reason when it has one. `ok` counts constituents whose backup
**completed**, `failed` counts constituents that never got a backup at
all, and anything still running or since deleted shows up only in
`total`. Compare `total` against the number of eligible deployments —
that count, not the status, is what tells you the fan-out covered
everything.

#### `restore` options

| Option | Default | Purpose |
|--------|---------|---------|
| `--wait` | off | Block until every constituent restore reaches a terminal state. |
| `--max-wait` | `900` | Seconds to wait, with `--wait`. |
| `--interval` | `5` | Poll interval in seconds, with `--wait`. |

`restore` prints the restored constituents and every skipped one with its
deployment name and reason, before any waiting. The skip list is complete
the moment the command returns — classification happens up front.

#### Exit codes

`create` and `restore` exit **non-zero on `PARTIAL` as well as on
`FAILED`**, with or without `--wait`. A `PARTIAL` snapshot is real and
restorable, but you asked to back up (or restore) a whole environment
and did not get every deployment — the exit code is the only
machine-readable place to say so, and a CI job that treats it as success
will not notice the gap.

The status is derived from the constituents on every read, so it can
already be `PARTIAL` or `FAILED` when the command returns: a fan-out
where every constituent was busy, or a restore where every constituent
was skipped, is finished before there is anything to wait for. In that
case the command reports the outcome and exits non-zero immediately
rather than polling. Without `--wait`, a command whose constituents are
still running exits successfully once the operation is accepted.

**A `--wait` that times out also exits 1.** `--max-wait` elapsing is not
an error the CLI distinguishes: the poll returns the last record it read,
so the command prints the non-terminal status it saw (`PENDING` or
`IN_PROGRESS`) and exits non-zero. Raise `--max-wait` rather than reading
that exit code as a failed backup — nothing has been abandoned, and the
constituents keep running.

:::note `delete` has no status guard

`env-backups delete` works regardless of the snapshot's status,
including while its constituents are still running. That is the escape
hatch for an environment blocked by a constituent backup that never got
picked up — deleting the snapshot releases the environment for new
environment-level operations.

:::

### `env-clones` — clone an environment

The `env-clones` group copies a live environment into a **new**
environment on the same cluster, built from a fresh environment backup of
the source, and tracks the operation afterwards. For the semantics behind
these commands — selection, the config override, what a clone is and
isn't isolated from — read [Cloning an
environment](../concepts-and-architecture/backups-and-restores.md#cloning-an-environment).

Three commands:

| Command | What it does |
|---------|--------------|
| `env-clones create [ENVIRONMENT] --name <new-name>` | Clone an environment into a new one. Requires the administrator role. |
| `env-clones get <ENVIRONMENT_CLONE_ID>` | Show one clone: derived status, per-deployment outcomes, operation-level events. |
| `env-clones list [ENVIRONMENT]` | List the clones taken **of** an environment, newest first. |

`create` and `list` target the source environment exactly the way
`env-backups` does: a positional name, or a UUID with `--id`, resolved
within `--cluster` (default `default`) or `--cluster-id`. Passing both a
name and `--id` — or neither — is an error.

`list` is scoped by **source**. A clone-born environment's own provenance
is an entry in its *source's* list, not in its own: run `env-clones list`
against the **source** environment, or `env-clones get <id>` on the clone
record itself. (The reverse lookup — from the created environment back to
the clone that made it — is the `Environment.clonedFrom` field, which the
UI and the GraphQL API expose; no `styrminctl` command reads it.)

#### `create` options

| Option | Default | Purpose |
|--------|---------|---------|
| `--name` | *required* | Name of the new environment to create. |
| `--deployment` | all eligible | A source deployment to include, by **name or UUID**. Repeat for several. Omit to include every eligible deployment. |
| `--config-override` | none | JSON `UpdateEnvironmentInput` merged over the captured config, inline or `@path/to/file.json`. camelCase or snake_case keys. |
| `--clear-config-field` | none | A captured config field to remove before the merge, by **snake_case** field name. Repeat for several. |
| `--wait` | off | Block until the clone reaches a terminal state. |
| `--max-wait` | `1800` | Seconds to wait, with `--wait`. Clones capture, create and restore, so the default is longer than `env-backups`'. |
| `--interval` | `5` | Poll interval in seconds, with `--wait`. |

`--deployment` accepts deployment **names**, resolved within the source
environment, as well as UUIDs. A name with no match in the source is
rejected by the CLI before the mutation is sent.

Omitting `--deployment` and passing an **empty** selection are different
requests. Omit it for "every eligible deployment"; pass Cyclopts'
generated `--empty-deployment` for "no applications at all", which clones
the environment's configuration only and settles on `COMPLETED` once that
environment exists. `env-clones get` tells the two apart: `all eligible`
versus `none (configuration only)`.

When the environment's config has an affinity term that names a
deployment, an empty selection is rejected with `VALIDATION_ERROR`,
because the clone copies no deployment. The error message names each
such deployment and the path of every term that names it. Add
`--clear-config-field scheduling`, or give a `scheduling` that names no
deployment in `--config-override`.

`--config-override` is an `UpdateEnvironmentInput` payload, so `envVars`
is a list of `{name, value}` entries rather than a map. camelCase keys
(`backupTtl`, `fqdnSuffix`) are the GraphQL spelling and always work;
the CLI also accepts their snake_case equivalents. `--clear-config-field`
names, by contrast, are **only** snake_case — that list is validated
against the config's own field names, not against the input type.

`create` prints the clone's id, its derived status, the source name, and
a `cloned/skipped/failed/total` deployment count, then one line per
source deployment with its outcome and reason, then any operation-level
events.

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

Track and inspect afterwards:

```bash
styrminctl env-clones list production
styrminctl env-clones get <environment-clone-id>
```

#### Exit codes

`create` exits **0 on `COMPLETED`**, and **1 on both `PARTIAL` and
`FAILED`** — `PARTIAL` with an explicit warning, because you asked for a
copy of an environment and did not get every deployment you selected.

The status is derived on every read, and the first reading — the one the
mutation returns — is always non-terminal: `PENDING`, or `IN_PROGRESS`
once anything has been recorded (an up-front skip counts). Even an
all-skipped, configuration-only clone reads `IN_PROGRESS` until its
environment exists. So a terminal status only ever comes from polling:
`create` reaches it with `--wait`, and `get` shows it afterwards.

Without `--wait`, a clone that is still working exits 0 once it has been
accepted. As with `env-backups`, a `--wait` that runs out of `--max-wait`
also exits 1: the CLI prints the non-terminal status it last saw and
stops waiting. Nothing has been abandoned — raise `--max-wait` rather
than reading that as a failed clone.

:::note There is no `env-clones delete`

A clone is discarded by deleting the **environment it created**
(`styrminctl environments delete <name>`), which works in any state and
frees the name for an immediate re-clone. If the clone stalled before its
environment appeared, delete its backing snapshot with `env-backups
delete <id>` instead. See [Discarding a
clone](../concepts-and-architecture/backups-and-restores.md#discarding-a-clone).

:::

### `deployment apply` is idempotent

`styrminctl deployment apply -f <manifest>` is declarative: the CLI
sends the full desired state on every run and the **backend** decides
whether anything actually changed. Re-applying an unchanged manifest is
a clean no-op — no new application instance is created, no reconcile
task is dispatched, and the deployment's active instance and status are
left untouched. The command still exits successfully.

Each deployment in a run is reported with its outcome:

- `created <name>` — a new deployment was provisioned.
- `updated <name>` — the desired state differed and a reconcile was
  dispatched.
- `unchanged <name>` — the resolved desired state already matched the
  live state; nothing was done.
- `failed <name>: <reason>` — the apply errored for that deployment. When
  the server rejected the manifest, the line ends with the server's error
  code, for example `[COMPONENT_CONTAINER_NOT_DECLARED]`, and nothing on
  the deployment changed.

A run ends with a summary line counting each outcome, for example:

```text
2 created, 1 updated, 3 unchanged, 0 failed
```

A run consisting solely of no-ops still exits with a success code, so
`apply` is safe to run repeatedly in a declarative loop.

For an existing deployment, `apply` sends the manifest's config,
parameters and version in one request. This needs a Styrmin server with
[#388](https://github.com/opsmill/styrmin/issues/388): against an older
server, every update fails with a message that says to upgrade the
server. Upgrade the server before or together with `styrminctl` and the
SDK.

:::note Re-applying a failed deployment

A no-op apply against a deployment in a terminal-failure state stays a
no-op — `apply` compares desired intent against current intent, not
health, so it will not retry a broken-but-unchanged deployment.

:::

:::note Rebuilt image under an unchanged version

`apply` compares the *resolved desired state*, which is keyed on the
application version (and driver version), not on image content. An
application image rebuilt and re-pushed under the **same** version, with
unchanged config, resolves to an identical instance and is therefore a
no-op — `apply` will not redeploy it. Bump the version to force a
redeploy.

:::

### Failure reasons of `deployments apply --wait`

With `--wait`, `apply` prints `submitted <name>` when it submits a
change, then `running <name>` or `failed <name>: <reason>` when the
deployment reaches a final state. For an upgrade, `running` comes only
after the upgrade task and the tasks its driver hook started have
finished (see
[Status reporting](../concepts-and-architecture/status-reporting.md)).
When the deployment state becomes `FAILED`, the reason names the failed step, in the form
`step "<step name>" failed: <error>`. `apply` looks for it in the steps of
the task that the apply started, then in the tasks that the task's hook
steps started, nearest first. When it finds no failed step, the reason
is `deployment reconciliation failed (status: <status>)`.

`--wait` gives up after `--max-wait` seconds (600 by default) with the
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

`chart` carries no number, because Styrmin does not read the count that
the chart renders.

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

When the command changes the deployment's driver version and the target
driver version no longer declares a parameter that the deployment sets,
Styrmin drops the value if it equals the parameter's default in the
current driver version. Any other value fails the command with
`RETIRED_PARAMETER_VALUE` before any task starts. `deployments apply`
follows the same rule. See
[Changing Driver Versions](../drivers/changing-driver-versions.md) and
[Migrating Replica Parameters](../drivers/migrating-replica-parameters.md).

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
   `message` and `deploymentId`. `status` follows only the Prefect flow
   run; `result` is the task result, calculated from the steps and the
   `status` of the task and of the tasks its hook steps started
   (`RUNNING`, `FAILED`, `SUCCEEDED` or `SUPERSEDED`).
2. A "Steps" table with one row per step, in start order with pending
   steps last: `step` (the step's name), `status`, `duration` (`running`
   while the step runs), `attempts` and `error`. The `error` column holds
   the error of each failed attempt as `attempt <n>: <message>`, oldest
   first, then FluxCD's current reason for the HelmRelease step, then the
   last line of a failed command's output as `output: <line>`, one per
   line. A task without steps prints "No steps recorded for this task."
   instead.
3. A "Started tasks" table with the `id`, `type` and `result` of each
   task that the task's hook steps started. It is printed only when there
   is one.

The full output of a failed command is on the deployment page.

### Manifest `spec.config` shape

`spec.config` accepts the same typed configuration whether `apply` creates
or updates a deployment. Environment variables — both deployment-scoped and
per-component — are written as a **list of `{name, value}` entries**, not as
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

`components[].image` is the component's
[image override](../concepts-and-architecture/image-overrides.md): one full
reference with an explicit tag or digest, where every `{{ app.version }}`
token becomes the deployment's application version. Quote it, since YAML
reads an unquoted `{` as a map. Removing the key clears the override on the
next apply, unless that leaves `spec.config` empty: an omitted or empty
`spec.config` keeps the stored configuration, so write `components: []` to
clear the last override. A reference that fails the image grammar, has no tag or digest,
carries another template expression, or becomes invalid once
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
rejected even when it is unchanged, with one exception: a block that holds
only `replicas`, sent with the stored value unchanged, is accepted, stored and
not applied. When a driver version removes or renames a component, remove its
block from the manifest in the same change that moves `spec.version`. Unchanged
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
See [Migrating env var wiring](../drivers/migrating-env-vars.md) and
[Migrating container overrides](../drivers/migrating-container-overrides.md).

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
the config, so it lists every token-free override, including one on a
component whose override does not currently apply. The SDK returns the same
components as `ApplyOutcome.pinned_image_components`, with
`ApplyOutcome.target_version` set on an `updated` outcome that changes the
version.

:::note Overrides in the apply that changes the version

Every component override (`env_vars`, `command`, `args`, `image`, `replicas`)
is checked against the target driver version, so all of them can go in the
apply that changes `spec.version`. The driver's upgrade action can start before the new
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
| `--driver-directory PATH` | the repository root | Folder of the repository that holds driver.styrmin.yml, relative to the repository root. |

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
directory does not exist, is not a folder, or holds no
`driver.styrmin.yml`, the message names the driver directory, the
repository, the branch and the commit:

```text
Error: Driver directory 'drivers/missing' does not exist in repository 'https://github.com/your-org/styrmin-drivers.git' (branch 'main', commit 0123456789abcdef0123456789abcdef01234567).
```

See [Loading a Driver](../drivers/loading-drivers.md#from-a-git-repository)
for the SDK, GraphQL and UI equivalents, and for how the actions of a
driver version loaded from a driver directory run.

### Related

- [Installation → Quickstart](../installation/quickstart.md) — the
  CLI's first appearance, plus authentication.
