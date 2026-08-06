---
title: Backups and restores
sidebar_position: 6
description: How Styrmin backs up an application stack, and what happens when you restore.
---

## Backups and restores

Backing up an application correctly is application-specific work. A
relational database needs a `pg_dump`. A graph database needs its own
dump tool. A stateless API server doesn't need any application-level
backup at all — just its persistent volumes.

Styrmin's job is to make backups across a whole stack feel like a single
operation, while still doing the right thing per component. This page
explains how.

### The pieces

- **[Velero](https://velero.io/)** — an open-source Kubernetes backup
  tool that snapshots volumes and ships them to S3-compatible object
  storage. Styrmin uses Velero under the hood.
- **A Backup Storage Location (BSL)** — an S3-compatible bucket (DO
  Spaces, Garage, AWS S3, …) that Velero writes backups to. You
  configure one per environment.
- **A backup strategy per component** — declared by the driver. Tells
  Styrmin *how* to back up that specific component.

### Backup strategies

Each component in a driver can declare a backup `kind`. Styrmin maps
kinds to strategies:

| Strategy | What it does | Used for |
|----------|--------------|----------|
| **`disk`** | Snapshot the component's volumes directly. | Stateless workloads, or stores that are safe to snapshot live. |
| **`postgres`** | Run `pg_dump` into a sidecar volume, then snapshot it. | Postgres databases. |
| **`mariadb`** | Run `mariadb-dump` into a sidecar volume, then snapshot it. | MariaDB / MySQL databases. |
| **`mongodb`** | Run `mongodump` into a sidecar volume, then snapshot it. | MongoDB databases. |
| **`neo4j`** | Run `neo4j-admin dump` into a sidecar volume, then snapshot it. | Neo4j graph databases. |
| **`action`** | Run a custom driver-defined Python action. | Anything that doesn't fit the patterns above. |

The driver author picks the strategy per component. The operator runs
the right one when a backup is triggered — you don't think about it.

:::caution Disk backups must name the volume

The `disk` strategy backs up **only the volumes you name** via the
component's `backup.volume` (single) or `backup.volumes` (list) field. The
name is the **pod-template volume name** (the entry under `volumes:` in the
rendered pod spec), not the PVC name. If you set `kind: disk` but omit
`volume`/`volumes`, Velero's opt-in file-system backup captures nothing and
the backup is a silent no-op — the component's data is not protected.

```yaml
server:
  identifier:
    label:
      app.kubernetes.io/name: my-app
  backup:
    enabled: true
    kind: disk
    volume: my-app-storage-data   # required: the pod-template volume name
```

:::

### What happens when you click "backup"

1. You trigger a backup for a deployment (UI, CLI, or GraphQL).
2. Styrmin schedules a Prefect flow on the agent.
3. For each component, Styrmin asks the strategy "what do I need to do
   before and after Velero takes its snapshot?" — for a Postgres
   component, that means running `pg_dump` first.
4. The agent creates a Velero `Backup` object describing what to snapshot
   and which hooks to run.
5. Velero does the snapshotting and ships the result to the BSL.
6. Styrmin records the backup, including the underlying Velero backup
   name, so it can be referenced later.

### What happens when you restore

A restore is the same machinery, run in reverse:

1. You pick a backup and a target deployment (the same one or a
   different one).
2. Styrmin asks each strategy "what do I need to do to bring this
   backup back?" — for a Postgres component, that means restoring the
   dump and replaying it.
3. The agent creates a Velero `Restore` object with the right hooks.
4. Velero pulls the data back from the BSL and lays it down.
5. The restore hooks run and the deployment is now serving the restored
   data.

A restore recreates the namespace from scratch, so your application pods
come back up **while** the restore hooks are still replaying data — Velero
starts everything at once and does not hold the application back. For a
Postgres component that matters: the database the application first
connects to is empty, and an application that migrates its own schema on
startup will try to do so on top of the restore. Styrmin's Postgres
restore hook handles this by locking other clients out of the database
until the dump has been replayed, and by replaying it in a single
transaction so a restore either lands whole or not at all. Your
application may log a few connection errors during that window; it should
reconnect on its own once the restore finishes.

### Why one BSL per environment?

A Backup Storage Location is attached to an **environment**, not to a
deployment. That gives you a few useful properties:

- **All backups for an environment live in one place.** Easy to
  retention-manage, easy to point at a different region per environment.
- **Cloning an environment can also copy its backup history.** If you
  clone production into a test environment, the clone can be pointed at
  the production BSL (or a copy of it) without per-deployment fiddling.
- **A BSL is shared infrastructure.** Setting it up once per environment
  is cheaper than setting it up per deployment.

### Retention: how long a backup lives

Every Velero backup Styrmin creates carries a **TTL** — the duration
Velero keeps it before garbage-collecting the backup and the data behind
it. Left alone, that's **`720h`** (30 days).

Expiry and bucket space are two separate steps: garbage collection drops
the expired backup, and a periodic **repository maintenance** pass then
reclaims the storage behind it. Maintenance runs hourly per backup
repository, and it deliberately leaves recently written data alone for
safety, so expect bucket usage to trail your retention policy rather
than fall the moment a backup expires.

Set `backup_ttl` in config to choose your own. It takes a Go duration
string in `h`, `m`, or `s` units: `2160h` (90 days), `8760h` (a year),
`1h30m`, `1.5h`. There is deliberately **no day unit** — `30d` is not a
Go duration and is rejected, as are `0h`, `-24h`, and a bare `720`. A
malformed value is refused the moment you submit it, with an error that
names `backup_ttl` and hints the `720h` syntax; nothing is stored and no
backup is affected.

#### Three scopes, deepest wins

`backup_ttl` sits on the same shared config as knobs like `db_size`, so
you can set it at three scopes. When a backup is created, the deepest
scope that sets it wins:

| Scope | Where you set it | Use it for |
|-------|----------------|------------|
| **Deployment** | `deploy`'s `config`, or `updateDeployment`'s `input` | One application that needs to keep its backups longer (or shorter) than its neighbours. |
| **Environment** | The environment's **Configuration** tab in the web UI, `createEnvironment`'s `config`, or `updateEnvironment`'s `input` | The usual place — one policy for everything in the environment. |
| **Cluster** | `createCluster`'s `config` | An org-wide baseline. |

A scope that leaves `backup_ttl` unset is transparent: resolution falls
through to the next-shallower scope, and down to the built-in `720h`
when no scope sets a policy. A cluster that never sets it behaves
exactly as before.

Every backup records the TTL that was applied, and the resulting expiry
date is in the backup list in the web UI and in `styrminctl backups
list` — no cluster access needed. The scope the value came from is
recorded internally alongside it and reported in the backup workflow's
log; it is not part of the backup's API surface, so answering "why this
retention?" means reading the workflow log or the scopes' config.

:::note Cluster scope is set at registration

There is no cluster-update mutation, so the cluster-scope value is
whatever you passed to `createCluster`'s `config`. To change a broad
default afterwards, set it at environment scope instead.

:::

#### Setting a retention policy

The environment scope has a form field. Open the environment, go to the
**Configuration** tab, and edit **Retention (`backup_ttl`)** in the
**Backup Retention** section. It takes the same Go duration string,
refuses a malformed one before it is submitted, and carries the rest of
the environment's configuration back unchanged. Saving is an
`updateEnvironment` like any other, so it fans out a redeploy to the
environment's deployments — the confirmation dialog names them before
anything happens. Leave the field empty and save to **clear** the
environment policy: retention then falls through to the cluster scope, or
to the built-in `720h`. An environment that carries `dedicated_ingress` or
`scheduling` overrides is the exception — the form cannot map those yet, so
it disables Save rather than clear them, and you set retention for that
environment through the API instead.

The other two scopes have no dedicated control, and `styrminctl` has no
retention flag at any scope. You set those through the generic config
surfaces: the GraphQL API (or the Python SDK, which wraps the same
mutations), or `styrminctl`'s `--config` payloads and deployment
manifests.

Watch the key casing — it follows the surface, not the feature:

| Surface | Key |
|---------|-----|
| `updateEnvironment` / `updateDeployment` `input`, `deploy`'s `config` | `backupTtl` (GraphQL input types are camelCase) |
| `createEnvironment`'s / `createCluster`'s `config` | `backup_ttl` (raw JSON, persisted as-is) |
| `styrminctl deployments update --config` | `backupTtl` or `backup_ttl` (both accepted) |
| `spec.config` in a `styrminctl deployments apply` manifest | `backupTtl` |
| `styrminctl environments create --config`, `styrminctl clusters create --config` | `backup_ttl` |

`updateEnvironment` takes the **complete desired configuration**, so
read the environment's current config first:

```graphql
query ReadEnvironmentConfig {
  environment(environmentName: "production", clusterName: "default") {
    id
    config
  }
}
```

(Looking an environment up by name needs cluster context — pass
`clusterName` or `clusterId` alongside it, or just use `environmentId`.)

Then submit it back with `backupTtl` added:

```graphql
mutation SetEnvironmentRetention {
  updateEnvironment(
    environmentId: "<environment-id>"
    input: {
      backupTtl: "2160h"
      ingressClass: "nginx"
      fqdnSuffix: "example.com"
    }
  ) {
    id
    config
  }
}
```

:::caution `updateEnvironment` replaces the whole config

`UpdateEnvironmentInput` is a **full-replacement** input: every field you
omit is persisted as its unset state. Carry the fields you want to keep
in the same call, or you'll clear them. This cuts both ways — the web UI
does the round-trip for you, so editing an environment variable in the
UI will not wipe a retention policy you set here, and saving the
retention field will not wipe the settings you set through the API.

:::

For a single application, set it in the deployment's config instead —
`backupTtl` on `deploy`'s `config` or `updateDeployment`'s `input`, or
`backupTtl` under `spec.config` in a `styrminctl` deployment manifest.
`updateDeployment` is full-replacement in the same way.

#### A change applies to future backups only

Velero fixes a backup's expiration at creation time, so changing
`backup_ttl` **does not** move the expiry of backups that already exist,
and Styrmin deliberately does not try to rewrite them. The new value
takes effect on the next backup you create. Shorten retention and the
existing backups still disappear on their original schedule; lengthen it
and the ones already taken are not rescued.

:::caution Restoring from an expired backup fails

When a backup's TTL elapses, Velero garbage-collects its data but
Styrmin's record of the backup stays in the list. A restore from an
expired backup fails at the Velero step. A short `backup_ttl` surfaces
this sooner, so check the expiry column before picking a backup to
restore from.

:::

### Backing up a whole environment

Everything above is per-deployment: one application, one backup. An
**environment backup** does the same thing for every application in an
environment in one action, and keeps the result together as a single
record — so you never again have to remember by hand which five backups
formed last Tuesday's snapshot.

One action — the **Backups** tab on the environment page, one
`styrminctl env-backups create`, or one `createEnvironmentBackup` call —
captures three things:

- the **environment's config** as it stands at that moment;
- the **declared state of every eligible deployment**: its Application
  Driver, driver version and provenance fingerprint, application
  version, config, and parameters;
- one **constituent backup** per eligible deployment — an ordinary
  per-deployment backup, taken by exactly the machinery described above,
  writing to the same BSL, expiring under the same retention rules.

A deployment is **eligible** when it isn't tombstoned, isn't one of
Styrmin's own internal deployments (the environment's ingress
controller, for instance), and has a running instance to back up. Its
current state doesn't matter — a `FAILED` deployment with an active
instance still contributes a constituent.

