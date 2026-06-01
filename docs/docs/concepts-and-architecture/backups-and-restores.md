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
  Spaces, MinIO, AWS S3, …) that Velero writes backups to. You
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
