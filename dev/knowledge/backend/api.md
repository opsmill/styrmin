# Backend API Documentation

## Overview

The backend exposes a single GraphQL endpoint at **`/graphql`** plus a small REST router under **`/api/*`**. There is no separate "internal" GraphQL endpoint — agent callbacks (`callback`, `reportPodStatuses`, `reportDeploymentStatuses`) and read-only operations live on the same `Mutation` / `Query` types as the user-facing operations.

The GraphQL schema is defined with [Strawberry GraphQL](https://strawberry.rocks/) and exported to `schema.graphql` at the repo root via:

```bash
uv run styrmin export graphql-schema schema.graphql
```

`schema.graphql` is the authoritative inventory of types, fields, queries, mutations, scalars, and enums. This document is a higher-level guide; when in doubt, read the schema file.

### Field naming

Strawberry's default `auto_camel_case` is in effect — Python `snake_case` field names on `@strawberry.type` classes are exposed as `camelCase` in the GraphQL schema. So `created_on` becomes `createdOn`, `application_version` becomes `applicationVersion`, etc.

## API Architecture

```text
styrmin_backend/api/
├── __init__.py           # init_graphql_router, init_rest_router, schema construction
├── dependency.py         # Context injection (UnitOfWork) — see get_context
├── errors.py             # StructuredErrorExtension middleware
├── resolvers.py          # Shared resolver helpers
├── scalars.py            # Custom scalars (JSON, ...)
├── rest/                 # REST endpoints (legacy + utility routes)
├── schema/
│   ├── __init__.py
│   ├── query.py          # The single Query type
│   └── mutation.py       # The single Mutation type
└── definitions/          # GraphQL type definitions, one subpackage per domain
    ├── action/
    ├── application_driver/
    ├── backup/
    ├── backup_storage_location/
    ├── callback/
    ├── cluster/
    ├── context/
    ├── deployment/
    ├── deployment_status/
    ├── deployment_timeline/
    ├── environment/
    ├── helm_chart/
    ├── pod_status/
    ├── service/
    └── task/
```

## Queries

The full list, in the order they appear on `type Query` in `schema.graphql`:

| Query | Arguments | Return |
|-------|-----------|--------|
| `clusters` | — | `[Cluster!]!` |
| `cluster` | `clusterId?, clusterName?` | `Cluster` |
| `backupStorageLocations` | — | `[BackupStorageLocation!]!` |
| `backupStorageLocation` | `backupStorageLocationId` | `BackupStorageLocation` |
| `task` | `taskId` | `Task` |
| `step` | `stepId` | `Step` (any signed-in user; `NOT_FOUND` for an unknown id; used to load one step's `output`) |
| `tasks` | — | `[Task!]!` |
| `environments` | — | `[Environment!]!` |
| `environment` | `environmentId?, environmentName?, clusterId?, clusterName?` | `Environment` |
| `deployment` | `deploymentId?` **or** `(name?, environmentId?)` | `Deployment` (two argument shapes, never mixed — see below) |
| `backup` | `backupId` | `Backup` |
| `backups` | exactly one of `deploymentId?` or `instanceId?`, plus `status?` | `[Backup!]!` (`deploymentId` lists the deployment's backup history; both or neither give `VALIDATION_ERROR`; see [ADR-062](../../adr/0062-backup-history-derived-through-instances.md)) <!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 --> |
| `restore` | `restoreId` | `Restore` |
| `restores` | `backupId, status?` | `[Restore!]!` |
| `environmentBackup` | `environmentBackupId` | `EnvironmentBackup` (`NOT_FOUND` for an unknown id) <!-- Extracted from specs/001-env-backup-restore on 2026-10-13 --> |
| `environmentBackups` | `environmentId` | `[EnvironmentBackup!]!` (newest first) |
| `environmentRestore` | `environmentRestoreId` | `EnvironmentRestore` (`NOT_FOUND` for an unknown id) |
| `environmentRestores` | `environmentBackupId` | `[EnvironmentRestore!]!` (newest first) |
| `environmentClone` | `environmentCloneId` | `EnvironmentClone!` (`NOT_FOUND` for an unknown id) <!-- Extracted from specs/010-environment-clone on 2026-10-13 --> |
| `environmentClones` | `environmentId` | `[EnvironmentClone!]!` (the clones made from that source environment, newest first) |
| `backupSchedule` | `scheduleId` | `BackupSchedule` |
| `backupSchedules` | `deploymentId` | `[BackupSchedule!]!` |
| `applicationDrivers` | — | `[ApplicationDriver!]!` |
| `applicationDriver` | `applicationDriverId` | `ApplicationDriver` |
| `environmentServices` | `environmentId` | `[DeployedService!]!` |
| `deploymentServices` | `deploymentId` | `[DeployedService!]!` |
| `deploymentTimeline` | `deploymentId` | `[DeploymentTimelineEntry!]!` |
| `podStatuses` | `deploymentId?, environmentId?, clusterId?` | `[PodStatus!]!` |
| `ok` | — | `Boolean!` (health probe) |

The environment backup, environment restore and environment clone queries require no role: any signed-in user can read them, as for `environmentBackup`, which already returns the captured environment config ([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) §6).

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

<!-- Extracted from specs/009-deployments-apply on 2026-08-04 -->

### `deployment` — two argument shapes

`deployment` accepts either a surrogate ID or the composite natural key, never
both:

```graphql
deployment(deploymentId: UUID = null, name: String = null, environmentId: UUID = null): Deployment
```

- `deployment(deploymentId:)` — the original lookup.
- `deployment(name:, environmentId:)` — natural-key lookup, added for declarative
  apply's create-or-update decision. `(name, environment_id)` is already unique
  per [ADR-011](../../adr/0011-scoped-tombstone-aware-name-uniqueness.md), so this
  is one indexed read.

All three arguments are nullable because Strawberry cannot express "exactly one
of these argument groups". The resolver enforces it at **runtime**: exactly one
of `(deploymentId)` or `(name AND environmentId)` must be supplied, else a
`ServiceError` naming both valid shapes. Passing `name` without `environmentId`
type-checks and fails at execution.

Both shapes return `null` on not-found rather than raising, and both apply the
same `internal=True` guard — a lookup landing on a platform-internal deployment
returns `null`. `Environment.deployments` leaves internal deployments out too,
unless the caller passes `includeInternal: true` (the agent status reporter
does, see `dev/knowledge/agent/overview.md`). Resolution itself lives in
`services/deployment.py::get_deployment_by_name`.

See [ADR-050](../../adr/0050-composite-natural-key-deployment-lookup.md) for why this
departs from the [ADR-031](../../adr/0031-dual-identifier-resolution-service-layer.md)
`<resource>Id` / `<resource>Name` pattern (a deployment's natural key is
composite, so a bare `deploymentName` would not be resolvable).

## Mutations

Defined on `type Mutation`:

| Mutation | Arguments | Return |
|----------|-----------|--------|
| `createCluster` | `name="default", config?` | `Cluster` |
| `deleteCluster` | `clusterId?, clusterName?` | `String` |
| `updateCluster` | `input: UpdateClusterInput!, clusterId?, clusterName?, dryRun = false` | `UpdateClusterResult!` (`ADMIN`; typed full-replacement input; triggers the cluster config fan-out and returns the cluster with the deployments redeployed, waiting for a dedicated ingress controller, skipped for a restore and failed to start; `dryRun` saves nothing and returns the plan — see [ADR-066](../../adr/0066-cluster-config-fanout.md)) |
| `createEnvironment` | `name, clusterId?, clusterName?, config?` | `Environment` |
| `updateEnvironment` | `environmentId, input: UpdateEnvironmentInput!` | `Environment` (typed full-replacement input; triggers per-deployment redeploy fanout and creates or redeploys the environment's dedicated ingress controller for the caller — see [ADR-012](../adr/0012-environment-config-fanout.md) and [ADR-066](../adr/0066-cluster-config-fanout.md)) |
| `deleteEnvironment` | `environmentId?, environmentName?, clusterId?, clusterName?` | `String` |
| `createBackupStorageLocation` | `name, endpoint, bucket, region, accessKeyId, secretAccessKey` | `BackupStorageLocation` |
| `updateBackupStorageLocation` | `backupStorageLocationId, name?, endpoint?, bucket?, region?, accessKeyId?, secretAccessKey?` | `BackupStorageLocation` |
| `deleteBackupStorageLocation` | `backupStorageLocationId` | `String` |
| `assignBackupStorageLocation` | `environmentId, backupStorageLocationId` | `Environment` |
| `unassignBackupStorageLocation` | `environmentId` | `Environment` |
| `loadLocalApplicationDriverVersion` | `path` | `ApplicationDriverVersion` (`ADMIN`; identity-aware per spec 013: new content → new row alongside existing; same content → the existing row, after writing `icon`, `description` and `links` when they differ from the file (spec 020); `loadWarnings` lists the `spec.info` values the load left out; registers the driver's actions in Prefect, keyed by the path, also when it returns the existing row, where it registers only the actions that have no registered flow; refuses a `path` that contains `{` or `}` when the driver declares actions (spec 029, [ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md))) <!-- Extracted from specs/020-driver-info-display on 2026-10-13 --> |
| `loadRemoteApplicationDriverVersion` | `repositoryUrl, branch, driverDirectory?` | `ApplicationDriverVersion` (`ADMIN`; identity-aware: keyed on resolved git commit SHA and driver directory; same reload and `loadWarnings` behaviour as the local load). `driverDirectory` is the folder of the repository that holds the driver, relative to the root; `null`, `""` and `"."` load from the root. The value is stored in one form (`./drivers/a/` becomes `drivers/a`), and the computed `ApplicationDriverVersion.driverDirectory` field returns it (`null` for the root and for local driver versions; `sourcePath` holds the same value for git and the server folder for local). An absolute path, a `..` segment, a backslash, `{` or `}`, a control character or a stored value over 255 characters is refused before the clone; a driver directory that leads outside the clone, a driver file that leads outside the driver directory, or one that cannot be followed (a symlink loop) is refused after it; all with `VALIDATION_ERROR`. The SDK sends this argument only with a driver directory (`load_version_with_driver_directory.graphql`), so loads from the root keep working against older servers (spec 028, [ADR-079](../../adr/0079-driver-actions-import-only-from-their-driver-directory.md)) |
| `deploy` | `driver, environmentId?, environmentName?, clusterId?, clusterName?, version?, name?, config?, parameters?, serviceNameOverrides?` | `Task` |
| `updateDeployment` | `deploymentId, input: UpdateDeploymentInput!` | `Task` — **`null` on a no-op** (see below) |
| `deleteDeployment` | `deploymentId` | `Task!` (born-complete `DELETE_DEPLOYMENT` audit record; patches `spec.deletionRequested` on the CR — operator drives teardown asynchronously) |
| `createBackup` | `instanceId, name?` | `Backup` |
| `createEnvironmentBackup` | `environmentId, name?` | `EnvironmentBackup!` (`READ_WRITE`; returns once the constituent backups are created and dispatched; `ALREADY_IN_PROGRESS` while another environment-level operation holds the environment) <!-- Extracted from specs/001-env-backup-restore on 2026-10-13 --> |
| `restoreEnvironmentBackup` | `environmentBackupId` | `EnvironmentRestore!` (`ADMIN`, because the restore reverts the environment config as `updateEnvironment` does; `OPERATION_DENIED` unless the derived status is `COMPLETED` or `PARTIAL`) |
| `cloneEnvironment` | `name, environmentId?, environmentName?, clusterId?, clusterName?, deploymentIds?, configOverride?: UpdateEnvironmentInput, clearConfigFields?` | `EnvironmentClone!` (`ADMIN`; returns the clone record at once, and the clone flow builds the new environment; see [backup-restore.md](backup-restore.md#environment-clone)) <!-- Extracted from specs/010-environment-clone on 2026-10-13 --> |
| `deleteEnvironmentBackup` | `environmentBackupId` | `Boolean!` (`READ_WRITE`; cascades through the constituent backups and the environment restores; `IN_USE` while a clone is still capturing into the snapshot) <!-- Extracted from specs/001-env-backup-restore on 2026-10-13 --> |
| `deleteBackup` | `backupId` | `String` |
| `createRestore` | `backupId` | `Restore` (the caller names only the backup: Styrmin derives the namespace, `styrmin-<deployment id>`, and the target instance, the deployment's active instance or none, from the deployment the backup was taken of, and records them on the `Restore` as `targetNamespace` and `targetInstanceId`, which stay readable fields. The `targetNamespace` and `targetInstanceId` arguments were removed in [#532](https://github.com/opsmill/styrmin/issues/532); see [backup-restore.md](backup-restore.md#restore-operations-servicesbackupservicepy)) |
| `createBackupSchedule` | `deploymentId, name, cronExpression, retentionCount=10, enabled=true` | `BackupSchedule` |
| `updateBackupSchedule` | `scheduleId, name?, cronExpression?, retentionCount?, enabled?` | `BackupSchedule` |
| `deleteBackupSchedule` | `scheduleId` | `String` |
| `callback` | `taskId, stateName, stateMessage?, stateType` | `CallbackResponse!` (Prefect → server) |
| `recordStep` | `input: RecordStepInput!` | `Step!` (Styrmin's flows and driver actions → server, with the action token; see [Step](#step)) |
| `stopComponents` | `deploymentId, components, startedByStepId?` | `Task` |
| `startComponents` | `deploymentId, components, startedByStepId?` | `Task` |
| `runJob` | `deploymentId, commands, env, image` | `Task` |
| `updateDeploymentVersion` | `deploymentId, version, parameters?, driverVersionId?, startedByStepId?, input?: UpdateDeploymentInput` | `Task` — **`null` on a no-op** (see below). `input` is written with the version and validated against the target driver version (ADR-065) |
| `reportPodStatuses` | `reports: [DeploymentPodStatusReport!]!` | `ReportPodStatusesResponse!` (agent → server) |
| `reportDeploymentStatuses` | `reports: [DeploymentStatusReportInput!]!` | `ReportDeploymentStatusesResponse!` (agent → server) |

<!-- Extracted from specs/014-deployment-update-noop on 2026-08-04 -->

### `null` Task means "no work needed", not "error"

`updateDeployment` and `updateDeploymentVersion` return **`null` when the
submitted state resolves to what is already deployed**. Both fields were always
nullable, so this is a behaviour contract rather than a schema change — but it
overloads `null`, which previously only appeared on error paths. **A client that
treats a null task as failure is wrong.**

The service regenerates a candidate instance and runs `Comparator.compare()`
*before* persisting or dispatching anything. An empty diff means: zero
`ApplicationInstance` rows, zero `Task` rows, no status transition, no timeline
entry, no reconcile. Service signatures are `-> Task | None`.

The comparison is against the **fully-resolved** instance, so a config payload
that is byte-identical but whose inherited environment or cluster config moved is
correctly detected as a change.

Two consequences worth knowing:

- Submitting no editable fields at all is a no-op returning `null`. The former
  `InvalidContextError("At least one of config, parameters, name, or
  serviceNameOverrides must be provided")` guard is gone. Validation of
  *malformed* input still fires before instance generation.
- `Comparator` excludes `status` from the diff, so **resubmitting the same config
  will not retry a `FAILED` deployment** — it is a no-op. Recovery needs an
  explicit redeploy path.

On `updateDeploymentVersion` with `input`, a change that the instance does not carry, such as a
rename at the current version, is still written without a task, as `updateDeployment` writes it
in its first phase, and the call returns `null`. The task is `UPGRADE_INSTANCE` (status
`DEPLOYING`) only when the application version or the driver binding changes; otherwise it is
`UPDATE_INSTANCE` (status `PENDING`). Deployed services are recreated only when the binding or a
resolved service name changes. Every check, including the service name overrides, runs before
`_ensure_ingress_controller`, so a rejected call starts no flow run.

Clients map the null to "unchanged": the SDK returns
`ApplyOutcome(action="unchanged")`. See
[ADR-054](../../adr/0054-backend-authoritative-noop-detection.md), and
[reconciliation.md](reconciliation.md) for the guard's placement inside the
two-UoW `update_deployment` flow.

The agent callbacks (`callback`, `reportPodStatuses`, `reportDeploymentStatuses`) are documented in [`../agent/overview.md`](../agent/overview.md) and [`reconciliation.md`](reconciliation.md). All three are still on the unauthenticated allow-list (`api/auth/allowlist.py`, tracked by [#396](https://github.com/opsmill/styrmin/issues/396)). Since spec 019, `reportDeploymentStatuses` also moves the operator-phase steps of the reported task (`services/steps/operator_history.py`), so a caller who can reach the API can change those steps as well as `Deployment.status`.

`startedByStepId` on `stopComponents`, `startComponents` and `updateDeploymentVersion` is optional. Styrmin's driver action primitives set it to the hook step that runs the action (`STYRMIN_STEP_ID`); the server stores it in `Task.started_by_step_id`. The argument adds the new task to the hook step's started tasks and changes the result of the hook's task, so the server accepts it only from the built-in `styrmin-actions` user: the three mutations carry `PermissionExtension([RequiresRole(Role.READ_WRITE), StartedByStepRequiresActionsServiceAccount()])`, and every other user who sends the argument, admins included, gets `FORBIDDEN`. A call without the argument needs only `READ_WRITE`. The step must also be a step of a task of the same deployment. `check_starting_step` (`services/steps/reads.py`) checks this right after the service loads the deployment, before it changes anything and before the no-op return of `updateDeploymentVersion`: an id that names no step raises `NOT_FOUND` (`StepNotFoundError`), and a step of another deployment's task, of a backup or of a restore raises `VALIDATION_ERROR` (`InvalidStartingStepError`). See [hooks-and-actions.md](hooks-and-actions.md#tasks-started-by-a-hook-step).

## Context Injection

The API uses dependency injection to provide a `UnitOfWork` to every resolver:

```python
# api/dependency.py
async def get_context(
    uow: SqlModelUnitOfWork = Depends(get_unit_of_work_dependency),
) -> dict[str, SqlModelUnitOfWork]:
    return {"uow": uow}
```

Every resolver receives the `UnitOfWork` via `info.context["uow"]`.

## Response Patterns

Mutations return the resource type directly (nullable) and let service-layer exceptions propagate. The `StructuredErrorExtension` middleware in `api/errors.py` shapes the error envelope; see [Error envelope](#error-envelope) below for the per-category contract.

### Error envelope

`StructuredErrorExtension` classifies every GraphQL error into one of three categories based on the `original_error` attached to the `GraphQLError` (graphql-core sets this when the error wraps a Python exception). The detection rule is *what raised it*, not *where* it was raised.

| Category | Triggered when `original_error` is… | Client-facing `message` | `extensions.code` | Extra `extensions` | Log level |
|----------|-------------------------------------|-------------------------|-------------------|--------------------|-----------|
| Service error | a `ServiceError` subclass | `str(exc)` (the exception's own message) | `exc.error_code` (e.g. `NOT_FOUND`, `ALREADY_EXISTS`, `DEPLOYMENT_RESTORING`) | merged from `exc.error_metadata` | `warning` |
| Request validation | `None` or another `GraphQLError` (parse / validate / variable coercion produced by graphql-core itself) | preserved verbatim from graphql-core | `VALIDATION_ERROR` (set only if not already present) | preserved if graphql-core attached any | `info` |
| Unexpected | any other Python exception | masked as `"An internal error occurred"` | `INTERNAL_ERROR` | none | `error` (with `exc_info`) |

The "request validation" branch is what surfaces messages like `Variable '$status' got invalid value 'NOT_A_REAL_STATUS'; Value 'NOT_A_REAL_STATUS' does not exist in 'BackupStatus' enum.` — a resolver that explicitly raises a `GraphQLError` will also flow through this branch (intentional: explicit `GraphQLError` is a deliberate choice to expose). Any other resolver-raised exception is masked.

`deleteDeployment` deserves a note: a delete on a tombstoned deployment surfaces `NOT_FOUND` (intentionally conflated with unknown id so automation can treat both identically as "already gone"); a delete during a restore raises the typed `DEPLOYMENT_RESTORING` so callers can specifically recover. A repeat delete on a deployment that's already `DELETING` returns the existing in-flight `DELETE_DEPLOYMENT` task without re-issuing the cluster patch (idempotent retry). A deployment without a `StyrminDeployment`, such as one whose create failed before it wrote the CR, is deleted like any other: the mutation returns the `DELETE_DEPLOYMENT` task and the deployment reaches `DELETED` on the next status report. While such a deployment is `PENDING` or `DEPLOYING`, the delete is refused with `ALREADY_IN_PROGRESS`, because the flow of the change can still write the CR (see [services.md](services.md), "Deployment Lifecycle").

`deleteCluster` never cascades: a cluster that still has environments is refused with the typed `IN_USE` code, the same one `deleteBackupStorageLocation` uses, and lists them in `extensions.environment_names`. Without the check, SQLAlchemy would null out the `NOT NULL` `environment.cluster_id` foreign key and the resulting `IntegrityError` would surface as `INTERNAL_ERROR`. `deleteEnvironment` is the opposite: it deletes the environment's snapshots and deployments with it (`delete_environment` in `services/environments.py`).

`deploy` and `updateDeployment` enforce **per-environment** name uniqueness: an `ALREADY_EXISTS` error fires when an active deployment with the chosen name already lives in the target environment. Names are reusable across environments, and a tombstoned deployment in the same environment does **not** block reuse — operators who delete `ansible` can immediately deploy a new `ansible` in the same env. The DB-side gate is a partial unique index on `(environment_id, name) WHERE deleted_at IS NULL` (see [`data-models.md`](data-models.md) → Deployment).

```python
@strawberry.mutation
async def create_cluster(
    self, info: strawberry.Info, name: str = "default"
) -> Cluster | None:
    uow = info.context["uow"]
    cluster = await create_cluster_service(uow=uow, name=name)
    return Cluster.from_instance(cluster)
```

On the client side, errors arrive as standard GraphQL errors with `extensions.code` for programmatic handling. The Python SDK raises a `StyrminAPIError` subclass chosen by the `extensions.code` of the first error (`BaseResource._check_graphql_errors` in `python_sdk/src/styrmin_sdk/resources/_base.py`). The exception gives the code as `typename` and all the extensions of that error as `extensions`, so the `error_metadata` of a `ServiceError` reaches SDK callers. See [`../guides/graphql-propagation-tests.md`](../guides/graphql-propagation-tests.md) for the per-field test pattern.

<!-- Extracted from specs/011-env-config-input-hardening on 2026-05-10 -->

#### Notable typed error codes

| Code | Source | Surface |
|------|--------|---------|
| `INVALID_ENV_VAR_VALUE` | `validate_env_var_value` rejecting a non-string value at the validator entry point (spec 011 / US3) | Reachable only on the JSON-config write path through `deploy()` (the env-var write paths through `updateDeployment()` and `updateEnvironment()` are now typed — `EnvVarInput.value: String!` — and reject non-string values at the GraphQL wire boundary before the validator runs). `error_metadata` carries `name`, `value_type`, and (when known) `scope`. |

The validator type-checks every env-var value against `isinstance(value, str)` *before* any encoding or size computation. Non-string inputs surface as a typed `INVALID_ENV_VAR_VALUE` rather than crashing the resolver with a generic `AttributeError` from a downstream `.encode("utf-8")` call. See [`adr-014`](../../adr/0014-schema-walking-input-propagation-tests.md) for the matching schema-walking input-completeness test pattern that prevents the upstream "missing field" class of bugs.

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

## Admin user/group surface

Issue #179 shipped the auth foundation (login/logout/`currentUser`/`changePassword`, default-deny + `RequiresRole`). Feature 011 builds the admin CRUD layer on top of it. All surface below is admin-gated (`PermissionExtension([RequiresRole(Role.ADMIN)])`); none of it is on the public allow-list.

### Mutations

| Mutation | Arguments | Return | Notes |
|----------|-----------|--------|-------|
| `createUser` | `input: CreateUserInput!` | `User` | Username is server-side `.casefold()`-canonicalized. Duplicate → `DUPLICATE_USERNAME`. |
| `updateUser` | `userId: UUID!, input: UpdateUserInput!` | `User` | Partial update; **no `username` field** (immutable post-create). `groupIds: [UUID!]` replaces the user's group set (see "Set-semantics" below). Deactivating (`active=false`) invalidates **all** of the target's sessions in the same transaction. |
| `resetUserPassword` | `userId: UUID!, newPassword: String!` | `User` | Admin sets another user's password without knowing the old one. Invalidates **all** of the target's sessions in the same transaction. |
| `deleteUser` | `userId: UUID!` | `String` | Hard-delete only when no FK references exist (deployments created by the user, etc.). If references exist → `USER_HAS_REFERENCES` and the admin must use `updateUser(setActive:false)` to soft-deactivate. Sessions and memberships cascade. |
| `createGroup` | `input: CreateGroupInput!` | `Group` | |
| `updateGroup` | `groupId: UUID!, input: UpdateGroupInput!` | `Group` | `memberIds: [UUID!]` replaces the group's member set. Renaming honours unique-name constraint. |
| `deleteGroup` | `groupId: UUID!` | `String` | Membership rows cascade. |

### Queries

| Query | Arguments | Return |
|-------|-----------|--------|
| `users` | `active: Boolean?, role: Role?, search: String?` | `[User!]!` |
| `groups` | `search: String?` | `[Group!]!` |
| `currentUser` | — | `User` (shipped in #179, public — kept here for completeness of the admin UI's auth surface) |

The `users` resolver uses `selectinload(User.groups)` so `User.groups` populates in a single follow-up query rather than per-row (see [`services.md` → Authorization helpers](services.md)). `users` and `groups` filters are server-side; the admin UI paginates the filtered list client-side (cursor pagination is deferred).

### Deployment attribution

`Deployment` exposes two attribution fields:

- `createdBy: User` — full user shape, admin-gated by the existing `_admin_only()` extension from #179.
- `createdByUsername: String` — username-only, **not** admin-gated. Added in 011 so drivers and the `UiScenarioDriver` can assert attribution without admin rights. A dedicated scalar field is cleaner than weakening the `User`-type gating story.

### Set-semantics for membership replacement

`updateUser.groupIds` and `updateGroup.memberIds` are nullable lists with three-state semantics:

| Wire value | Meaning |
|------------|---------|
| Omitted / `null` | Leave the existing set unchanged |
| `[]` | Clear all memberships |
| `[id, id, ...]` | Replace the set with exactly these ids |

The resolver diffs against the existing set and issues only the minimum `INSERT`/`DELETE` rows (see `auth/membership` in [`services.md`](services.md)). A no-change update produces zero statements.

`UpdateUserInput` and `UpdateGroupInput` apply the same "omitted = no change, `null` = clear, value = apply" semantics to every scalar field. `UpdateUserInput` deliberately has **no** `username` field — usernames are immutable; a client sending one gets a Strawberry schema error.

### Structured error codes

Admin mutations surface the following typed codes via `extensions.code`:

| Code | Source | Surface |
|------|--------|---------|
| `LAST_ADMIN` | `LastAdminError` | Any operation that would leave zero active admins — deactivate / delete / demote the only admin, remove the only admin from the only admin-conferring group, or any of those acting on self. |
| `DUPLICATE_USERNAME` | `DuplicateUsernameError` | `createUser` on unique-constraint violation (case-insensitive after server-side casefold). |
| `USER_HAS_REFERENCES` | `UserHasReferencesError` | `deleteUser` when FK references exist. The admin should fall back to `updateUser(setActive:false)`. |
| `USER_NOT_FOUND` | `UserNotFoundError` | `updateUser` / `resetUserPassword` / `deleteUser` with an unknown id. |
| `GROUP_NOT_FOUND` | `GroupNotFoundError` | Any mutation referencing an unknown `group_id` / `member_id`. |
| `DUPLICATE_GROUP_NAME` | `DuplicateGroupNameError` | `createGroup` / `updateGroup` rename hitting the unique-name constraint. |
| `WEAK_PASSWORD` | `WeakPasswordError` | Password rejected by the argon2 length/strength policy. |

These ride the existing `StructuredErrorExtension` envelope; clients consume them via `extensions.code` exactly like every other typed error.

## GraphQL Types

Below is a sample of the most-frequently-touched types; consult `schema.graphql` for the full set.

### Cluster

```graphql
type Cluster {
  id: UUID!
  name: String!
  config: JSON
  capabilities: JSON
  environments: [Environment!]!
  createdOn: DateTime
  updatedOn: DateTime
}
```

### Environment

```graphql
type Environment {
  id: UUID!
  name: String!
  config: JSON
  capabilities: JSON
  clusterId: UUID!
  cluster: Cluster!
  deployments: [Deployment!]!
  backupStorageLocation: BackupStorageLocation
  clonedFrom: EnvironmentClone   # The clone that created this environment; null otherwise
}
```

`clonedFrom` points from a cloned environment back to the clone that created it, because `environmentClones` lists clones by source environment. It still resolves after the source environment is deleted when the clone record is kept; see [backup-restore.md](backup-restore.md#environment-clone) for which clone records are kept.

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

### Deployment

```graphql
type Deployment {
  id: UUID!
  name: String!
  status: String!                # See "Status strings" below
  config: JSON!
  parameters: JSON!
  applicationVersion: String!
  applicationDriverVersionId: UUID!
  environmentId: UUID!
  internal: Boolean!             # True for system deployments (e.g. ingress controller)
  applicationInstance: ApplicationInstance
  components: [Component!]!
  environment: Environment!
  applicationDriverVersion: ApplicationDriverVersion!
  deployedServices: [DeployedService!]!
  podStatuses: [PodStatus!]!
  resolvedScheduling: [ResolvedComponentScheduling!]!
  envVars: [EnvVar!]!                          # see specs/008-deployment-env-vars
  componentEnvVars: [ComponentEnvVars!]!       # per-component effective dicts (incl. orphan flag)
  componentReplicas: [ComponentReplicas!]!     # replica count and its source per component (023)
  crdStatus: DeploymentStatusType
}
```

`Environment` gains a parallel `envVars: [EnvVar!]!`. Operator-set env vars travel through the typed `input: UpdateDeploymentInput!` argument on `updateDeployment()` (`envVars: [EnvVarInput!]` per scope) and through the typed `input: UpdateEnvironmentInput!` on `updateEnvironment()`. The legacy `config: JSON` write path persists on `deploy()` (Pydantic-validated against `DeploymentConfig`) until the analogous deploy-side migration ships. See "Environment-config update + fanout" below for the environment-scope contract; see [`specs/011-typed-deployment-input/spec.md`](../../../specs/011-typed-deployment-input/spec.md) for the deployment-scope contract. Driver-side documentation (`ApplicationDriverVersion.envVars`), orphan tracking on per-component blocks (`ComponentEnvVars.isOrphaned = true`), and chart-vs-user collision warnings (`DeploymentTimelineEntry.envVarCollisions`) are scoped for follow-up user stories (US4/US5/US7) and will be added as those ship.

#### Component container read fields

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

Env vars reach pods by post-render injection into each component's declared **component container** ([ADR-057](../../adr/0057-post-render-component-overrides.md)). Three additive fields expose it:

```graphql
type Component {                 # Deployment.components
  container: String              # from the deployment's Component.config["container"]
}
type ComponentConfig {           # ApplicationDriverVersion.componentConfigs
  container: String              # from ComponentConfig.config["container"]
}
type ComponentEnvVars {          # Deployment.componentEnvVars
  isApplicable: Boolean!         # not isOrphaned and the component declares a container
}
```

`container` is `null` when the driver declares no component container. `Component.container` follows the deployment's pinned driver version, because component rows are recreated on a driver-version switch. `isApplicable` is computed in the resolver from that driver version's component configs; it is not stored and not part of the instance context. `isOrphaned` keeps its meaning (the driver no longer declares the component), so a block stranded by an upgrade that drops the container reads `isOrphaned: false, isApplicable: false`: kept, returned, never injected.

#### Image override fields

<!-- Extracted from specs/018-component-image-overrides on 2026-10-04 -->

Image overrides ride the same component container ([ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md)):

```graphql
input ComponentConfigInput {     # UpdateDeploymentInput.components, deploy config
  image: String                  # null/omitted clears it (full replacement)
}
type ComponentImageOverride {    # Deployment.componentImageOverrides
  component: String!
  reference: String!             # stored, {{ app.version }} tokens included
  resolvedReference: String!     # tokens replaced by Deployment.applicationVersion
  isOrphaned: Boolean!
  isApplicable: Boolean!         # not isOrphaned and the component declares a container
}
```

Writes raise `UNKNOWN_COMPONENT_IMAGE_OVERRIDE`, then `INVALID_IMAGE_REFERENCE` (metadata
`component_name`, `reference`, `reason`, `application_version`), then
`COMPONENT_CONTAINER_NOT_DECLARED` with `override: "image"`. On `updateDeployment`, entries equal
to the stored reference skip the `INVALID_IMAGE_REFERENCE` check. `updateDeploymentVersion` raises
`INVALID_IMAGE_REFERENCE` before dispatching a task when an override that applies in the
target driver version is invalid at the target application version; with `input`, it checks the
submitted config instead of the stored one, against the target driver version. `COMPONENT_CONTAINER_NOT_FOUND`
never reaches `extensions.code`: the operator writes its message to the StyrminDeployment status,
read back as `Deployment.crdStatus.message`.

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

`componentImageOverrides` returns one entry per component with a stored `image`: live components
sorted by name, then orphans sorted by name (the `Deployment.components` relationship has no
order, so the resolver sorts). When `applicationVersion` is empty, `resolvedReference` is the
stored reference unchanged, so a remaining `{{ app.version }}` token means "not resolved".

#### Container override fields

<!-- Extracted from specs/022-post-render-container-overrides on 2026-10-14 -->

Container `command` and `args` overrides ride the same component container
([ADR-069](../../adr/0069-container-command-args-by-post-render.md)):

```graphql
input ComponentConfigInput {     # UpdateDeploymentInput.components, deploy config
  command: [String!]             # null/omitted clears it (full replacement); [] is rejected
  args: [String!]
}
type ComponentContainerOverrides {   # Deployment.componentContainerOverrides
  component: String!
  command: [String!]             # null when not set: the chart's own value applies
  args: [String!]
  isOrphaned: Boolean!
  isApplicable: Boolean!         # not isOrphaned and the component declares a container
}
```

`isApplicable` is computed in the resolver with `override_applies`
(`services/component_container/overrides.py`), from the component containers of the deployment's
`Component` rows. `ComponentEnvVars.isApplicable` and `ComponentImageOverride.isApplicable` call the
same function. Applicable overrides are applied by the post-render merge patch; the others are
returned but not applied. Live components with neither slot set are left out; orphaned blocks are
always returned.

Writes raise `INVALID_CONTAINER_COMMAND`, `INVALID_CONTAINER_ARGS`,
`CONTAINER_OVERRIDE_SIZE_LIMIT_EXCEEDED` or `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE` first, then
`COMPONENT_CONTAINER_NOT_DECLARED` with `override: "command"` or `override: "args"` when a value is
added or changed on a component without a component container. A removal (`null` or an omitted
key) and the same list sent again pass. `COMPONENT_CONTAINER_NOT_FOUND` also fires when `command`
or `args` is the only override on a component; as for images, it reaches
`Deployment.crdStatus.message`, not `extensions.code`.

Spec 022 removed `ApplicationDriverVersion.containerOverrides` and the `DriverContainerOverrideDoc`
type, together with `spec.container_overrides`. A query that selects `containerOverrides` fails
validation, and the SDK no longer has `get_driver_container_override_docs`. The apply check in
`styrminctl deployments apply` (`get_deployment_override_applicability.graphql`) reads
`isApplicable` from `componentEnvVars`, `componentImageOverrides` and
`componentContainerOverrides`, so it warns about a submitted `command` or `args` that does not
apply.

#### Replica override fields

<!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

A replica override patches `spec.replicas` of the component's `Deployment` and `StatefulSet`
workloads, not the component container, so it needs no component container
([ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md)):

```graphql
input ComponentConfigInput {     # UpdateDeploymentInput.components, deploy config
  replicas: Int                  # 1 to 2147483647; null/omitted clears it (full replacement)
}
enum ReplicaSource { OVERRIDE DRIVER_DEFAULT CHART }
type ComponentReplicas {         # Deployment.componentReplicas
  component: String!
  count: Int                     # null when source is CHART or the row is orphaned
  source: ReplicaSource!         # CHART for an orphaned row
  override: Int                  # the stored override, applied or not
  singleton: Boolean!            # false for an orphaned row
  isOrphaned: Boolean!
  isApplicable: Boolean!         # false only when a stored override is not applied
}
type ComponentConfig {           # ApplicationDriverVersion.componentConfigs
  replicas: Int                  # null when not declared or when the stored value is invalid
  singleton: Boolean!            # false when not declared or when the stored value is invalid
}
```

`componentReplicas` has one row per component of the deployment's `Component` rows (the bound
driver version's components) plus one row per orphaned override, sorted by component name. The
resolver reads the deployment the parent field loaded, without another database read. It parses
each stored declaration with `parse_stored_replica_declaration`, as the
`ComponentConfig.replicas` and `ComponentConfig.singleton` resolvers do, and computes
`count` and `source` with `resolve_replicas` (`services/replicas/resolver.py`), the function the
patch builder uses. `count` ignores the stopped state: a stopped component reports the count it
returns to, and `Deployment.components[].enabled` is `false`. `ReplicaSource` is a plain Strawberry
enum whose values carry descriptions.

Writes raise these errors. For each check, the first failing component in the order of the
submitted blocks is reported:

- `INVALID_REPLICA_COUNT` (metadata `component_name`, `requested_replicas` as submitted) from the
  `ComponentConfigBlock` validator. Every GraphQL write path types `replicas` as `Int`, so through
  GraphQL only a count of 0 or less reaches the validator. GraphQL type validation rejects a
  `bool`, a non-integer and a count above 2147483647 first, with the code `VALIDATION_ERROR` and
  the message `Int cannot represent ...`, not `INVALID_REPLICA_COUNT`.
  The SDK and the CLI check every `components[].replicas` with `check_replica_counts`
  (`styrmin_sdk/resources/deployments.py`) before Pydantic can convert it, so `true` and `"3"`
  fail before the request is sent. The validator still rejects a `bool`, a non-integer or an
  out-of-range value on paths that do not go through GraphQL.
- `UNKNOWN_COMPONENT_REPLICA_OVERRIDE` (metadata `component_name`, `known_components` sorted,
  `checked_against`) when an override is added or changed on a component that the driver version
  bound after the write does not declare. The stored value sent again passes.
- `SINGLETON_REPLICA_OVERRIDE` (metadata `component_name`, `requested_replicas`,
  `checked_against`) for an override above 1 on a component marked `singleton: true`, also when
  it equals the stored value. `updateDeploymentVersion` without `input` checks the stored overrides
  against the target driver version.
- `REPLICA_COUNT_ABOVE_MAXIMUM` (metadata `component_name`, `requested_replicas`,
  `max_replica_count`) when an override is added or changed to a count above the server setting
  `STYRMIN_MAX_REPLICA_COUNT` (`Settings.max_replica_count`, default 20, Helm value
  `styrmin.maxReplicaCount`). The stored value sent again passes, so lowering the setting does not
  block other writes. The check runs in `validate_replica_overrides`, not in the context model,
  because a stored context must still parse on the agent, which does not read the setting.

`COMPONENT_CONTAINER_NOT_DECLARED` never fires for `replicas`. The apply check
(`get_deployment_override_applicability.graphql`) selects `componentReplicas { component
isApplicable }`, and the SDK lists the kind `replicas` in `ApplyOutcome.inapplicable_overrides`.
The SDK exports `ComponentReplicas` and `ReplicaSource` from `styrmin_sdk.models`.

#### Retired parameters on a driver version change

<!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

When `updateDeploymentVersion` changes the driver version, a parameter that the current driver
version declares and the target does not is dropped from the merged parameter map when its value
equals the current default with the same type. Any other value raises `RETIRED_PARAMETER_VALUE`
(metadata `parameter_name`, `value`, `default`, `checked_against`; the first parameter by name when
several differ) before any task starts. The message prints the value and the default as JSON and
links `https://styrmin.pages.dev/docs/drivers/migrating-replica-parameters`. A key that neither
version declares still fails with `OPERATION_FAILED` "Unknown parameter". See
[services.md](services.md#retired-parameters-servicesparametersretiredpy).

#### Environment-config update + fanout

<!-- Extracted from specs/009-environment-update on 2026-05-08 -->

`updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!)` is the single typed write surface for environment configuration. The prior JSON-blob shape (`config: JSON`) is **gone** — the schema does not accept it post-009 and CI fails if it is reintroduced (FR-024).

`UpdateEnvironmentInput` is **full-replacement**: the input represents the complete desired environment configuration; any field omitted is persisted as its unset state. Operators editing one field MUST read the existing config first and re-supply the unchanged fields. The input mirrors `EnvironmentConfig` field-for-field (`envVars: [EnvVarInput!]`, `ipWhitelist: [String!]`, `dedicatedIngress: DedicatedIngressInput`, `scheduling: SchedulingInput`, `fqdnSuffix: String`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`).

Validation flows through the same Pydantic pipeline as `deploy()` / `updateDeployment()`, surfacing the typed error codes from 008 at the GraphQL boundary: `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, plus `ENVIRONMENT_NOT_FOUND` for unknown ids.

After persistence, the platform fans out a redeploy Task to **every live, non-internal deployment in the environment** whose active instance is not already at the new config (per-deployment no-op detection — see [ADR-012](../adr/0012-environment-config-fanout.md) §1). It creates or redeploys the environment's dedicated ingress controller, attributed to the calling administrator, and redeploys the applications that move onto it only once it is `RUNNING` with the new values ([ADR-066](../adr/0066-cluster-config-fanout.md) decisions 2 and 3, #424). The mutation returns once the env-config row is committed and Tasks are dispatched (it does NOT block on Task completion). Per-deployment Task failures are recorded on the affected deployment's timeline; they do NOT roll back the env-config row or affect peer deployments (FR-008/FR-009a).

Frontend form caveat (v1, US4): the env-vars edit form on the environment detail Configuration tab maps only the `envVars` and flat-scalar slices of `EnvironmentConfig` back into the full-replacement input. The nested `dedicatedIngress` and `scheduling` fields are NOT yet carried through the form — to prevent silent clears under full-replacement semantics, **the form blocks submission** when the persisted config carries either nested override: it renders a destructive Alert above the rows and disables the Save button, leaving the rows readable + editable so operators can copy values into their SDK call. When neither nested override is set, the form behaves normally. Operators hitting the block use the SDK or GraphiQL until a future iteration extends the form. See [ADR-012](../adr/0012-environment-config-fanout.md) §2 for details.

Observability:

- One structured log line per fanout dispatch (`env_config_fanout_dispatched ...`) records `evaluated`, `dispatched`, `skipped_noop`, `skipped_restoring`, `dispatch_failed`, `skipped_waiting_for_ingress`, `evaluation_failed` and the `ingress_controller*` counts (FR-023).
- The number of deployments per outcome is emitted via `_emit_fanout_metric` against the metric `env_config_fanout_deployments_total{environment, outcome}` (FR-023a). The metric backend is **not yet wired**: the helper at `services/environments.py::_emit_fanout_metric` currently logs the would-be metric at `info` level with a clear marker. Replacing the log call with a real counter increment is a one-line edit once a metrics client is registered. Until then, dashboards consume the structured log lines.

#### Cluster-config update + typed input

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

```graphql
updateCluster(input: UpdateClusterInput!, clusterId: UUID = null, clusterName: String = null, dryRun: Boolean! = false): UpdateClusterResult!
```

`updateCluster` requires the `ADMIN` role. It identifies the cluster by `clusterId` or `clusterName` ([ADR-031](../../adr/0031-dual-identifier-resolution-service-layer.md)), saves the new config, and starts the cluster config fan-out. The decisions are in [ADR-066](../../adr/0066-cluster-config-fanout.md); the fan-out itself is described in [services.md](services.md#cluster-config-fan-out).

`UpdateClusterInput` has 11 fields that mirror `ClusterConfig` field by field: `ingressClass`, `runtimeClass`, `fqdnSuffix`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`, `dedicatedIngress`, `standardStorage`, `fastStorage`, `dbSize` and `backupTtl`. `ClusterConfig.scheduling` has no input field, because a cluster does not take scheduling (#482). A parity test (`backend/tests/functional/graphql/test_cluster_update_propagation.py`) fails when any other `ClusterConfig` field has no input field. The input replaces the whole config: a top-level field that is `null` or omitted is removed from the stored config, except `ingressClass` and `runtimeClass`, which get the `createCluster` defaults (`traefik` and `default`). `createCluster` still takes `config: JSON`.

`UpdateClusterResult` reports what the update did, or would do in a dry run:

- `cluster`: the cluster after the update.
- `redeployed`: the deployments whose redeploy started, each with the `taskId` of its `update_instance` task.
- `waitingForIngress`: the applications that move onto a dedicated ingress controller. They are redeployed later, once the controller is `RUNNING` with the new values.
- `skippedRestoring`: the deployments not redeployed because a restore is running.
- `failedToStart`: the deployments whose redeploy could not start, and the applications whose config comparison raised an error.
- `unchangedCount`: the number of deployments already at their resolved config.
- `ingressControllers`: one `{action, failed}` entry per environment whose dedicated ingress controller the update acts on. `IngressControllerAction` is `CREATE`, `REDEPLOY` or `REMOVE`.
  - `REMOVE` is listed for every environment whose effective `dedicated_ingress` is off and that has a live controller, even when the removal happens later, from the status reporter.
  - `failed` can be true only for `CREATE` and `REDEPLOY`. A failed removal check is counted in the `cluster_config_fanout` log line and does not appear in the result.
- `failedEnvironments`: the environments whose evaluation failed; none of their deployments was redeployed.

With `dryRun: true`, the mutation runs the clone guard and the config validation, plans the fan-out as an administrator's update would (controller creation allowed), and saves nothing. It returns the stored cluster, and every `taskId` is `null`.

Errors:

- `VALIDATION_ERROR` (`AmbiguousIdentifierError`) when the call gives both `clusterId` and `clusterName`, or neither.
- `NOT_FOUND` (`ClusterNotFoundError`) for an unknown cluster.
- `VALIDATION_ERROR` (`InvalidContextError`) for an invalid config.
- `ALREADY_IN_PROGRESS` (`EnvironmentOperationInProgressError`) while an environment clone is still capturing a source environment of the cluster or still building an environment of the cluster. The message names the environment and says that nothing was saved. Environment backups and restores in progress do not block the update.

#### Deployment-config update + typed input

<!-- Extracted from specs/011-typed-deployment-input on 2026-05-16 -->

`updateDeployment(deploymentId: UUID!, input: UpdateDeploymentInput!)` is the single typed write surface for deployment configuration. The prior loose-argument shape (`name`, `config: JSON`, `parameters: JSON`, `serviceNameOverrides: [ServiceNameOverride!]`) is **gone** in the same release that ships the typed input — clean replace, no deprecation window (mirrors the 009 cutover precedent; see [ADR-012](../adr/0012-environment-config-fanout.md) §3 and [ADR-018](../adr/0018-typed-update-deployment-input.md)).

`UpdateDeploymentInput` is **full-replacement** at the top level with **one deliberate exception**: `parameters` keeps merge semantics. Omitting any other top-level field (`envVars`, `ipWhitelist`, `dedicatedIngress`, `scheduling`, `fqdnSuffix`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`, `ingressClass`, `dbSize`, `runtimeClass`, `standardStorage`, `components`, `serviceNameOverrides`, `name`) persists it as its unset state; omitting `parameters` leaves the persisted parameters dict alone. The asymmetry is documented on the GraphQL field description so introspection consumers see it without reading source. See [ADR-018](../adr/0018-typed-update-deployment-input.md) for the rationale (operators bumping one parameter value continue to work with a single-entry input; the unnamed keys survive).

Named-dict-typed config fields (`parameters`, `components`, top-level `envVars`, per-component `envVars`) travel as `list[{name, value, …}]` on the wire and are flattened to `dict` at the GraphQL-input boundary with typed duplicate detection. The flatten step raises:

- `DUPLICATE_PARAMETER_NAME` (`DuplicateParameterNameError`) — two `parameters` entries with the same `name`.
- `DUPLICATE_COMPONENT_NAME` (`DuplicateComponentNameError`) — two `components` entries with the same `name`.
- `DUPLICATE_ENV_VAR_NAME` (existing) — two env-var entries with the same `name`, with scope `"deployment"` (top-level) or `"component:<name>"` (per-component).

Detection at the flatten step is the only natural location — by the time the dict is built, duplicate keys silently collapse with last-wins semantics. Future typed inputs that mirror a Pydantic `dict[str, T]` field MUST use the same list-shape grammar; JSON-typed dict inputs are forbidden ([ADR-018](../adr/0018-typed-update-deployment-input.md)).

Explicit empty list = full clear; omitted/null field = "do not touch". `components: []` clears every per-component block; `components: [{name: "web", envVars: null}]` keeps the `web` key but collapses its inner env-vars block to its absent state (recursive nested-omission rule inherited from the shared `_convert_value` helper in `api/definitions/config/inputs.py`).

The full per-scope env-var error matrix from 008 — `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR` — surfaces at the GraphQL boundary for **both** the top-level `envVars` field and every per-component `envVars` field, with the offending name and scope in the payload. Per-component `envVars` additionally raise `COMPONENT_CONTAINER_NOT_DECLARED` (metadata `component_name`, `components_with_container`, `override: "env_vars"`; image overrides raise it with `override: "image"`, container overrides with `override: "command"` or `"args"`) when they add or change a value on a component whose driver declares no component container (017, [ADR-057](../../adr/0057-post-render-component-overrides.md)). The wire layer (`EnvVarInput.value: String!`) rejects non-string values structurally — the legacy `INVALID_ENV_VAR_VALUE` error code is no longer reachable through `updateDeployment()` (it survives only on the JSON-config write path through `deploy()`).

Submitting an empty input (`input: {}`) surfaces a `VALIDATION_ERROR` from the existing service-side "at least one of config / parameters / name / serviceNameOverrides must be provided" check — no new GraphQL-level non-empty constraint is introduced.

Shared leaf inputs (`EnvVarInput`, `SchedulingInput`, `DedicatedIngressInput`, `AffinityBlockInput`, `ResourceRequirementsInput`, the enum mirrors, …) live in `api/definitions/config/inputs.py` and are reused unchanged by `UpdateEnvironmentInput` and `UpdateDeploymentInput`. Top-level inputs and their conversion helpers (`update_environment_input_to_dict`, `update_deployment_input_to_dict`) stay co-located with their entities under `api/definitions/{environment,deployment}/inputs.py`.

`UpdateClusterInput` and `update_cluster_input_to_dict` follow the same layout in `api/definitions/cluster/inputs.py`. The cluster input added two shared leaf inputs to `api/definitions/config/inputs.py`: `StandardStorageInput` and `FastStorageInput`.

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

The frontend `deploymentConfigToInput()` helper in `frontend/src/lib/deployment-input.ts` converts the read-API config dict (with dict-shaped `envVars` and `components`) into the new list-shaped input shape; the `SchedulingConfigDialog` and any future caller submitting `UpdateDeploymentInput` go through this helper (mirrors the submit-boundary-transform discipline in [ADR-015](../adr/0015-frontend-value-transform-boundary.md)).

There is no `tasks` field on `Deployment` — query `tasks` at the root and filter by `deploymentId` if you need a deployment's task history.

### ApplicationDriverVersion: logo, description, links and load warnings

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

Four fields carry the `spec.info` values of the driver specification file:

```graphql
type ApplicationDriverVersion {
  icon: String                   # spec.info.icon; null when STYRMIN_DRIVER_SHOW_LOGOS is false
  description: String            # spec.info.description
  links: [DriverLink!]!          # spec.info.links, in file order; [] when none are stored
  loadWarnings: [String!]!       # filled only in the result of the two load mutations
}

type DriverLink {
  label: String!                 # from the `link` key of the entry
  url: String!                   # absolute http or https URL
}
```

- `icon` is read from the stored column on each request. When the server setting `driver.show_logos` is false, the resolver returns `null` and the stored URL is kept, so turning the setting back on shows the logos again without reloading the drivers (`api/definitions/application_driver/model.py`, `from_instance`).
- `links` maps the stored `{"link", "url"}` entries to `DriverLink`. The field is named `label` rather than `link`, because `DriverLink.link` would read as "the link's link" (research R6).
- `loadWarnings` is set by `loadLocalApplicationDriverVersion` and `loadRemoteApplicationDriverVersion` from the warnings the load returns. Warnings are not stored, so every other read returns an empty list, and loading the same file again returns them again. See [ADR-068](../../adr/0068-invalid-driver-info-dropped-with-load-warning.md).
- Of the SDK operations, only `load_version.graphql` and `load_local_version.graphql` select `loadWarnings`. No SDK operation selects `icon`, `description` or `links`.

The browser of each viewer loads the logo from `icon`; Styrmin never fetches it. See [ADR-067](../../adr/0067-driver-logos-loaded-by-the-viewer-browser.md).

### Task

```graphql
type Task {
  id: UUID!
  type: String!                  # Stored as TaskType enum value (see below)
  status: String!                # Stored as TaskStatus enum value (see below)
  message: String
  deploymentId: UUID
  startedByStepId: UUID          # The hook step that started this task
  createdOn: DateTime
  updatedOn: DateTime
  deployment: Deployment
  steps: [Step!]!                # By start time, pending steps last
  result: TaskResult!            # Calculated on every read, never stored
  startedBy: Task                # The task whose hook step started this task
  startedTasks: [Task!]!         # Tasks started by this task's hook steps
}
```

`type` and `status` are exposed as `String!` (not GraphQL enums), but they always carry one of the database enum values — see "Status strings" below. For a task that runs a Prefect flow, `status` follows only that flow run; a `delete_deployment` task runs no flow and is created with `status` `success`. `result` is what users view, calculated from the steps and `status` of the task and of the tasks its hook steps started, at any depth (`services/steps/results.py`; rules in [data-models.md](data-models.md#task-result) and [ADR-060](../../adr/0060-steps-and-derived-task-result.md)).

### Step

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

One unit of work inside a task, a backup or a restore. Read through `Task.steps`, `Backup.steps`, `Restore.steps` and `Query.step`.

```graphql
type Step {
  id: UUID!
  key: String!                   # Stable within the parent, e.g. "hook:upgrade:core"
  name: String!                  # What users view, e.g. "Run the upgrade hook"
  kind: StepKind!
  status: StepStatus!
  startedAt: DateTime
  endedAt: DateTime
  attemptCount: Int!
  errors: [StepError!]!          # The error of each failed attempt, oldest first
  detail: String                 # FluxCD's current reason and message, HelmRelease step only
  rolledBackAt: DateTime
  rollbackMessage: String
  output: String                 # End of a failed command's output; request for one step at a time
  outputTruncated: Boolean!
  taskId: UUID
  backupId: UUID
  restoreId: UUID
  durationSeconds: Float         # Derived: endedAt - startedAt, null until both are set
  error: String                  # Derived: the newest error
  hasOutput: Boolean!            # Derived: output is stored
  supersededBy: Task             # The later task that interrupted this step
  startedTasks: [Task!]!         # Tasks that this hook step started
  noReportSince: DateTime        # See below
}

type StepError {
  attempt: Int!
  message: String!
  occurredAt: DateTime!
}

input RecordStepInput {
  stepId: UUID                   # Address an existing step, or ...
  taskId: UUID                   # ... exactly one parent id with a key
  backupId: UUID
  restoreId: UUID
  key: String
  name: String                   # Required with STARTED when the step does not exist yet
  kind: StepKind                 # Same
  event: StepEvent!
  error: String                  # Required with FAILED
  output: String                 # Required with OUTPUT, allowed with FAILED
  outputTruncated: Boolean! = false
  occurredAt: DateTime           # The writer's clock; defaults to the server's time
}
```

`recordStep(input: RecordStepInput!): Step!` is the only way into the step recorder from outside the server. It carries `PermissionExtension([RequiresRole(Role.READ_WRITE), IsActionsServiceAccount()])`: an unauthenticated caller gets `UNAUTHENTICATED`, and every authenticated user other than the built-in `styrmin-actions` user, admins included, gets `FORBIDDEN`, so no person can change the record of what happened. No person can get a session for that user: `login` rejects its username, `resetUserPassword` and `changePassword` refuse it with `FORBIDDEN` (`ActionsServiceAccountError`), and `createUser` refuses the username the same way. Styrmin's USER flows and driver actions call it with the action token ([ADR-059](../../adr/0059-driver-action-api-tokens.md)) through the flow step reporter (`agent/steps/reporter.py`). It is not on the allow-list. A record that names no step, or no single parent with a key, or lacks a required field raises `VALIDATION_ERROR` (`InvalidStepRecordError`); an unknown step, task, backup or restore raises `NOT_FOUND`. A transition the state rules forbid (for example a late `SUCCEEDED` on a superseded step) is logged and returns the step unchanged.

`Step.noReportSince` is calculated on each read: for a running `OPERATOR_PHASE` step, it is the deployment's `DeploymentStatus.last_polled_at` (or the step's `startedAt` when there is no report) when that time is more than 60 seconds ago, and `null` otherwise (`services/steps/reads.py`). Nothing is stored for it.

**Read cost.** Most resolvers in this schema query per object, so per-field resolvers for steps, results and links would run about one query per task and step on every 10-second refresh of the deployment page. `deploymentTimeline` therefore builds a read model in `services/deployment_timeline.py` (`load_timeline_read_model`): one query for the steps of all the timeline's tasks, one for the tasks those steps started (two more per generation of started tasks outside the timeline), and one for the last agent reports of the deployments, only when a running operator-phase step needs it. Task results and `noReportSince` are calculated in memory. The GraphQL `Task` and `Step` objects carry their part of the read model in `strawberry.Private` fields (`steps_view`, `result_view`, `started_by_view`, `started_tasks_view`, `superseded_by_view`, `no_report_since_view`); their resolvers use these when set and query only for single reads such as `Query.task` and `Query.step`. `Backup.steps` and `Restore.steps` read through per-request data loaders (`api/loaders.py`): a response reads the steps of all its backups, and of all its restores, with one query each, wherever they appear (backup and restore lists, environment backup constituents, environment restores), and reads none when `steps` is not requested. The timeline query and the SDK's task query (`get_task.graphql`) do not request `output`; clients read `hasOutput` and load the output of one step with `Query.step`.

### PodStatus

```graphql
type PodStatus {
  id: UUID!
  deploymentId: UUID!
  podName: String!
  namespace: String!
  phase: PodPhase!               # GraphQL enum (PENDING/RUNNING/SUCCEEDED/FAILED/UNKNOWN)
  ready: Boolean!
  restartCount: Int!
  containerStatuses: JSON!
  nodeName: String
  componentName: String          # styrmin/component label, recorded as observed
  startedAt: DateTime
  lastPolledAt: DateTime
  createdOn: DateTime
  updatedOn: DateTime
}
```

### ResolvedComponentScheduling

<!-- Extracted from specs/001-pod-scheduling-config on 2026-05-17 -->

Per-component resolved scheduling exposed as `Deployment.resolvedScheduling: [ResolvedComponentScheduling!]!`. Carries the merged `SchedulingConfig` for each component **and** the per-field provenance map so the frontend can show "where did this value come from?" without re-running the merge.

```graphql
type ResolvedComponentScheduling {
  component: String!
  scheduling: JSON!     # serialised SchedulingConfig (affinity / tolerations / topology_spread / resources / runtime_class / inject)
  provenance: JSON!     # dotted-path → "environment" | "deployment" | "component"
}
```

`scheduling` is a typed `SchedulingConfig` blob — see [`data-models.md`](data-models.md) → SchedulingConfig for the field set. Exposing it as `JSON` (rather than as strongly-typed GraphQL types per sub-object) preserves the same loose-typed JSON wire pattern the rest of `config` uses; clients introspect by dotted path. See [ADR-029](../adr/0029-config-additions-via-baseconfigsection-no-migration.md).

`provenance` is a flat dict keyed by dotted paths into the resolved `scheduling` object — e.g.:

```json
{
  "resources.limits.cpu": "deployment",
  "resources.limits.memory": "component",
  "affinity.pod.required[0]": "environment",
  "tolerations[2]": "deployment",
  "runtime_class": "component"
}
```

For accumulated lists (affinity terms, tolerations, topology-spread constraints), provenance is recorded **per element** at the resolved list's index — drivers and the frontend index into the map by index. See [ADR-036](../adr/0036-scheduling-provenance-map.md) for the rationale.

### Deployment references in config inputs

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

A pod affinity or pod anti-affinity term (`AffinityTermInput.deploymentRef`, or `deployment_ref` in a JSON config) can name another deployment of the same environment with `DeploymentReferenceInput { deploymentId, deploymentName, components }`. Exactly one of `deploymentId` and `deploymentName` is given. The input's descriptions say that a name is replaced with the id when the config is written; no field was added or removed for this.

`Deployment.config` and `Environment.config` (`JSON!`) return the stored form, which gives `deployment_id` only, as a lowercase UUID string, and keeps `components`. A client that writes back a config as it read it sends the id, and the write starts no reconcile ([ADR-054](../../adr/0054-backend-authoritative-noop-detection.md)).

| Operation | A reference that gives a name | A reference to a missing or deleted deployment |
| --- | --- | --- |
| `deploy(config:)` | Stored as the id. The name of the deployment being created gives its new id. | Refused, nothing saved |
| `updateDeployment(input:)` | Stored as the id, resolved after the rename in the same request | Refused, nothing saved |
| `updateDeploymentVersion(input:)` | Stored as the id, resolved after the rename in the same request | Refused, nothing saved |
| `createEnvironment(config:)` | Refused: a new environment has no deployment | Refused |
| `updateEnvironment(input:)` | Stored as the id | Refused, config unchanged |
| `cloneEnvironment(configOverride:)` | Resolved against the source environment, then pointed at the counterpart | Refused |

`updateDeployment` also refuses, before it saves, a term of the environment's config or of a component's config that names a deleted deployment, because building the next instance resolves the terms of every level.

Two errors carry the deployment that a term names. Both use the code `VALIDATION_ERROR`, so the SDK and `styrminctl` map them like any validation error and show the message.

- `UnresolvableAffinityReferenceError` (`services/exceptions.py`): `extensions` gives `path` (for example `deployment.config.scheduling.pod_affinity.required[0]` or `component[server].config.scheduling…`), `deployment_id` and/or `deployment_name`, and `deleted: true` when the deployment is deleted. The message gives the path, the environment's name when known and the reason. For a deleted deployment, it also says how to fix the term at that level.
- `UnclonedDeploymentReferenceError`: returned by `cloneEnvironment` before any record or backup is created. `extensions.deployments` lists `{deployment_id, deployment_name, paths, reason}` for each deployment that a copied term names and the clone does not copy. `deployment_id` is `null` for a name, given by a driver version, that no deployment of the source environment has.

See [ADR-075](../../adr/0075-deployment-references-stored-by-id.md), [`data-models.md`](data-models.md) → Affinity-by-deployment-reference for the stored form, and [`backup-restore.md`](backup-restore.md#affinity-terms-in-a-clone) for the clone.

### DeploymentTimelineEntry

<!-- Extracted from specs/001-deployment-history-timeline on 2026-05-17 -->

Per-deployment history exposed through the `deploymentTimeline(deploymentId: UUID!): [DeploymentTimelineEntry!]!` query, ordered `created_on DESC` (newest first). The entry, version, and context diff are all **derived server-side** from the existing `Task` and `ApplicationInstance` rows — no schema additions back this query. See [ADR-028](../adr/0028-deployment-history-derived-from-existing-data.md). Each entry's `task` also carries its steps, result and task links from the timeline read model (see [Step](#step)).

```graphql
type DeploymentTimelineEntry {
  task: Task!
  applicationVersion: String         # correlated from ApplicationInstance.created_on
  contextDiff: ContextDiff           # null on the first entry
}

type ContextDiff {
  changes: [ContextChange!]!
}

type ContextChange {
  path: String!                       # dot-notation path into GlobalContext, e.g. "deployment.version"
  action: String!                     # "added" | "removed" | "modified"
  oldValue: JSON
  newValue: JSON
}
```

**Version correlation**: for each task, the timeline picks the latest `ApplicationInstance.created_on <= task.created_on`; ties fall back to the earliest instance. This preserves historical accuracy — a task from before an upgrade shows the pre-upgrade version, not the deployment's current desired version.

**Diff source**: each `ApplicationInstance.context` JSON column stores the full resolved `GlobalContext` at instance creation time. The diff between two adjacent entries is computed as a flat list of typed changes; the first entry's `contextDiff` is `null`.

No pagination in v1; frontend virtual scrolling handles ≥100 entries.

### DeployedService

<!-- Extracted from specs/001-service-fqdn-context on 2026-05-17 -->

```graphql
type DeployedService {
  id: UUID!
  deploymentId: UUID!
  driverServiceName: String!
  resolvedName: String!
  kind: String!
  scope: String!
  port: Int!
  component: String!
  primaryFqdn: String          # UUID-based FQDN; null when fqdn_suffix unresolved
  humanReadableFqdn: String    # environment-name-based FQDN; null when fqdn_suffix unresolved
}
```

Both FQDN fields are computed at runtime by the `Deployment.deployed_services()` resolver (single batched lookup of environment + cluster + resolved config, one pass over all services) and injected into the Strawberry instances. They are **not** persisted on `DeployedService` in the database — see [ADR-022](../adr/0022-compute-service-fqdns-at-runtime.md). The same `context/fqdn.py` helpers compute these values for driver-template context, guaranteeing UI ↔ driver consistency.

### DeploymentStatusType

<!-- Extracted from specs/001-crd-status-reporting on 2026-05-17 -->

Latest StyrminDeployment CRD status snapshot, exposed as `Deployment.crdStatus`. The wire types reflect the post-rename surface (`DeploymentStatusType` / `reportDeploymentStatuses` / `DeploymentStatusReportInput`); the original spec authored these as `DeploymentCrdStatus` / `reportCrdStatuses`. See [ADR-020](../adr/0020-separate-crd-status-reporting-mutation.md) and [ADR-021](../adr/0021-deployment-crd-status-snapshot-table.md).

```graphql
type CrdCondition {
  type: String!
  status: String!
  reason: String
  message: String
  lastTransitionTime: DateTime
}

type ManagedResourceCounts {
  networkPolicies: Int!
  secrets: Int!
  helmReleases: Int!
  services: Int!
  middlewares: Int!
}

type DeploymentStatusType {
  id: UUID!
  deploymentId: UUID!
  phase: String!                 # CRD phase: Pending/CreatingPrerequisites/CreatingHelmRelease/CreatingServices/Ready/Failed/Deleting/Deleted
  message: String
  conditions: [CrdCondition!]!
  managedResourceCounts: ManagedResourceCounts
  lastPolledAt: DateTime!
  createdOn: DateTime!
  updatedOn: DateTime!
}
```

The agent-side wire payload additionally carries `displayState` and `instanceId` (see [`data-models.md`](data-models.md) → `DeploymentStatus`) — those drive the parent `Deployment.status`, the stale-instance guard and the operator-phase steps of the task that rolled out that instance, and are **not** exposed on this GraphQL type. `instanceId` is the CR's `status.instanceId`, else its `spec.instanceId`.

## Enums

The schema exposes only a handful of GraphQL enums; most "enum-shaped" fields are `String!` carrying a value from one of the DB-level enums in [`data-models.md`](data-models.md).

GraphQL enums in the schema:

- `PodPhase` — `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `UNKNOWN` (uppercase wire format; the agent's `agent/status/models.py::PodPhase` mirrors these values).
- `BackupStatus` — `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`.
- `RestoreStatus` — `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`.
- `EnvironmentBackupStatus` and `EnvironmentRestoreStatus` — `PENDING`, `IN_PROGRESS`, `COMPLETED`, `PARTIAL`, `FAILED`. Both are derived on every read and never stored; both map the same service-layer `EnvironmentOperationStatus` ([ADR-055](../../adr/0055-environment-backup-parent-records.md)). <!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->
- `EnvironmentCloneStatus` — the same five values, derived on every read from different inputs ([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md)).
- `EnvironmentCloneDeploymentOutcome` — `PENDING`, `CLONED`, `SKIPPED`, `FAILED`. The outcome is a closed enum on the wire, while the `reason` next to it is open text that clients show and do not compare. <!-- Extracted from specs/010-environment-clone on 2026-10-13 -->
- `StepStatus` — `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SUPERSEDED`.
- `StepKind` — `PLAN`, `HOOK`, `RESOURCE_WRITE`, `OPERATOR_PHASE`, `COMMAND`, `RESTORE`, `BACKUP_COMPONENT`.
- `StepEvent` — `STARTED`, `SUCCEEDED`, `FAILED`, `OUTPUT` (input only, on `RecordStepInput`).
- `TaskResult` — `RUNNING`, `FAILED`, `SUCCEEDED`, `SUPERSEDED`.
- `ReplicaSource` — `OVERRIDE`, `DRIVER_DEFAULT`, `CHART` (on `ComponentReplicas.source`, derived on every read). <!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

### Status strings

Fields typed `String!` that carry well-known enum values:

- `Deployment.status` — `pending`, `deploying`, `running`, `restoring`, `failed` (lowercase; values come from `DeploymentState` in `db/models.py`).
- `Task.status` — `pending`, `running`, `success`, `failed` (`TaskStatus`).
- `Task.type` — `noop`, `create_instance`, `delete_instance`, `update_instance`, `upgrade_instance`, `stop_components`, `start_components`, `run_job`, `delete_deployment` (`TaskType`). Reconcile tasks carry the operation their caller started (see [orchestration-flows.md](orchestration-flows.md#task-types-of-reconcile-tasks)); `noop` remains on reconcile tasks created before spec 019.
- `Backup.status` / `Restore.status` — same casing as the corresponding GraphQL enums above.

The DB-level enum casing is intentionally lowercase; the agent-side `PodPhase` happens to be uppercase to match the GraphQL wire format. See [`data-models.md`](data-models.md) for the authoritative list of database enum values.

## Nested Object Resolvers

GraphQL types expose nested object fields that allow clients to traverse entity relationships in a single query. Each nested field resolves the related entity on demand.

A representative subset:

| Parent Type | Field | Return Type | Nullable | Notes |
|-------------|-------|-------------|----------|-------|
| `Deployment` | `environment` | `Environment` | No | Via `environment_id` FK |
| `Deployment` | `applicationDriverVersion` | `ApplicationDriverVersion` | No | Via `application_driver_version_id` FK |
| `Deployment` | `applicationInstance` | `ApplicationInstance` | Yes | Active instance only |
| `ApplicationDriverVersion` | `applicationDriver` | `ApplicationDriver` | No | Sync resolver (eager-loaded) |
| `ApplicationInstance` | `applicationDriverVersion` | `ApplicationDriverVersion` | No | Via FK |
| `Task` | `deployment` | `Deployment` | Yes | `deployment_id` may be null |
| `Task` | `startedBy` | `Task` | Yes | Via `started_by_step_id` → step → task |
| `Task` | `startedTasks` | `[Task!]!` | No | Tasks whose `started_by_step_id` is one of the task's steps |
| `Step` | `supersededBy` | `Task` | Yes | Via `superseded_by_task_id` |
| `Step` | `startedTasks` | `[Task!]!` | No | Tasks whose `started_by_step_id` is the step |
| `Backup` | `steps` | `[Step!]!` | No | One step per component |
| `Restore` | `steps` | `[Step!]!` | No | The three restore steps; a cross-target restore can have a fourth, "Create and delete service aliases" |
| `BackupSchedule` | `deployment` | `Deployment` | No | Via `deployment_id` FK |
| `Backup` | `instance` | `ApplicationInstance` | No | Via `instance_id` FK |
| `Restore` | `backup` | `Backup` | No | Via `backup_id` FK |

All `*Id` scalar fields are preserved alongside the nested object fields for backward compatibility. Clients can chain nested fields for deep traversal (e.g., `restore → backup → instance → applicationDriverVersion → applicationDriver`); no depth limit is enforced.

## Custom Scalars

| Scalar | Purpose |
|--------|---------|
| `JSON` (`api/scalars.py`) | Arbitrary JSON for configuration / parameter / status fields |
| `UUID` | Standard UUID string |
| `DateTime` | ISO-8601 timestamp |

## Key Files

| File | Purpose |
|------|---------|
| [api/__init__.py](backend/styrmin_backend/api/__init__.py) | Schema construction, `init_graphql_router`, `init_rest_router` |
| [api/schema/query.py](backend/styrmin_backend/api/schema/query.py) | The `Query` type |
| [api/schema/mutation.py](backend/styrmin_backend/api/schema/mutation.py) | The `Mutation` type (includes agent callbacks) |
| [api/dependency.py](backend/styrmin_backend/api/dependency.py) | `get_context` (DI for `UnitOfWork`) |
| [api/errors.py](backend/styrmin_backend/api/errors.py) | `StructuredErrorExtension` middleware |
| [api/definitions/](backend/styrmin_backend/api/definitions/) | One subpackage per domain (cluster, deployment, task, ...) |
| [api/definitions/step/model.py](backend/styrmin_backend/api/definitions/step/model.py) | `Step`, `StepError`, the step enums, `RecordStepInput` |
| [api/auth/permissions.py](backend/styrmin_backend/api/auth/permissions.py) | `RequiresRole`, `IsActionsServiceAccount`, `StartedByStepRequiresActionsServiceAccount` |
| [services/deployment_timeline.py](backend/styrmin_backend/services/deployment_timeline.py) | Timeline and its read model (steps, started tasks, results, no-report times) |
| [services/steps/reads.py](backend/styrmin_backend/services/steps/reads.py) | Step reads and the `noReportSince` rule |
| [schema.graphql](schema.graphql) | Generated schema; the authoritative inventory |
