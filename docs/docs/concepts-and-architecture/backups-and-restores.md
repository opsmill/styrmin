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
  Styrmin _how_ to back up that specific component.

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
5. The restore hooks run, the application comes back up, and the
   deployment is now serving the restored data.

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