An environment with no eligible deployments is not an error: you get a
config-only snapshot that reports `COMPLETED` immediately. That is the
useful shape for capturing an environment's settings before you populate
it.

#### Near-consistent, not stop-the-world

Constituent backups are all started together and run in parallel.
Nothing is quiesced — no component is stopped, no writes are frozen, and
the constituents do not finish at the same instant. The snapshot is
**near-consistent**: the right tool for getting an environment back to a
known-good state, not a distributed transaction. If one application
needs a genuinely quiesced backup, stop its components and back that one
up on its own.

A per-deployment conflict never derails the rest. If one deployment
already has a backup running, that constituent is recorded as failed
with the reason attached and its neighbours carry on — the environment
backup never waits for it and never aborts because of it.

#### Status is derived, never stored

An environment backup has no status column of its own. Every time you
read one, Styrmin computes its status from its constituents:

| Status | What it means |
|--------|---------------|
| `PENDING` | Nothing has started yet. |
| `IN_PROGRESS` | At least one constituent is still running. |
| `COMPLETED` | Every constituent completed and none failed to start. |
| `PARTIAL` | At least one constituent completed and at least one did not. |
| `FAILED` | Nothing completed. |

Because the status is recomputed on every read, it can never drift out
of step with the constituents it summarises. It also means `PARTIAL` is
a first-class, normal outcome rather than a bug: the snapshot is real and
restorable, and the constituents it is missing are named on it. Expand a
snapshot in the UI — or run `styrminctl env-backups get <id>` — to see
each deployment's constituent, its status, or the error that stopped it
being created.

