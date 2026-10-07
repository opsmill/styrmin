# Styrmin changelog

This is the changelog for Styrmin.
All notable changes to this project will be documented in this file.

Issue tracking is located in [GitHub](https://github.com/opsmill/styrmin/issues).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This project uses [*towncrier*](https://towncrier.readthedocs.io/) and the changes for the upcoming release can be found in <https://github.com/opsmill/styrmin/tree/develop/changelog/>.

<!-- towncrier release notes start -->

## [Styrmin - v0.1.47](https://github.com/opsmill/styrmin/tree/v0.1.47) - 2026-10-07

### Added

- Added per-component image overrides: a deployment can run a custom or patched build on one component, without forking its driver, by setting one image reference on that component. Styrmin applies it after the Helm chart renders, to the component container the driver declares; a `{{ app.version }}` token follows the deployment's application version, while a literal tag or digest pins the image, the upgrade dialog warns about pinned overrides before an application version change, and `styrminctl deployments apply` names them in its output when it changes the version. Available as `ComponentConfigInput.image` on `deploy` and `updateDeployment`, the `Deployment.componentImageOverrides` read field (stored reference, resolved reference, and whether it applies), `components[].image` in `styrminctl deployments apply` manifests, `ApplyOutcome.pinned_image_components` in the SDK, and an **Image** field per component in the deployment's Configuration editor. Invalid references, unknown components, and components without a component container are rejected before anything is deployed, and an application version upgrade that would make a stored override invalid is rejected before any lifecycle action runs. ([#20](https://github.com/opsmill/styrmin/issues/20))

### Changed

- Changed the agent and operator settings (poll retries and intervals, status poll interval, reconcile interval, deployment ready timeout, peering, deleted StyrminDeployment retention and janitor interval) to load with the other Styrmin settings: they keep their environment variable names, can also be set in `styrmin.toml` under `[agent]` and `[operator]`, and appear in `styrmin config show`. Removed `STYRMIN_OPERATOR_HR_READY_TIMEOUT`, which had no effect. A value below 1 for a poll interval, the reconcile or janitor interval, or the deployment ready timeout is now rejected when the settings load, instead of making a poll loop run without waiting. ([#16](https://github.com/opsmill/styrmin/issues/16))
- Changed `get_component_images` to return the component container's image first (the other images keep their pod-template order), so a driver action that takes `images[0]` sees the component's image override; the example drivers' `upgrade` actions now do so instead of matching an image name. A driver that declares a component container name its chart does not render now fails the deployment with `COMPONENT_CONTAINER_NOT_FOUND`, naming the component and the container, as soon as env vars or an image override target that component, instead of the Helm release failing on an added container without an image; Styrmin never adds a container. Clear every image override before rolling Styrmin back below this release: older releases reject the `image` key in a deployment's config. ([#20](https://github.com/opsmill/styrmin/issues/20))
- Upgraded Prefect to 3.8.6 (from 3.6.25). The Helm chart now installs the Prefect server 3.8.6 chart (`prefect-server` 2026.9.14141910), and the server pod gets the chart's default startup, liveness and readiness probes. The local `docker-compose.yml` uses the `prefecthq/prefect:3.8.6-python3.14` image. ([#236](https://github.com/opsmill/styrmin/issues/236))

### Fixed

- Fixed Prefect workers holding database connections open after backup, restore, environment clone and reconcile flows; each flow step now returns its connection to the pool when it ends. ([#140](https://github.com/opsmill/styrmin/issues/140))
- Fixed user actions running the driver's branch tip instead of the commit the driver version was loaded from. Driver versions loaded from now on run the code at their recorded `sourceCommitSha`, and reloading a driver at a newer commit no longer overwrites the actions of earlier versions. ([#375](https://github.com/opsmill/styrmin/issues/375))
- Fixed driver actions failing with "Authentication is required" when they call `stop_components`, `start_components` or `upgrade_deployment_version`. Upgrades of bundled-driver deployments ended with a failed task, and the steps after the first call (such as the Infrahub database migration) did not run. Each reconcile now gives its actions a short-lived token for the built-in `styrmin-actions` user and revokes the token when the reconcile ends. ([#381](https://github.com/opsmill/styrmin/issues/381))
- Fixed a deployment reading `running` instead of `restoring` while a restore of it is in progress: an agent status report sent before Velero finished replaced the `restoring` state, so the guards that refuse other operations on a restoring deployment did not apply during that time. A restore whose workflow could not be dispatched is now marked `failed`, together with its deployment, instead of staying `pending` and keeping the deployment in `restoring`. A second restore of a deployment is now refused while a restore of it into another namespace is still in progress. ([#389](https://github.com/opsmill/styrmin/issues/389))
- Fixed `styrmin config show` dropping the `[section]` headers from its TOML output, which made the output invalid TOML.

## [Styrmin - v0.1.46](https://github.com/opsmill/styrmin/tree/v0.1.46) - 2026-10-04

### Removed

- Removed the `component_env_vars` driver template filter. A driver `values.j2.yml` that still calls it now fails rendering with an error that names the [migration guide](https://styrmin.pages.dev/docs/drivers/migrating-env-vars), so a deployment pinned to an unmigrated driver version fails on its next change (including the redeploy an environment env var edit triggers) until it is upgraded to a driver version that declares component containers. ([#385](https://github.com/opsmill/styrmin/issues/385))

### Added

- Added environment clone: one action copies a live environment into a brand-new environment on the same cluster, built from a fresh backup of the source, with a choice of which deployments to include and a clone-time config override (set or clear captured config fields) so the copy can be made safe before it starts. Available as the `cloneEnvironment` mutation (ADMIN) plus the `environmentClone` / `environmentClones` queries, `client.environment_clones` in the SDK, the `styrminctl env-clones` command group, and a **Clones** tab with a clone dialog on the environment detail page. A clone's status is derived from its backup, the environment it created and the restores into that environment's deployments; deleting the created environment discards the clone. ([#6](https://github.com/opsmill/styrmin/issues/6))
- Added environment-level backup and restore: one action snapshots an environment — its config plus the declared state and a constituent backup of every eligible deployment — and one action restores it in place. Available as the `createEnvironmentBackup`, `restoreEnvironmentBackup` (ADMIN, since it rewrites the environment's config) and `deleteEnvironmentBackup` mutations plus the `environmentBackup(s)` / `environmentRestore(s)` queries, `client.environment_backups` in the SDK, the `styrminctl env-backups` command group, and a **Backups** tab on the environment detail page. An environment backup's status is derived from its constituents and adds a `PARTIAL` outcome; existing per-deployment backups are unaffected. ([#7](https://github.com/opsmill/styrmin/issues/7))

### Changed

- Changed how env vars reach pods: a driver now declares one component container per component (`components.<name>.container`), and Styrmin merges the environment, deployment, and component env vars into that container by name after the Helm chart renders, so the chart's own env defaults are kept and a user value replaces a chart entry of the same name. User env vars no longer reach chart Jobs, init containers, or other containers; adding or changing a component env var on a component without a component container is rejected with `COMPONENT_CONTAINER_NOT_DECLARED`; and on every update Styrmin replaces each HelmRelease spec key it writes (keys it never writes, such as `spec.suspend`, are kept), so env values written by an old driver template no longer linger. Every example driver declares its component containers. Rolling Styrmin back below this release stops env var injection for drivers already migrated. ([#385](https://github.com/opsmill/styrmin/issues/385))

### Fixed

- Fixed `createUser`, `updateUser`, `createGroup`, and `updateGroup` returning an opaque "An internal error occurred" when a `groupIds`/`memberIds` entry is not a valid UUID: malformed IDs now return a typed `VALIDATION_ERROR` naming the offending value. ([#351](https://github.com/opsmill/styrmin/issues/351))
- Fixed the example `slurpit` driver passing its hard-coded database credentials and warehouse tokens to the slurpit chart as a list: the chart expects a map, so its ConfigMaps held keys `0`, `1`, … and neither that wiring nor the chart's own env defaults reached the containers. Fixed the example `infrahub` and `infrahub-enterprise` drivers dropping the Prefect server chart's env defaults (`PREFECT_UI_SERVE_BASE`, plus `PROMETHEUS_MULTIPROC_DIR` on the community chart).

## [Styrmin - v0.1.45](https://github.com/opsmill/styrmin/tree/v0.1.45) - 2026-09-25

### Added

- Added a `deployment(name, environmentId)` GraphQL query that resolves a non-internal, non-soft-deleted deployment by its natural identity, exposed in the SDK as `client.deployments.get_by_name(name, environment_id=...)`. The existing `deployment(deploymentId)` lookup is unchanged.
- Added declarative deployment management via `styrminctl deployments apply`: author YAML manifests (`apiVersion: styrmin/v1`, `kind: Deployment`) and apply them with `styrminctl deployments apply -f <path>` to create or update deployments by their natural identity `(name, environment)`. Supports single files, directories, multi-document YAML, multiple `-f` flags, and CLI/env-var overrides; the optional `--wait` flag blocks until each deployment reaches a terminal state.

### Changed

- Changed the `styrmin-agent` Helm chart to default `image.tag` to the chart's `appVersion` instead of the hardcoded `latest`, matching the `styrmin` chart, so a default install of a released chart pins the agent to that release's image rather than tracking a floating tag. Installs that need a locally-built or otherwise floating image must now set `styrmin-agent.image.tag` explicitly — see `helm/styrmin/README.md` ("Running against a locally-built image").
- Changed the `velero` subchart from 8.3.0 to 12.1.0 (Velero 1.15.2 to 1.18.1) and `velero-plugin-for-aws` from v1.11.1 to v1.14.2. On `helm upgrade` the chart's CRD job applies the new Velero CRDs and the Velero server and node-agent pods restart once.
- Changed the local demo and the E2E suite to provision [Garage](https://garagehq.deuxfleurs.fr/) instead of MinIO as the in-cluster S3-compatible store Velero writes backups to: `uv run invoke cluster.minio` becomes `uv run invoke cluster.garage`, the manifest moves from `dev/local/minio.yaml` to `dev/local/garage.yaml`, and the bootstrapped backup storage location points at `http://garage.styrmin.svc:3900` (region `garage`). Nothing about the product's S3 support changes — any S3-compatible bucket still works.

### Fixed

- Fixed the light/dark theme toggle being reachable only from the Environments page: it now lives in the shared application header, so it is available from every page — Environments, Clusters, Deployments, Drivers, Backup Storage, Settings, Profile — and from the login screen. ([#331](https://github.com/opsmill/styrmin/issues/331))
- Fixed renaming a backup storage location to a name already in use failing with an opaque "An internal error occurred": the update path now rejects the duplicate with a typed `ALREADY_EXISTS` error, matching the create path. ([#350](https://github.com/opsmill/styrmin/issues/350))
- Fixed Velero backup-repository maintenance, which had never run in any Styrmin install: Velero resolves its own Deployment by the hardcoded name `velero` to build the kopia maintenance Job, but the `velero` subchart named it `<release>-velero`, so every cycle failed with `Deployment.apps "velero" not found`, kopia never pruned, and the data behind expired backups was never reclaimed from the bucket. `helm/styrmin/values.yaml` now pins `velero.fullnameOverride: velero`. **Upgrading:** the Velero Deployment, Service, ServiceAccount, and ConfigMaps are renamed, so `helm upgrade` replaces them and the Velero pod restarts once; update anything referring to the old names (`deployment/<release>-velero`, dashboards, scrape configs) to `velero`. The PVC-patch ConfigMap is now `velero-restore-pvc-patch`; Restores created before the upgrade keep pointing at the old name and cannot be re-driven, but Restores are one-shot objects and new ones are unaffected. Helm creates the renamed Deployment before it deletes the old one, so two Velero servers overlap for a few seconds; do not upgrade while a backup or restore is in flight.
- Fixed Velero's idle log volume, now roughly 5x quieter: `--backup-sync-period` and `--store-validation-frequency` default to `5m` instead of Velero's 1m. Each cycle spawned and killed an object-store plugin process whose teardown logs a spurious error ([velero#7892](https://github.com/vmware-tanzu/velero/issues/7892)), so the default cadence buried real backup logs under ~7 noise lines a minute per BackupStorageLocation. Styrmin names the BSL on every backup and tracks backup state in its own database, so neither loop was load-bearing.

### Housekeeping

- Replaced hand-edited changelog entries with towncrier newsfragments: `CHANGELOG.md` is now generated at release time from files in `changelog/`, using the same towncrier configuration and rules as infrahub.
