# Styrmin changelog

This is the changelog for Styrmin.
All notable changes to this project will be documented in this file.

Issue tracking is located in [GitHub](https://github.com/opsmill/styrmin/issues).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This project uses [*towncrier*](https://towncrier.readthedocs.io/) and the changes for the upcoming release can be found in <https://github.com/opsmill/styrmin/tree/develop/changelog/>.

<!-- towncrier release notes start -->

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