:::caution A fresh `COMPLETED` is not proof the fan-out finished

Styrmin commits the environment backup record *before* it starts
dispatching constituent backups, so a crash mid-fan-out leaves a real
snapshot rather than a half-written one. The side effect: for a moment
after creation, the record has zero constituents and zero errors — and
"nothing failed" derives to `COMPLETED`. A snapshot read inside that
window looks finished when its constituents haven't been created yet.

Don't treat an immediate `COMPLETED` as evidence that every deployment
was captured. Check that the constituent count matches the number of
eligible deployments — the CLI prints it as `ok/failed/total` — and
re-read the snapshot rather than trusting the first status you see.
`--wait` polls for a terminal status, which does not close this window
either.

:::

#### Restoring an environment

Restoring a `COMPLETED` or `PARTIAL` environment backup is also one
action. Styrmin reverts the environment's config to the captured value
and restores every usable constituent **in place**, back into the
deployment it came from.

Two things it deliberately does **not** do:

- **It never creates or deletes deployments.** Restoring is a config-and-
  data operation, not a topology one. A deployment you deleted since the
  backup is not recreated; a deployment you added since is not removed.
- **It never touches data it has no backup for.** A deployment created
  after the snapshot keeps its data untouched. It does still pick up the
  reverted environment config, through the same config propagation any
  environment edit triggers — that is the intended outcome, not a leak.

