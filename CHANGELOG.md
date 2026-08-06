# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Environment-level backup and restore. One action snapshots an environment —
  its config plus the declared state and a constituent backup of every eligible
  deployment — and one action restores it in place. New GraphQL surface:
  `createEnvironmentBackup`, `restoreEnvironmentBackup` (ADMIN — it rewrites
  `Environment.config`), `deleteEnvironmentBackup` (cascading through the
  constituents), plus the `environmentBackup(s)` / `environmentRestore(s)`
  queries. The parent status is **derived** from its constituents on every read
  and adds a `PARTIAL` outcome, so it can never contradict them. Exposed as
  `client.environment_backups` in the SDK, the `styrminctl env-backups` command
  group (`create`, `get`, `list`, `restore`, `restore-get`, `restore-list`,
  `delete`), and a **Backups** tab on the environment detail page. Ships one
  Alembic revision (`c1d2e3f4a5b6`) adding the two parent tables and a nullable
  membership FK on `Backup` / `Restore` — existing per-deployment backups are
  unaffected. See
  `docs/docs/concepts-and-architecture/backups-and-restores.md` ("Backing up a
  whole environment") and `docs/docs/reference/styrminctl.md`.
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

- The `styrmin-agent` Helm chart now defaults `image.tag` to the chart's
  `appVersion` instead of the hardcoded `latest`, matching the `styrmin`
  chart. A default install of a released chart now pins the agent to that
  release's image rather than tracking a floating tag. The release workflow
  bumps the agent chart's `appVersion` alongside the parent's. Installs that
  need a locally-built or otherwise floating image must now set
  `styrmin-agent.image.tag` explicitly — see `helm/styrmin/README.md`
  ("Running against a locally-built image").
