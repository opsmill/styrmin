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
