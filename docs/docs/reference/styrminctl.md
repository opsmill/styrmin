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
`deployments`, `drivers`, `backups`, `env-backups`, `backup-locations`,
`tasks`, `auth`, and `telemetry`. `login`, `logout`, and `whoami` are
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
  parameters:
    replicas: 2
```

`spec.parameters` stays a `{name: value}` map.

### Related

- [Installation → Quickstart](../installation/quickstart.md) — the
  CLI's first appearance, plus authentication.
