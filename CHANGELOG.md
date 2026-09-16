# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Declarative deployment management via `styrminctl deployments apply`. Author
  YAML manifests (`apiVersion: styrmin/v1`, `kind: Deployment`) and apply them
  with `styrminctl deployments apply -f <path>` to create or update deployments
  by their natural identity `(name, environment)`. Supports single files,
  directories, multi-document YAML, multiple `-f` flags, and CLI/env-var
  overrides. The optional `--wait` flag blocks until each deployment reaches a
  terminal state. See `specs/009-deployments-apply/quickstart.md`.
- New GraphQL query shape: `deployment(name, environmentId)` resolves a
  non-internal, non-soft-deleted deployment by its natural identity. The
  existing `deployment(deploymentId)` lookup is unchanged. Exposed in the SDK
  as `client.deployments.get_by_name(name, environment_id=...)`, with the
  generated `GetDeploymentByNameDeployment` type re-exported from
  `styrmin_sdk` for external callers.

### Changed

- The local demo and the E2E suite now provision
  [Garage](https://garagehq.deuxfleurs.fr/) instead of MinIO as the in-cluster
  S3-compatible store Velero writes backups to. `uv run invoke cluster.minio`
  becomes `uv run invoke cluster.garage`, the manifest moves from
  `dev/local/minio.yaml` to `dev/local/garage.yaml`, and the bootstrapped
  Backup Storage Location points at `http://garage.styrmin.svc:3900`
  (region `garage`). Nothing about the product's S3 support changes — any
  S3-compatible bucket still works.
- The `styrmin-agent` Helm chart now defaults `image.tag` to the chart's
  `appVersion` instead of the hardcoded `latest`, matching the `styrmin`
  chart. A default install of a released chart now pins the agent to that
  release's image rather than tracking a floating tag. The release workflow
  bumps the agent chart's `appVersion` alongside the parent's. Installs that
  need a locally-built or otherwise floating image must now set
  `styrmin-agent.image.tag` explicitly — see `helm/styrmin/README.md`
  ("Running against a locally-built image").
