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
| `tasks` | — | `[Task!]!` |
| `environments` | — | `[Environment!]!` |
| `environment` | `environmentId?, environmentName?, clusterId?, clusterName?` | `Environment` |
| `deployment` | `deploymentId` | `Deployment` |
| `backup` | `backupId` | `Backup` |
| `backups` | `instanceId, status?` | `[Backup!]!` |
| `restore` | `restoreId` | `Restore` |
| `restores` | `backupId, status?` | `[Restore!]!` |
| `backupSchedule` | `scheduleId` | `BackupSchedule` |
| `backupSchedules` | `deploymentId` | `[BackupSchedule!]!` |
| `applicationDrivers` | — | `[ApplicationDriver!]!` |
| `applicationDriver` | `applicationDriverId` | `ApplicationDriver` |
| `environmentServices` | `environmentId` | `[DeployedService!]!` |
| `deploymentServices` | `deploymentId` | `[DeployedService!]!` |
| `deploymentTimeline` | `deploymentId` | `[DeploymentTimelineEntry!]!` |
| `podStatuses` | `deploymentId?, environmentId?, clusterId?` | `[PodStatus!]!` |
| `ok` | — | `Boolean!` (health probe) |

## Mutations

Defined on `type Mutation`:

| Mutation | Arguments | Return |
|----------|-----------|--------|
| `createCluster` | `name="default", config?` | `Cluster` |
| `deleteCluster` | `clusterId?, clusterName?` | `String` |
| `createEnvironment` | `name, clusterId?, clusterName?, config?` | `Environment` |
| `updateEnvironment` | `environmentId, input: UpdateEnvironmentInput!` | `Environment` (typed full-replacement input; triggers per-deployment redeploy fanout — see [ADR-020](../adr/adr-020-environment-config-fanout.md)) |
| `deleteEnvironment` | `environmentId?, environmentName?, clusterId?, clusterName?` | `String` |
| `createBackupStorageLocation` | `name, endpoint, bucket, region, accessKeyId, secretAccessKey` | `BackupStorageLocation` |
| `updateBackupStorageLocation` | `backupStorageLocationId, name?, endpoint?, bucket?, region?, accessKeyId?, secretAccessKey?` | `BackupStorageLocation` |
| `deleteBackupStorageLocation` | `backupStorageLocationId` | `String` |
| `assignBackupStorageLocation` | `environmentId, backupStorageLocationId` | `Environment` |
| `unassignBackupStorageLocation` | `environmentId` | `Environment` |
| `loadLocalApplicationDriverVersion` | `path` | `ApplicationDriverVersion` |
| `loadRemoteApplicationDriverVersion` | `repositoryUrl, branch` | `ApplicationDriverVersion` |
| `deploy` | `driver, environmentId?, environmentName?, clusterId?, clusterName?, version?, name?, config?, parameters?, serviceNameOverrides?` | `Task` |
| `updateDeployment` | `deploymentId, name?, config?, parameters?, serviceNameOverrides?` | `Task` |
| `deleteDeployment` | `deploymentId` | `Task!` (born-complete `DELETE_DEPLOYMENT` audit record; patches `spec.deletionRequested` on the CR — operator drives teardown asynchronously) |
| `createBackup` | `instanceId, name?` | `Backup` |
| `deleteBackup` | `backupId` | `String` |
| `createRestore` | `backupId, targetNamespace, targetInstanceId?` | `Restore` |
| `createBackupSchedule` | `deploymentId, name, cronExpression, retentionCount=10, enabled=true` | `BackupSchedule` |
| `updateBackupSchedule` | `scheduleId, name?, cronExpression?, retentionCount?, enabled?` | `BackupSchedule` |
| `deleteBackupSchedule` | `scheduleId` | `String` |
| `callback` | `taskId, stateName, stateMessage?, stateType` | `CallbackResponse!` (Prefect → server) |
| `stopComponents` | `deploymentId, components` | `Task` |
| `startComponents` | `deploymentId, components` | `Task` |
| `runJob` | `deploymentId, commands, env, image` | `Task` |
| `updateDeploymentVersion` | `deploymentId, version, parameters?` | `Task` |
| `reportPodStatuses` | `reports: [DeploymentPodStatusReport!]!` | `ReportPodStatusesResponse!` (agent → server) |
| `reportDeploymentStatuses` | `reports: [DeploymentStatusReportInput!]!` | `ReportDeploymentStatusesResponse!` (agent → server) |

The agent callbacks (`callback`, `reportPodStatuses`, `reportDeploymentStatuses`) are documented in [`../agent/overview.md`](../agent/overview.md) and [`reconciliation.md`](reconciliation.md).

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

`deleteDeployment` deserves a note: a delete on a tombstoned deployment surfaces `NOT_FOUND` (intentionally conflated with unknown id so automation can treat both identically as "already gone"); a delete during a restore raises the typed `DEPLOYMENT_RESTORING` so callers can specifically recover. A repeat delete on a deployment that's already `DELETING` returns the existing in-flight `DELETE_DEPLOYMENT` task without re-issuing the cluster patch (idempotent retry).

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

On the client side, errors arrive as standard GraphQL errors with `extensions.code` for programmatic handling. See [`../guides/graphql-propagation-tests.md`](../guides/graphql-propagation-tests.md) for the per-field test pattern.

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
}
```

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
  crdStatus: DeploymentStatusType
}
```

