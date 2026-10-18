---
title: Backups and restores
sidebar_position: 6
description: How Styrmin backs up an application stack, what happens when you restore, and how cloning an environment works.
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

#### Backup size

The size shown for a completed backup (`sizeBytes` in GraphQL, `size_bytes`
in the SDK and `styrminctl backups`) is the number of bytes of volume data
that Velero read from the deployment's volumes. Styrmin adds up the bytes
that each of Velero's `PodVolumeBackup` objects reports for the backup.

- The value is measured before Velero deduplicates and compresses the data,
  so the space the backup uses in the BSL is usually smaller.
- The Kubernetes resource definitions that Velero also stores are not
  counted.
- The size is empty when the backup captured no volume data (for example,
  no component declares a backup strategy, or a `disk` component names no
  volume), when the backup did not complete, or when Styrmin could not read
  the `PodVolumeBackup` objects.

### Backup history of a deployment

Each backup is a backup of one instance of a deployment. When you back
up a deployment, Styrmin backs up its active instance. A deployment gets
a new instance, which becomes its active instance, after each of these
operations:

- an upgrade of the deployment to another application version
- an edit of the deployment's config
- a change to the config of the deployment's environment, which
  redeploys every deployment in that environment
- a change to the cluster config that changes the deployment's resolved
  config (see
  [When an environment or cluster config changes](./reconciliation.md#when-an-environment-or-cluster-config-changes))

The deployment's Backups tab, `styrminctl backups list <deployment>`
and the `backups(deploymentId:)` GraphQL query list the deployment's
backup history: the backups of every instance the deployment has had,
newest first. A backup you created before one of these operations stays
in the list. Each backup shows the application version of the instance
it was taken of, in the "Application version" column of the Backups tab
and the `application_version` column of `styrminctl backups list`. On
the Backups tab, the backups of the active instance are marked "current
instance".

To list the backups of one instance only, run
`styrminctl backups list --instance-id <instance-id>` or query
`backups(instanceId:)`.

#### Expired backups

Velero deletes a backup when its expiry date has passed, but Styrmin
keeps the backup's status `completed`. On the Backups tab, such a backup
shows "Expired" under its expiry date, and its restore action is
disabled. `styrminctl backups restore --last` skips it and chooses the
newest completed backup that has not expired. An environment restore
also skips expired backups.

#### Restoring a backup of an earlier instance

You can restore a backup of an earlier instance into the deployment,
for example a backup taken before an upgrade. The restore puts the
earlier instance's `StyrminDeployment` and `HelmRelease` back in the
deployment's namespace, with that instance's application version and
config. Styrmin does not change the deployment's active instance, so the
deployment page and `styrminctl` keep showing the application version of
the active instance.

Before such a restore:

- The Restore dialog on the Backups tab shows the backup's application
  version and the deployment's current application version, and warns
  that the backup was taken of an earlier instance.
- `styrminctl backups restore --last` shows both versions and asks for
  confirmation. Pass `--yes` to restore without the question. Without a
  terminal and without `--yes`, the command refuses the restore.

A restore of a backup whose ID you pass to `styrminctl backups restore`
asks no question.

#### Backup history of a deleted deployment

A deleted deployment keeps its backup history:

- On the environment's page, turn on "Show deleted" and open the
  deleted deployment. Its Backups tab lists the history. The restore and
  delete actions on each backup are disabled, as every action is on a
  deleted deployment.
- From the CLI, run `styrminctl backups list --id <deployment-id>`. The
  lookup by name does not find a deleted deployment. To find the
  deployment id, open the deleted deployment as described above: the id
  is the last part of the page's URL,
  `/environments/<environment-id>/deployments/<deployment-id>`.

A deleted deployment's backups cannot be restored, into the deleted
deployment or into another deployment. Styrmin refuses such a restore
with the error code `OPERATION_DENIED`. An environment restore and an
environment clone also skip a deleted deployment.

A new deployment that reuses the name of a deleted deployment starts
with an empty backup history, because the history is listed by
deployment id, not by name. The deleted deployment keeps its own
history, which you reach by its id.

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

A restore keeps the [service aliases](./ingress-and-networking.md#service-aliases)
of the restored deployment in the other namespaces of its environment, and
Velero restores the aliases in its own namespace. A deployment of the
environment that is created, updated or upgraded while the restore runs
skips the aliases between itself and the restored deployment, because the
restored deployment's namespace is being deleted or does not exist yet.
Nothing writes them after the restore, so the two applications cannot
reach each other by short name. Once the restore has finished, make a
change to either deployment, such as a change to its configuration or its
parameters, to write the aliases. Saving the same values does not change
the deployment, so it writes no alias.

The restore that an [environment clone](#cloning-an-environment) runs
into each counterpart deployment does not restore the source's service
aliases, because they point to the namespaces of the source environment.
At its end, after "Run the recovery", it writes the aliases between the
counterpart and the other deployments of the new environment.

The database itself also starts on an empty data volume and needs some
time before it accepts connections. The MariaDB and MongoDB restore hooks
retry loading the dump every 2 seconds, for up to 2 minutes, until the
database accepts it. The Velero log of a successful restore can show
failed attempts before the one that loaded the dump.

Backups and restores leave out the `CiliumEndpoint` objects that Cilium
writes for each pod. Cilium writes new ones when the restored pods start.
A restored copy would still hold the addresses of the pods that were
backed up, and Cilium could then leave a restored pod unreachable from
pods on other nodes. On a cluster that does not run Cilium, this has no
effect.

### Following a backup or a restore

On the deployment page, each backup and each restore row lists its steps
under "Steps", with their status, times and errors.

A restore has three steps, in this order:

1. "Delete the namespace": Styrmin deletes the target namespace and waits
   until it is gone, so the restore starts from a clean namespace.
2. "Run the Velero restore": Styrmin creates the Velero `Restore` object
   and waits for Velero to finish.
3. "Run the recovery": Styrmin prepares the restored `StyrminDeployment`
   so that the operator takes it over again. This step runs only after
   Velero completed the restore.

The restore that an environment clone runs into a counterpart deployment
has a fourth step, "Create and delete service aliases", which runs after
"Run the recovery" succeeded. Styrmin writes the service aliases between
the counterpart and the other deployments of the new environment. The
step is left out when there is no alias to write or delete.

"Delete the namespace" fails with `Namespace <namespace> was not deleted
within 600s` when the namespace is still `Terminating` after 600
seconds. Either its pods take longer than that to stop, or an agent of
Styrmin v0.1.48 or earlier kept the finalizer of the namespace's
`StyrminDeployment`. To find which, and to recover, see
[A `StyrminDeployment` that keeps its finalizer](./operator-and-crds.md#a-styrmindeployment-that-keeps-its-finalizer).

A backup has one step per component, "Back up" followed by the component
name. Velero backs up the whole namespace at once and creates one
`PodVolumeBackup` object for each pod volume it backs up. Styrmin maps
each of these objects to a component through the pod's
`styrmin/component` label: a component's step starts with its first pod
volume, ends with its last one, and fails when one of them failed. Velero
creates these objects while the backup is in its `InProgress` phase, so a
component's step stays running until the backup has left that phase, even
when all of the component's pod volumes are already backed up. A
component without pod volumes gets the start time, end time and result of
the whole backup.

A restore of a backup that Velero no longer has, for example because it
was removed from the storage location, fails within seconds: Velero
rejects the restore in its `FailedValidation` phase, and "Run the Velero
restore" fails with an error that starts with "Velero restore failed
validation:" followed by Velero's validation errors. The restore's error
message is the same. When Velero ends a backup or a restore without a
failure reason, its error message is the error of the failed step. Without
validation errors either, that error names the Velero phase, in the form
`Velero backup phase: <phase>` or `Velero restore phase: <phase>`, followed
by the number of Velero's errors in parentheses when Velero reports any.

Backups and restores that ran before Styrmin recorded steps show "No
steps recorded for this backup." or "No steps recorded for this
restore." When the server cannot create the token that the backup or
restore flow uses to record its steps, the backup or restore runs without
steps.

### Why one BSL per environment?

A Backup Storage Location is attached to an **environment**, not to a
deployment. That gives you a few useful properties:

- **All backups for an environment live in one place.** Easy to
  retention-manage, easy to point at a different region per environment.
- **One place to point at a region, or to swap out.** Repointing an
  environment's backups is one assignment, not one per deployment.
  Note that a **cloned** environment does not inherit the source's BSL:
  assign one before the clone can take backups of its own (see
  [Cloning an environment](#cloning-an-environment)).
- **A BSL is shared infrastructure.** Setting it up once per environment
  is cheaper than setting it up per deployment.

### What a BSL creates in the cluster

When you assign a BSL to the first environment of a cluster, Styrmin
creates two objects in the `styrmin` namespace:

- a Velero `BackupStorageLocation` named `styrmin-bsl-<BSL id>`;
- a Secret named `styrmin-bsl-<BSL id>-credentials`, which holds the
  S3 access key and secret key.

Both carry the label `styrmin.io/bsl-id=<BSL id>`. Styrmin creates them
only when no Velero `BackupStorageLocation` with that label exists, so
assigning the same BSL again does not add a second one. To list them:

```bash
kubectl get backupstoragelocations.velero.io,secrets -n styrmin \
  -l styrmin.io/bsl-id=<BSL id>
```

The names come from the BSL's id, not its name, so you can rename a BSL
at any time: backups, credential updates and the removal of the objects
when you unassign the BSL keep working. Styrmin versions before this
change named the objects after the BSL's name (`styrmin-bsl-<name>`).
Styrmin finds those objects by the same label and keeps using them; it
does not rename them.

To create or update the Secret, the agent reads the S3 keys from a
Prefect Secret block named `styrmin-bsl-<BSL id>-credentials`, which
Styrmin saves on the Prefect server. The Prefect UI shows the block's
value as `********`, and the Prefect API returns it only to a call that
asks for secret values. Deleting the BSL deletes the block. Styrmin
versions before this change passed the keys to these flows as flow-run
parameters, so the Prefect UI and API show the keys in the flow runs
that those versions started, until Prefect deletes the runs. To make
those keys useless, rotate them in your object storage and update the
BSL with the new keys.

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

:::caution A terminal status is not proof the snapshot still covers the environment

The record and *all* of its constituents are written together, in one
transaction, before Styrmin dispatches any backup work. So there is no
moment at which you can read a snapshot that is missing constituents it
was about to create: a snapshot with work to do reports `PENDING` or
`IN_PROGRESS`, one whose every constituent was blocked at creation
reports `FAILED`, and an immediate `COMPLETED` means one specific thing
— there was nothing eligible to back up, so it's a config-only snapshot.

What a terminal status still doesn't tell you is whether the snapshot
*covers* the environment today. Constituent backups can be deleted
individually afterwards, and the snapshot keeps reporting `COMPLETED`
with a gap where that deployment used to be — that visibility is the
point, not a bug. Read the per-constituent list rather than the status
alone: a constituent shown with neither a backup nor a failure reason
(`deleted` in the CLI's output) is a gap.

:::

#### Restoring an environment

Restoring a `COMPLETED` or `PARTIAL` environment backup is also one
action. Styrmin reverts the environment's config to the captured value
and restores every usable constituent **in place**, back into the
deployment it came from.

Two things it deliberately does **not** do:

- **It never creates or deletes your deployments.** Restoring is a config-and-
  data operation, not a topology one. A deployment you deleted since the
  backup is not recreated; a deployment you added since is not removed.
  Only the environment's dedicated ingress controller is created, redeployed
  or removed to match the restored `dedicated_ingress`, as on an environment
  update (see
  [Changing the dedicated ingress of an environment](./ingress-and-networking.md#changing-the-dedicated-ingress-of-an-environment)).
- **It never touches data it has no backup for.** A deployment created
  after the snapshot keeps its data untouched. It does still pick up the
  reverted environment config, through the same config propagation any
  environment edit triggers — that is the intended outcome, not a leak.
  A deployment that is already at the reverted config is not redeployed.

Every constituent that is **not** restored is reported with its
deployment name and a reason. There are no silent skips — if a
deployment isn't in the restore's list of restored constituents, it is in
the skipped list with a reason. These six cover the expected cases:

| Reason | What happened |
|--------|---------------|
| `backup failed at creation` | The constituent backup never got started — usually a conflicting backup already running at snapshot time. |
| `backup not completed` | The constituent backup exists but didn't finish successfully. |
| `backup deleted` | Someone deleted that constituent backup individually. |
| `backup expired` | The constituent's retention TTL elapsed and Velero garbage-collected the data. |
| `deployment no longer exists` | The deployment was deleted (or tombstoned) after the snapshot was taken. |
| `deployment busy with another restore` | A separately started restore is already running on that deployment. |

They are not the only possible values. Anything else that stops a
constituent restore from being created is reported verbatim as
`restore could not be created: <error>`, and the set is expected to grow.
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

When the redeploy of one of those deployments cannot start, the other
redeploys still run and the restore returns normally, with a status that
does not show the failure. The failure is written only to the server log,
not on the restore, so `styrminctl env-backups restore-get` and the UI do
not list it ([#520](https://github.com/opsmill/styrmin/issues/520)): an
`env_restore_fanout_dispatch_error` line gives the restore's
`environment_restore_id`, the `deployment_id` and, when the error has
them, the `error_code` and the term's `path`. The
`env_restore_fanout_dispatched` line counts the failure in
`config_redeploy_failed`. One case: the captured config has an affinity term
that names a deployment you deleted after the backup. The restore puts
the config back as captured, and the next update of each deployment that
the term applies to fails with the deleted deployment's last name and
`deleted: true` until you write the term again.

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

There is one exception. While an environment clone is still capturing
into the snapshot, deleting it is refused with `IN_USE`, for at most two
hours. See [Discarding a clone](#discarding-a-clone).

Deleting an environment takes its environment backups with it. In this
release a snapshot does not outlive its environment.

### Cloning an environment

An environment backup captures an environment so you can put it *back*. A
**clone** uses the same capture to stand up a **second, brand-new
environment** next to the source — running, with the source's data as of
clone time — in one action.

The typical reason is a rehearsal: you want to practise a migration, an
upgrade, or an incident against production-shaped data without touching
production. Clone it, work in the copy, delete the copy.

One action — the **Clones** tab on the environment page, one
`styrminctl env-clones create`, or one `cloneEnvironment` call — does all
of this:

1. Captures a **fresh environment backup** of the source, limited to the
   deployments you selected.
2. Waits for that capture to finish. If it fails outright, **nothing is
   created** — no environment, no deployments.
3. Creates the new environment from the **captured** config, with your
   override merged over it.
4. Creates one **counterpart deployment** per included source
   deployment, pinned to the driver version the capture recorded.
5. Restores each source deployment's data **into its counterpart**.

Everything after step 1 is built from the capture. The live source is
never read again, so data written to the source *after* the capture
completes is not in the clone — that's the point of a defined clone
point, not a gap.

**Cloning needs the administrator role**, for the same reason restoring
does: it writes environment configuration. Reading clone records does
not.

:::note The source is not modified

A clone leaves the source environment's config and declared state exactly
as they were. The only source-side artefact is the environment backup it
captured — an ordinary snapshot, in the source's list, expiring under the
source's retention rules.

:::

#### Choosing which deployments come along

Leave the selection empty and every **eligible** deployment comes along —
the same eligibility rule as an environment backup: not tombstoned, not
one of Styrmin's own internal deployments, and with a running instance.

Name specific deployments and only those are captured and cloned, which
is how you leave a heavyweight analytics stack out of a rehearsal. The
selection filters the capture too, so excluded deployments are not backed
up at all.

What happens depends on what you name, and the difference matters:

| What you named | What happens |
|----------------|--------------|
| A deployment that doesn't exist, or belongs to a different environment | The whole request is **rejected up front**. Nothing is created and no backup is taken. |
| A deployment that exists but isn't eligible | It's **skipped**, by name, with a reason. Not an error. |
| An eligible deployment | It's included. |
| A selection that leaves out a deployment, or includes one that isn't eligible, when an affinity term that the clone copies names that deployment | The whole request is **rejected up front** with `VALIDATION_ERROR`. The error message lists each such deployment, the reason the clone does not copy it, and the path of every term that names it. Nothing is created and no backup is taken. Add the deployment to the selection, leave out the deployment whose term names it, or, for a term in the environment's config, clear or override `scheduling`. |

An affinity term can name another deployment of the same environment, in
`scheduling.pod_affinity` or `scheduling.pod_anti_affinity`. Styrmin stores
the id of the deployment it names. The clone checks the terms of the new
environment's config, of each deployment it copies, and of the component
definitions of that deployment's driver version. Each copied term names
the counterpart of the deployment it named, so the clone's pods are
placed relative to each other and not to the source's pods.

An application in the clone reaches the clone's other deployments by
short service name, through the
[service aliases](./ingress-and-networking.md#service-aliases) of the new
environment. A deployment that you leave out of the clone cannot be
reached by short service name from the clone: the clone has no alias for
that deployment's services, so a call to it by short name fails instead
of reaching the source environment.

Every source deployment you could have selected is accounted for on the
clone record — cloned, skipped with a reason, or failed with a reason.
Styrmin's **internal** deployments are the exception: they are left off
the record entirely unless you named one explicitly, because the clone
gets its own fresh ingress controller as part of ordinary environment
setup.

An **empty** selection is legal and means something useful: clone the
environment only — its configuration, none of its applications. That
clone reports `COMPLETED`, unless the environment's config has an
affinity term that names a deployment. The clone copies no deployment, so
that request is rejected up front, as the last row of the table above
describes. Clear `scheduling` (`clearConfigFields: ["scheduling"]`,
`--clear-config-field scheduling`), or replace it in the override
(`configOverride`, `--config-override`) with a `scheduling` that names no
deployment.

#### Changing the config on the way in

A clone of production that keeps production's configuration will behave
like production: send real email, call real webhooks, register real DNS.
So the clone takes an environment-config override, applied **before** the
new environment is created — the counterparts' very first startup already
sees the changed values. There is no window in which cloned workloads run
under the source's settings.

The override works one field at a time. A field you supply replaces the
captured field **wholesale**; a field you leave out keeps its captured
value. So overriding one environment variable list replaces that list,
and leaves `fqdn_suffix`, retention, and everything else untouched.

To **remove** a setting rather than change it — a production-only DNS
integration, say — name it in the clear-fields list instead. A cleared
field is *absent* from the clone's configuration: not empty, not
defaulted. Naming a field that the capture never set is a harmless no-op;
only an unknown field *name* is an error. Name a field in both places and
the override wins.

Watch the casing here, because it follows the surface rather than the
feature:

| Where | Casing |
|-------|--------|
| The override input (`configOverride`, `--config-override`) | **camelCase** on GraphQL — the same `UpdateEnvironmentInput` shape as `updateEnvironment`, including `envVars` as a list of `{name, value}` entries rather than a map. The CLI and Python SDK also accept the snake_case field names, since their generated input model populates by either. |
| The clear-fields list (`clearConfigFields`, `--clear-config-field`) | **snake_case** config field names: `fqdn_suffix`, `external_dns_endpoints_type`, `backup_ttl`, … |
| What the clone record reports back | **snake_case** canonical JSON, whatever casing you sent. |

:::caution A misspelled override field is dropped silently

The override input tolerates keys it doesn't recognise, so a typo'd field
name is ignored rather than rejected — and the captured value stays in
place. Read the `configOverride` echoed back on the clone record (or the
new environment's configuration) to confirm an override actually landed.
A misspelled *clear-field* name **is** rejected, because that list is
validated against the config's field names.

:::

#### Watching a clone, and what its status means

A clone runs asynchronously and is tracked by its own record: which
capture it was built from, which environment it created, one outcome per
source deployment, and a list of operation-level events. Its status is
**derived on every read** from those parts, exactly like an environment
backup's:

| Status | What it means |
|--------|---------------|
| `PENDING` | Registered, capture not started. |
| `IN_PROGRESS` | The capture, the environment, or a data restore is still moving. |
| `COMPLETED` | Every included deployment was cloned. |
| `PARTIAL` | Some included deployments were cloned and some failed. |
| `FAILED` | Nothing was cloned — or the clone was discarded (see below). |

Two things surprise people:

- **A clone can read `IN_PROGRESS` the instant you create it.** Anything
  skipped up front is recorded together with the clone, and recorded
  progress counts. Don't wait for `PENDING`.
- **An all-skipped clone is `COMPLETED`, not a failure.** So is a clone
  of an empty selection. The environment was created; there was simply
  nothing eligible to bring across.

`PARTIAL` is a normal outcome, not a bug. One way to get there: the
driver version the capture recorded no longer exists by the time the
counterpart is created. That deployment is attributed as failed, its
neighbours are cloned, and the clone reports the mix.

A deployment whose restore failed is also attributed as failed, with the
reason `the restore failed`, followed by the restore's error when it has
one. The clone records a deployment as cloned when it starts the restore,
and reports it as failed once the restore has failed. One cause is the step
"Create and delete service aliases": when Styrmin cannot write the
counterpart's service aliases, the restore fails with the error
`Service alias step failed: <error>`.

The failed restore sets the counterpart to `FAILED`. When only the alias
step failed, the counterpart's workloads run, so its status then follows
them and can read `RUNNING`. The clone's attribution and the failed
restore record the failure. To write
the missing aliases, make a change to the counterpart's configuration or
parameters, or upgrade it. The update or upgrade writes the counterpart's
aliases and the aliases of its services in the namespaces of the other
deployments. Saving the same values does not always run an update, so it
might write no alias.

A failure also reaches the deployments whose affinity terms name the
failed one. A deployment fails this way when its captured data cannot be
used (its capture failed, or its backup was deleted, did not complete or
expired) or when its counterpart fails:

- A deployment whose own config has such a term is attributed as failed,
  and no counterpart is created for it. The reason is
  `an affinity term names deployment <name>, which was not cloned`.
- When two deployments' terms name each other, one counterpart is
  created first. If the other counterpart then fails, the first one is
  attributed as failed with the same reason. Its counterpart exists in
  the new environment, and its next update is refused until you change
  the term.
- A term that comes from the component definitions of the deployment's
  driver version gives a name, which Styrmin looks up when it creates the
  counterpart. When no counterpart has that name, the counterpart is not
  created and the deployment is attributed as failed with the reason
  `Affinity term at <path> names deployment '<name>', which is not a
  deployment of environment '<new environment>'.`
- When the new environment's config names the failed deployment, the
  clone reports `FAILED` with a `referenced_deployment_not_cloned` event.
  When the deployment's captured data cannot be used, no environment is
  created; after a failed counterpart, no further counterpart is created.

#### Discarding a clone

**Delete the environment the clone created.** That is the supported
discard path, it works in any state including `PARTIAL` and `FAILED`, and
it takes the counterpart deployments with it. The clone record keeps a
`created_environment_deleted` event, and the UI labels the clone
*Discarded*. A clone that was still running then reads `FAILED`. A clone
that had already finished keeps its outcome (`COMPLETED`, `PARTIAL` or
`FAILED`); the event only records that its environment is gone.

Because a clone's name is deliberately not unique, and deleting the
environment frees the environment name, you can immediately re-clone the
same source under the same name.

Two more handles, for the cases where there is no environment to delete
yet:

- **Deleting the backing environment backup** is refused (`IN_USE`) only
  while that clone's *capture* is still running, and only for as long as
  the clone could still be waiting for it (two hours, the clone's own
  wait budget). Once the capture has landed — or that budget has run out,
  which is what a capture whose constituent work was never picked up
  eventually does — deleting it is allowed, and it is the escape hatch for
  a clone that stalled before its environment appeared. On a still-running
  clone the deletion is recorded and the clone ends `FAILED`; on a clone
  that already finished, the recorded outcome stands.
- **Deleting the source environment** keeps the clone record whenever it
  has an environment to be the provenance of: the source link is cleared
  and the source's *name* stays on the record. A clone that was still
  building that environment also picks up a fatal
  `source_environment_deleted` event and ends `FAILED` — its capture goes
  with the source, so it can make no further progress. Only a clone that
  never created anything is removed outright. Because the source's
  snapshots cascade with it, a finished clone also picks up a non-fatal
  note that its backing capture is gone.

:::note Deleting an environment now removes its deployments

Environment deletion tears down and removes the deployments inside the
environment, rather than refusing. This is what makes the discard path
above work — a cloned environment owns at least its counterparts, and its
own ingress controller when it uses a dedicated one — and it applies to
every environment, not just clones.

:::

#### What a clone is *not* isolated from

This is the part to read before you point a clone at anything live.

A clone is isolated at the Kubernetes level: its own namespaces, its own
workloads, its own ingress controller. The config override is a genuine
lever over environment-level settings. **Neither of those touches values
stored inside the restored application data.**

Database rows, config tables, and secrets that came across in the restore
are copied **verbatim**. If your application stores an outbound webhook
URL, a payment-provider API key, an SMTP credential, a licence key, or a
partner endpoint in its own data, the clone holds the same value and can
reach the same system as the source. Cloned workloads are real workloads:
schedulers fire, queues drain, integrations call out.

Treat "neutralise the data-borne references" as a step you own, before
the clone is allowed to talk to anything that matters. The override
handles configuration; it cannot reach into a table.

One more, narrower caveat. A counterpart's Helm values are re-rendered
while its data is restored from the source. A driver whose chart
**generates** credentials at install time — a random password minted per
release — can therefore mint a fresh credential over restored data that
expects the old one, leaving the restored component unreachable. Drivers
meant to be cloneable should take credentials from configuration rather
than generating them at deploy time.

#### Details worth knowing

- **A counterpart's Helm release is named after the source deployment.**
  `helm list -n styrmin-<counterpart-id>` shows a release named for the
  *source*. That is intentional: the restored objects carry the source's
  Helm ownership metadata, and matching the release name is what keeps
  Helm's view consistent. It is not drift.
- **A cloned environment has no backup storage location.** Locations are
  assigned per environment, and a clone does not inherit the source's, so
  the new environment cannot take its own backups until you assign one.
  Restoring the capture *into* the clone is unaffected.
- **A clone occupies its new environment until it finishes.** While a
  clone is running, environment-level operations and config edits on the
  environment it is building are refused. Deleting it is always allowed —
  that's the discard path.
- **You can clone a clone**, and you can run several clones of one source
  at once. Only the capture window is serialised: a second clone started
  while the first is still *capturing* is refused with a busy error.

For the commands and their exit codes, see
[the `env-clones` CLI reference](../reference/styrminctl.md#env-clones--clone-an-environment).

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
