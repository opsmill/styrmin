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
| `deployment` | `deploymentId?` **or** `(name?, environmentId?)` | `Deployment` (two argument shapes, never mixed — see below) |
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
returns `null`. Resolution itself lives in
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
| `createEnvironment` | `name, clusterId?, clusterName?, config?` | `Environment` |
| `updateEnvironment` | `environmentId, input: UpdateEnvironmentInput!` | `Environment` (typed full-replacement input; triggers per-deployment redeploy fanout — see [ADR-012](../adr/0012-environment-config-fanout.md)) |
| `deleteEnvironment` | `environmentId?, environmentName?, clusterId?, clusterName?` | `String` |
| `createBackupStorageLocation` | `name, endpoint, bucket, region, accessKeyId, secretAccessKey` | `BackupStorageLocation` |
| `updateBackupStorageLocation` | `backupStorageLocationId, name?, endpoint?, bucket?, region?, accessKeyId?, secretAccessKey?` | `BackupStorageLocation` |
| `deleteBackupStorageLocation` | `backupStorageLocationId` | `String` |
| `assignBackupStorageLocation` | `environmentId, backupStorageLocationId` | `Environment` |
| `unassignBackupStorageLocation` | `environmentId` | `Environment` |
| `loadLocalApplicationDriverVersion` | `path` | `ApplicationDriverVersion` (identity-aware per spec 013: same content → idempotent, new content → new row alongside existing) |
| `loadRemoteApplicationDriverVersion` | `repositoryUrl, branch` | `ApplicationDriverVersion` (identity-aware: keyed on resolved git commit SHA) |
| `deploy` | `driver, environmentId?, environmentName?, clusterId?, clusterName?, version?, name?, config?, parameters?, serviceNameOverrides?` | `Task` |
| `updateDeployment` | `deploymentId, input: UpdateDeploymentInput!` | `Task` — **`null` on a no-op** (see below) |
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
| `updateDeploymentVersion` | `deploymentId, version, parameters?` | `Task` — **`null` on a no-op** (see below) |
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

Clients map the null to "unchanged": the SDK returns
`ApplyOutcome(action="unchanged")`. See
[ADR-054](../../adr/0054-backend-authoritative-noop-detection.md), and
[reconciliation.md](reconciliation.md) for the guard's placement inside the
two-UoW `update_deployment` flow.

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

`Environment` gains a parallel `envVars: [EnvVar!]!`. Operator-set env vars travel through the typed `input: UpdateDeploymentInput!` argument on `updateDeployment()` (`envVars: [EnvVarInput!]` per scope) and through the typed `input: UpdateEnvironmentInput!` on `updateEnvironment()`. The legacy `config: JSON` write path persists on `deploy()` (Pydantic-validated against `DeploymentConfig`) until the analogous deploy-side migration ships. See "Environment-config update + fanout" below for the environment-scope contract; see [`specs/011-typed-deployment-input/spec.md`](../../../specs/011-typed-deployment-input/spec.md) for the deployment-scope contract. Driver-side documentation (`ApplicationDriverVersion.envVars`), orphan tracking on per-component blocks (`ComponentEnvVars.isOrphaned = true`), and chart-vs-user collision warnings (`DeploymentTimelineEntry.envVarCollisions`) are scoped for follow-up user stories (US4/US5/US7) and will be added as those ship.

#### Environment-config update + fanout

<!-- Extracted from specs/009-environment-update on 2026-05-08 -->

`updateEnvironment(environmentId: UUID!, input: UpdateEnvironmentInput!)` is the single typed write surface for environment configuration. The prior JSON-blob shape (`config: JSON`) is **gone** — the schema does not accept it post-009 and CI fails if it is reintroduced (FR-024).

