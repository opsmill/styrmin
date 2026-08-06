# GraphQL Contract: Environment Clone

**Feature**: `specs/002-env-clone` | **Date**: 2026-08-06

New surface under `backend/styrmin_backend/api/schema/`. Every field, argument, and mutation below requires a propagation test (`dev/guides/graphql-propagation-tests.md`). After implementing: `uv run styrmin export graphql-schema schema.graphql` then `uv run invoke generate`.

## Types

```graphql
"""One environment clone operation: the source capture, the created environment,
and per-deployment attribution. Status is derived on every read — never stored."""
type EnvironmentClone {
  id: UUID!
  createdOn: DateTime!
  """Derived (PENDING, IN_PROGRESS, COMPLETED, PARTIAL, FAILED) — see data-model.md."""
  status: EnvironmentCloneStatus!
  """Null after the source environment is deleted (the clone is unaffected)."""
  sourceEnvironment: Environment
  sourceEnvironmentName: String!
  """The backing capture; null after that backup is deleted."""
  environmentBackup: EnvironmentBackup
  """The clone environment; null until created, and after its deletion."""
  createdEnvironment: Environment
  newEnvironmentName: String!
  """Operator selection at clone time; null means all eligible deployments."""
  selectedDeploymentIds: [UUID!]
  environmentConfigOverride: JSON
  """One entry per selected deployment — cloned, skipped, or failed, with reason (zero silent omissions)."""
  deploymentResults: [DeploymentCloneResult!]!
  """Constituent data restores dispatched into the clone."""
  restores: [Restore!]!
  finishedAt: DateTime
}

enum EnvironmentCloneStatus { PENDING IN_PROGRESS COMPLETED PARTIAL FAILED }

type DeploymentCloneResult {
  deploymentId: UUID!
  deploymentName: String!
  counterpartDeploymentId: UUID
  outcome: DeploymentCloneOutcome!
  """Open text — render it, do not switch on it."""
  reason: String
  """True when the driver version was re-resolved by name+version because the captured fingerprint no longer matched."""
  fingerprintFallback: Boolean!
}

enum DeploymentCloneOutcome { CLONED SKIPPED FAILED }
```

## Mutations

| Mutation | Args | Returns | Role | Errors (`extensions.code`) |
|---|---|---|---|---|
| `cloneEnvironment` | `environmentId: UUID!`, `newEnvironmentName: String!`, `deploymentIds: [UUID!] = null`, `environmentConfigOverride: JSON = null` | `EnvironmentClone` | **ADMIN** (writes an `Environment.config` the caller did not author — same argument as `restoreEnvironmentBackup`; spec FR-014) | `NOT_FOUND` (source environment), `ALREADY_EXISTS` (new name taken — FR-012, zero side effects), `VALIDATION_ERROR` (selection contains a non-eligible or unknown deployment id; merged config invalid), `ALREADY_IN_PROGRESS` (environment-level operation in flight on the source — research.md D4) |
| `deleteEnvironmentClone` | `environmentCloneId: UUID!` | `Boolean` | `READ_WRITE` | `NOT_FOUND` |

Behavioral notes:

- `cloneEnvironment` validates synchronously and returns immediately with the record in `PENDING`; all materialisation happens in the `EXECUTE_ENVIRONMENT_CLONE` flow. Nothing exists until the backing environment backup reaches a usable terminal status (FR-002): a `FAILED` backup ends the clone with no environment created.
- The config override merges **top-level shallow** over the captured config (`{**captured, **override}`), is validated before the environment is created, and has no key-removal semantics in v1.
- `deleteEnvironmentClone` deletes the **record only** — never the clone environment, the backing backup, or constituent restores' rows (linked restores' `environment_clone_id` FK rows are deleted with the record, matching `deleteEnvironmentBackup`'s treatment of `EnvironmentRestore` rows). Legal regardless of derived status (escape hatch; releases the FR-008 guard).
- `deleteEnvironmentBackup` (existing) gains a guard: `OPERATION_DENIED` (`EnvironmentBackupInUseError`) while a linked clone is in flight (FR-008). Surfaces identically through `deleteEnvironment` on the source (cascade).
- Deleting the **clone environment** is ordinary `deleteEnvironment` (ADMIN, existing) — nothing clone-specific blocks it (FR-013/SC-005).

## Queries

| Query | Args | Returns | Role |
|---|---|---|---|
| `environmentClone` | `environmentCloneId: UUID!` | `EnvironmentClone` | authenticated (ungated read, env-backup precedent) |
| `environmentClones` | `environmentId: UUID!` | `[EnvironmentClone!]!` (newest first; matches on **source** environment) | authenticated |

## Client operation files

SDK (`python_sdk/src/styrmin_sdk/graphql/`): `clone_environment.graphql`, `get_environment_clone.graphql`, `list_environment_clones.graphql`, `delete_environment_clone.graphql`.

Frontend (`frontend/src/graphql/`): `clone_environment.graphql`, `list_environment_clones.graphql`, `delete_environment_clone.graphql`.

One named operation per file; validate with `uv run invoke validate-graphql`.

## SDK facade (`client.environment_clones.*`, ADR-0037 shape)

`create(environment_id, new_environment_name, deployment_ids=None, environment_config_override=None)`, `get(environment_clone_id)`, `list(environment_id)`, `delete(environment_clone_id)`, `wait_for_clone(environment_clone_id, max_wait=1800, interval=10)` — polls until derived status is terminal (`COMPLETED`, `PARTIAL`, `FAILED`); returns the last observation on timeout (env-backup poller contract).

## CLI (`styrminctl env-clones …`)

| Command | Key options |
|---|---|
| `create <environment> --new-name <name> [--cluster …] [--id …] [--deployment <name-or-id>]… [--config-override <json>] [--wait --max-wait --interval]` | Dual-identifier source resolution (ADR-0031); repeatable `--deployment` builds the selection; synchronously-derived terminal failure reported non-zero without polling (env-backups rule) |
| `get <environment-clone-id>` | Key/value detail incl. per-deployment results and the created environment |
| `list <environment> …` | Table: new name, status, results (cloned/skipped/failed of total), created |
| `delete <environment-clone-id>` | Record-only deletion |
