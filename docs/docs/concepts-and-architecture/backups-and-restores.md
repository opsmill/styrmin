---
title: Backups and restores
sidebar_position: 6
description: How Styrmin backs up the applications of a deployment or an environment, what happens when you restore, and how cloning an environment works.
---

## Backups and restores

Each application needs its own backup procedure. A relational database
needs a `pg_dump`. A graph database needs its own dump tool. A stateless
API server needs only a copy of its persistent volumes.

Back up one deployment, or every deployment of an environment, with one
operation. The driver of each application defines how Styrmin backs up
each of its components.

### What a backup uses

- **[Velero](https://velero.io/)**: an open-source Kubernetes backup
  tool that takes volume snapshots and stores them in S3-compatible
  object storage. Styrmin runs every backup and restore with Velero.
- **A backup storage location (BSL)**: an S3-compatible bucket
  (DigitalOcean Spaces, Garage, AWS S3, …) that Velero writes backups
  to. You configure one per environment.
- **A backup strategy per component**: declared by the driver. It
  defines how Styrmin backs up that component.

### Backup strategies

Each component in a driver can declare a backup `kind`. Styrmin maps each
kind to a strategy:

| Strategy | What it does | Used for |
|----------|--------------|----------|
| **`disk`** | Snapshot the component's volumes directly. | Stateless workloads, or data stores that are safe to snapshot while they run. |
| **`postgres`** | Run `pg_dump` into a sidecar volume, then snapshot it. | PostgreSQL databases. |
| **`mariadb`** | Run `mariadb-dump` into a sidecar volume, then snapshot it. | MariaDB and MySQL databases. |
| **`mongodb`** | Run `mongodump` into a sidecar volume, then snapshot it. | MongoDB databases. |
| **`neo4j`** | Run `neo4j-admin dump` into a sidecar volume, then snapshot it. | Neo4j graph databases. |
| **`action`** | Run a custom Python action that the driver defines. | Any data that the strategies above do not cover. |

The driver author chooses the strategy of each component. Styrmin runs it
when a backup starts.

:::caution Disk backups must name the volume

The `disk` strategy backs up **only the volumes you name** in the
component's `backup.volume` (one volume) or `backup.volumes` (a list)
field. The name is the **pod-template volume name** (the entry under
`volumes:` in the rendered pod spec), not the PVC name. If you set
`kind: disk` and omit `volume` and `volumes`, Velero's opt-in file-system
backup copies nothing: the backup contains no data of the component, and
no error reports it.

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

### What happens when you start a backup

1. You start a backup of a deployment from the UI, the CLI, or the
   GraphQL API.
2. Styrmin starts a Prefect flow for the backup.
3. For each component, Styrmin adds the steps of its strategy before and
   after the Velero snapshot. For a PostgreSQL component, the step before
   the snapshot runs `pg_dump`.
4. The agent creates a Velero `Backup` object that lists what to back up
   and which hooks to run.
5. Velero takes the snapshot and stores it in the BSL.
6. Styrmin records the backup with the name of its Velero backup, so that
   a restore can find it.

#### Backup size

The size shown for a completed backup (`sizeBytes` in GraphQL, `size_bytes`
in the SDK and `styrminctl backups`) is the number of bytes of volume data
that Velero read from the deployment's volumes. Styrmin adds up the bytes
that each of Velero's `PodVolumeBackup` objects reports for the backup.

- The value is measured before Velero deduplicates and compresses the data,
  so the space the backup uses in the BSL is usually smaller.
- The Kubernetes resource definitions that Velero also stores are not
  counted.
- The size is empty when the backup contains no volume data (for example,
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
for example a backup taken before an upgrade. The restore writes the
earlier instance's `StyrminDeployment` and `HelmRelease` to the
deployment's namespace again, with that instance's application version
and config. When the restore completes, Styrmin makes that instance the
deployment's active instance, and gives the deployment that instance's
application version, config, parameters, and driver version. The
deployment page and `styrminctl` then show the application version that
runs, and the next change to the deployment starts from the restored
state. A backup you take after the restore belongs to that instance.

If Styrmin cannot record the instance, the restore still completes and
the deployment keeps its previous active instance. The server log has the
error.

Before such a restore:

- The Restore dialog on the Backups tab shows the backup's application
  version, the deployment's current application version, and the
  deployment and namespace the backup is restored into. It warns that
  the backup was taken of an earlier instance, or at another application
  version.
- `styrminctl backups restore --last` shows both versions and asks for
  confirmation. Pass `--yes` to restore without the question. Without a
  terminal and without `--yes`, the command refuses the restore.

A deployment without an active instance can also receive a restore. It
has no instance that the backup could be earlier than, so the dialog and
`styrminctl` warn only when the backup was taken at another application
version. The restore does not give the deployment an active instance.

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

A deleted deployment's backups cannot be restored. A restore writes a
backup to the deployment it was taken of, and Styrmin refuses a restore
into a deleted deployment with the error code `OPERATION_DENIED`. Only an
environment clone restores a backup into another deployment, and an
environment restore and an environment clone both skip a deleted
deployment.

A new deployment that reuses the name of a deleted deployment starts
with an empty backup history, because the history is listed by
deployment id, not by name. The deleted deployment keeps its own
history, which you can list by its id.

### What happens when you restore

A restore runs the same steps in reverse order:

1. You choose a backup. Styrmin restores it into the deployment it was
   taken of, in that deployment's namespace `styrmin-<deployment id>`.
   Before it changes anything in the cluster, the restore fails when the
   namespace it received is not that one, for example for a restore
   that an earlier version of Styrmin queued with another namespace.
2. Styrmin adds the restore steps of each component's strategy. For a
   PostgreSQL component, these steps load the dump into the database.
3. The agent creates a Velero `Restore` object with these restore hooks.
4. Velero reads the data from the BSL and writes it to the restored
   volumes.
5. The restore hooks run, and the deployment serves the restored data.

A restore creates the namespace again, so the application pods start
**while** the restore hooks still load the data: Velero starts all pods
at once and does not wait for the hooks. This matters for a PostgreSQL
component. The database that the application first connects to is empty,
and an application that migrates its own schema at startup tries to do so
before the restore has loaded the data. Styrmin's PostgreSQL restore hook
prevents this: it blocks other clients from the database until the dump
is loaded, and it loads the dump in one transaction, so the restore loads
all of the data or none of it. The application can log connection errors
during the restore. An application that reconnects by itself recovers
when the restore finishes.

The restore of a deployment, and each restore that the
[restore of an environment](#restoring-an-environment) runs, keeps the
[service aliases](./ingress-and-networking.md#service-aliases) of the
restored deployment in the other namespaces of its environment, and Velero
restores the aliases in the restored deployment's namespace from the
backup. A deployment of the environment that is created, updated or
upgraded while the restore runs skips the aliases between itself and the
restored deployment, because the restored deployment's namespace is being
deleted or does not exist yet. Nothing writes them after the restore, so
the two applications cannot reach each other by short name. After the
restore has finished, make a change to either deployment, such as a change
to its configuration or its parameters, to write the aliases. Saving the
same values does not change the deployment, so it writes no alias.

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
A restored copy would still contain the addresses of the pods that were
backed up, and Cilium could then make a restored pod unreachable from
pods on other nodes. On a cluster that does not run Cilium, this has no
effect.

A backup contains the objects in the namespace, not the namespace itself,
so Velero creates the restored namespace with its name as its only label.
After the Velero restore, Styrmin sets the labels of the deployment on the
namespace again (`styrmin/environment_id` and `styrmin/deployment_id`),
before it applies the network policies again. Network policies select
namespaces by these labels. The restore that an environment clone runs
writes the labels of the counterpart deployment, which contain the new
environment's id.

### Following a backup or a restore

On the deployment page, each backup and each restore row lists its steps
under "Steps", with their status, times and errors.

The restore of a deployment or of an environment has three steps, in this
order:

1. "Delete the namespace": Styrmin deletes the namespace of the
   deployment that receives the restore and waits until it is gone, so
   the restore starts from an empty namespace.
2. "Run the Velero restore": Styrmin creates the Velero `Restore` object
   and waits for Velero to finish.
3. "Run the recovery": Styrmin prepares the restored `StyrminDeployment`
   so that the operator manages it again. This step runs only after
   Velero completed the restore.

The restore that an environment clone runs into a counterpart deployment
has a fourth step, "Create and delete service aliases", which runs after
"Run the recovery" succeeded. Styrmin writes the service aliases between
the counterpart and the other deployments of the new environment. The
step is left out when there is no alias to write or delete. When Styrmin
cannot list the service aliases in the cluster, the step is recorded as
failed with the error.

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

A backup storage location is assigned to an **environment**, not to a
deployment, for these reasons:

- **All backups of an environment are in one bucket.** You manage them,
  and choose their region, for the whole environment.
- **One assignment sets where an environment's backups go.** To use
  another bucket or region, you change one assignment, not one per
  deployment. A **cloned** environment does not get the source's BSL:
  assign one before the clone can take backups of its own (see
  [Cloning an environment](#cloning-an-environment)).
- **A BSL is shared infrastructure.** Setting it up once per environment
  costs less than setting it up per deployment.

### What a BSL creates in the cluster

When you assign a BSL to the first environment of a cluster, Styrmin
creates two objects in the `styrmin` namespace:

- a Velero `BackupStorageLocation` named `styrmin-bsl-<BSL id>`;
- a `Secret` named `styrmin-bsl-<BSL id>-credentials`, which contains the
  S3 access key and secret key.

Both have the label `styrmin.io/bsl-id=<BSL id>`. Styrmin creates them
only when no Velero `BackupStorageLocation` with that label exists, so
assigning the same BSL again does not add a second one. To list them:

```bash
kubectl get backupstoragelocations.velero.io,secrets -n styrmin \
  -l styrmin.io/bsl-id=<BSL id>
```

The names come from the BSL's id, not its name, so you can rename a BSL
at any time: backups, credential updates and the removal of the objects
when you unassign the BSL keep working. Styrmin v0.1.49 and earlier
named the objects after the BSL's name (`styrmin-bsl-<name>`). Styrmin
finds those objects by the same label and keeps using them; it does not
rename them.

To create or update the `Secret`, the agent reads the S3 keys from a
Prefect Secret block named `styrmin-bsl-<BSL id>-credentials`, which
Styrmin saves on the Prefect server. The Prefect UI shows the block's
value as `********`, and the Prefect API returns it only to a call that
asks for secret values. Deleting the BSL deletes the block. Styrmin
v0.1.49 and earlier passed the keys to these flows as flow-run
parameters, so the Prefect UI and API show the keys in the flow runs
that those versions started, until Prefect deletes the runs. To make
those keys unusable, rotate them in your object storage and update the
BSL with the new keys.

### Retention: how long Velero keeps a backup

Every Velero backup that Styrmin creates has a **TTL** (time to live):
the time Velero keeps the backup before it deletes the backup and its
data. The default is **`720h`** (30 days).

Expiry and the space used in the bucket are two separate steps. Velero's
garbage collection deletes the expired backup, and a periodic
**repository maintenance** run then frees the storage of its data.
Maintenance runs once an hour for each backup repository, and it keeps
recently written data, so the space used in the bucket decreases some
time after a backup expires, not at the moment it expires.

Set `backup_ttl` in the config to change the TTL. It takes a Go duration
string in `h`, `m`, or `s` units: `2160h` (90 days), `8760h` (a year),
`1h30m`, `1.5h`. There is **no day unit**: `30d` is not a Go duration and
is rejected, as are `0h`, `-24h`, and `720` without a unit. Styrmin
refuses a malformed value when you submit it, with an error that names
`backup_ttl` and shows the `720h` format. Nothing is stored and no backup
changes.

#### Three scopes; the most specific wins

You can set `backup_ttl` at three scopes, as you can other config values
such as `db_size`. When Styrmin creates a backup, it uses the value of the
most specific scope that sets it:

| Scope | Where you set it | Use it for |
|-------|------------------|------------|
| **Deployment** | `deploy`'s `config`, or `updateDeployment`'s `input` | An application that keeps its backups longer or shorter than the other applications of its environment. |
| **Environment** | The environment's **Configuration** tab in the web UI, `createEnvironment`'s `config`, or `updateEnvironment`'s `input` | One policy for every application in the environment (the usual scope). |
| **Cluster** | `createCluster`'s `config`, `updateCluster`'s `input`, or `styrminctl clusters update --config` | A default for every environment of the cluster. |

When a scope does not set `backup_ttl`, Styrmin uses the next broader
scope, and `720h` when no scope sets it.

Every backup records the TTL that Styrmin applied, and the web UI and
`styrminctl backups list` show the resulting expiry date, so you do not
need access to the cluster. Styrmin also records which scope the value
came from and writes it to the log of the backup flow. The API does not
return the scope: to find where a backup's retention comes from, read the
flow log or the config of each scope.

:::note Changing the cluster scope

`updateCluster` and `styrminctl clusters update` replace the whole
cluster config, and Styrmin redeploys the deployments that take a changed
value. The **Edit** dialog on the cluster detail page does not show
`backup_ttl` and keeps its stored value. See
[`clusters update`](../reference/styrminctl.md#clusters-update--change-a-clusters-config).

:::

#### Setting a retention policy

The environment scope has a form field. Open the environment, go to the
**Configuration** tab, and edit **Retention (`backup_ttl`)** in the
**Backup Retention** section. The field takes the same Go duration string
and refuses a malformed value before it submits it. Saving keeps the rest
of the environment's config unchanged. Saving is an `updateEnvironment`,
so Styrmin redeploys the environment's deployments; the confirmation
dialog lists them before anything changes. To **clear** the environment
policy, empty the field and save: Styrmin then uses the cluster scope, or
the default `720h`.

The form cannot save an environment that sets `dedicated_ingress` or
`scheduling`: it disables Save instead of clearing them. Set the retention
of such an environment through the API.

The deployment and cluster scopes have no form field, and `styrminctl`
has no retention option at any scope. Set those scopes with the GraphQL
API or the Python SDK, which calls the same mutations, or with
`styrminctl` `--config` payloads and deployment manifests.

The key name depends on where you set it:

| Where | Key |
|-------|-----|
| `input` of `updateEnvironment`, `updateDeployment` and `updateCluster`; `deploy`'s `config` | `backupTtl` (GraphQL input types use camelCase) |
| `createEnvironment`'s and `createCluster`'s `config` | `backup_ttl` (raw JSON, stored as sent) |
| `styrminctl deployments update --config` | `backupTtl` or `backup_ttl` (both accepted) |
| `styrminctl clusters update --config` | `backup_ttl` or `backupTtl` (both accepted) |
| `spec.config` in a `styrminctl deployments apply` manifest | `backupTtl` |
| `styrminctl environments create --config`, `styrminctl clusters create --config` | `backup_ttl` |

`updateEnvironment` takes the **complete config**, so read the
environment's current config first:

```graphql
query ReadEnvironmentConfig {
  environment(environmentName: "production", clusterName: "default") {
    id
    config
  }
}
```

To look up an environment by name, also pass `clusterName` or
`clusterId`, or use `environmentId` instead.

Then send the config back with `backupTtl` added:

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

`UpdateEnvironmentInput` replaces the whole config: Styrmin clears every
field you omit. Send every field you want to keep in the same call. The
web UI reads the stored config and sends it back with your change, so
editing an environment variable in the UI keeps a retention policy that
you set through the API, and saving the retention field keeps the
settings that you set through the API.

:::

For one application, set it in the deployment's config instead:
`backupTtl` in `deploy`'s `config` or `updateDeployment`'s `input`, or
`backupTtl` under `spec.config` in a `styrminctl` deployment manifest.
`updateDeployment` also replaces the whole config.

#### A change applies to future backups only

Velero sets a backup's expiry when it creates the backup, so a change to
`backup_ttl` **does not** change the expiry of existing backups, and
Styrmin does not update them. The new value applies from the next backup.
Whether you shorten or lengthen the retention, existing backups expire on
their original date.

:::caution Restoring from an expired backup fails

When a backup's TTL ends, Velero deletes its data, but the backup stays in
Styrmin's list. A restore from an expired backup fails at the Velero
step. With a short `backup_ttl`, backups expire sooner, so check the
expiry column before you choose a backup to restore.

:::

### Backing up a whole environment

The sections above describe the backup of one deployment. An
**environment backup** backs up every application of an environment in
one action and records the result as one environment backup.

One action, from the **Backups** tab on the environment page,
`styrminctl env-backups create`, or `createEnvironmentBackup`, captures
three things:

- the **environment's config** at the time of the backup;
- the **declared state of every eligible deployment**: its application
  driver, driver version and provenance fingerprint, application
  version, config, and parameters;
- one **constituent backup** per eligible deployment: a deployment
  backup, taken as described above, written to the same BSL, and kept
  for the same retention.

A deployment is **eligible** when it is not deleted (tombstoned), is not
one of Styrmin's internal deployments (such as the environment's ingress
controller), and has a running instance to back up. Its state does not
matter: a `FAILED` deployment with an active instance still gets a
constituent backup.

For an environment without eligible deployments, the environment backup
contains only the config and reports `COMPLETED` at once. Use it to save
an environment's settings before you deploy applications to it.

#### Deployment backups run in parallel

Styrmin starts every constituent backup at the same time, and they run in
parallel. Styrmin does not stop components or block writes during the
backup, so the constituent backups do not finish at the same moment. Use
an environment backup to return an environment to a known working state;
it is not a transaction across applications. To back up one application
with no writes during the backup, stop its components and back it up
separately.

A conflict on one deployment does not stop the others. If a deployment
already has a backup running, Styrmin records its constituent backup as
failed, with the reason, and the other backups continue. The environment
backup does not wait for that deployment and does not stop because of it.

#### Status is derived, never stored

An environment backup stores no status. Each time you read one, Styrmin
computes its status from its constituent backups:

| Status | What it means |
|--------|---------------|
| `PENDING` | Nothing has started yet. |
| `IN_PROGRESS` | At least one constituent is still running. |
| `COMPLETED` | Every constituent completed and none failed to start. |
| `PARTIAL` | At least one constituent completed and at least one did not. |
| `FAILED` | Nothing completed. |

Because Styrmin computes the status on every read, the status always
matches the constituent backups. `PARTIAL` is an expected result: you can
restore the environment backup, and it names the deployments it is
missing. Expand an environment backup in the UI, or run
`styrminctl env-backups get <id>`, to view each deployment's constituent
backup, its status, or the error that prevented its creation.

:::caution A final status does not show what the backup still covers

Styrmin writes the environment backup and *all* its constituent backups
in one transaction, before it starts any backup. You therefore never read
an environment backup that is missing a constituent it was about to
create. An environment backup with work to do reports `PENDING` or
`IN_PROGRESS`. One whose constituent backups were all blocked at creation
reports `FAILED`. A `COMPLETED` status right after creation means that no
deployment was eligible, so the environment backup contains only the
config.

A final status does not show whether the environment backup still
*covers* the environment. You can delete constituent backups one by one
afterwards, and the environment backup still reports `COMPLETED`, with an
empty entry for each deleted one. Read the list of constituent backups,
not only the status: a constituent shown with neither a backup nor a
failure reason (`deleted` in the CLI's output) has no backup.

:::

#### Restoring an environment

Restoring a `COMPLETED` or `PARTIAL` environment backup is also one
action. Styrmin sets the environment's config back to the captured value
and restores every usable constituent **in place**, into the deployment
it was taken of.

A restore does not do the following:

- **It does not create or delete deployments.** A restore changes config
  and data, not the list of deployments. A deployment you deleted after
  the backup is not created again, and a deployment you added after it is
  not removed. Only the environment's dedicated ingress controller is
  created, redeployed or removed to match the restored
  `dedicated_ingress`, as on an environment update (see
  [Changing the dedicated ingress of an environment](./ingress-and-networking.md#changing-the-dedicated-ingress-of-an-environment)).
- **It does not change data that it has no backup of.** A deployment
  created after the backup keeps its data. Styrmin still redeploys it
  with the restored environment config, as after any environment update.
  A deployment that is already at the restored config is not redeployed.

Styrmin reports every constituent that it does not restore, with the
deployment name and a reason: a deployment that is not in the restore's
list of restored constituents is in its list of skipped ones. These six
reasons cover the expected cases:

| Reason | What happened |
|--------|---------------|
| `backup failed at creation` | The constituent backup never started, usually because another backup of the deployment was running when the environment backup started. |
| `backup not completed` | The constituent backup exists but did not complete. |
| `backup deleted` | Someone deleted that constituent backup. |
| `backup expired` | The constituent backup's TTL ended and Velero deleted its data. |
| `deployment no longer exists` | The deployment was deleted after the environment backup was taken. |
| `deployment busy with another restore` | Another restore is already running on that deployment. |

Other reasons are possible. When anything else prevents Styrmin from
creating a constituent restore, it reports the error as
`restore could not be created: <error>`, and more reasons may be added.
The reason is free text: read it as a message, not as a code to match in
a script.

:::note Restoring an environment requires the administrator role

Creating and deleting environment backups requires the same role as a
deployment backup. **Restoring** one requires the administrator role,
because it changes the environment's config, which also requires that
role. The UI hides the restore action from users without it.

:::

Styrmin computes a restore's status from its constituent restores in the
same way as a backup's, with the same meaning of `PARTIAL`. The same
limit applies: when the restore reports a final status, its constituent
data restores are done, but the deployments that did not receive a
restore can still be redeploying with the restored config. Each of these
redeploys is a reconciliation of its own deployment: check the status of
those deployments, not of the restore.

When the redeploy of one of those deployments cannot start, the other
redeploys still run and the restore returns normally, with a status that
does not show the failure. The failure is written only to the server log,
not on the restore, so `styrminctl env-backups restore-get` and the UI do
not list it ([#520](https://github.com/opsmill/styrmin/issues/520)): an
`env_restore_fanout_dispatch_error` line gives the restore's
`environment_restore_id`, the `deployment_id` and, when the error has
them, the `error_code` and the term's `path`. The
`env_restore_fanout_dispatched` line counts the failure in
`config_redeploy_failed`. For example, the captured config has an
affinity term that names a deployment you deleted after the backup. The
restore sets the config back as captured, and the next update of each
deployment that the term applies to fails with the deleted deployment's
last name and `deleted: true` until you write the term again.

#### One environment operation at a time

An environment runs at most one environment-level operation, a backup or
a restore, at a time. Styrmin rejects a second request while one runs,
with an error that a program can read, and does not queue it. Operations
on different environments do not block each other, and deployment backups
and restores have their own checks.

Styrmin also computes whether an operation runs from the constituents. If
a constituent backup never starts, it never reaches a final status, its
environment backup does not either, and the environment stays blocked.
Delete the environment backup to unblock the environment (see below).

#### Deleting environment backups

Deleting an environment backup deletes its constituent backups and their
restores, in one action. Each constituent backup still expires on its own
TTL. The environment backup record stays after every constituent backup
has expired, and lists the ones that are gone, so an environment backup
that can restore only three of its five applications shows it.

You can delete an environment backup **in any status**, even while its
constituent backups still run. Use this to unblock an environment whose
environment backup never finishes because a constituent backup never
started.

There is one exception. While an environment clone still captures into
the environment backup, Styrmin refuses to delete it with `IN_USE`, for
at most two hours. See [Discarding a clone](#discarding-a-clone).

Deleting an environment also deletes its environment backups.

### Cloning an environment

An environment backup lets you restore an environment. A **clone** uses
the same kind of capture to create a **second, new environment** next to
the source, running, with the source's data at the time of the clone, in
one action.

Use a clone to test a migration, an upgrade, or an incident procedure on
a copy of production data before you do it in production. Create the
clone, work in it, then delete it.

One action, from the **Clones** tab on the environment page,
`styrminctl env-clones create`, or `cloneEnvironment`, runs these steps:

1. Captures a **new environment backup** of the source, limited to the
   deployments you selected.
2. Waits for that capture to finish. If the capture fails, Styrmin
   **creates nothing**: no environment, no deployments.
3. Creates the new environment from the **captured** config, with your
   override merged into it.
4. Creates one **counterpart deployment** for each included source
   deployment, with the driver version that the capture recorded.
5. Restores each source deployment's data **into its counterpart**.

Every step after step 1 uses the capture. Styrmin does not read the
source again, so data written to the source *after* the capture is not
in the clone: the clone contains the source as it was at one point in
time.

**Cloning requires the administrator role**, as restoring does, because
it writes environment config. Reading clone records does not.

:::note The source is not modified

A clone does not change the source environment's config or declared
state. The only thing it adds to the source is the environment backup it
captured: an ordinary environment backup, in the source's list, that
expires under the source's retention rules.

:::

#### Choosing which deployments come along

When the selection is empty, the clone includes every **eligible**
deployment, with the same eligibility rule as an environment backup: not
deleted, not one of Styrmin's internal deployments, and with a running
instance.

When you name deployments, Styrmin captures and clones only those, for
example to leave a large analytics application out of the clone. The
selection also limits the capture, so Styrmin does not back up the
deployments you leave out.

The result depends on what you name:

| What you named | What happens |
|----------------|--------------|
| A deployment that does not exist, or belongs to another environment | Styrmin **rejects the whole request**. It creates nothing and takes no backup. |
| A deployment that exists but is not eligible | Styrmin **skips** it, by name, with a reason. The request does not fail. |
| An eligible deployment | Styrmin includes it. |
| A selection that leaves out a deployment, or includes one that is not eligible, when an affinity term that the clone copies names that deployment | Styrmin **rejects the whole request** with `VALIDATION_ERROR`. The error message lists each such deployment, the reason the clone does not copy it, and the path of every term that names it. Styrmin creates nothing and takes no backup. Add the deployment to the selection, leave out the deployment whose term names it, or, for a term in the environment's config, clear or override `scheduling`. |

For a program, the GraphQL error of the last row gives the same details in
`extensions.deployments`: one entry per deployment, with its
`deployment_id`, `deployment_name`, `reason` and the `paths` of the terms
that name it. The Python SDK raises `OperationFailedError`, and its
`extensions` attribute contains these extensions:

```python
from styrmin_sdk.exceptions import OperationFailedError

try:
    await client.environment_clones.create(
        "prod-rehearsal", environment_id=environment_id, deployment_ids=[peer_id]
    )
except OperationFailedError as refused:
    for entry in refused.extensions.get("deployments", []):
        print(entry["deployment_name"], entry["paths"])
```

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

The clone record lists every source deployment that you could have
selected: cloned, skipped with a reason, or failed with a reason.
Styrmin's **internal** deployments are the exception: the record does not
list them unless you named one, because Styrmin creates a new ingress
controller for the clone when it creates the environment.

An **empty** selection clones only the environment's config, none of its
applications. That clone reports `COMPLETED`, unless the environment's
config has an affinity term that names a deployment. Because the clone
copies no deployment, Styrmin rejects that request before it creates
anything, as the last row of the table above describes. Clear
`scheduling` (`clearConfigFields: ["scheduling"]`,
`--clear-config-field scheduling`), or replace it in the override
(`configOverride`, `--config-override`) with a `scheduling` that names no
deployment.

#### Changing the config of the clone

A clone that keeps the production config acts like production: it sends
real email, calls real webhooks, and registers real DNS records. A clone
therefore takes an override of the environment config, which Styrmin
applies **before** it creates the new environment, so the counterparts
start with the changed values. Cloned workloads never run with the
source's settings.

The override replaces fields one by one. A field you set replaces the
whole captured field; a field you leave out keeps its captured value. An
override of one environment variable list therefore replaces that list,
and keeps `fqdn_suffix`, retention, and every other field.

To **remove** a setting instead of changing it, for example a DNS
integration used only in production, name it in the clear-fields list. A
cleared field is *absent* from the clone's config: not empty and not set
to its default. Naming a field that the capture did not set has no
effect; only an unknown field *name* is an error. When you name a field
in both lists, the override wins.

The key casing depends on where you set it:

| Where | Casing |
|-------|--------|
| The override input (`configOverride`, `--config-override`) | **camelCase** in GraphQL: the same `UpdateEnvironmentInput` format as `updateEnvironment`, with `envVars` as a list of `{name, value}` entries, not a map. The CLI and the Python SDK also accept the snake_case field names, because their generated input model accepts both. |
| The clear-fields list (`clearConfigFields`, `--clear-config-field`) | **snake_case** config field names: `fqdn_suffix`, `external_dns_endpoints_type`, `backup_ttl`, … |
| What the clone record returns | **snake_case** JSON, whatever casing you sent. |

:::caution Styrmin ignores a misspelled override field

The override input accepts keys it does not recognize, so Styrmin ignores
a misspelled field name instead of rejecting it, and the captured value
stays. Read the `configOverride` that the clone record returns, or the
new environment's config, to check that Styrmin applied your override. A
misspelled name in the clear-fields list **is** rejected, because Styrmin
checks that list against the config's field names.

:::

#### Watching a clone, and what its status means

A clone runs asynchronously, and Styrmin tracks it in its own record: the
capture it uses, the environment it created, one outcome per source
deployment, and a list of operation-level events. Styrmin **computes its
status on every read** from those parts, as for an environment backup:

| Status | What it means |
|--------|---------------|
| `PENDING` | Registered, capture not started. |
| `IN_PROGRESS` | The capture, the environment creation, or a data restore is still running. |
| `COMPLETED` | Every included deployment was cloned. |
| `PARTIAL` | Some included deployments were cloned and some failed. |
| `FAILED` | Nothing was cloned, or the clone was discarded (see below). |

Note:

- **A clone can report `IN_PROGRESS` as soon as you create it.** Styrmin
  records the deployments it skips together with the clone, and a
  recorded outcome counts as progress. Do not wait for `PENDING`.
- **A clone in which every deployment was skipped is `COMPLETED`, not
  `FAILED`.** So is a clone of an empty selection. Styrmin created the
  environment, and no deployment was eligible.

`PARTIAL` is an expected result. For example, the driver version that the
capture recorded no longer exists when Styrmin creates the counterpart.
Styrmin records that deployment as failed, clones the other deployments,
and reports `PARTIAL`.

When the clone is `COMPLETED` or `PARTIAL`, a script can check the new
environment with one call for its pods and one for its services:

```python
from styrmin_sdk.models import EnvironmentCloneStatus

clone = await client.environment_clones.wait_for_clone(clone_id)
if clone.status in (EnvironmentCloneStatus.COMPLETED, EnvironmentCloneStatus.PARTIAL):
    environment_id = clone.created_environment.id
    pods = await client.environments.get_pod_statuses(environment_id)
    services = await client.environments.get_services(environment_id)
```

A pod that started less than about 5 seconds ago is not in `pods` yet.
See [Reading pod statuses from a script](./status-reporting.md#reading-pod-statuses-from-a-script)
and [Listing the services of an environment](./ingress-and-networking.md#listing-the-services-of-an-environment).

Styrmin also records a deployment whose restore failed as failed, with
the reason `the restore failed`, followed by the restore's error when it
has one. The clone records a deployment as cloned when it starts the
restore, and reports it as failed once the restore has failed. One cause
is the step "Create and delete service aliases": when Styrmin cannot write
the counterpart's service aliases, the restore fails with this error:

```text
Create and delete service aliases: <cause>. To write the aliases, change the configuration or the parameters of the deployment, or upgrade it.
```

When the Kubernetes API refused a request, the cause is
`the Kubernetes API answered <HTTP status>: <message>`, for example
`the Kubernetes API answered 403: services is forbidden: …`. The step
"Create and delete service aliases" in the restore's list of steps
contains the full error.

When only the alias step failed, the restore sets the counterpart to
`RUNNING`, because Styrmin recovered its workloads and they run. Only the
failed restore and the clone's entry for that deployment record the
failure. A restore that fails for another cause sets the counterpart to
`FAILED`.

To write the missing aliases, make a change to the counterpart's
configuration or parameters, or upgrade it. The update or upgrade writes
the counterpart's aliases and the aliases of its services in the
namespaces of the other deployments. Saving the same values does not
always run an update, so it might write no alias. After the repair, the
failed restore and the clone's entry for that deployment still show
failed, because they record the restore, not the aliases that the
deployment has now.

A restore that fails after it has started changes only the outcome of the
deployment it restores. A deployment that fails before its restore
starts also fails the deployments whose affinity terms name it. A
deployment fails this way when its captured data cannot be used (its
capture failed, or its backup was deleted, did not complete or expired),
or when its counterpart cannot be created or its restore cannot be
started:

- A deployment whose own config has such a term is recorded as failed,
  and no counterpart is created for it. The reason is
  `an affinity term names deployment <name>, which was not cloned`.
- When two deployments' terms name each other, one counterpart is
  created first. If the other counterpart then fails, the first one is
  recorded as failed with the same reason. Its counterpart exists in
  the new environment, and its next update is refused until you change
  the term.
- A term that comes from the component definitions of the deployment's
  driver version gives a name, which Styrmin looks up when it creates the
  counterpart. When no counterpart has that name, the counterpart is not
  created and the deployment is recorded as failed with the reason
  `Affinity term at <path> names deployment '<name>', which is not a
  deployment of environment '<new environment>'.`
- When the new environment's config names the failed deployment, the
  clone reports `FAILED` with a `referenced_deployment_not_cloned` event.
  When the deployment's captured data cannot be used, no environment is
  created; after a failed counterpart, no further counterpart is created.

#### Discarding a clone

**Delete the environment that the clone created.** This discards the
clone in any status, including `PARTIAL` and `FAILED`, and also deletes
the counterpart deployments. The clone record keeps a
`created_environment_deleted` event, and the UI labels the clone
*Discarded*. A clone that was still running then reports `FAILED`. A
clone that had already finished keeps its outcome (`COMPLETED`, `PARTIAL`
or `FAILED`); the event only records that its environment is deleted.

A clone's name does not have to be unique, and deleting the environment
frees the environment name, so you can clone the same source again under
the same name right away.

When the clone has not created its environment yet, two other actions
end it:

- **Delete the clone's environment backup.** Styrmin refuses this
  (`IN_USE`) only while the clone's *capture* still runs, and only for as
  long as the clone can still wait for it: two hours, the clone's wait
  limit. After the capture finishes, or after the two hours, you can
  delete it. When the constituent backups of a capture never start, the
  two hours run out. Delete the environment backup to end a clone that
  stopped before it created its environment. A clone that is still
  running records the deletion and ends `FAILED`; a clone that already
  finished keeps its outcome.
- **Delete the source environment.** Styrmin keeps the clone record when
  the clone created an environment: it clears the link to the source and
  keeps the source's *name* on the record. A clone that was still
  building its environment also records a fatal
  `source_environment_deleted` event and ends `FAILED`, because Styrmin
  deleted its capture with the source. Styrmin removes the record of a
  clone that created nothing. Because deleting the source also deletes
  its environment backups, a finished clone also records a non-fatal note
  that its capture is deleted.

:::note Deleting an environment deletes its deployments

Deleting an environment deletes the deployments in it, instead of
refusing. This is why deleting a clone's environment discards the clone:
a cloned environment contains at least its counterpart deployments, and
its own ingress controller when it uses a dedicated one. This applies to
every environment, not only to clones.

:::

#### What a clone is *not* isolated from

A clone is isolated at the Kubernetes level: it has its own namespaces,
workloads, and ingress controller. The config override changes
environment-level settings. **Neither changes values stored in the
restored application data.**

The restore copies database rows, config tables, and secrets
**unchanged**. If your application stores an outbound webhook URL, a
payment-provider API key, an SMTP credential, a license key, or a partner
endpoint in its own data, the clone has the same value and can connect to
the same system as the source. Cloned workloads run like the source:
scheduled jobs run, queues are processed, and integrations send requests.

Before the clone connects to other systems, change the external
addresses and credentials stored in its application data yourself. The
override changes only config, not database tables.

One more limit applies to some drivers. Styrmin renders a counterpart's
Helm values again while it restores the counterpart's data from the
source. A driver whose chart **generates** credentials at install time,
such as a random password for each release, can therefore generate a new
credential that the restored data does not accept, and the restored
component becomes unreachable. To support clones, take credentials from
configuration in your driver instead of generating them at deploy time.

#### Other clone behavior

- **A counterpart's Helm release has the source deployment's name.**
  `helm list -n styrmin-<counterpart-id>` shows a release named after the
  *source*. This is intended: the restored objects contain the source's
  Helm ownership metadata, and the same release name keeps Helm's
  records consistent with them. It is not drift.
- **A cloned environment has no backup storage location.** Locations are
  assigned per environment, and a clone does not get the source's, so
  the new environment cannot take its own backups until you assign one.
  This does not affect the restore of the capture *into* the clone.
- **A running clone blocks its new environment.** While a clone runs,
  Styrmin refuses environment-level operations and config changes on the
  environment it builds. You can always delete that environment to
  discard the clone.
- **You can clone a clone**, and run several clones of one source at the
  same time. Only one clone of a source can capture at a time: Styrmin
  refuses a second clone that starts while the first one still
  *captures*, with a busy error.

For the commands and their exit codes, see
[the `env-clones` CLI reference](../reference/styrminctl.md#env-clones--clone-an-environment).

### What you configure and what Styrmin does

| When | What you configure |
|------|--------------------|
| Once per environment | The bucket, the credentials, and the BSL. |
| Once per driver | The backup `kind` of each component, in the driver specification. |
| For each backup | Nothing. Styrmin runs every step. |

### Next steps

- [**Lifecycle hooks and actions**](./hooks-and-actions.md): how drivers
  run Python actions, which a backup strategy of `kind: action` also
  uses.
- [**Ingress and networking**](./ingress-and-networking.md): how traffic
  reaches the applications of each environment.