`UpdateEnvironmentInput` is **full-replacement**: the input represents the complete desired environment configuration; any field omitted is persisted as its unset state. Operators editing one field MUST read the existing config first and re-supply the unchanged fields. The input mirrors `EnvironmentConfig` field-for-field (`envVars: [EnvVarInput!]`, `ipWhitelist: [String!]`, `dedicatedIngress: DedicatedIngressInput`, `scheduling: SchedulingInput`, `fqdnSuffix: String`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`).

Validation flows through the same Pydantic pipeline as `deploy()` / `updateDeployment()`, surfacing the typed error codes from 008 at the GraphQL boundary: `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, plus `ENVIRONMENT_NOT_FOUND` for unknown ids.

After persistence, the platform fans out a redeploy Task to **every non-tombstoned, non-internal deployment in the environment** whose active instance is not already at the new config (per-deployment no-op detection — see [ADR-012](../adr/0012-environment-config-fanout.md) §1). The mutation returns once the env-config row is committed and Tasks are dispatched (it does NOT block on Task completion). Per-deployment Task failures are recorded on the affected deployment's timeline; they do NOT roll back the env-config row or affect peer deployments (FR-008/FR-009a).

Frontend form caveat (v1, US4): the env-vars edit form on the environment detail Configuration tab maps only the `envVars` and flat-scalar slices of `EnvironmentConfig` back into the full-replacement input. The nested `dedicatedIngress` and `scheduling` fields are NOT yet carried through the form — to prevent silent clears under full-replacement semantics, **the form blocks submission** when the persisted config carries either nested override: it renders a destructive Alert above the rows and disables the Save button, leaving the rows readable + editable so operators can copy values into their SDK call. When neither nested override is set, the form behaves normally. Operators hitting the block use the SDK or GraphiQL until a future iteration extends the form. See [ADR-012](../adr/0012-environment-config-fanout.md) §2 for details.

Observability:

- One structured log line per fanout dispatch (`env_config_fanout_dispatched ...`) records `evaluated`, `dispatched`, `skipped_noop`, `dispatch_failed` counts (FR-023).
- Per-deployment outcomes are emitted via `_emit_fanout_metric` against the metric `env_config_fanout_deployments_total{environment, outcome}` (FR-023a). The metric backend is **not yet wired**: the helper at `services/environments.py::_emit_fanout_metric` currently logs the would-be metric at `info` level with a clear marker. Replacing the log call with a real counter increment is a one-line edit once a metrics client is registered. Until then, dashboards consume the structured log lines.

#### Deployment-config update + typed input

<!-- Extracted from specs/011-typed-deployment-input on 2026-05-16 -->

`updateDeployment(deploymentId: UUID!, input: UpdateDeploymentInput!)` is the single typed write surface for deployment configuration. The prior loose-argument shape (`name`, `config: JSON`, `parameters: JSON`, `serviceNameOverrides: [ServiceNameOverride!]`) is **gone** in the same release that ships the typed input — clean replace, no deprecation window (mirrors the 009 cutover precedent; see [ADR-012](../adr/0012-environment-config-fanout.md) §3 and [ADR-018](../adr/0018-typed-update-deployment-input.md)).

`UpdateDeploymentInput` is **full-replacement** at the top level with **one deliberate exception**: `parameters` keeps merge semantics. Omitting any other top-level field (`envVars`, `ipWhitelist`, `dedicatedIngress`, `scheduling`, `fqdnSuffix`, `externalUrlScheme`, `externalUrlPort`, `externalDnsEndpointsType`, `ingressClass`, `dbSize`, `runtimeClass`, `nodeSelector`, `standardStorage`, `components`, `serviceNameOverrides`, `name`) persists it as its unset state; omitting `parameters` leaves the persisted parameters dict alone. The asymmetry is documented on the GraphQL field description so introspection consumers see it without reading source. See [ADR-018](../adr/0018-typed-update-deployment-input.md) for the rationale (operators bumping one parameter value continue to work with a single-entry input; the unnamed keys survive).

Named-dict-typed config fields (`parameters`, `components`, top-level `envVars`, per-component `envVars`) travel as `list[{name, value, …}]` on the wire and are flattened to `dict` at the GraphQL-input boundary with typed duplicate detection. The flatten step raises:

- `DUPLICATE_PARAMETER_NAME` (`DuplicateParameterNameError`) — two `parameters` entries with the same `name`.
- `DUPLICATE_COMPONENT_NAME` (`DuplicateComponentNameError`) — two `components` entries with the same `name`.
- `DUPLICATE_ENV_VAR_NAME` (existing) — two env-var entries with the same `name`, with scope `"deployment"` (top-level) or `"component:<name>"` (per-component).

Detection at the flatten step is the only natural location — by the time the dict is built, duplicate keys silently collapse with last-wins semantics. Future typed inputs that mirror a Pydantic `dict[str, T]` field MUST use the same list-shape grammar; JSON-typed dict inputs are forbidden ([ADR-018](../adr/0018-typed-update-deployment-input.md)).

Explicit empty list = full clear; omitted/null field = "do not touch". `components: []` clears every per-component block; `components: [{name: "web", envVars: null}]` keeps the `web` key but collapses its inner env-vars block to its absent state (recursive nested-omission rule inherited from the shared `_convert_value` helper in `api/definitions/config/inputs.py`).

The full per-scope env-var error matrix from 008 — `INVALID_ENV_VAR_NAME`, `ENV_VAR_SIZE_LIMIT_EXCEEDED`, `DUPLICATE_ENV_VAR_NAME`, `UNKNOWN_COMPONENT_ENV_VAR` — surfaces at the GraphQL boundary for **both** the top-level `envVars` field and every per-component `envVars` field, with the offending name and scope in the payload. Per-component `envVars` additionally raise `COMPONENT_CONTAINER_NOT_DECLARED` (metadata `component_name`, `components_with_container`) when they add or change a value on a component whose driver declares no component container (017, [ADR-055](../adr/0055-post-render-component-overrides.md)). The wire layer (`EnvVarInput.value: String!`) rejects non-string values structurally — the legacy `INVALID_ENV_VAR_VALUE` error code is no longer reachable through `updateDeployment()` (it survives only on the JSON-config write path through `deploy()`).

Submitting an empty input (`input: {}`) surfaces a `VALIDATION_ERROR` from the existing service-side "at least one of config / parameters / name / serviceNameOverrides must be provided" check — no new GraphQL-level non-empty constraint is introduced.

Shared leaf inputs (`EnvVarInput`, `SchedulingInput`, `DedicatedIngressInput`, `AffinityBlockInput`, `ResourceRequirementsInput`, the enum mirrors, …) live in `api/definitions/config/inputs.py` and are reused unchanged by `UpdateEnvironmentInput` and `UpdateDeploymentInput`. Top-level inputs and their conversion helpers (`update_environment_input_to_dict`, `update_deployment_input_to_dict`) stay co-located with their entities under `api/definitions/{environment,deployment}/inputs.py`.

The frontend `deploymentConfigToInput()` helper in `frontend/src/lib/deployment-input.ts` converts the read-API config dict (with dict-shaped `envVars` and `components`) into the new list-shaped input shape; the `SchedulingConfigDialog` and any future caller submitting `UpdateDeploymentInput` go through this helper (mirrors the submit-boundary-transform discipline in [ADR-015](../adr/0015-frontend-value-transform-boundary.md)).

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

### ResolvedComponentScheduling

<!-- Extracted from specs/001-pod-scheduling-config on 2026-05-17 -->

Per-component resolved scheduling exposed as `Deployment.resolvedScheduling: [ResolvedComponentScheduling!]!`. Carries the merged `SchedulingConfig` for each component **and** the per-field provenance map so the frontend can show "where did this value come from?" without re-running the merge.

```graphql
type ResolvedComponentScheduling {
  component: String!
  scheduling: JSON!     # serialised SchedulingConfig (affinity / tolerations / topology_spread / resources / node_selector / runtime_class / inject)
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

### DeploymentTimelineEntry

<!-- Extracted from specs/001-deployment-history-timeline on 2026-05-17 -->

Per-deployment history exposed through the `deploymentTimeline(deploymentId: UUID!): [DeploymentTimelineEntry!]!` query, ordered `created_on DESC` (newest first). The entry, version, and context diff are all **derived server-side** from the existing `Task` and `ApplicationInstance` rows — no schema additions back this query. See [ADR-028](../adr/0028-deployment-history-derived-from-existing-data.md).

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

The agent-side wire payload additionally carries `displayState` and `instanceId` (see [`data-models.md`](data-models.md) → `DeploymentStatus`) — those drive the parent `Deployment.status` and the stale-instance guard, and are **not** exposed on this GraphQL type.

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
