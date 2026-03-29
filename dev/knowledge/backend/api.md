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
| `cluster(cluster_id)` | Get cluster by ID | `Cluster \| ClusterNotFound` |
| `environments` | Get all environments | `[Environment]` |
| `environment(environment_id)` | Get environment by ID | `Environment \| EnvironmentNotFound` |
| `deployment(deployment_id)` | Get deployment by ID (async) | `Deployment \| DeploymentNotFound` |
| `tasks` | Get all tasks | `[Task]` |
| `task(task_id)` | Get task by ID | `Task \| TaskNotFound` |

### Mutations

| Mutation | Description | Return Type |
|----------|-------------|-------------|
| `create_cluster(name="default", config?)` | Create a cluster (only one allowed) | `ClusterCreated \| ClusterLimitReached \| ClusterCreationFailed` |
| `delete_cluster(cluster_id)` | Delete a cluster | `ClusterDeleted \| ClusterNotFound` |
| `create_environment(name, cluster_id, config?)` | Create environment in cluster | `EnvironmentCreated \| EnvironmentAlreadyExists \| EnvironmentCreationFailed` |
| `delete_environment(environment_id)` | Delete an environment | `EnvironmentDeleted \| EnvironmentNotFound` |
| `create_application_driver(name)` | Create application driver (async) | `ApplicationDriverCreated \| ApplicationDriverCreationFailed` |
| `load_remote_application_driver_version(repository_url, branch)` | Load driver from Git (async) | `ApplicationDriverVersionCreated \| ApplicationDriverVersionCreationFailed` |
| `deploy(version, name, environment_id, config?)` | Deploy application (async) | `DeploymentInProgress \| DeploymentFailed` |
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

The API uses union types for responses, allowing typed error handling:

```python
# Example response union
GetClusterResponse = Annotated[
    Cluster | ClusterNotFound,
    strawberry.union("GetClusterResponse")
]

# In resolver
@strawberry.field
def cluster(self, cluster_id: UUID, info: strawberry.Info) -> GetClusterResponse:
    try:
        cluster = get_cluster(cluster_id=cluster_id, uow=uow)
    except ClusterNotFoundError:
        return ClusterNotFound()
    return Cluster.from_instance(cluster)
```

## GraphQL Types

### Core Types

#### Cluster

```graphql
type Cluster {
  id: UUID!
  name: String!
  config: JSON
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
  status: DeploymentStatus!
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

**DeploymentStatus**: `PENDING`, `RUNNING`, `FAILED`

**TaskStatus**: `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`

**TaskType**: `DEPLOYMENT`, `CREATE_INSTANCE`, `DELETE_INSTANCE`, `UPDATE_INSTANCE`, `UPGRADE_INSTANCE`, `STOP_COMPONENTS`, `START_COMPONENTS`, `RUN_JOB`

## Custom Scalars

**JSON** (`api/scalars.py`) - Allows passing arbitrary JSON objects for configuration.

## Key Files

| File | Purpose |
|------|---------|
| [api/**init**.py](backend/styrmin_backend/api/__init__.py) | Router initialization |
| [api/schema/query.py](backend/styrmin_backend/api/schema/query.py) | Query definitions |
| [api/schema/mutation.py](backend/styrmin_backend/api/schema/mutation.py) | Mutation definitions |
| [api/dependency.py](backend/styrmin_backend/api/dependency.py) | Context injection |
