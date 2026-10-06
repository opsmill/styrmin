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

### `env-backups` — environment-level backup and restore

The `env-backups` group covers whole-environment snapshots: one command
backs up every eligible deployment in an environment, and one restores
them. Per-deployment backups stay in the `backups` group — the two are
deliberately separate namespaces, because `backups` options are
instance-scoped (`--deployment`, `--instance-id`) and these are not. For
the semantics behind these commands, read [Backups and
restores](../concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment).

Seven commands:

| Command | What it does |
|---------|--------------|
| `env-backups create [ENVIRONMENT]` | Create a coordinated backup of an environment. |
| `env-backups get <ENVIRONMENT_BACKUP_ID>` | Show one snapshot, including per-constituent outcomes. |
| `env-backups list [ENVIRONMENT]` | List an environment's snapshots, newest first. |
| `env-backups restore <ENVIRONMENT_BACKUP_ID>` | Restore a snapshot in place. Requires the administrator role. |
| `env-backups restore-get <ENVIRONMENT_RESTORE_ID>` | Show one restore, including skipped constituents and their reasons. |
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
- `failed <name>` — the apply errored for that deployment.

A run ends with a summary line counting each outcome, for example:

```text
2 created, 1 updated, 3 unchanged, 0 failed
```

A run consisting solely of no-ops still exits with a success code, so
`apply` is safe to run repeatedly in a declarative loop.

:::note Re-applying a failed deployment

A no-op apply against a deployment in a terminal-failure state stays a
no-op — `apply` compares desired intent against current intent, not
health, so it will not retry a broken-but-unchanged deployment.
Recovering such a deployment is a separate refresh path.

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
deployment reaches a final state. When the deployment state becomes
`FAILED`, the reason names the failed step, in the form
`step "<step name>" failed: <error>`. `apply` looks for it in the steps of
the task that the apply started, then in the tasks that the task's hook
steps started, nearest first. When it finds no failed step, the reason
is `deployment reconciliation failed (status: <status>)`.

`--wait` gives up after 300 seconds with the reason `wait timeout`. The
operator's default readiness timeout is also 300 seconds, but counts from
the start of the rollout, which is later, and FluxCD retries a failed
release before it reports it as stalled. A failed HelmRelease can
therefore end the wait with `wait timeout` instead of a step. Read the steps
with `styrminctl tasks get <task-id>`; `styrminctl tasks list` shows the
type and deployment of each task.

### `tasks get` — a task's steps

`styrminctl tasks get <task-id>` prints three parts:

1. A "Task" table with the columns `id`, `type`, `status`, `result`,
   `message` and `deploymentId`. `status` follows only the Prefect flow
   run; `result` is the task result, calculated from the task's steps and
   from the tasks its hook steps started (`RUNNING`, `FAILED`,
   `SUCCEEDED` or `SUPERSEDED`).
2. A "Steps" table with one row per step, in start order with pending
   steps last: `step` (the step's name), `status`, `duration` (`running`
   while the step runs), `attempts` and `error`. The `error` column holds
   the newest error, FluxCD's current reason for the HelmRelease step, and
   the last line of a failed command's output, one per line. A task
   without steps prints "No steps recorded for this task." instead.
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
  parameters:
    replicas: 2
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

Adding or changing per-component `env_vars` or `image` on a component whose
driver version declares no component container fails with
`COMPONENT_CONTAINER_NOT_DECLARED`. `apply` writes `spec.config` before it
moves the deployment to a new driver version, so the check runs against the
current version. See
[Migrating env var wiring](../drivers/migrating-env-vars.md).

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

:::note Image override and version change in one apply

`apply` writes `spec.config` before it changes the version, but the driver's
upgrade action can read the component's workload before the new override
reaches it. Its first Job can then run with the previous image repository.
Apply the override on its own first, then change the version in a second
apply.

:::

### Related

- [Installation → Quickstart](../installation/quickstart.md) — the
  CLI's first appearance, plus authentication.
