---
title: Beta status
description: What the Styrmin beta includes, what changed since the alpha, what to do before you upgrade from the alpha, and the known limitations and broken features.
---

<!--
  TODO(beta): replace "the beta release" with its version number once it is tagged.
  Every change marked "the beta release" below is merged on develop after v0.1.52
  and is not in a release yet.
-->

## Styrmin is in beta

<!--
  TODO(beta): decide the compatibility promise and the production statement.
  The three bullets below keep the alpha position where nothing is decided yet.
-->

The features that the alpha listed as coming before the beta are in this
release. Before you rely on Styrmin, read what the beta means:

- The GraphQL API, `styrminctl` commands and flags, the Python SDK and the
  driver format can still change between releases.
- The release notes of each release list its breaking changes with the steps
  to take, and the [Changelog](./changelog.md) describes the notable ones. A
  change to the driver format also comes with a migration guide, such as
  [Migrating Container Overrides](./drivers/migrating-container-overrides.md).
- Styrmin is not yet recommended for production-critical workloads. Use it for
  lab, staging and internal-tooling deployments, and read the
  [known broken features](#known-broken-features) first.

## Workflows added since the alpha

These workflows are new since the alpha (v0.1.26, 27 May 2026). Each item
links to the page that explains it.

### Deploying and changing applications

- Describe deployments in `styrmin/v1` manifest files and create or update
  them with `styrminctl deployments apply -f <path>`. An apply that changes
  nothing starts no task and reports the deployment as `unchanged`. See
  [`deployments apply`](./reference/styrminctl.md#deployment-apply-is-idempotent).
- Choose the driver version of a deployment, or let Styrmin use the newest
  loaded driver version that supports the application version. See
  [Selecting a driver version](./drivers/loading-drivers.md#selecting-a-driver-version-when-deploying-or-upgrading).
- Change one component of one deployment without changing its application
  driver. Styrmin applies these overrides to the component container after
  the Helm chart renders:
  - environment variables, see [Migrating Env Var Wiring](./drivers/migrating-env-vars.md)
  - the container `command` and `args`, see [Migrating Container Overrides](./drivers/migrating-container-overrides.md)
  - the container image, see [Image overrides](./concepts-and-architecture/image-overrides.md)
  - the replica count, also with `styrminctl deployments scale`, see
    [Replica overrides](./concepts-and-architecture/replica-overrides.md)
- Follow a task step by step. The deployment page and `styrminctl tasks get`
  list the steps of each task with their status, duration, attempts and
  errors, and show the task result: `RUNNING`, `FAILED`, `SUCCEEDED` or
  `SUPERSEDED`. See [`tasks get`](./reference/styrminctl.md#tasks-get--a-tasks-steps)
  and [Steps from status reports](./concepts-and-architecture/status-reporting.md#steps-from-status-reports).
- Change the config of a cluster without recreating it, with the Edit button
  on the cluster page or with `styrminctl clusters update`. The `--dry-run`
  option lists the deployments that the change redeploys. See
  [`clusters update`](./reference/styrminctl.md#clusters-update--change-a-clusters-config).

### Backing up, restoring and cloning

- Back up and restore a whole environment in one operation, from the Backups
  tab of the environment page or with `styrminctl env-backups`. See
  [Backing up a whole environment](./concepts-and-architecture/backups-and-restores.md#backing-up-a-whole-environment).
- Clone an environment, with the data of the deployments you select, into a
  new environment on the same cluster, from the Clones tab of the environment
  page or with `styrminctl env-clones`. See
  [Cloning an environment](./concepts-and-architecture/backups-and-restores.md#cloning-an-environment).
- Set how long backups are kept with `backup_ttl` on the cluster, the
  environment or the deployment. See
  [Retention](./concepts-and-architecture/backups-and-restores.md#retention-how-long-a-backup-lives).
- View the backups of a deployment across upgrades and config changes, with
  the application version of each backup, and restore a backup of an earlier
  instance. See
  [Backup history of a deployment](./concepts-and-architecture/backups-and-restores.md#backup-history-of-a-deployment).

### Using application drivers

- Deploy a single-container HTTP application without writing a driver, with
  the bundled [generic-app driver](./drivers/generic-app.md).
- Serve an existing Infrahub instance through an MCP server, with the bundled
  `infrahub-mcp` driver. See
  [Loading a Driver](./drivers/loading-drivers.md).
- View the logo, description and links of each driver on the driver pages.
  Driver authors set them in `spec.info`. See
  [Warnings about spec.info values](./drivers/loading-drivers.md#warnings-about-specinfo-values).
- Load several drivers from one Git repository, by giving the driver
  directory with `styrminctl drivers load-version --driver-directory` or in
  the Load a driver drawer. See
  [Loading a driver from a driver directory](./drivers/loading-drivers.md#loading-a-driver-from-a-driver-directory).
- Run the actions of a driver loaded from a local directory, such as the
  bundled drivers under `/styrmin/drivers`. See
  [Actions of a driver loaded from a local directory](./drivers/loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory).
- Run the upgrade actions of the bundled drivers. Actions now call the Styrmin
  API with a short-lived token, so their calls to `stop_components`,
  `start_components` and `upgrade_deployment_version` no longer fail, and a
  second `execute_commands` call deletes the Job that the earlier call left
  once that Job has ended. See
  [How actions call the Styrmin API](./concepts-and-architecture/hooks-and-actions.md#how-actions-call-the-styrmin-api).
- Keep the actions of a deployment stable. The actions of a driver version run
  at the commit that the driver version was loaded from, so a push to the
  driver's branch does not change them.

### Running Styrmin

- The agent installs the controllers of FluxCD v2.9 and runs helm-controller
  with the defaults of Helm v4. See
  [The HelmRelease](./concepts-and-architecture/operator-and-crds.md#the-helmrelease--styrmins-other-crd).
- `styrminctl` and the server send anonymous telemetry, which you can turn
  off. See [Telemetry & privacy](./reference/telemetry.md).
- When the Prefect worker that runs a flow stops, Styrmin marks the flow run
  as crashed, so its task no longer stays `RUNNING`.

## Changes to make before you upgrade from the alpha

Releases between the alpha and the beta changed or removed behaviour that
installs, deployments, drivers and scripts rely on. Read the list for each
role you have before you upgrade. The version in brackets is the first
release with the change.

### Changes for the people who install and upgrade Styrmin

<!--
  TODO(beta): the chart does not run `styrmin db migrate`, and the server only
  creates missing tables when it starts (`SQLModel.metadata.create_all`). Releases
  since the alpha add columns and data revisions. Document how a Helm install
  applies them, or add a migration step to the chart, before the beta ships.
-->

- Run Kubernetes 1.34.1 or later. The agent installs the FluxCD v2.9
  controllers, which need it (v0.1.48).
- Keep the CRD upgrade Job of the agent chart turned on
  (`styrmin-agent.crdUpgrade.enabled`, on by default). It applies the agent's
  CRDs before each install and upgrade. If you turn it off, apply the files of
  the agent chart's `crds/` directory yourself before each upgrade, or the FluxCD
  controllers cannot start (v0.1.48).
- Update dashboards and scrape configs that name `<release>-velero`. The
  Velero Deployment, Service, ServiceAccount and ConfigMaps are now named
  `velero`, and Velero moves to 1.18.1. Do not upgrade while a backup or a
  restore runs (v0.1.45).
- Set `styrmin-agent.image.tag` if you run an agent image other than the
  chart's version. The tag no longer defaults to `latest` (v0.1.42).
- Turn off server telemetry with `styrmin.telemetry.enabled: false` if you do
  not want the daily anonymous report. It is on by default (v0.1.48). See
  [Turning server telemetry off](./reference/telemetry.md#turning-server-telemetry-off).
- Upgrade the server and the agent before `styrminctl` and the Python SDK.
  `deployments apply` and the backup list of v0.1.48 need a v0.1.48 server,
  and replica overrides need the agent of v0.1.50.
- Upgrade the server, `styrminctl` and the Python SDK together to the beta
  release, and reload the web pages that were open during the upgrade,
  because the restore request changes (the beta release). See
  [A restore lands only in the deployment its backup was taken of](./changelog.md#a-restore-lands-only-in-the-deployment-its-backup-was-taken-of).
- Load your local drivers again after you upgrade, so that Styrmin registers
  their actions. Deployments created from local drivers before v0.1.51 never
  ran their setup actions, and Styrmin does not run them now (v0.1.51).
- Before you roll back below v0.1.47, clear every image override. Before you
  roll back below v0.1.50, clear every replica override. See
  [Upgrading and rolling back Styrmin](./concepts-and-architecture/replica-overrides.md#upgrading-and-rolling-back-styrmin).
- Remove `STYRMIN_OPERATOR_HR_READY_TIMEOUT` from your settings: it had no
  effect and is removed (v0.1.47). `STYRMIN_OPERATOR_DEPLOYMENT_READY_TIMEOUT`
  now defaults to 270 seconds instead of 300 (v0.1.48).
- Read credentials from your own secrets, not from `styrmin config show`,
  which no longer prints passwords, the database URL or tokens (v0.1.48).

### Changes for the people who run deployments

- Move the replica counts of Infrahub deployments to replica overrides. The
  `infrahub` driver version 5 and the `infrahub-enterprise` driver version 4
  remove the `replicas_server` and `replicas_task_worker` parameters. A
  deployment that stores a value other than the default cannot change driver
  version until you move the value (v0.1.50). See
  [Migrating Replica Parameters](./drivers/migrating-replica-parameters.md).
- Before you upgrade to v0.1.48, list the stored container `command` and
  `args` overrides and remove the ones you do not want. From v0.1.48 they
  reach the pods, also for drivers whose templates never used them. See
  [Before you upgrade Styrmin](./drivers/migrating-container-overrides.md#before-you-upgrade-styrmin).
- Move each deployment to a driver version that declares component
  containers before you edit its env vars. On a driver version that still
  uses the removed `component_env_vars` filter, the next change fails
  (v0.1.46). See [If you run deployments](./drivers/migrating-env-vars.md#if-you-run-deployments).
- Replace `node_selector` with `scheduling.node_affinity` on the environment
  or the deployment. `node_selector` is removed from cluster and deployment
  config, and `scheduling` is removed from cluster config. Styrmin never
  applied `node_selector` to pods (v0.1.50). See
  [Replacing a node selector](./concepts-and-architecture/node-affinity.md#replacing-a-node-selector).
- Check required node affinity terms set on both an environment and one of
  its deployments. A pod now runs only on a node that matches a term of both,
  so pods can stay `Pending` after the next redeploy. Run
  `styrminctl clusters update --dry-run` to list the deployments that a
  cluster update redeploys (v0.1.50). See
  [When the environment and the deployment both set terms](./concepts-and-architecture/node-affinity.md#when-the-environment-and-the-deployment-both-set-terms).
- Set `dedicated_ingress` again on the environment or the cluster if you rely
  on an environment's dedicated ingress controller, for example for its load
  balancer IP. When an environment update turns the environment's
  `dedicated_ingress` off and the cluster does not set it, Styrmin removes the
  controller (v0.1.48). See
  [Changing the dedicated ingress of an environment](./concepts-and-architecture/ingress-and-networking.md#changing-the-dedicated-ingress-of-an-environment).
- Name only deployments that exist in the environment in pod affinity and
  pod anti-affinity terms (`deploymentRef`). Styrmin now stores the id of the
  named deployment, and refuses with `VALIDATION_ERROR` a write whose term
  names a deployment the environment does not have or a deleted deployment.
  `createEnvironment` refuses every term that names a deployment, because a
  new environment has no deployments yet. After you delete a deployment that
  a term names, updates of the deployments that the term applies to fail
  until you write the term again (v0.1.50).
- Expect deleting an environment to delete its deployments and its
  environment backups. Before v0.1.46 the request failed when the environment
  had deployments.

### Changes for the people who write application drivers

- Declare `components.<name>.container` for each component that receives env
  vars, `command`, `args` or an image override, and remove the
  `component_env_vars`, `component_command` and `component_args` template
  filters and `spec.container_overrides`. A driver that still uses them fails
  to load with `RETIRED_TEMPLATE_FILTER` (v0.1.46 and v0.1.48). See
  [If you write drivers](./drivers/migrating-container-overrides.md#if-you-write-drivers).
- Set `backup.volume` or `backup.volumes` on each component with
  `backup.kind: disk`. Without one, the driver fails to load (v0.1.30).
- Take `images[0]` in actions. `get_component_images` returns the image of
  the component container first (v0.1.47). See
  [Reading a component's images](./concepts-and-architecture/hooks-and-actions.md#reading-a-components-images).
- Load the new commit and upgrade deployments onto it to change their
  actions. Actions run at the commit that the driver version was loaded from,
  not at the tip of the branch (v0.1.47).
- Put the code of each action in `actions.py`, declare one action for each
  hook and mode, and load a local driver by its absolute path. A load from a
  local directory of a driver with actions is refused when the path is
  relative or when an action's `location` is in a file other than
  `actions.py`, and every load is refused when the driver declares two
  actions for one hook and mode (v0.1.51).
- Replace a symlink in a Git repository with the file it points to when it
  points outside the repository or outside the driver directory. A load from
  Git fails when `driver.styrmin.yml`, `values.j2.yml` or `actions.py` is such
  a symlink, or when the driver directory is (v0.1.50).
- Do not write secrets to the output or the logs of actions. The end of a
  failed command's output (v0.1.48) and the first `ERROR` log line of a
  crashed action (v0.1.51) are readable by every signed-in user who can read
  the task.
- Do not test for an empty `ingress_class` to detect a dedicated ingress
  controller. With a dedicated ingress controller, `ingress_class` in the
  context now holds the resolved class, and Styrmin removes
  `spec.ingressClassName` from every Ingress after the chart renders
  (v0.1.50). See
  [Ingress and networking](./concepts-and-architecture/ingress-and-networking.md).
- Expect a field that the chart sets to return to the chart's value at the
  next upgrade, also when `kubectl` or an action changed it. New deployments
  are installed with server-side apply (v0.1.50).
- Do not combine `singleton: true` with `replicas` above 1 on a component. The
  driver fails to load (v0.1.50).
- Read `backup.velero.storage_location` as the name of the Velero object,
  `styrmin-bsl-<location id>`. It held the backup storage location's name
  before (v0.1.50).

### Changes for the people who write scripts against the API, the SDK or styrminctl

- Send `deploy` a typed `config: DeploymentConfigInput` and
  `parameters: [ParameterValueInput!]` instead of JSON. The SDK's
  `deployments.create()` takes the matching models (v0.1.34).
- Handle `null` from `updateDeployment`. It returns no task when the request
  changes nothing (v0.1.34).
- Pass a deployment name or `--id` to `styrminctl backups create` and
  `backups list`, or `--instance-id` for an instance (v0.1.29).
- Restore a backup by its id alone. `createRestore` no longer takes
  `targetNamespace` and `targetInstanceId`, `create_restore()` in the Python
  SDK no longer takes `target_namespace` and `target_instance_id`, and
  `styrminctl backups restore` no longer has `--target-namespace`.
  `styrminctl backups restore <backup-id>` refuses `--target-deployment`,
  `--target-deployment-id`, `--target-instance-id` and `--environment`, which
  work only with `--last` (the beta release). See
  [A restore lands only in the deployment its backup was taken of](./changelog.md#a-restore-lands-only-in-the-deployment-its-backup-was-taken-of).
- Pass `--yes` to `styrminctl backups restore --last` in scripts. It asks for
  confirmation when the chosen backup is of an earlier instance (v0.1.48),
  also with `--target-instance-id` (the beta release).
- Read the config from `styrminctl clusters get --json`. `clusters get` and
  `clusters list` print the config as JSON instead of Python text (v0.1.48).
- Pass `includeInternal: true` to `Environment.deployments` to list internal
  deployments, such as the dedicated ingress controller (v0.1.48).
- Filter reconcile tasks on `create_instance`, `update_instance`,
  `upgrade_instance`, `stop_components` and `start_components` instead of
  `noop` (v0.1.48).
- Read `Backup.sizeBytes` as bytes, in the `BigInt` scalar (v0.1.48).
- Remove `nodeSelector` from `UpdateClusterInput`, `UpdateDeploymentInput` and
  `DeploymentConfigInput`, and `scheduling` from `UpdateClusterInput`
  (v0.1.50).
- Read `deployment_id` in the deployment references of affinity terms.
  Reading a config back gives the id of the named deployment without its
  name (v0.1.50).
- Expect `IN_USE` from `deleteCluster` on a cluster that still has
  environments (v0.1.49).

## Features that are not in the beta

- Network isolation of a cloned environment, tracked in
  [opsmill/styrmin#36](https://github.com/opsmill/styrmin/issues/36). Values
  stored in the restored data, such as credentials or webhook URLs, are copied
  as they are, so a clone can reach the same external systems as its source.
  See [What a clone is not isolated from](./concepts-and-architecture/backups-and-restores.md#what-a-clone-is-not-isolated-from).
- More than one cluster per Styrmin install, and cloning an environment into
  another cluster.
- Restoring a backup into another deployment. Styrmin restores a backup only
  into the deployment it was taken of. An environment clone is the only way
  to copy the data of a deployment into another deployment.
- Scheduled backups. The API accepts backup schedules, but Styrmin does not
  run them. Start each backup yourself.
- Long-lived API tokens. Scripts log in with `STYRMIN_USERNAME` and
  `STYRMIN_PASSWORD`, or reuse the session token of `styrminctl login` in
  `STYRMIN_TOKEN`. A session ends after 30 days, or after 7 days without use.
- Pagination, filtering and ordering of GraphQL lists, tracked in
  [opsmill/styrmin#26](https://github.com/opsmill/styrmin/issues/26) and
  [opsmill/styrmin#27](https://github.com/opsmill/styrmin/issues/27).
- CPU and memory requests and limits for each component, tracked in
  [opsmill/styrmin#382](https://github.com/opsmill/styrmin/issues/382).
- Stopping, starting and restarting a whole deployment, tracked in
  [opsmill/styrmin#99](https://github.com/opsmill/styrmin/issues/99). You can
  stop and start components.
- Deleting an environment from the environment page, tracked in
  [opsmill/styrmin#254](https://github.com/opsmill/styrmin/issues/254). Use
  `styrminctl environments delete`.
- Changing the config of an environment with `styrminctl`, tracked in
  [opsmill/styrmin#425](https://github.com/opsmill/styrmin/issues/425). Use
  the environment page or the API.
- Ingress controllers other than Traefik, backup systems other than Velero,
  and the planned environment network features on CNIs other than Cilium,
  tracked in [opsmill/styrmin#464](https://github.com/opsmill/styrmin/issues/464),
  [opsmill/styrmin#466](https://github.com/opsmill/styrmin/issues/466) and
  [opsmill/styrmin#463](https://github.com/opsmill/styrmin/issues/463).

## Security limitations

<!-- TODO(beta): decide whether this section ships on the public site. -->

- The agent's status reporter and the Prefect flow callback call the API
  without credentials. As a result, the `environments` query and the
  `reportPodStatuses`, `reportDeploymentStatuses` and `callback` mutations
  accept requests without a session, so anyone who can reach the API can list
  environments and deployments and change their stored status. Make the API
  reachable only from networks you trust. Tracked in
  [opsmill/styrmin#396](https://github.com/opsmill/styrmin/issues/396).
- Many `login` requests without a session can block the server until its
  liveness probe fails and it restarts. Tracked in
  [opsmill/styrmin#377](https://github.com/opsmill/styrmin/issues/377).
- Styrmin does not check parameter values before it renders them into Helm
  values, so a user who can deploy can set Helm values the driver does not
  declare. Give the `READ_WRITE` role only to users you trust. Tracked in
  [opsmill/styrmin#282](https://github.com/opsmill/styrmin/issues/282).

## Known broken features

- An Infrahub backup ends `PartiallyFailed`. The Neo4j pre-backup hook
  runs a Neo4j Enterprise command against the Community image that the
  Infrahub driver deploys. Tracked in
  [opsmill/styrmin#263](https://github.com/opsmill/styrmin/issues/263).
- On a cluster that enforces NetworkPolicies, some deployments cannot open
  outbound connections. The NetworkPolicies that Styrmin creates in each
  application namespace allow outbound traffic only for Traefik, Prefect and
  Infrahub pods, so the pods of other drivers that declare no NetworkPolicies
  of their own are blocked. Tracked in
  [opsmill/styrmin#284](https://github.com/opsmill/styrmin/issues/284).
- A component with `backup.kind: action` is not backed up, but the backup
  completes. Tracked in
  [opsmill/styrmin#437](https://github.com/opsmill/styrmin/issues/437).
- Deleting an environment leaves its backup storage location in the
  cluster. The Velero object and the Secret that holds the S3 keys stay in
  the `styrmin` namespace. Tracked in
  [opsmill/styrmin#475](https://github.com/opsmill/styrmin/issues/475).
- After you restore a backup of an earlier instance, Styrmin shows the
  wrong active instance. The cluster runs the application version of the
  earlier instance, but Styrmin still shows the newer one. Tracked in
  [opsmill/styrmin#426](https://github.com/opsmill/styrmin/issues/426).
- `styrminctl deployments create --config` and `styrminctl drivers create`
  fail with an error. Use `styrminctl deployments apply` to create a
  deployment with config. Tracked in
  [opsmill/styrmin#349](https://github.com/opsmill/styrmin/issues/349) and
  [opsmill/styrmin#355](https://github.com/opsmill/styrmin/issues/355).

If something looks broken and it is not listed here, file an issue as
described below.

## Giving feedback

<!--
  TODO(beta): the GitHub links on this page work only for readers with access
  to opsmill/styrmin. Decide whether the repository is public for the beta, or
  point readers to a public channel instead.
-->

- To report a bug or request a feature, open an issue on
  [GitHub Issues](https://github.com/opsmill/styrmin/issues/new/choose). If
  you work in the repository with an AI coding assistant, the `create-issue`
  skill (`/create-issue`) formats the issue to the project's conventions and
  applies the labels.
- For questions and discussion, join the
  [OpsMill Discord](https://discord.gg/opsmill).
