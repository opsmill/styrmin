# Backend Services Documentation

## Overview

The services layer contains the business logic of the application. It sits between the API layer and the data access layer, orchestrating operations across repositories and external systems.

```text
styrmin_backend/services/
├── clusters.py              # Cluster management
├── environments.py          # Environment management
├── deployment.py            # Deployment orchestration
├── applications.py          # Application driver management
├── instances.py             # Instance lifecycle
├── tasks.py                 # Task state management
├── deployment_timeline.py   # Deployment history timeline with version correlation and context diffs
├── context.py               # Context generation
├── primitives.py            # Primitive operations
├── user.py                  # User action workflows
├── unit_of_work.py          # Repository coordination
├── exceptions.py            # Service exceptions
├── utils.py                 # Utilities
│
├── driver/                  # Application driver parsing
│   ├── provider.py         # Git-based driver fetching
│   ├── loaders.py          # Load from filesystem
│   ├── deserializers.py    # Parse YAML/JSON
│   ├── validators.py       # Validate driver structure
│   ├── parsers.py          # Extract metadata
│   └── models/             # Driver domain models
│
├── reconciliation/          # State reconciliation
│   ├── diffs/              # Diff computation
│   │   ├── comparison.py
│   │   ├── diffs.py
│   │   └── serializer.py
│   └── remediation.py      # Remediation strategies
│
├── helm/                    # Helm operations
│   ├── renderer.py         # Template rendering
│   └── _environment.py     # Environment setup
│
├── workflow/                # Workflow execution
│   ├── worker.py           # Workflow executor
│   └── utils.py            # Utilities
│
└── utilities/               # Infrastructure utilities
    └── utilities.py        # Utility management
```

## Unit of Work Pattern

The `UnitOfWork` pattern coordinates database operations across multiple repositories within a single transaction.

### Interface

```python
class UnitOfWork(ABC):
    clusters: ClusterRepository
    environments: EnvironmentRepository
    helm_repositories: HelmRepositoryRepository
    helm_charts: HelmChartRepository
    component_configs: ComponentConfigRepository
    application_drivers: ApplicationDriverRepository
    application_driver_versions: ApplicationDriverVersionRepository
    actions: ActionRepository
    utilities: UtilityRepository
    tasks: TaskRepository
    deployments: DeploymentRepository

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

### Usage Pattern

```python
async def some_operation(uow: UnitOfWork) -> Result:
    with uow:
        entity = uow.repository.get(id)
        entity.update(...)
        uow.repository.save(entity)
        uow.commit()
        return entity
```

## Core Services

### Clusters Service (`clusters.py`)

Manages Kubernetes cluster definitions. Only one cluster may exist at a time.

| Function | Description |
|----------|-------------|
| `create_cluster(uow, name="default", config=None)` | Create a cluster (raises `ClusterLimitReachedError` if one already exists). Computes and persists capabilities. |
| `resolve_cluster(uow, cluster_id?, cluster_name?)` | Resolve cluster by ID or name (exactly one required) |
| `get_cluster(cluster_id, uow)` | Retrieve cluster by ID |
| `get_clusters(uow)` | List all clusters |
| `delete_cluster(cluster_id, uow)` | Delete a cluster |

### Environments Service (`environments.py`)

Manages environments within clusters.

| Function | Description |
|----------|-------------|
| `resolve_environment(uow, environment_id?, environment_name?, cluster_id?, cluster_name?)` | Resolve environment by ID or name with cluster context |
| `create_environment(name, cluster_id, config, uow)` | Create environment in cluster (name unique per cluster). Computes and persists capabilities. |
| `get_environment(environment_id, uow)` | Retrieve environment by ID |
| `get_environments(uow)` | List all environments |
| `delete_environment(environment_id, uow)` | Delete an environment |

### Capabilities Service (`capabilities.py`)

Derives hierarchical capabilities from cluster/environment configuration. Capabilities are persisted as JSON and recalculated on relevant config changes.

| Function | Description |
|----------|-------------|
| `compute_cluster_capabilities(cluster)` | Compute capabilities from cluster config (storage, ingress) |
| `compute_environment_capabilities(environment)` | Compute capabilities from environment config and BSL (backup, ingress) |

Called automatically by cluster/environment creation and BSL assign/unassign operations.

### Deployment Service (`deployment.py`)

Orchestrates application deployments.

| Function | Description |
|----------|-------------|
| `deploy_application(name, version, environment_id, config, uow)` | Deploy an application |
| `get_deployment(deployment_id, uow)` | Get deployment by ID |
| `update_deployment(deployment_id, config, uow)` | Update deployment configuration |
| `update_deployment_version(deployment_id, version, uow)` | Change application version |
| `refresh_deployment(deployment_id, uow)` | Re-reconcile deployment state |

**Deployment Flow:**

1. Validate configuration
2. Find matching application driver version
3. Create deployment with components
4. Generate instance from deployment
5. Apply state via reconciliation
6. Return task for tracking

### Applications Service (`applications.py`)

Manages application drivers and their versions.

| Function | Description |
|----------|-------------|
| `create_application_driver(name, uow)` | Create application driver |
| `load_application_driver_from_git_repository(repository_url, branch, uow)` | Load driver from Git |

### Tasks Service (`tasks.py`)

Tracks async operation status.

| Function | Description |
|----------|-------------|
| `get_task(task_id, uow)` | Get task by ID |
| `get_tasks(uow)` | List all tasks |
| `update_task_state(task_id, state_name, state_message, uow)` | Update task status |

### Primitives Service (`primitives.py`)

Low-level operations on deployments.

| Function | Description |
|----------|-------------|
| `run_job(deployment_id, commands, env, image, uow)` | Run job in deployment context |
| `stop_components(deployment_id, components, uow)` | Stop specific components |
| `start_components(deployment_id, components, uow)` | Start specific components |

### Context Service (`context.py`)

Generates deployment contexts.

| Function | Description |
|----------|-------------|
| `generate_context_from_deployment_id(deployment_id, uow)` | Generate GlobalContext for deployment |

## Driver Services (`services/driver/`)

Handles loading and parsing of application driver specifications from Git repositories.

### Provider (`provider.py`)

```python
class DriverProvider(ABC):
    async def get(self, repository_url: str, branch: str) -> Path:
        """Clone repository and return local path"""
