---
title: Changelog
sidebar_position: 99
description: Notable changes in each Styrmin release, and the steps to take when you upgrade.
---

Notable changes in each Styrmin release, with the steps to take when you
upgrade. For every change, including fixes, see
[`CHANGELOG.md`](https://github.com/opsmill/styrmin/blob/develop/CHANGELOG.md)
in the repository.

## Unreleased

### Restores no longer delete a namespace that the caller names

**Security fix. Breaking change to `createRestore`, `create_restore()` and
`styrminctl backups restore`.**

Before this change, `createRestore` took the namespace from the caller, and
the restore deleted that namespace before it restored the backup into it. A
user with the `READ_WRITE` role could therefore delete the namespace of
another deployment, or a namespace such as `kube-system`
([#532](https://github.com/opsmill/styrmin/issues/532)).

Styrmin now restores a backup into the deployment it was taken of, in that
deployment's namespace `styrmin-<deployment id>`. You name only the backup.
See
[What happens when you restore](./concepts-and-architecture/backups-and-restores.md#what-happens-when-you-restore).

#### What's new

- The Backups tab, `styrminctl backups restore`, `create_restore()` in the
  Python SDK, `createRestore` and an environment restore all restore a
  backup into the deployment it was taken of. The deployment keeps its
  active instance, even when the backup belongs to an earlier instance.
- Before it changes anything in the cluster, the restore fails when the
  namespace it received is not the namespace of its deployment. The error
  says that nothing changed in the cluster.
- The Restore dialog shows, as text, the deployment and the namespace that
  the backup is restored into.
- `styrminctl backups restore --last --target-instance-id` asks for
  confirmation when the backup was taken of an earlier instance or at
  another application version, as `--target-deployment` and
  `--target-deployment-id` already did. `--target-deployment` and
  `--target-deployment-id` no longer refuse a deployment without an active
  instance.
- The "Restore already in progress" error says to wait until that restore
  completes or fails, and where to view its status.

#### Migration

- Upgrade the server, `styrminctl` and the Python SDK together:
  - A `styrminctl`, Python SDK or web page from before this change sends
    `targetNamespace` on every restore, `--last` included. The server
    refuses it with an error that starts with "createRestore no longer
    takes the argument targetNamespace" and says to upgrade.
  - A server from before this change requires `targetNamespace`, so it
    refuses a restore from a newer `styrminctl`, Python SDK or web page.
    The newer `styrminctl` and Python SDK then raise
    `IncompatibleServerError`, which says to upgrade the server.
- Reload the web pages that were open during the upgrade.
- Remove `targetNamespace` and `targetInstanceId` from your GraphQL
  requests, `target_namespace` and `target_instance_id` from your calls to
  `create_restore()`, and `--target-namespace` from your
  `styrminctl backups restore` commands.
- Run `styrminctl backups restore <backup-id>` with the backup id alone.
  The command now refuses a backup id combined with `--target-deployment`,
  `--target-deployment-id`, `--target-instance-id` or `--environment`, and
  exits with status 1. The earlier example of the `styrminctl` README,
  `styrminctl backups restore <backup-id> --target-deployment my-app`,
  fails this way. These options work only with `--last`, where they choose
  which backups the newest completed backup is picked from.
- A restore that an earlier version created with another namespace, and
  whose flow starts after the upgrade, fails. Start a new restore of the
  backup.
- Apart from an environment clone, Styrmin offers no way to restore a
  backup into another deployment.

## v0.1.50 (2026-10-19)

### FluxCD uses the defaults of Helm v4

The agent now runs FluxCD's helm-controller with the defaults of Helm v4,
without the `UseHelm3Defaults` feature gate that kept the client-side apply
and health checks of Helm v3
([#435](https://github.com/opsmill/styrmin/issues/435)). See
[The HelmRelease](./concepts-and-architecture/operator-and-crds.md#the-helmrelease).

#### What's new

- A deployment created after the agent upgrade is installed with
  server-side apply. helm-controller is the field manager and forces field
  ownership conflicts, so at each upgrade a field that the chart sets
  returns to the chart's value, even when `kubectl` or a driver action
  changed it. The upgrade does not fail.
- Installs and upgrades wait for the chart's resources with kstatus. The
  wait ends before the HelmRelease timeout when kstatus reports a resource
  as failed, for example a `Job` that failed or a `Deployment` past its
  `progressDeadlineSeconds`. When pods cannot pull their image, FluxCD
  still waits the full timeout, and the failed step still names the pods'
  reason, such as `ImagePullBackOff`.
- Helm hooks of a driver's chart, the resources annotated `helm.sh/hook`,
  receive Styrmin's post-render patches as the chart's other resources do
  (see
  [Step 1 of Create a driver](./drivers/creating-a-driver.md#step-1-analyze-the-helm-chart)):
  - Styrmin's labels reach every hook.
  - The deployment's scheduling settings reach hook `Job`, `CronJob`,
    `Deployment`, `StatefulSet`, `DaemonSet` and `ReplicaSet` resources
    whose own `metadata.labels` include a component's first identifier
    label, or every hook of these kinds when the driver declares no
    components.
  - Env var, image and container overrides, and the check of the
    component container, reach a hook only when it is a `Deployment` or
    `StatefulSet` that matches a component.
- A chart resource without `metadata.labels`, such as a Helm hook, no
  longer fails the install or upgrade. Styrmin adds its labels to it.

#### Migration

- Deployments created before the agent upgrade keep client-side apply on
  their later upgrades and rollbacks, because an upgrade uses the apply
  method recorded in the release's newest revision, and a rollback uses
  the method of the revision it returns to. From their next upgrade,
  FluxCD waits for their resources with kstatus and their Helm hooks
  receive the post-render patches.
- A Helm hook `Job` that must run with the deployment's scheduling
  settings needs a component's first identifier label in its own
  `metadata.labels`, not only on its pod template.
- A Helm hook `Deployment` or `StatefulSet` that matches a component but
  does not render the component container fails the install or upgrade
  with `COMPONENT_CONTAINER_NOT_FOUND` once an override applies to that
  component, as a template would.
- With a `progressDeadlineSeconds` below 270 seconds on a chart
  `Deployment`, FluxCD fails a change and rolls the release back before
  Styrmin reads why the pods are not ready, so the failed step shows
  FluxCD's `ProgressDeadlineExceeded` failure instead of the pods' reason.
- A driver action that changes a resource of the chart directly, for
  example with `kubectl patch`, does not keep a field that the chart sets
  on a deployment installed with server-side apply: the field returns to
  the chart's value at the next upgrade. `stop_components` and
  `start_components` change the component's state through Styrmin, which
  applies it in its next render, so their effect lasts.
- To return to the behavior of Helm v3, downgrade the agent chart to a
  release that runs helm-controller with the `UseHelm3Defaults` gate.
  Deployments created while the gate was off keep server-side apply on
  their later upgrades and rollbacks.

### Set the replica count of each component

**Breaking change:** the `infrahub` and `infrahub-enterprise` drivers no
longer declare the `replicas_server` and `replicas_task_worker`
parameters, and the agent chart must be upgraded together with the server.

You can now set how many pods each component of a deployment runs, with a
**replica override**, without a driver parameter. Styrmin sets the count on
`spec.replicas` of the component's `Deployment` and `StatefulSet`
workloads after the Helm chart renders
([#202](https://github.com/opsmill/styrmin/issues/202)). See
[Replica overrides](./concepts-and-architecture/replica-overrides.md).

#### What's new

- Set, change and clear a count in the **Deploy** form, in the **Edit
  configuration** drawer, with `ComponentConfigInput.replicas` in the API
  and the SDK, with `components[].replicas` in a `styrminctl deployments
  apply` manifest, and with the new `styrminctl deployments scale` command,
  which keeps the other overrides of the deployment.
- The count comes from the replica override, then from the driver default
  (`components.<name>.replicas`), then from the chart. The **Component
  Overrides** card, `styrminctl deployments get` and
  `Deployment.componentReplicas` show each component's count and its
  source.
- A driver marks a component that must run a single pod with
  `singleton: true`. A count above 1 on it is rejected with
  `SINGLETON_REPLICA_OVERRIDE`.
- The server setting `STYRMIN_MAX_REPLICA_COUNT` (Helm value
  `styrmin.maxReplicaCount`, default 20) limits the count a user can set.
  A higher count is rejected with `REPLICA_COUNT_ABOVE_MAXIMUM`.
- The update task completes when the workloads run the new count of ready
  pods, and no more.
- The `infrahub` driver moves to version 5 and `infrahub-enterprise` to
  version 4: `server` and `task-worker` have driver defaults of 1 and 2
  pods, and `database`, `task-manager-db` and `cache` are singleton
  components. `simple-app` version 4 marks `database` as singleton.
- When a deployment changes driver version, Styrmin drops a parameter that
  the target version no longer declares if the parameter holds its
  default, and otherwise rejects the change with `RETIRED_PARAMETER_VALUE`.
  See
  [Change a deployment's driver version](./drivers/changing-driver-versions.md).

#### Migration

- **Upgrade the agent chart together with the server.** An agent from an
  earlier release rejects a deployment context that contains a replica
  override, and ignores `replicas` in a driver declaration: the components
  of `infrahub` 5 and `infrahub-enterprise` 4 then run the chart's count
  without any message.
- **Upgrade the Python SDK and `styrminctl` after the server.** Their
  `deployments get` fails against an earlier server.
- **Clear every replica override before you roll Styrmin back** below
  v0.1.50. Earlier releases reject the `replicas` key in a deployment's
  config.
- **Move infrahub deployments to the new driver versions.** The
  `replicas_server` and `replicas_task_worker` parameters are removed. A
  deployment that kept their defaults moves without a manual step. A
  deployment with another value, including every deployment created from
  the earlier `examples/deployments/infrahub.yml` manifest, which set
  `replicas_task_worker: 1`, must first move the value to a replica
  override. See
  [Migrate the infrahub replica parameters](./drivers/migrating-replica-parameters.md).
- **If you maintain a driver,** load a version that marks each
  single-primary component with `singleton: true` before you upgrade.
  Users can set a replica override on any component as soon as the server
  runs v0.1.50, even on a driver version loaded earlier.
- **On a shared cluster,** keep `STYRMIN_MAX_REPLICA_COUNT` low and add a
  `ResourceQuota` to each deployment namespace: the maximum applies per
  component, not per deployment.

## v0.1.48 (2026-10-15)

### Override `command` and `args` on any component with a component container

**Breaking change for driver authors:** a driver version whose
`values.j2.yml` calls `component_command` or `component_args`, or whose
`driver.styrmin.yml` contains `spec.container_overrides`, no longer loads.

Styrmin now applies the container `command` and `args` overrides that users
set on a deployment after the Helm chart renders, to each component's
declared **component container**, as it already does for env vars and image
overrides. Drivers no longer pass these overrides to the chart in
`values.j2.yml` ([#457](https://github.com/opsmill/styrmin/issues/457)).
See
[Migrate command and args overrides to component containers](./drivers/migrating-container-overrides.md).

#### What's new

- A `command` or `args` override reaches the component container whether
  or not the chart exposes it as a value. The `server` and `task-worker`
  components of the `infrahub` and `infrahub-enterprise` drivers now accept
  `command`.
- An override replaces the whole `command` or `args` list, and a field
  without an override keeps the chart's value. Clearing an override
  restores the chart's `command` and `args`.
- Adding or changing `command` or `args` on a component without a
  component container is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`.
  The deployment's **Edit configuration** drawer hides the Command and Args editors
  for such a component, shows stored values read-only, marked **not
  applied**, with a remove button, and offers no **Add override**.
  `ComponentContainerOverrides.isApplicable` in the API reports whether a
  stored override applies.
- The **Component Overrides** card on the **Settings** tab lists the
  stored `command` and `args` of each component, with an **applied** or
  **not applied** badge, and lists every block stored on a component that
  the driver no longer declares.
- In the **Edit configuration** drawer, a change to only the `command` or `args` of
  a component now enables **Review & apply**.
- `styrminctl deployments apply` warns once per component about the
  overrides it stores but the driver version does not apply, names their
  kinds and says how to fix it. The SDK lists the kinds per component in
  `ApplyOutcome.inapplicable_overrides`.
- The example drivers no longer call the retired filters: `simple-app`
  version 3, `infrahub` version 4 and `infrahub-enterprise` version 3.

#### Migration

- Before you upgrade Styrmin, list the stored `command` and `args` of your
  deployments with `styrminctl deployments get`. Remove the values you do
  not want with `styrminctl deployments update --config` or
  `styrminctl deployments apply`. The **Edit configuration** drawer of earlier
  releases cannot submit a change that only removes `command` or `args`.
  See
  [Before you upgrade Styrmin](./drivers/migrating-container-overrides.md#before-you-upgrade-styrmin).
- After the upgrade, Styrmin applies the stored values to every component
  with a component container on the next render of the deployment. An env
  var edit on its environment or a cluster config update can also start
  that render. Values that a driver template did not pass to the chart
  reach the pods for the first time, such as `command` on the infrahub
  `server`, or any value on the `slurpit`, `semaphore`, `infrahub-mcp` and
  `db-test` drivers.
- The `component_command` and `component_args` template filters are
  retired. Loading a driver version whose `values.j2.yml` calls either one,
  or the earlier retired `component_env_vars`, fails with
  `RETIRED_TEMPLATE_FILTER`. A deployment pinned to a driver version loaded
  earlier that still calls them fails on its next change, even when it has
  no override set; its pods keep running. Load the migrated drivers and
  move each deployment to them.
- `spec.container_overrides` is removed from `driver.styrmin.yml`: a driver
  file that still contains it fails to load, with an error that links to
  the migration guide. The API no longer has
  `ApplicationDriverVersion.containerOverrides` or the
  `DriverContainerOverrideDoc` type, and the SDK no longer has
  `get_driver_container_override_docs`.
- Container overrides now reach only the component container, not chart
  Jobs, init containers, or other containers in the pod.

### Change a cluster's config without recreating it

**Breaking change for scripts:** `styrminctl clusters get` and
`clusters list` print the config as JSON instead of Python dict text.

With the administrator role, you can now change any value of a cluster's
config, such as the FQDN suffix, the ingress class, a storage class or the
dedicated ingress, without deleting and recreating the cluster, its
environments and its deployments. See
[`clusters update`](./reference/styrminctl.md#clusters-update--change-a-clusters-config).

#### What's new

- `styrminctl clusters update`, `clusters.update()` in the Python SDK, the
  `updateCluster` GraphQL mutation and an **Edit** button on the cluster
  detail page replace the whole cluster config
  ([#423](https://github.com/opsmill/styrmin/issues/423)).
- Styrmin redeploys each deployment whose resolved config changes, in
  every environment of the cluster. The command, the SDK and the dialog
  list the deployments that are redeployed, that wait for a dedicated
  ingress controller, and that could not start. Run the update again to
  retry the ones that could not start.
- `styrminctl clusters update --dry-run`, the `dryRun` argument and the
  dialog's review step list the changes and the deployments to redeploy
  before anything is saved.
- `styrminctl clusters get --json` prints only the cluster config, to edit
  and pass to `clusters update --config @FILE`.
- When `dedicated_ingress` changes, the applications of an environment move
  to its dedicated ingress controller only after the controller is
  `RUNNING`, and Styrmin removes the controller only after the
  applications have moved off it.

#### Migration

- When an environment update turns the environment's own
  `dedicated_ingress` off and the cluster does not set
  `dedicated_ingress`, Styrmin now removes the environment's dedicated
  ingress controller after its applications are redeployed to the
  cluster's `ingress_class`. Before, the controller stayed until the last
  application of the environment was deleted. If you rely on that
  controller, for example for its load balancer IP, set
  `dedicated_ingress` on the environment or the cluster again before you
  upgrade.
- Whenever an environment's dedicated ingress controller reaches
  `RUNNING`, Styrmin now also redeploys the applications of that
  environment that are not at the config they resolve to.
- `styrminctl clusters get` and `clusters list` print the config as JSON
  instead of Python dict text. Change scripts that parse the old output,
  or use `clusters get --json`.
- A storage class change makes deployments whose StatefulSets use the
  storage class `FAILED`, because Kubernetes refuses to change the storage
  class of an existing volume claim. The Infrahub drivers are affected.
  Saving again does not retry them: submit the previous storage class
  again, or delete and redeploy the deployment.

### Env vars and image overrides reach the pods after every change

The agent now installs the FluxCD controllers of Flux v2.9.6:
helm-controller v1.6.5 and source-controller v1.9.6, in place of
helm-controller v1.1.0 and source-controller v1.4.0. helm-controller v1.1.0
could report a change of env vars or image overrides as in sync without
applying it, and the pods kept the previous values.

#### What's new

- An upgrade to another driver version applies the new env vars and image
  overrides, even when the Helm values stay the same
  ([#432](https://github.com/opsmill/styrmin/issues/432)).
- A change of env vars or image overrides that reaches the cluster while
  FluxCD still upgrades the previous change is applied after that upgrade
  ([#433](https://github.com/opsmill/styrmin/issues/433)).
- Before each `helm install` and `helm upgrade`, a Job of the agent chart
  applies the agent's CRDs, because Helm never updates the files in a
  chart's `crds/` directory. Set `styrmin-agent.crdUpgrade.enabled` to
  `false` to apply them yourself.

#### Migration

- The FluxCD v2.9 controllers support Kubernetes 1.34.1 and later.
- `helm upgrade` runs the CRD Job first. It deletes and creates again the
  `ocirepositories.source.toolkit.fluxcd.io` CRD, which Styrmin does not
  use, because the new CRD no longer lists the `v1beta2` version that the
  old one stored. The Job fails the upgrade instead if the cluster has
  `OCIRepository` objects.
- When you disable the CRD Job, apply the files of `helm/agent/crds/`
  before you upgrade. Otherwise helm-controller and source-controller
  cannot start, and no change of a deployment reaches the cluster.
- A deployment whose pods kept older env vars or images because of #432
  or #433 keeps them after the upgrade. Its next change applies the
  current values.

## v0.1.47 (2026-10-07)

### Run a custom image on one component

You can now run a custom or patched build on one component of a
deployment without forking its driver. Styrmin applies the **image
override** after the Helm chart renders, to the component's declared
**component container**
([#20](https://github.com/opsmill/styrmin/issues/20)). See
[Image overrides](./concepts-and-architecture/image-overrides.md).

#### What's new

- Set an image per component in the deployment's **Edit configuration** drawer, in
  a `styrminctl deployments apply` manifest (`components[].image`), or
  with `ComponentConfigInput.image` in the API and SDK. The **Settings**
  tab shows the stored and resolved reference and whether it is applied.
- A `{{ app.version }}` token follows the deployment's application
  version; a literal tag or digest pins the image. The upgrade dialog and
  `styrminctl deployments apply` warn about pinned overrides before an
  application version change.
- Styrmin rejects an invalid reference when you save it, and rejects an
  upgrade that would make a reference invalid before any lifecycle action
  runs.

#### Migration

- A driver whose declared component container name the chart does not
  render now fails the deployment with `COMPONENT_CONTAINER_NOT_FOUND`,
  naming the component and the container, as soon as env vars or an image
  override target it. Styrmin never adds a container.
- `get_component_images` returns the component container's image first.
  Driver actions take `images[0]` instead of searching for an image name;
  the example drivers do this.
- Clear every image override before you roll Styrmin back below v0.1.47:
  earlier releases reject the `image` key.

## v0.1.46 (2026-10-04)

### Env vars keep the chart's env defaults

**Breaking change for driver authors:** the `component_env_vars` template
filter is removed.

Styrmin now merges the env vars that users set on a deployment into each
component's declared **component container** after the Helm chart renders,
instead of having the driver write them into the chart's values. Chart env
defaults are no longer dropped
([#385](https://github.com/opsmill/styrmin/issues/385)).

#### What's new

- Drivers declare `components.<name>.container` in `driver.styrmin.yml`.
  User env vars reach that container by name: the chart's own env entries
  are kept, and a user value replaces a chart entry of the same name.
- Adding or changing a component env var on a component without a
  component container is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`.
  The deployment's **Edit configuration** drawer hides the env var editor for such
  components, and the driver's **Components** tab shows each component's
  container.
- Every example driver declares its component containers. The `infrahub`
  task manager keeps the Prefect chart's `PROMETHEUS_MULTIPROC_DIR` and
  `PREFECT_UI_SERVE_BASE` defaults.

#### Migration

- A deployment pinned to a driver version that still calls
  `component_env_vars` fails on its next change. Load the migrated drivers
  and upgrade each deployment before you edit env vars on an environment.
  Driver authors declare containers and remove the filter. See
  [Migrate env vars to component containers](./drivers/migrating-env-vars.md).
- User env vars now reach only the component container, not chart Jobs,
  init containers, or other containers in the pod.

### Clone an environment, with its data, in one action

An **environment clone** uses an environment backup to create a second,
running environment next to the source, with the source's data at the
time of the clone, in one operation
([#6](https://github.com/opsmill/styrmin/issues/6)).

#### What's new

- One action captures a new environment backup of the source, waits for
  it, creates a new environment from the captured config, creates one
  **counterpart deployment** per included source deployment (pinned to the
  driver version the capture recorded), and restores each source
  deployment's data **into its counterpart**. Every step after the capture
  uses the capture, and Styrmin does not read the live source again, so
  the clone holds the data of one point in time. The source's config and
  declared state do not change.
- **Choose the deployments to clone.** Leave the selection empty to clone
  every eligible deployment, or name the deployments to clone. The
  selection also filters the capture, so Styrmin does not back up the
  deployments you leave out. Styrmin rejects an unknown deployment id, or
  the id of a deployment of another environment, before it creates
  anything. It skips an ineligible deployment by name, with a reason, and
  reports no error. An empty selection clones only the configuration.
- **Change the configuration before the clone starts,** so that a clone
  of production does not start with production's outbound integrations. A
  field you supply replaces the whole captured field. A separate list of
  fields to clear **removes** a captured setting. Styrmin applies both
  before it creates the new environment, so the counterparts start with
  the changed values.
- Styrmin computes a clone's status (`PENDING`, `IN_PROGRESS`,
  `COMPLETED`, `PARTIAL` or `FAILED`) on every read, from the capture, the
  created environment, the outcome of each deployment and the restores.
  The clone record lists every source deployment you could have selected,
  by name. A new clone often reads `IN_PROGRESS` instead of `PENDING`, and
  a clone whose deployments were all skipped is `COMPLETED`, not a
  failure.
- **Discard a clone by deleting the environment it created,** in any
  state, including `PARTIAL` and `FAILED`. The clone record keeps the
  history as a discarded outcome. A clone's name is not unique, so you can
  clone again under the same name at once. For a clone that stopped
  before its environment was created, delete its environment backup.
- **Cloning requires the administrator role,** because it writes
  environment configuration, as a restore does. Reading clone records does
  not.
- New in the UI, the CLI, the SDK and the API: a **Clones** tab on the
  environment detail page, with a Clone dialog that requires the
  administrator role and shows each ineligible deployment as disabled,
  with its reason; the `styrminctl env-clones` group (`create`, `get`,
  `list`, with `--deployment`, `--config-override`, `--clear-config-field`
  and `--wait` on `create`); `client.environment_clones` in the Python SDK;
  and the `cloneEnvironment` mutation with the `environmentClone` and
  `environmentClones` queries and the `Environment.clonedFrom` field.

#### Limits

- **A clone copies the external addresses and credentials stored in the
  application data.** Credentials, webhook URLs, API endpoints and license
  keys stored in the restored application data are copied unchanged, so
  the clone can connect to the same external systems as the source. The
  config override changes environment-level settings, not database
  tables. Change these values yourself.
- A driver whose chart **generates** credentials at install time can
  generate new credentials over the restored data. Drivers that support
  cloning take credentials from configuration.
- A counterpart's Helm release is named after the **source** deployment,
  which keeps Helm's ownership metadata consistent with the restored
  objects. `helm list` in the counterpart's namespace shows a release
  named after the source; this is expected.
- A cloned environment does **not** get the source's backup storage
  location. Assign one before it can take backups of its own.

#### Behavior changes

- **Deleting an environment now deletes its deployments.** Before,
  `deleteEnvironment` failed when the environment had deployments. This
  applies to every environment, not only to clones, and it is how you
  discard a clone.
- **Styrmin now refuses a second restore only while the deployment has a
  `PENDING` or `IN_PROGRESS` restore.** Before, it refused a restore
  whenever the deployment was in the `RESTORING` state, so a deployment
  whose restore never finished could not be restored again.
- Deleting an environment backup is refused with `IN_USE` while a clone
  still captures it. After the capture finishes, deletion is allowed
  again.

#### Migration

- No action required. Existing environments, deployments and backups do
  not change. A clone runs in the cluster of its source; clones to another
  cluster are not supported.
- See
  [Cloning an environment](./concepts-and-architecture/backups-and-restores.md#cloning-an-environment)
  for how cloning works and
  [the CLI reference](./reference/styrminctl.md#env-clones--clone-an-environment)
  for the commands, flags and exit codes.

### Back up and restore a whole environment in one action

Before, Styrmin backed up one deployment at a time. An **environment
backup** captures a whole environment as one record, and you restore it
with one action ([#7](https://github.com/opsmill/styrmin/issues/7)).

#### What's new

- One action captures the environment's config, the declared state of
  every eligible deployment (application driver, driver version and
  provenance fingerprint, application version, config, parameters), and
  one constituent backup per eligible deployment. Constituent backups are
  ordinary deployment backups: same storage location, same retention
  rules, and you can list and delete each one.
- Restoring a `COMPLETED` or `PARTIAL` environment backup restores the
  environment config and every usable constituent backup **in place**. It
  never creates or deletes deployments: a deployment added or deleted
  since the backup is reported, not changed. The restore names every
  constituent backup that it does not restore, with a reason. **Restoring
  requires the administrator role**, because it rewrites the environment
  config. Creating and deleting need the same role as a deployment backup.
- Styrmin computes the status of an environment backup from its
  constituent backups on every read, so the status always matches them.
  `PARTIAL` is an expected result: an environment backup that covered four
  of five applications says so, and you can still restore it.
- An environment runs at most one environment-level operation at a time.
  Styrmin rejects a second request with a machine-readable error and does
  not queue it.
- New in the UI, the CLI, the SDK and the API: a **Backups** tab on the
  environment detail page; the `styrminctl env-backups` command group
  (`create`, `get`, `list`, `restore`, `restore-get`, `restore-list`,
  `delete`, with `--wait` on `create` and `restore`);
  `client.environment_backups` in the Python SDK; and the
  `createEnvironmentBackup`, `restoreEnvironmentBackup` and
  `deleteEnvironmentBackup` mutations with the `environmentBackup`,
  `environmentBackups`, `environmentRestore` and `environmentRestores`
  queries.

#### Migration

- No action required. Existing deployment backups do not change.
- Deleting an environment deletes its environment backups.
- See
  [Backups and restores](./concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment)
  for how environment backups work and
  [the CLI reference](./reference/styrminctl.md#env-backups--environment-level-backup-and-restore)
  for the commands, flags and exit codes.

## v0.1.32 (2026-06-03)

### Pin a driver version when you deploy or upgrade

When several loaded driver versions support the same application version,
deployments now bind to one driver version by a fixed rule, latest wins,
and the deploy and upgrade APIs accept a driver version to pin.

#### What's new

- Styrmin selects the driver version with the highest parseable
  `spec.version`. Between versions with the same `spec.version`, including
  rebuilds with different fingerprints, the one loaded last wins. Before,
  Styrmin used the first matching row in database order.
- Every upgrade selects the driver version again. Running
  `styrminctl deployments update-version <id> <same-version>` after you load
  a newer driver build for the same application version moves the
  deployment to that build. Before, this changed nothing while the current
  build still matched.
- The `deploy` and `updateDeploymentVersion` GraphQL mutations accept an
  optional `driverVersionId` to pin a specific build. The SDK
  (`deployments.create`, `deployments.update_version`) and the CLI
  (`--driver-version-id` on `deployments create` and
  `deployments update-version`) accept it too.
- The Upgrade dialog has a driver-version picker that defaults to
  **Latest (auto)**.

#### Migration

- No action required. Deployments keep their current driver version until
  the next upgrade, which follows the rule above. See
  [Selecting a driver version](./drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading).

## v0.1.26 (2026-05-27)

### Reload a driver without changing `spec.version`

Styrmin now identifies an application driver version by a **provenance
fingerprint** as well as its `spec.version` string. The fingerprint is a
SHA-256 content hash for local drivers and the resolved git commit SHA for
git drivers.

#### What's new

- Running `styrminctl drivers load-local-version <path>` again on an
  edited driver records a new application driver version, even when
  `spec.version` is unchanged. Three files make up the content hash:
  `driver.styrmin.yml`, the values template, and `actions.py` (only when
  `spec.actions` is not empty).
- Loading unchanged content again changes nothing: repeated loads no
  longer create duplicate rows, and no longer fail with the
  `IntegrityError` that local reloads raised before.
- The UI, the CLI and the SDK show every driver-version label as
  `<version>@<short-fingerprint>` (the first 7 hex characters). Detail
  pages show the full 64-character content hash or 40-character commit
  SHA, with a copy-to-clipboard control.
- The `ApplicationDriverVersion` GraphQL type has two new nullable fields:
  `contentHash` (set for `sourceType == "local"`) and `sourceCommitSha`
  (set for `sourceType == "git"`). Exactly one is set per driver version.

#### Migration

- No action required. Driver versions loaded before this release keep the
  bare `version` label until you load them again.
- See
  [`dev/guides/driver-iteration.md`](https://github.com/opsmill/styrmin/blob/develop/dev/guides/driver-iteration.md)
  for the steps to iterate on a driver.

## v0.1.22 (2026-05-22)

### Edit every deployment setting on one Settings tab

The **Settings** tab of the deployment detail page replaces the
**Parameters** tab.

#### What's new

- The Settings tab shows the configuration that the application runs
  with. Each value shows the level that sets it: cluster, environment or
  deployment. A small filled marker shows the rows that the deployment
  overrides.
- The **Update Settings** drawer on the right edits every deployment
  setting in one place: environment variables, services, driver
  parameters, scheduling, and per-component overrides.
- Each apply opens a review dialog that classifies each change as
  informational, warning or disruptive, from a fixed table of rules. You
  do not type a confirmation.
- If another client changes the deployment while you edit it, a banner
  appears above your pending changes, with a **Reload** button that merges
  them with the new values. Styrmin keeps your pending edits.

#### Migration

- The **Scheduling** button is removed from the deployment header.
  Scheduling is now on the Settings tab: open the tab and click **Update
  Settings**.
- The **Parameters** tab is renamed **Settings**. The same fields are
  editable in the drawer.
- A banner explains the change on your first visit; click **×** to close
  it.

#### Limits

- In v0.1.22, **Networking** and **Storage & Runtime** are shown on the
  Settings tab but cannot be edited from the drawer.