Every constituent that is **not** restored is reported with its
deployment name and a reason. There are no silent skips — if a
deployment isn't in the restore's list of restored constituents, it is in
the skipped list with one of these reasons:

| Reason | What happened |
|--------|---------------|
| `backup failed at creation` | The constituent backup never got started — usually a conflicting backup already running at snapshot time. |
| `backup not completed` | The constituent backup exists but didn't finish successfully. |
| `backup deleted` | Someone deleted that constituent backup individually. |
| `backup expired` | The constituent's retention TTL elapsed and Velero garbage-collected the data. |
| `deployment no longer exists` | The deployment was deleted (or tombstoned) after the snapshot was taken. |
| `deployment busy with another restore` | A separately started restore is already running on that deployment. |

The reason is free text, so treat it as a message to read rather than a
fixed set of codes to switch on.

:::note Restoring an environment requires the administrator role

Creating and deleting environment backups needs the same role as an
ordinary per-deployment backup. **Restoring** one needs the
administrator role, because it rewrites the environment's config — the
same privilege you need to edit that config directly. The UI hides the
restore action from anyone without it.

:::

A restore's status is derived from its constituent restores exactly the
way a backup's is, with the same `PARTIAL` semantics. And the same
caveat applies at the far end: when the restore reports a terminal
status, its constituent data restores are done, but the reverted config
may still be propagating to the deployments that *didn't* receive a
restore. That propagation is tracked by those deployments' own
reconciliations — watch their status, not the restore's.

#### One environment operation at a time

An environment runs at most one environment-level operation — backup or
restore — at a time. A second request while one is in flight is
rejected with a machine-readable error rather than queued. Different
environments never block each other, and per-deployment backups and
restores keep their own separate guards.

"In flight" is derived from the constituents too, which has one sharp
edge: if a constituent backup never gets picked up, it stays
non-terminal, its snapshot stays non-terminal, and the environment stays
blocked. Deleting the snapshot is the way out — see below.

#### Deleting snapshots

Deleting an environment backup deletes its constituent backups and any
restores of them, in one action. Retention still works per constituent:
each one expires on its own TTL, so an old snapshot decays piecewise and
its record survives even after every constituent has expired. The gaps
stay visible, which is the point — a snapshot that can only restore
three of its five applications should say so.

Deleting works **regardless of status**, including while constituents
are still running. That is deliberate: it's the escape hatch for a
snapshot pinned in progress by a constituent that never ran, and it's
what releases the environment for new operations.

Deleting an environment takes its environment backups with it. In this
release a snapshot does not outlive its environment.

### What you set up vs what Styrmin handles

| Step | What it covers |
|------|----------------|
| Once per environment | The bucket, credentials, and Velero BSL configuration. |
| Once per driver | The backup `kind` per component, in the driver spec. |
| Per backup | Nothing — Styrmin orchestrates the rest. |

### Next

- [**Lifecycle hooks and actions**](./hooks-and-actions.md) — backup is
  one of the hooks the driver can attach actions to.
- [**Ingress and networking**](./ingress-and-networking.md) — the other
  big per-environment subsystem.