```

**GitDriverProvider**: Clones Git repositories using Dulwich, optionally with GitHub credentials.

### Loaders (`loaders.py`)

Load driver definitions from the filesystem after cloning.

### Deserializers (`deserializers.py`)

Parse driver manifest files (YAML/JSON) into domain models.

### Validators (`validators.py`)

Validate driver structure and content against schema requirements.

### Driver Models (`models/`)

Domain models representing driver resources:

- `Driver` - Root driver definition
- `Action` - Custom actions with hooks (pre/core/post)
- `Code` - Code resource references
- `Component` - Component definitions

## Reconciliation Engine (`services/reconciliation/`)

Implements declarative state management by comparing desired state (deployment) with current state (instance). See [reconciliation.md](reconciliation.md) for full details.

### Diffs (`diffs/`)

Compares current and new `Instance` objects using DeepDiff:

- `InstanceCreation` - New instance, no current (first deployment)
- `InstanceDeletion` - Current instance, no new (not implemented)
- `InstanceUpdate` - Both exist, contains typed diff entries:
  - `ApplicationVersionChange` - Version string changed
  - `ApplicationDriverVersionChange` - Driver version ID changed
  - `ContextChange` - Resolved configuration changed

### Remediation (`remediation.py`)

Maps diff types to remediation strategies:

```python
class Remediator:
    strategies = {
        InstanceCreation: InstanceCreationStrategy,   # Implemented (with setup hooks)
        InstanceDeletion: InstanceDeletionStrategy,   # Not implemented
        InstanceUpdate: InstanceUpdateStrategy,       # Implemented (with upgrade hook support)
    }
```

When `InstanceUpdate` contains an `ApplicationVersionChange`, the strategy first attempts the upgrade path (looking up driver upgrade hooks from Prefect). If no upgrade hook is defined, it falls back to a regular update. See [hooks-and-actions.md](hooks-and-actions.md) for details.

### State Application

```python
async def apply_state(
    deployment: Deployment,
    current_instance: Instance | None,
    uow: UnitOfWork,
) -> Task:
    """Compare instances, generate remediation, submit to Prefect."""
```

## Helm Services (`services/helm/`)

### Renderer (`renderer.py`)

Renders Helm values templates using Jinja2:

```python
def render_values(template: str, context: GlobalContext) -> dict:
    """Render Jinja2 template with context"""
```

## Workflow Services (`services/workflow/`)

### Worker (`worker.py`)

`StyrminWorkflowExecutor` submits workflows to Prefect for execution.

## Utilities Service (`services/utilities/`)

Manages infrastructure utilities (e.g., Ingress controllers).

```python
def initialize_utilities():
    """Initialize built-in utilities on startup"""
```

## Exception Hierarchy

```text
styrmin_backend/services/exceptions.py

ServiceError (base)
├── ClusterNotFoundError
├── ClusterAlreadyExistsError
├── EnvironmentNotFoundError
├── EnvironmentAlreadyExistsError
├── DeploymentNotFoundError
├── ApplicationDriverNotFoundError
├── InstanceNotFoundError
├── TaskNotFoundError
├── InvalidContextError
└── InvalidVersionError
```

## Key Files

| File | Purpose |
|------|---------|
| [services/unit_of_work.py](backend/styrmin_backend/services/unit_of_work.py) | Repository coordination |
| [services/deployment.py](backend/styrmin_backend/services/deployment.py) | Deployment orchestration |
| [services/applications.py](backend/styrmin_backend/services/applications.py) | Driver management |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | State reconciliation |
| [services/driver/provider.py](backend/styrmin_backend/services/driver/provider.py) | Git-based driver loading |
