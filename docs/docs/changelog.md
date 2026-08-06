---
title: Changelog
sidebar_position: 99
description: Notable user-visible changes to the Styrmin platform.
---

## Changelog

Notable user-visible changes are recorded here. For full commit history, see the [GitHub repository](https://github.com/opsmill/styrmin).

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
