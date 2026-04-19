# Backend API Documentation

## Overview

The backend exposes two GraphQL APIs:

- **Public API** (`/graphql`) - User-facing operations for managing clusters, environments, and deployments
- **Internal API** (`/internal/graphql`) - Agent callbacks and internal operations

Both APIs use [Strawberry GraphQL](https://strawberry.rocks/) for schema definition.

## API Architecture

```text
styrmin_backend/api/
├── __init__.py           # Router initialization
├── dependency.py         # Context injection (UnitOfWork)
├── scalars.py           # Custom scalars (JSON)
├── schema/
│   ├── query.py         # Query, InternalQuery
│   └── mutation.py      # Mutation, InternalMutation
├── definitions/         # GraphQL type definitions
│   ├── cluster/
│   ├── environment/
│   ├── deployment/
│   ├── task/
│   ├── deployment_timeline/
│   ├── application_driver/
│   ├── context/
│   ├── callback/
│   ├── action/
│   └── helm_chart/
└── fragments/           # Response union types
    ├── cluster.py
    ├── environment.py
    ├── deployment.py
    ├── task.py
    ├── application.py
    └── context.py
```

## Public API

### Queries

| Query | Description | Return Type |
|-------|-------------|-------------|
| `clusters` | Get all clusters | `[Cluster]` |
| `cluster(cluster_id?, cluster_name?)` | Get cluster by ID or name | `Cluster \| ClusterNotFound` |
| `environments` | Get all environments | `[Environment]` |
| `environment(environment_id?, environment_name?, cluster_id?, cluster_name?)` | Get environment by ID or name (with cluster context) | `Environment \| EnvironmentNotFound` |
| `deployment(deployment_id)` | Get deployment by ID (async) | `Deployment \| DeploymentNotFound` |
| `tasks` | Get all tasks | `[Task]` |
| `task(task_id)` | Get task by ID | `Task \| TaskNotFound` |
| `deploymentTimeline(deployment_id)` | Get deployment history timeline with version info and context diffs | `[DeploymentTimelineEntry]` |

### Mutations

| Mutation | Description | Return Type |
|----------|-------------|-------------|
| `create_cluster(name="default", config?)` | Create a cluster (only one allowed) | `ClusterCreated \| ClusterLimitReached \| ClusterCreationFailed` |
| `delete_cluster(cluster_id?, cluster_name?)` | Delete a cluster by ID or name | `ClusterDeleted \| ClusterNotFound` |
| `create_environment(name, cluster_id?, cluster_name?, config?)` | Create environment in cluster (by ID or name) | `EnvironmentCreated \| EnvironmentAlreadyExists \| EnvironmentCreationFailed` |
| `delete_environment(environment_id?, environment_name?, cluster_id?, cluster_name?)` | Delete an environment by ID or name | `EnvironmentDeleted \| EnvironmentNotFound` |
| `create_application_driver(name)` | Create application driver (async) | `ApplicationDriverCreated \| ApplicationDriverCreationFailed` |
| `load_remote_application_driver_version(repository_url, branch)` | Load driver from Git (async) | `ApplicationDriverVersionCreated \| ApplicationDriverVersionCreationFailed` |
| `deploy(driver, version?, environment_id?, environment_name?, cluster_id?, cluster_name?, name?, config?)` | Deploy application (async) | `DeploymentInProgress \| DeploymentFailed` |
| `update_deployment(deployment_id, config)` | Update deployment config (async) | `DeploymentUpdateInProgress \| DeploymentUpdateFailed` |

## Internal API

Used by agents and internal services for callbacks and privileged operations.

### Internal Queries

| Query | Description | Return Type |
|-------|-------------|-------------|
| `context(instance_id)` | Get deployment context for instance | `Context \| ApplicationInstanceNotFound` |

### Internal Mutations

| Mutation | Description | Return Type |
|----------|-------------|-------------|
| `callback(task_id, state_name, state_message?, state_type)` | Update task state from Prefect | `CallbackResponse` |
| `stop_components(deployment_id, components)` | Stop specific components (async) | `DeploymentUpdateInProgress \| DeploymentUpdateFailed` |
| `start_components(deployment_id, components)` | Start specific components (async) | `DeploymentUpdateInProgress \| DeploymentUpdateFailed` |
| `run_job(deployment_id, commands, env, image)` | Run job in deployment context (async) | `JobRunInProgress \| JobRunFailed` |
| `update_deployment_version(deployment_id, version)` | Update application version (async) | `DeploymentUpdateInProgress \| DeploymentUpdateFailed` |

## Context Injection

The API uses dependency injection to provide database access:

```python
# api/dependency.py
async def get_graphql_context(uow: SqlModelUnitOfWork = Depends(get_uow)):
    return {"uow": uow}
```

Every resolver receives the `UnitOfWork` via `info.context["uow"]`.

## Response Patterns

Mutations return the resource type directly (nullable) and let service-layer
exceptions propagate. The `StructuredErrorExtension` (see `api/errors.py`)
catches any `ServiceError` and converts it into a GraphQL error with a
structured `extensions.code` field (e.g. `NOT_FOUND`, `ALREADY_EXISTS`,
`IN_USE`). Additional metadata from `ServiceError.error_metadata` is merged
into the extensions object.

```python
# Mutation — return the resource directly, let exceptions propagate
@strawberry.mutation
async def create_cluster(
    self, info: strawberry.Info, name: str = "default"
) -> Cluster | None:
    uow = info.context["uow"]
    cluster = await create_cluster(uow=uow, name=name)
    return Cluster.from_instance(cluster)
```

On the client side, errors arrive as standard GraphQL errors with
`extensions.code` for programmatic handling.

## GraphQL Types

### Core Types

#### Cluster

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

#### Environment

```graphql
type Environment {
  id: UUID!
  name: String!
  config: JSON
  capabilities: JSON
  clusterId: UUID!
  deployments: [Deployment!]!
}
```

#### Deployment

```graphql
type Deployment {
  id: UUID!
  name: String!
  applicationVersion: String!
  config: JSON
  status: String!
  components: [Component!]!
  tasks: [Task!]!
}
```

#### Task

```graphql
type Task {
  id: UUID!
  type: TaskType!
  status: TaskStatus!
  message: String
  deploymentId: UUID!
}
```

### Enums

**Deployment state values** (string): `pending`, `deploying`, `running`, `failed`

**TaskStatus**: `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`

**TaskType**: `DEPLOYMENT`, `CREATE_INSTANCE`, `DELETE_INSTANCE`, `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, `STOP_COMPONENTS`, `START_COMPONENTS`, `RUN_JOB`

## Nested Object Resolvers

<!-- Extracted from specs/001-graphql-nested-resolvers on 2026-04-01 -->

GraphQL types expose nested object fields that allow clients to traverse entity relationships in a single query, eliminating follow-up requests. Each nested field resolves the related entity on demand.

### Available Nested Relationships

| Parent Type | Field | Return Type | Nullable | Notes |
|-------------|-------|-------------|----------|-------|
| `Deployment` | `environment` | `Environment` | No | Via `environment_id` FK |
| `Deployment` | `applicationDriverVersion` | `ApplicationDriverVersion` | No | Via `application_driver_version_id` FK |
| `ApplicationDriverVersion` | `applicationDriver` | `ApplicationDriver` | No | Sync resolver (eager-loaded) |
| `ApplicationInstance` | `applicationDriverVersion` | `ApplicationDriverVersion` | No | Via `application_driver_version_id` FK |
| `Task` | `deployment` | `Deployment` | Yes | `deployment_id` may be null |
| `BackupSchedule` | `deployment` | `Deployment` | No | Via `deployment_id` FK |
| `Backup` | `instance` | `ApplicationInstance` | No | Via `instance_id` FK |
| `Restore` | `backup` | `Backup` | No | Via `backup_id` FK |

All existing `*Id` scalar fields are preserved alongside the new nested object fields for backward compatibility.

Clients can chain nested fields for deep traversal (e.g., `restore → backup → instance → applicationDriverVersion → applicationDriver`). No depth limit is enforced.

## Custom Scalars

**JSON** (`api/scalars.py`) - Allows passing arbitrary JSON objects for configuration.

## Key Files

| File | Purpose |
|------|---------|
| [api/**init**.py](backend/styrmin_backend/api/__init__.py) | Router initialization |
| [api/schema/query.py](backend/styrmin_backend/api/schema/query.py) | Query definitions |
| [api/schema/mutation.py](backend/styrmin_backend/api/schema/mutation.py) | Mutation definitions |
| [api/dependency.py](backend/styrmin_backend/api/dependency.py) | Context injection |
