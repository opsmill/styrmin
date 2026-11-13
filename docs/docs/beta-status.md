---
title: Beta status
description: What the Styrmin beta includes, what changed since the alpha, what to do before you upgrade from the alpha, what is coming next, and the known limitations and broken features.
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
release. Before you use Styrmin, note the following:

- The GraphQL API, `styrminctl` commands and flags, the Python SDK and the
  driver format can still change between releases.
- The release notes of each release list its breaking changes with the steps
  to take, and the [Changelog](./changelog.md) describes the notable ones. A
  change to the driver format also has a migration guide, such as
  [Migrating Container Overrides](./drivers/migrating-container-overrides.md).
- Styrmin is not yet recommended for production-critical workloads. Use it for
  lab, staging and internal-tooling deployments, and read the
  [known broken features](#known-broken-features) first.

## Workflows added since the alpha

These workflows are new since the alpha (v0.1.26, May 27, 2026). Each item
links to the page that explains it.

### Deploying and changing applications

- Describe deployments in `styrmin/v1` manifest files and create or update
  them with `styrminctl deployments apply -f <path>`. An apply that changes
  nothing starts no task and reports the deployment as `unchanged`. See
  [`deployments apply`](./reference/styrminctl.md#deployments-apply-is-idempotent).
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
- View the steps of each task. The deployment page and `styrminctl tasks get`
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
  [Retention: how long Velero keeps a backup](./concepts-and-architecture/backups-and-restores.md#retention-how-long-velero-keeps-a-backup).
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
- Run the actions of a driver version at the commit that the driver version
  was loaded from. A push to the driver's branch does not change the actions
  of the deployments that use it.

### Writing scripts with the Python SDK

- Wait until a deployment change has finished with one call,
  `deployments.wait_for_task()`. See
  [Waiting for a change from a script](./concepts-and-architecture/status-reporting.md#waiting-for-a-change-from-a-script).
- Read the pod statuses and the services of a whole environment, or the pod
  statuses of a whole cluster, in one call. See
  [Reading pod statuses from a script](./concepts-and-architecture/status-reporting.md#reading-pod-statuses-from-a-script).
- Read the phase, message and conditions that the operator reported for a
  deployment, with `deployments.get_crd_status()`. See
  [Reading the operator's status from a script](./concepts-and-architecture/status-reporting.md#reading-the-operators-status-from-a-script).

### Running Styrmin

- The agent installs the controllers of FluxCD v2.9 and runs helm-controller
  with the defaults of Helm v4. See
  [The HelmRelease](./concepts-and-architecture/operator-and-crds.md#the-helmrelease).
- `styrminctl` and the server send anonymous telemetry, which you can turn
  off. See [Telemetry & privacy](./reference/telemetry.md).
- When the Prefect worker that runs a flow stops, Styrmin marks the flow run
  as crashed, so its task no longer stays `RUNNING`.

## Changes to make before you upgrade from the alpha

Releases between the alpha and the beta changed or removed behavior that
installs, deployments, drivers and scripts depend on. Before you upgrade,
read the list for each role you have. The version in parentheses is the
first release with the change.

### If you install or upgrade Styrmin

<!--
  TODO(beta): the chart does not run `styrmin db migrate`, and the server only
  creates missing tables when it starts (`SQLModel.metadata.create_all`). Releases
  since the alpha add columns and data revisions. Document how a Helm install
  applies them, or add a migration step to the chart, before the beta ships.
-->

- Run Kubernetes 1.25 or later. Earlier versions do not check the validation
  rules of the agent's CRDs. The agent installs the FluxCD v2.10 controllers,
  which work on Kubernetes 1.25 to 1.37. The FluxCD project supports them only
  on Kubernetes 1.35.2 and later (v0.1.48).
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
  [Turn server telemetry off](./reference/telemetry.md#turn-server-telemetry-off).
- Upgrade the server and the agent before `styrminctl` and the Python SDK.
  `deployments apply` and the backup list of v0.1.48 need a v0.1.48 server,
  and replica overrides need the agent of v0.1.50.
- Upgrade the server, `styrminctl` and the Python SDK together to the beta
  release, and reload the web pages that were open during the upgrade,
  because the restore request changes (the beta release). See
  [Restores no longer delete a namespace that the caller names](./changelog.md#restores-no-longer-delete-a-namespace-that-the-caller-names).
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

### If you create and change deployments

- Move the replica counts of Infrahub deployments to replica overrides. The
  `infrahub` driver version 5 and the `infrahub-enterprise` driver version 4
  remove the `replicas_server` and `replicas_task_worker` parameters. A
  deployment that stores a value other than the default cannot change driver
  version until you move the value (v0.1.50). See
  [Migrating Replica Parameters](./drivers/migrating-replica-parameters.md).
- Before you upgrade to v0.1.48, list the stored container `command` and
  `args` overrides and remove the ones you do not want. From v0.1.48,
  Styrmin applies them to the pods, also for drivers whose templates never
  used them. See
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
- Check the scripts and procedures that delete environments. Deleting an
  environment deletes its deployments and its environment backups (v0.1.46).
  Before, the request failed when the environment had deployments.
- Find the deployments whose driver version declares a service `scope: external`
  and renders its own Ingress for it. Of the drivers that OpsMill ships in
  `driver/examples`, only `generic-app` driver version 1 does. Styrmin now
  builds an Ingress for each external service, so these deployments have two
  Ingresses on the same host once they run a release that includes this
  change, before any driver version change. The number of the Styrmin release
  that includes this change is not known yet. `generic-app` version 2,
  `infrahub` version 6 and `infrahub-enterprise` version 5 declare an external
  service and render no Ingress for it. An apply error on an Ingress now fails
  the deploy flow, so an ingress controller that rejects a duplicate host and
  path could fail the deploy flow of a deployment with two Ingresses. This is
  plausible and not verified. See
  [Migrate a driver whose external service renders its own Ingress](./drivers/migrating-external-service-ingress.md).
- Expect a short interruption when you move a running Infrahub deployment to
  `infrahub-enterprise` driver version 5 or `infrahub` version 6. The chart's
  Prefect UI Ingress is removed and Styrmin builds its own. On a local vCluster
  with the operator pass every 60 seconds, the Prefect UI host answered HTTP
  404 for about 7 seconds and about 12 seconds (2 samples, `infrahub-enterprise`
  from driver version 4 to 5). With the pass every 5 seconds, no request failed
  (2 samples). The length depends on when the next operator pass falls, and it
  was not measured on other systems or for `infrahub` version 6. See
  [What was measured](./drivers/migrating-external-service-ingress.md#what-was-measured-when-a-running-infrahub-deployment-moves-to-the-new-driver-version).
- Clear a service ingress override before you change a deployment to a driver
  version that removes the service, declares it `internal`, or gives it kind `tcp`
  or `udp`. Styrmin refuses
  the change with `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` otherwise. See
  [Change a deployment's driver version](./drivers/changing-driver-versions.md#stored-service-ingress-overrides).

### If you write application drivers

- Declare `components.<name>.container` for each component that receives env
  vars, `command`, `args` or an image override, and remove the
  `component_env_vars`, `component_command` and `component_args` template
  filters and `spec.container_overrides`. A driver that still uses them fails
  to load with `RETIRED_TEMPLATE_FILTER` (v0.1.46 and v0.1.48). See
  [If you write drivers](./drivers/migrating-container-overrides.md#if-you-write-drivers).
- Set `backup.volume` or `backup.volumes` on each component with
  `backup.kind: disk`. Without one, the driver fails to load (v0.1.30).
- Use `images[0]` in actions. `get_component_images` returns the image of
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
- Change a field that the chart sets through the chart's values, not with
  `kubectl` or an action. New deployments are installed with server-side
  apply, and on those deployments the next upgrade sets the field back to the
  chart's value (v0.1.50).
- Do not combine `singleton: true` with `replicas` above 1 on a component. The
  driver fails to load (v0.1.50).
- Read `backup.velero.storage_location` as the name of the Velero object,
  `styrmin-bsl-<location id>`. It held the backup storage location's name
  before (v0.1.50).
- Turn off the chart's Ingress for each service that you declare
  `scope: external`. Styrmin builds the Ingress of an external service, so a
  chart Ingress for it gives two Ingresses on the same host. A service with
  `scope: internal` keeps the chart's Ingress. See
  [Migrate a driver whose external service renders its own Ingress](./drivers/migrating-external-service-ingress.md).

### If you write scripts that use the API, the Python SDK or styrminctl

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
  [Restores no longer delete a namespace that the caller names](./changelog.md#restores-no-longer-delete-a-namespace-that-the-caller-names).
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
- Handle `IN_USE` from `deleteCluster` on a cluster that still has
  environments (v0.1.49).

## Features that are not in the beta

- Network isolation of a cloned environment. A clone runs in its own
  namespaces, but values stored in the restored data, such as credentials
  or webhook URLs, are copied as they are, so a clone can reach the same
  external systems as its source. See
  [What a clone is not isolated from](./concepts-and-architecture/backups-and-restores.md#what-a-clone-is-not-isolated-from).
  [Coming next](#coming-next) lists outbound traffic control for
  environments.
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
- Deleting an environment from the environment page, tracked in
  [opsmill/styrmin#254](https://github.com/opsmill/styrmin/issues/254). Use
  `styrminctl environments delete`.

## Coming next

These features have an open issue, and no release date is set for them.
Some already have a written design or an open pull request, as noted.

### Isolating environments and routing traffic

- Control the outbound traffic of an environment: allow only traffic inside
  the cluster, only traffic to a list of addresses, or all traffic. A cloned
  environment starts with traffic inside the cluster only. Tracked in
  [opsmill/styrmin#36](https://github.com/opsmill/styrmin/issues/36).
- Give the outbound traffic of an environment a fixed source IP address or
  range, so that firewalls can match it. Tracked in
  [opsmill/styrmin#32](https://github.com/opsmill/styrmin/issues/32).
- Put the traffic of an environment in its own VLAN. Tracked in
  [opsmill/styrmin#33](https://github.com/opsmill/styrmin/issues/33).
- Declare in an application driver which components can connect to each
  other and which can reach the internet, and block all other traffic.
  Tracked in [opsmill/styrmin#131](https://github.com/opsmill/styrmin/issues/131).
- Use the planned environment network features on clusters whose CNI is not
  Cilium. Tracked in
  [opsmill/styrmin#463](https://github.com/opsmill/styrmin/issues/463).
- Serve applications through an ingress controller other than Traefik, or
  through the Kubernetes Gateway API. Tracked in
  [opsmill/styrmin#464](https://github.com/opsmill/styrmin/issues/464) and
  [opsmill/styrmin#465](https://github.com/opsmill/styrmin/issues/465).

### Backing up and restoring

- Restore a backup into a new deployment in the same environment, without
  changing the deployment the backup was taken of. This also works for a
  backup of a deleted deployment. The issue has a written design. Tracked in
  [opsmill/styrmin#534](https://github.com/opsmill/styrmin/issues/534).
- Rename a backup and add a description to it. Tracked in
  [opsmill/styrmin#39](https://github.com/opsmill/styrmin/issues/39).
- Back up the Neo4j Community database of Infrahub with an offline dump that
  a backup action makes. Tracked in
  [opsmill/styrmin#438](https://github.com/opsmill/styrmin/issues/438).
- Run backups and restores with a backup system other than Velero. Tracked
  in [opsmill/styrmin#466](https://github.com/opsmill/styrmin/issues/466).

### Deploying and changing applications

- Stop, start and restart a whole deployment in one action. Tracked in
  [opsmill/styrmin#99](https://github.com/opsmill/styrmin/issues/99).
- Set CPU and memory requests and limits for each component of a
  deployment. Tracked in
  [opsmill/styrmin#382](https://github.com/opsmill/styrmin/issues/382).
- Choose the application version from a list of releases when you deploy or
  upgrade, instead of typing it. Tracked in
  [opsmill/styrmin#336](https://github.com/opsmill/styrmin/issues/336).
- Get an error before the deployment starts when its application driver
  needs a storage class that the cluster does not set. Tracked in
  [opsmill/styrmin#303](https://github.com/opsmill/styrmin/issues/303).
- View the name of the deployment that a pod affinity term names when you
  read a config, and get a warning before you delete a deployment that an
  affinity term names. Tracked in
  [opsmill/styrmin#521](https://github.com/opsmill/styrmin/issues/521) and
  [opsmill/styrmin#523](https://github.com/opsmill/styrmin/issues/523).
- Record an owner and contact details on a deployment. Tracked in
  [opsmill/styrmin#35](https://github.com/opsmill/styrmin/issues/35).

### Writing and loading application drivers

- Check the files of a driver and render its templates on your machine,
  without a Styrmin server or a cluster. Tracked in
  [opsmill/styrmin#23](https://github.com/opsmill/styrmin/issues/23).
- Load a driver version from a Git tag or a commit, in addition to the tip
  of a branch. Tracked in
  [opsmill/styrmin#528](https://github.com/opsmill/styrmin/issues/528).
- Deploy Peering Manager, Netpicker, Akvorado, Gitea and Workflow
  Orchestrator with new bundled application drivers. Tracked in
  [opsmill/styrmin#200](https://github.com/opsmill/styrmin/issues/200),
  [opsmill/styrmin#144](https://github.com/opsmill/styrmin/issues/144),
  [opsmill/styrmin#139](https://github.com/opsmill/styrmin/issues/139),
  [opsmill/styrmin#63](https://github.com/opsmill/styrmin/issues/63) and
  [opsmill/styrmin#34](https://github.com/opsmill/styrmin/issues/34).

### Viewing the state and the history of Styrmin

- View which clusters have a running agent, when each agent last reported,
  and the health of its components. Tracked in
  [opsmill/styrmin#97](https://github.com/opsmill/styrmin/issues/97).
- View a log of the actions on deployments, environments, clusters and
  backups: what changed, who made the change and when. Tracked in
  [opsmill/styrmin#201](https://github.com/opsmill/styrmin/issues/201).
- View who changed the config of a cluster, when, and what the previous
  config was. Tracked in
  [opsmill/styrmin#447](https://github.com/opsmill/styrmin/issues/447).
- View the logs of a component from the frontend or the API. The issue is
  open for a design discussion. Tracked in
  [opsmill/styrmin#147](https://github.com/opsmill/styrmin/issues/147).
- Collect the metrics and logs of the deployed applications with an
  observability stack that Styrmin runs. The tools and the scope are not
  decided yet. Tracked in
  [opsmill/styrmin#462](https://github.com/opsmill/styrmin/issues/462).

### Integrating Styrmin with other tools

- Declare Styrmin resources as Kubernetes resources and apply them with
  `kubectl`. Which resources this covers is not decided yet. Tracked in
  [opsmill/styrmin#544](https://github.com/opsmill/styrmin/issues/544).
- Read credentials from an external secrets manager, such as Vault, AWS
  Secrets Manager or Sealed Secrets. Tracked in
  [opsmill/styrmin#22](https://github.com/opsmill/styrmin/issues/22).
- Give AI agents access to the clusters, environments, deployments, drivers
  and tasks of Styrmin through an MCP server in the Styrmin server. Tracked
  in [opsmill/styrmin#60](https://github.com/opsmill/styrmin/issues/60).

### Using the API, the Python SDK and styrminctl

- Page, filter and order the results of GraphQL list queries. Tracked in
  [opsmill/styrmin#26](https://github.com/opsmill/styrmin/issues/26) and
  [opsmill/styrmin#27](https://github.com/opsmill/styrmin/issues/27).
- Change the config of an environment with `styrminctl`. Tracked in
  [opsmill/styrmin#425](https://github.com/opsmill/styrmin/issues/425).
- Read the parameters, services and env vars that a driver version declares
  with the SDK. Tracked in
  [opsmill/styrmin#546](https://github.com/opsmill/styrmin/issues/546).
- Change one override of one component with the SDK without sending every
  component block again. Tracked in
  [opsmill/styrmin#549](https://github.com/opsmill/styrmin/issues/549).

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
