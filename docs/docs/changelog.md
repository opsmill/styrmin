---
title: Changelog
sidebar_position: 99
description: Notable user-visible changes to the Styrmin platform.
---

## Changelog

Notable user-visible changes are recorded here. For full commit history, see the [GitHub repository](https://github.com/opsmill/styrmin).

### FluxCD installs and upgrades deployments with Helm v4's defaults

The agent now runs FluxCD's helm-controller with the defaults of Helm
v4, without the `UseHelm3Defaults` feature gate that kept Helm v3's
client-side apply and health checks
([#435](https://github.com/opsmill/styrmin/issues/435)). See
[The HelmRelease](./concepts-and-architecture/operator-and-crds.md#the-helmrelease--styrmins-other-crd).

#### What's new

- A deployment created after the agent upgrade is installed with
  server-side apply. helm-controller is the field manager and forces
  field ownership conflicts, so at each upgrade a field that the chart
  sets returns to the chart's value, also when `kubectl` or a driver
  action changed it. The upgrade does not fail.
- Installs and upgrades wait for the chart's resources with kstatus.
  The wait ends before the HelmRelease timeout when kstatus reports a
  resource as failed, for example a `Job` that failed or a `Deployment`
  past its `progressDeadlineSeconds`. When pods cannot pull their image,
  FluxCD still waits the full timeout, and the failed step still names
  the pods' reason, such as `ImagePullBackOff`.
- Helm hooks of a driver's chart, the resources annotated
  `helm.sh/hook`, receive Styrmin's post-render patches as the chart's
  other resources do (see
  [Step 1 of Creating a driver](./drivers/creating-a-driver.md#step-1-analyse-the-helm-chart)):
  - Styrmin's labels reach every hook.
  - The deployment's scheduling settings reach hook `Job`, `CronJob`,
    `Deployment`, `StatefulSet`, `DaemonSet` and `ReplicaSet` resources
    whose own `metadata.labels` carry a component's first identifier
    label, or every hook of these kinds when the driver declares no
    components.
  - Env var, image and container overrides, and the component-container
    guard, reach a hook only when it is a `Deployment` or `StatefulSet`
    that matches a component.
- A chart resource without `metadata.labels`, such as a Helm hook, no
  longer fails the install or upgrade. Styrmin adds its labels to it.

#### Migration

- Deployments created before the agent upgrade keep client-side apply
  on their later upgrades and rollbacks, because an upgrade uses the
  apply method recorded in the release's newest revision, and a rollback
  uses the method of the revision it returns to. From their next upgrade, FluxCD waits for their resources
  with kstatus and their Helm hooks receive the post-render patches.
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
  FluxCD's `ProgressDeadlineExceeded` failure instead of the pods'
  reason.
- A driver action that changes a resource of the chart directly, for
  example with `kubectl patch`, does not keep a field that the chart
  sets on a deployment installed with server-side apply: the field
  returns to the chart's value at the next upgrade. `stop_components`
  and `start_components` change the component's state through Styrmin,
  which applies it in its next render, so their effect lasts.
- To go back to Helm v3's behaviour, downgrade the agent chart to a
  release that runs helm-controller with the `UseHelm3Defaults` gate.
  Deployments created while the gate was off keep server-side apply on
  their later upgrades and rollbacks.

### Set the replica count of each component

A user can now set how many pods each component of a deployment runs,
with a **replica override**, without a driver parameter. Styrmin sets the
count on `spec.replicas` of the component's `Deployment` and `StatefulSet`
workloads after the Helm chart renders
([#202](https://github.com/opsmill/styrmin/issues/202)). See
[Replica overrides](./concepts-and-architecture/replica-overrides.md).

#### What's new

- Set, change and clear a count in the **Deploy** form, in the **Edit
  configuration** drawer, with `ComponentConfigInput.replicas` in the API
  and the SDK, with `components[].replicas` in a `styrminctl deployments
  apply` manifest, and with the new `styrminctl deployments scale`
  command, which keeps the other overrides of the deployment.
- The count comes from the replica override, then from the driver
  default (`components.<name>.replicas`), then from the chart. The
  **Component Overrides** card, `styrminctl deployments get` and
  `Deployment.componentReplicas` show each component's count and its
  source.
- A driver marks a component that must run a single pod with
  `singleton: true`. A count above 1 on it is rejected with
  `SINGLETON_REPLICA_OVERRIDE`.
- The server setting `STYRMIN_MAX_REPLICA_COUNT` (Helm value
  `styrmin.maxReplicaCount`, default 20) limits the count a user can set.
  A higher count is rejected with `REPLICA_COUNT_ABOVE_MAXIMUM`.
- The update task completes when the workloads run the new count of
  ready pods, and no more.
- The `infrahub` driver moves to version 5 and `infrahub-enterprise` to
  version 4: `server` and `task-worker` have driver defaults of 1 and 2
  pods, and `database`, `task-manager-db` and `cache` are singleton
  components. `simple-app` version 4 marks `database` as singleton.
- When a deployment changes driver version, a parameter that the target
  version no longer declares is dropped if it holds its default, and
  otherwise rejects the change with `RETIRED_PARAMETER_VALUE`. See
  [Changing Driver Versions](./drivers/changing-driver-versions.md).

#### Migration

- **Upgrade the agent chart together with the server.** An agent from an
  earlier release rejects a deployment context that carries a replica
  override, and ignores `replicas` in a driver declaration: the
  components of `infrahub` 5 and `infrahub-enterprise` 4 then run the
  chart's count without any message.
- **Upgrade the Python SDK and `styrminctl` after the server.** Their
  `deployments get` fails against an earlier server.
- **Clear every replica override before you roll Styrmin back** below
  this release. Earlier releases reject the `replicas` key in a
  deployment's config.
- **Move infrahub deployments to the new driver versions.** The
  `replicas_server` and `replicas_task_worker` parameters are removed. A
  deployment that kept their defaults moves without a manual step. A
  deployment with another value, including every deployment created from
  the earlier `examples/deployments/infrahub.yml` manifest, which set
  `replicas_task_worker: 1`, must carry the value over as a replica
  override first. See
  [Migrating Replica Parameters](./drivers/migrating-replica-parameters.md).
- **If you maintain a driver,** load a version that marks each
  single-primary component with `singleton: true` before you upgrade.
  Users can set a replica override on any component as soon as the server
  runs this release, also on a driver version loaded earlier.
- **On a shared cluster,** keep `STYRMIN_MAX_REPLICA_COUNT` low and add a
  `ResourceQuota` to each deployment namespace: the maximum applies per
  component, not per deployment.

### Override `command` and `args` on any component with a component container

Styrmin now applies the container `command` and `args` overrides users
set on a deployment after the Helm chart renders, to each component's
declared **component container**, as it already does for env vars and
image overrides. Drivers no longer pass these overrides to the chart in
`values.j2.yml` ([#457](https://github.com/opsmill/styrmin/issues/457)).
See [Migrating container overrides](./drivers/migrating-container-overrides.md).

#### What's new

- A `command` or `args` override reaches the component container whether
  or not the chart exposes it as a value. The `server` and `task-worker`
  components of the `infrahub` and `infrahub-enterprise` drivers now
  accept `command`.
- An override replaces the whole `command` or `args` list, and a field
  without an override keeps the chart's value. Clearing an override
  brings back the chart's `command` and `args`.
- Adding or changing `command` or `args` on a component without a
  component container is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`.
  The deployment's Configuration editor hides the Command and Args
  editors for such a component, shows stored values read-only, marked
  **not applied**, with a remove button, and offers no **Add override**.
  `ComponentContainerOverrides.isApplicable` in the API reports whether
  a stored override applies.
- The **Component Overrides** card on the Configuration tab lists the
  stored `command` and `args` of each component, with an **applied** or
  **not applied** badge, and lists every block stored on a component the
  driver no longer declares.
- In the Configuration editor, a change to only the `command` or `args`
  of a component now enables **Review & apply**.
- `styrminctl deployments apply` warns once per component about the
  overrides it stores but the driver version does not apply, names their
  kinds and says how to fix it. The SDK lists the kinds per component in
  `ApplyOutcome.inapplicable_overrides`.
- The example drivers no longer call the retired filters: `simple-app`
  version 3, `infrahub` version 4 and `infrahub-enterprise` version 3.

#### Migration

- Before you upgrade Styrmin, list the stored `command` and `args` of
  your deployments with `styrminctl deployments get` and remove the
  values you do not want with `styrminctl deployments update --config`
  or `styrminctl deployments apply`. After the upgrade, Styrmin applies
  them to every component with a component container on the next render
  of the deployment, which an env var edit on its environment or a
  cluster config update can also start. Values that a driver template
  did not pass to the chart, such as `command` on the infrahub `server`
  or any value on the `slurpit`, `semaphore`, `infrahub-mcp` and
  `db-test` drivers, reach the pods for the first time. The
  Configuration editor of earlier releases cannot submit a change that
  only removes `command` or `args`. See
  [Before you upgrade Styrmin](./drivers/migrating-container-overrides.md#before-you-upgrade-styrmin).
- The `component_command` and `component_args` template filters are
  retired. Loading a driver version whose `values.j2.yml` calls either
  one, or the earlier retired `component_env_vars`, fails with
  `RETIRED_TEMPLATE_FILTER`. A deployment pinned to a driver version
  loaded earlier that still calls them fails on its next change, also
  when it has no override set; its pods keep running. Load the migrated
  drivers and move each deployment onto them.
- `spec.container_overrides` is removed from `driver.styrmin.yml`: a
  driver file that still contains it fails to load, with an error that
  links the migration guide. The API no longer has
  `ApplicationDriverVersion.containerOverrides` or the
  `DriverContainerOverrideDoc` type, and the SDK no longer has
  `get_driver_container_override_docs`.
- Container overrides now reach only the component container, not chart
  Jobs, init containers, or other containers in the pod.

### Change a cluster's config without recreating it

An administrator can now change any value of a cluster's config, such
as the FQDN suffix, the ingress class, a storage class or the dedicated
ingress, without deleting and recreating the cluster, its environments
and its deployments. See
[`clusters update`](./reference/styrminctl.md#clusters-update--change-a-clusters-config).

#### What's new

- `styrminctl clusters update`, `clusters.update()` in the Python SDK,
  the `updateCluster` GraphQL mutation and an **Edit** button on the
  cluster detail page replace the whole cluster config
  ([#423](https://github.com/opsmill/styrmin/issues/423)).
- Styrmin redeploys each deployment whose resolved config changes, in
  every environment of the cluster. The command, the SDK and the dialog
  list the deployments that are redeployed, that wait for a dedicated
  ingress controller and that could not start. Run the update again to
  retry the ones that could not start.
- `styrminctl clusters update --dry-run`, the `dryRun` argument and the
  dialog's review step list the changes and the deployments to redeploy
  before anything is saved.
- `styrminctl clusters get --json` prints only the cluster config, to
  edit and pass to `clusters update --config @FILE`.
- When `dedicated_ingress` changes, the applications of an environment
  move onto its dedicated ingress controller only once the controller is
  `RUNNING`, and the controller is removed only after the applications
  have moved off it.

#### Migration

- When an environment update turns the environment's own
  `dedicated_ingress` off and the cluster does not set
  `dedicated_ingress`, Styrmin now removes the environment's dedicated
  ingress controller once its applications are redeployed to the
  cluster's `ingress_class`. Before, the controller stayed until the
  last application of the environment was deleted. If you rely on that
  controller, for example for its load balancer IP, set
  `dedicated_ingress` on the environment or the cluster again before
  you upgrade.
- Whenever an environment's dedicated ingress controller reaches
  `RUNNING`, Styrmin now also redeploys the applications of that
  environment that are not at the config they resolve to.
- `styrminctl clusters get` and `clusters list` print the config as
  JSON instead of Python dict text. Scripts that parse the old output
  need to change; use `clusters get --json`.
- A storage class change makes deployments whose StatefulSets use the
  storage class `FAILED`, because Kubernetes refuses to change the
  storage class of an existing volume claim. The Infrahub drivers are
  affected. Saving again does not retry them: submit the previous
  storage class again, or delete and redeploy the deployment.

### Env vars and image overrides reach the pods after every change

The agent now installs the FluxCD controllers of Flux v2.9.6:
helm-controller v1.6.5 and source-controller v1.9.6, in place of
helm-controller v1.1.0 and source-controller v1.4.0. helm-controller
v1.1.0 could report a change of env vars or image overrides in sync
without applying it, and the pods kept the previous values.

#### What's new

- An upgrade to another driver version applies the new env vars and
  image overrides, also when the Helm values stay the same
  ([#432](https://github.com/opsmill/styrmin/issues/432)).
- A change of env vars or image overrides that reaches the cluster
  while FluxCD still upgrades the previous change is applied after that
  upgrade ([#433](https://github.com/opsmill/styrmin/issues/433)).
- Before each `helm install` and `helm upgrade`, a Job of the agent
  chart applies the agent's CRDs, because Helm never updates the files
  in a chart's `crds/` directory. Set `styrmin-agent.crdUpgrade.enabled`
  to `false` to apply them yourself.

#### Migration

- The FluxCD v2.9 controllers support Kubernetes 1.34.1 and later.
- `helm upgrade` runs the CRD Job first. It deletes and creates again
  the `ocirepositories.source.toolkit.fluxcd.io` CRD, which Styrmin does
  not use, because the new CRD no longer lists the `v1beta2` version
  that the old one stored. The Job fails the upgrade instead if the
  cluster has `OCIRepository` objects.
- When you disable the CRD Job, apply the files of `helm/agent/crds/`
  before you upgrade. Otherwise helm-controller and source-controller
  cannot start, and no change of a deployment reaches the cluster.
- A deployment whose pods kept older env vars or images because of
  #432 or #433 keeps them after the upgrade. Its next change applies
  the current values.

### Run a custom image on one component

A deployment can now point one component at a custom or patched build
without forking its driver. Styrmin applies the **image override** after
the Helm chart renders, to the component's declared **component
container**. See [Image overrides](./concepts-and-architecture/image-overrides.md).

#### What's new

- Set an image per component in the deployment's Configuration editor,
  in a `styrminctl deployments apply` manifest (`components[].image`), or
  through `ComponentConfigInput.image` in the API and SDK. The
  Configuration tab shows the stored and resolved reference and whether
  it is applied.
- A `{{ app.version }}` token follows the deployment's application
  version; a literal tag or digest pins the image. The upgrade dialog and
  `styrminctl deployments apply` warn about pinned overrides before an
  application version change.
- Invalid references are rejected when you save them, and an upgrade
  that would make one invalid is rejected before any lifecycle action
  runs.

#### Migration

- A driver whose declared component container name the chart does not
  render now fails the deployment with `COMPONENT_CONTAINER_NOT_FOUND`,
  naming the component and the container, as soon as env vars or an image
  override target it. Styrmin never adds a container.
- `get_component_images` returns the component container's image first.
  Driver actions should take `images[0]` instead of searching for an
  image name; the example drivers do.
- Clear every image override before rolling Styrmin back below this
  release: older releases reject the `image` key.

### Env vars keep the chart's env defaults

Styrmin now merges the env vars users set on a deployment into each
component's declared **component container** after the Helm chart
renders, instead of having the driver write them into the chart's
values. Chart env defaults are no longer dropped.

#### What's new

- Drivers declare `components.<name>.container` in
  `driver.styrmin.yml`. User env vars reach that container by name: the
  chart's own env entries are kept, and a user value replaces a chart
  entry of the same name.
- Adding or changing a component env var on a component without a
  component container is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`.
  The deployment's Configuration editor hides the env var editor for such
  components, and the driver's **Components** tab shows each component's
  container.
- Every example driver declares its component containers. The `infrahub`
  task manager keeps the Prefect chart's `PROMETHEUS_MULTIPROC_DIR` and
  `PREFECT_UI_SERVE_BASE` defaults.

#### Migration

- The `component_env_vars` template filter is removed. A deployment
  pinned to a driver version that still calls it fails on its next
  change. Load the migrated drivers and upgrade each deployment before
  editing env vars on an environment; driver authors declare containers and
  remove the filter. See
  [Migrating env var wiring](./drivers/migrating-env-vars.md).
- User env vars now reach only the component container, not chart Jobs,
  init containers, or other containers in the pod.

### Clone an environment, with its data, in one action

Environment backups could put an environment **back**. An **environment
clone** uses the same capture to stand up a **second, running
environment** beside the source — with the source's data as of clone
time — in one operation.

#### What's new

- One action captures a fresh environment backup of the source, waits for
  it, creates a new environment from the captured config, creates one
  **counterpart deployment** per included source deployment (pinned to the
  driver version the capture recorded), and restores each source
  deployment's data **into its counterpart**. Everything after the capture
  is built from the capture — the live source is never read again, so the
  clone holds a defined point in time. The source's config and declared
  state are untouched.
- **Selective inclusion.** Omit the selection to bring every eligible
  deployment; name deployments to bring only those (the selection filters
  the capture, so excluded deployments are not backed up at all). An
  unknown or foreign deployment id is rejected up front with no side
  effects; a known-but-ineligible one is *skipped* by name with a reason,
  never an error. An empty selection is legal and clones the
  configuration only.
- **A config override applied before anything starts**, so a clone of
  production doesn't come up with production's outbound integrations. A
  supplied field replaces the captured field wholesale; a separate
  clear-fields list **removes** a captured setting entirely rather than
  changing it. The merge happens before the new environment is created,
  so the counterparts' first startup already sees it.
- A clone's status is **derived** on every read (`PENDING` /
  `IN_PROGRESS` / `COMPLETED` / `PARTIAL` / `FAILED`) from the capture,
  the created environment, the per-deployment outcomes and the restores.
  Every source deployment you could have selected is accounted for by
  name. Two consequences worth knowing: a brand-new clone commonly reads
  `IN_PROGRESS` rather than `PENDING`, and an all-skipped clone is
  `COMPLETED`, not a failure.
- **Discard by deleting the environment the clone created** — in any
  state, including `PARTIAL` and `FAILED`. The clone record keeps the
  history as a discarded outcome, and because a clone's name is not
  unique you can immediately re-clone under the same name. For a clone
  that stalled before its environment appeared, deleting its backing
  snapshot is the escape hatch.
- **Cloning requires the administrator role** (it writes environment
  configuration, like restoring). Reading clone records does not.
- New surfaces: a **Clones** tab on the environment detail page with an
  ADMIN-gated Clone dialog (ineligible deployments disabled with their
  reason); the `styrminctl env-clones` group (`create`, `get`, `list`,
  with `--deployment`, `--config-override`, `--clear-config-field` and
  `--wait` on `create`); `client.environment_clones` in the Python SDK;
  and the `cloneEnvironment` mutation with `environmentClone` /
  `environmentClones` queries and an `Environment.clonedFrom`
  back-reference.

#### Know before you clone

- **A clone is not isolated from data-borne references.** Credentials,
  webhook URLs, API endpoints and licence keys stored *inside* the
  restored application data are copied verbatim, so a clone can reach the
  same external systems the source pointed at. The config override
  handles environment-level settings; it cannot reach into a table.
  Neutralising those values is a step you own.
- A driver whose chart **generates** credentials at install time can mint
  fresh credentials over restored data. Cloneable drivers should take
  credentials from configuration.
- A counterpart's Helm release is named after the **source** deployment,
  which keeps Helm's ownership metadata consistent with the restored
  objects. `helm list` in the counterpart's namespace showing a
  source-named release is intentional.
- A cloned environment does **not** inherit the source's backup storage
  location — assign one before it can take backups of its own.

#### Behaviour changes

- **Deleting an environment now tears down and removes the deployments
  inside it**, instead of failing. Previously `deleteEnvironment` did not
  cascade deployments at all; the failure was masked by callers' cleanup
  handling. This applies to every environment, not just clones — it is
  what makes clone discard work.
- **A second restore is now refused only when a restore is actually in
  flight** for that deployment (a `PENDING` or `IN_PROGRESS` restore
  record), rather than whenever the deployment sits in the `RESTORING`
  state. A deployment left `RESTORING` by a restore that never finished is
  therefore restorable again instead of permanently stuck.
- Deleting an environment backup is refused with `IN_USE` while a clone's
  *capture* of it is still running. Once the capture has landed, deletion
  is allowed again.

#### Migration

- No action required, and nothing existing changes shape: clone adds its
  own record and two nullable links. Cloning is a same-cluster operation
  — cross-cluster clones remain out of scope.
- See [Cloning an environment](./concepts-and-architecture/backups-and-restores.md#cloning-an-environment)
  for the semantics and [the CLI reference](./reference/styrminctl.md#env-clones--clone-an-environment)
  for the commands, flags, and exit codes.

### Back up and restore a whole environment in one action

Backups were per-deployment only. An **environment backup** captures the
whole environment as a single record — and restores it as a single
action.

#### What's new

- One action captures the environment's config, the declared state of
  every eligible deployment (Application Driver, driver version and
  provenance fingerprint, application version, config, parameters), and
  one constituent backup per eligible deployment. Constituents are
  ordinary per-deployment backups: same storage location, same retention
  rules, individually listable and deletable.
- Restoring a `COMPLETED` or `PARTIAL` snapshot reverts the environment
  config and restores every usable constituent **in place**. It never
  creates or deletes deployments — topology drift is reported, never
  repaired — and every constituent that is not restored is named with a
  reason. **Restoring requires the administrator role**, because it
  rewrites the environment config; creating and deleting need the same
  role as an ordinary backup.
- A snapshot's status is **derived** from its constituents on every read,
  so it can never contradict them, and `PARTIAL` is a first-class
  outcome: a snapshot that covered four of five applications says so and
  is still restorable.
- An environment runs at most one environment-level operation at a time;
  a second request is rejected with a machine-readable error rather than
  queued.
- New surfaces: a **Backups** tab on the environment detail page; the
  `styrminctl env-backups` command group (`create`, `get`, `list`,
  `restore`, `restore-get`, `restore-list`, `delete`, with `--wait` on
  `create` and `restore`); `client.environment_backups` in the Python
  SDK; and the `createEnvironmentBackup` /
  `restoreEnvironmentBackup` / `deleteEnvironmentBackup` mutations with
  their four `environmentBackup(s)` / `environmentRestore(s)` queries.

#### Migration

- No action required. Existing per-deployment backups are untouched:
  membership in an environment backup is a nullable link, and a backup
  without one behaves exactly as before.
- In this release an environment backup does not outlive its
  environment — deleting an environment deletes its snapshots.
- See [Backups and restores](./concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment)
  for the semantics and [the CLI reference](./reference/styrminctl.md#env-backups--environment-level-backup-and-restore)
  for the commands, flags, and exit codes.

### Deterministic driver-version selection and explicit pinning

When several loaded driver versions support the same application version,
deployments now bind to a **deterministic latest-wins** choice, and the
deploy/upgrade APIs accept an explicit driver-version pin.

#### What's new

- Driver-version resolution is deterministic: highest parseable
  `spec.version` wins, ties (including same-`version` rebuilds with
  different fingerprints) break by load time, newest first. Previously
  the first matching row in database order was used.
- Upgrades always re-resolve the binding. Re-running
  `styrminctl deployments update-version <id> <same-version>` after
  loading a fresher overlapping driver build moves the deployment onto
  that build — previously this was a no-op while the current build still
  matched.
- The `deploy` and `updateDeploymentVersion` GraphQL mutations accept an
  optional `driverVersionId` to pin a specific build, plumbed through
  the SDK (`deployments.create` / `deployments.update_version`) and the
  CLI (`--driver-version-id` on `deployments create` /
  `deployments update-version`).
- The UI's Upgrade dialog gains a driver-version picker that defaults to
  **Latest (auto)**.

#### Migration

- No action required. Deployments keep their current binding until the
  next upgrade; from then on resolution follows the documented rule.
  See [Selecting a driver version](./drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading).

### Driver reload no longer requires bumping `version`

Application Driver Versions are now identified by a **provenance
fingerprint** in addition to their `spec.version` string. The
fingerprint is a SHA-256 content hash for local drivers and the
resolved git commit SHA for git drivers.

#### What's new

- Re-running `styrminctl drivers load-local-version <path>` on an
  edited driver records a new Application Driver Version row, even when
  `spec.version` is unchanged. Three files feed the content hash:
  `driver.styrmin.yml`, the values template, and `actions.py` (only
  when `spec.actions` is non-empty).
- Re-loading unchanged content is now a no-op — repeated loads no
  longer create duplicate rows and no longer crash with the cascade
  `IntegrityError` that used to surface on local reloads.
- Every driver-version label across the UI, CLI, and SDK is rendered as
  `<version>@<short-fingerprint>` (the first 7 hex chars). Detail
  surfaces show the full 64-char content hash or 40-char commit SHA
  with a copy-to-clipboard control.
- The `ApplicationDriverVersion` GraphQL type gains two nullable fields:
  `contentHash` (set for `sourceType == "local"`) and `sourceCommitSha`
  (set for `sourceType == "git"`). Exactly one is non-null per row.

#### Migration

- No action required. The new columns are nullable; legacy rows keep
  the bare `version` label until reloaded once.
- See [`dev/guides/driver-iteration.md`](https://github.com/opsmill/styrmin/blob/develop/dev/guides/driver-iteration.md)
  for the iteration-loop reference and the planned `drivers prune`
  follow-up.

### Unified deployment Settings tab

The deployment detail page's **Parameters** tab has been replaced with a unified **Settings** tab.

#### What's new

- Settings shows the *effective* configuration that the application runs with — every value is walked through the **Cluster → Environment → Deployment** inheritance chain and attributed to the layer that defined it. Look for the small filled marker on rows the deployment layer explicitly overrides.
- A single right-side **Update Settings** drawer edits every deployment-scoped setting in one place: environment variables, services, driver parameters, scheduling, and per-component overrides.
- Every apply is gated by a **diff + impact** review dialog that classifies each change as informational, warning, or disruptive (with a static rule table) — no type-to-confirm friction.
- If another client modifies the deployment while you're editing, an inline conflict banner appears above your pending diff with a one-click **Reload** to merge against the new baseline. Your pending edits are preserved.

#### Migration

- The standalone **Scheduling** button has been removed from the deployment header. Scheduling now lives in the Settings tab alongside every other deployment-scoped setting — open the Settings tab and click **Update Settings**.
- The **Parameters** tab has been renamed to **Settings**. The same fields are editable from inside the unified drawer.
- A one-time hint banner explains the consolidation on first visit; click the **×** to dismiss it.

#### Known v1 scope limits

- **Networking** and **Storage & Runtime** are visible on the Settings tab but not editable from the drawer in v1 — they return in a follow-up when their nested-form UX is ready.
- **Per-component overrides** edit environment variables in v1; resource limits and replica counts return when the GraphQL surface exposes them.