`Environment` gains a parallel `envVars: [EnvVar!]!`. Operator-set env vars travel through the existing `config: JSON` argument on `deploy()` and `updateDeployment()` (Pydantic-validated against `DeploymentConfig`). Environment-scope edits go through the typed `updateEnvironment(environmentId, input: UpdateEnvironmentInput!)` mutation — see "Environment-config update + fanout" below for the full contract. Driver-side documentation (`ApplicationDriverVersion.envVars`), orphan tracking on per-component blocks (`ComponentEnvVars.isOrphaned = true`), and chart-vs-user collision warnings (`DeploymentTimelineEntry.envVarCollisions`) are scoped for follow-up user stories (US4/US5/US7) and will be added as those ship.

#### Environment-config update + fanout

<!-- Extracted from specs/009-environment-update on 2026-05-08 -->

`updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!)` is the single typed write surface for environment configuration. The prior JSON-blob shape (`config: JSON`) is **gone** — the schema does not accept it post-009 and CI fails if it is reintroduced (FR-024).

`UpdateEnvironmentInput` is **full-replacement**: the input represents the complete desired environment configuration; any field omitted is persisted as its unset state. Operators editing one field MUST read the existing config first and re-supply the unchanged fields. The input mirrors `EnvironmentConfig` field-for-field (`envVars: [EnvVarInput!]`, `ipWhitelist: [String!]`, `dedicatedIngress: DedicatedIngressInput`, `scheduling: SchedulingInput`, `fqdnSuffix: String`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`).

Validation flows through the same Pydantic pipeline as `deploy()` / `updateDeployment()`, surfacing the typed error codes from 008 at the GraphQL boundary: `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, plus `ENVIRONMENT_NOT_FOUND` for unknown ids.

After persistence, the platform fans out a redeploy Task to **every non-tombstoned, non-internal deployment in the environment** whose active instance is not already at the new config (per-deployment no-op detection — see [ADR-020](../adr/adr-020-environment-config-fanout.md) §1). The mutation returns once the env-config row is committed and Tasks are dispatched (it does NOT block on Task completion). Per-deployment Task failures are recorded on the affected deployment's timeline; they do NOT roll back the env-config row or affect peer deployments (FR-008/FR-009a).

Frontend form caveat (v1, US4): the env-vars edit form on the environment detail Configuration tab maps only the `envVars` and flat-scalar slices of `EnvironmentConfig` back into the full-replacement input. The nested `dedicatedIngress` and `scheduling` fields are NOT yet carried through the form — to prevent silent clears under full-replacement semantics, **the form blocks submission** when the persisted config carries either nested override: it renders a destructive Alert above the rows and disables the Save button, leaving the rows readable + editable so operators can copy values into their SDK call. When neither nested override is set, the form behaves normally. Operators hitting the block use the SDK or GraphiQL until a future iteration extends the form. See [ADR-020](../adr/adr-020-environment-config-fanout.md) §2 for details.

Observability:

- One structured log line per fanout dispatch (`env_config_fanout_dispatched ...`) records `evaluated`, `dispatched`, `skipped_noop`, `dispatch_failed` counts (FR-023).
- Per-deployment outcomes are emitted via `_emit_fanout_metric` against the metric `env_config_fanout_deployments_total{environment, outcome}` (FR-023a). The metric backend is **not yet wired**: the helper at `services/environments.py::_emit_fanout_metric` currently logs the would-be metric at `info` level with a clear marker. Replacing the log call with a real counter increment is a one-line edit once a metrics client is registered. Until then, dashboards consume the structured log lines.

There is no `tasks` field on `Deployment` — query `tasks` at the root and filter by `deploymentId` if you need a deployment's task history.

### Task

```graphql
type Task {
  id: UUID!
  type: String!                  # Stored as TaskType enum value (see below)
  status: String!                # Stored as TaskStatus enum value (see below)
  message: String
  deploymentId: UUID
  createdOn: DateTime
  updatedOn: DateTime
  deployment: Deployment
}
```

`type` and `status` are exposed as `String!` (not GraphQL enums), but they always carry one of the database enum values — see "Status strings" below.

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

## Enums

The schema exposes only a handful of GraphQL enums; most "enum-shaped" fields are `String!` carrying a value from one of the DB-level enums in [`data-models.md`](data-models.md).

GraphQL enums in the schema:

- `PodPhase` — `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `UNKNOWN` (uppercase wire format; the agent's `agent/status/models.py::PodPhase` mirrors these values).
- `BackupStatus` — `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`.
- `RestoreStatus` — `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`.

### Status strings

Fields typed `String!` that carry well-known enum values:

- `Deployment.status` — `pending`, `deploying`, `running`, `restoring`, `failed` (lowercase; values come from `DeploymentState` in `db/models.py`).
- `Task.status` — `pending`, `running`, `success`, `failed` (`TaskStatus`).
- `Task.type` — `noop`, `create_instance`, `delete_instance`, `update_instance`, `upgrade_instance`, `stop_components`, `start_components`, `run_job` (`TaskType`).
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
| [schema.graphql](schema.graphql) | Generated schema; the authoritative inventory |
