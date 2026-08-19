# GraphQL Contract: Environment Clone

**Feature**: 010-environment-clone | **Date**: 2026-08-19

Additive-only. Conventions follow the environment-backup surface: flat scalar
arguments, entity returned directly (no payload wrappers), plain non-null lists, no
pagination, typed errors via `StructuredErrorExtension` (`extensions.code`).

## Mutation

```graphql
"""
Clone an environment into a new environment on the same cluster, built from a
fresh environment backup of the source. Asynchronous: returns the clone record
immediately; status is derived on every read.
"""
cloneEnvironment(
  environmentId: UUID
  environmentName: String
  clusterId: UUID
  clusterName: String
  name: String!                      # target environment name
  deploymentIds: [UUID!] = null     # selection; null = all eligible (FR-003)
  configOverride: UpdateEnvironmentInput = null  # merged over captured config (FR-006, D7)
  clearConfigFields: [String!] = null  # captured config fields removed before the merge (FR-006, D7)
): EnvironmentClone!
```

- **Auth**: `ADMIN` (`_requires(Role.ADMIN)`) — FR-010; mirrors
  `restoreEnvironmentBackup`'s rationale (ADR-055 decision 7), which clone strictly
  supersets. Covered by `test_mutation_authz_coverage.py`.
- Source resolution: dual-identifier convention (ADR-031), same as
  `deleteEnvironment`.
- **Upfront typed errors** (zero side effects — FR-011):
  - `ALREADY_EXISTS` — `name` taken in the cluster (`EnvironmentAlreadyExistsError`).
  - `NOT_FOUND` — source environment / any selected deployment id unknown or not in
    the source environment.
  - `VALIDATION_ERROR` — `configOverride` fails `EnvironmentConfig` validation;
    `clearConfigFields` names a field that is not a top-level `EnvironmentConfig`
    field; an empty effective selection is fine (yields an empty `COMPLETED` clone)
    but a selection listing only tombstoned/foreign deployments is rejected.
  - `ALREADY_IN_PROGRESS` — another environment-level operation (backup, restore, or
    a clone in its capture window) is running on the source
    (`EnvironmentOperationInProgressError`, D8).

## Queries

```graphql
environmentClone(environmentCloneId: UUID!): EnvironmentClone!      # NOT_FOUND if unknown
environmentClones(environmentId: UUID!): [EnvironmentClone!]!       # by SOURCE environment, newest first
```

Read access ungated (matches `environmentBackup`/`environmentBackups`).

## Types

```graphql
enum EnvironmentCloneStatus {          # derived on every read, never stored (FR-009)
  PENDING
  IN_PROGRESS
  COMPLETED
  PARTIAL
  FAILED
}

enum EnvironmentCloneDeploymentOutcome {
  PENDING
  CLONED
  SKIPPED
  FAILED
}

type EnvironmentCloneDeploymentResult {
  deploymentId: UUID!                  # source deployment
  deploymentName: String!
  outcome: EnvironmentCloneDeploymentOutcome!
  reason: String                       # non-null for SKIPPED/FAILED (FR-004, SC-003)
  counterpartDeploymentId: UUID        # in the created environment; null unless CLONED
  restoreId: UUID                      # constituent cross-target restore; null unless dispatched
}

type EnvironmentClone {
  id: UUID!
  name: String!                        # requested target environment name
  status: EnvironmentCloneStatus!      # derived (data-model.md derivation)
  sourceEnvironment: Environment       # null after the source was deleted (terminal clones survive it)
  sourceEnvironmentName: String!       # denormalised; readable provenance regardless
  environmentBackup: EnvironmentBackup # the capture; null once deleted post-terminality
  createdEnvironment: Environment      # null until materialised / after deletion
  requestedDeploymentIds: [UUID!]      # null = all eligible
  configOverride: JSON                 # as supplied (canonicalised); null if none
  clearConfigFields: [String!]         # as supplied; null if none
  deploymentResults: [EnvironmentCloneDeploymentResult!]!
  cloneErrors: [String!]!              # operation-level events, rendered "step: error"
  createdOn: DateTime!
  updatedOn: DateTime!
}
```

Back-reference for provenance (P1): the existing `Environment` type gains

```graphql
clonedFrom: EnvironmentClone   # the clone that created this environment; null if not clone-born
```

Implementation pattern: `db_model: strawberry.Private[...]` with computed `status()` /
`deployment_results()` resolvers, like `EnvironmentBackup`
(`api/definitions/backup/environment_backup.py:109-232`). `EnvironmentCloneStatus` is
its own Python enum mirror (strawberry binds one GraphQL name per Python class).
Unlike the JSON-reason convention inside the DB row, the wire outcome is a closed
enum — the write-side vocabulary is fixed at four values by the service, so the wire
can afford the type safety; `reason` stays a free string (ADR-055 decision 4).

## Changed existing surface

- `deleteEnvironmentBackup`: unchanged signature; can now raise `IN_USE`
  (`EnvironmentBackupInUseByCloneError`) while a referencing clone's **capture** is
  in flight (FR-008, D9). Post-capture deletion is allowed and updates referencing
  clones (non-terminal → attributed `FAILED`; terminal → outcome stands). Documented
  in the mutation's docstring.
- `createRestore`, `createEnvironmentBackup`, `restoreEnvironmentBackup`: unchanged.
  (Cross-target restore and the capture's deployment filter are service-level
  parameters used by the clone path only — not exposed on the public schema in v1.)

## Propagation-test obligations (Constitution §V)

Every element above gets a propagation test under
`backend/tests/functional/graphql/` with named operations in `operations/*.graphql`:
mutation persistence (clone row + capture + links + upfront skips), each upfront
typed error (including invalid `clearConfigFields`), derived-status projection matrix
from real DB state, both queries, `deploymentResults` join projection,
`configOverride` merge and `clearConfigFields` removal visibility on the created
environment, `Environment.clonedFrom` back-reference, ADMIN gating (FORBIDDEN for
`read_write_client`), and the `deleteEnvironmentBackup` `IN_USE`-during-capture and
allowed-post-capture paths.

## Regeneration duties

`uv run styrmin export graphql-schema schema.graphql` + `uv run invoke generate`
(SDK Pydantic types + frontend TS types) in the same change; `uv run invoke
validate-graphql` for all new operation files (SDK, frontend, tests).
