# Backend Services Documentation

## Overview

The services layer contains the business logic of the application. It sits between the API layer and the data access layer, orchestrating operations across repositories and external systems.

```text
styrmin_backend/services/
├── clusters.py                    # Cluster management
├── environments.py                # Environment management
├── deployment.py                  # Deployment orchestration
├── deployment_status.py           # Server-side handler for reportDeploymentStatuses
├── deployment_timeline.py         # Deployment history with version correlation and context diffs
├── applications.py                # Driver loading (Git, local, object) and application instantiation
├── application_drivers.py         # Read-side accessors for application drivers
├── instances.py                   # Instance lifecycle
├── tasks.py                       # Task state management
├── pod_status.py                  # Server-side handler for reportPodStatuses
├── parameters.py                  # Driver parameter resolution
├── services_discovery.py          # In-cluster service discovery
├── capabilities.py                # Cluster/environment capability derivation
├── backup_storage_locations.py    # Backup storage location (BSL) management
├── context.py                     # Context generation (generate_context_from_deployment)
├── primitives.py                  # run_job, stop_components, start_components
├── user.py                        # User action workflow registration helpers
├── unit_of_work.py                # Repository coordination (UnitOfWork + SqlModelUnitOfWork)
├── exceptions.py                  # ServiceError hierarchy
├── utils.py                       # Utilities
│
├── driver/                        # Application driver parsing
│   ├── provider.py                # Git-based driver fetching
│   ├── loaders.py                 # Load from filesystem
│   ├── deserializers.py           # Parse YAML/JSON
│   ├── validators.py              # Validate driver structure
│   ├── parsers.py                 # Extract metadata
│   └── models/                    # Driver domain models
│
├── reconciliation/                # State reconciliation (see reconciliation.md)
│   ├── diffs/                     # Diff computation
│   │   ├── comparison.py
│   │   ├── diffs.py
│   │   └── serializer.py
│   └── remediation.py             # Remediation strategies
│
├── backup/                        # Backup/restore (see backup-restore.md)
│   ├── service.py                 # Backup/restore service functions and STRATEGY_MAP
│   ├── scheduler.py               # Backup schedule management
│   └── strategies/                # disk / postgres / mariadb / mongodb / neo4j / action
│
├── helm/                          # Helm rendering helpers
│   ├── renderer.py                # render_helm_repository_spec / render_helm_chart_spec
│   └── _environment.py            # Jinja2 environment setup
│
├── workflow/                      # Prefect workflow execution wrapper
│   ├── __init__.py                # StyrminWorkflowExecutor (abstract)
│   ├── worker.py                  # WorkflowWorkerExecutor (concrete impl)
│   └── utils.py                   # Utilities
│
├── ingress_controller/            # Ingress controller lifecycle
│
├── scheduling/                    # Pod scheduling helpers
│
└── utilities/                     # Infrastructure utilities (ingress, etc.)
    └── utilities.py               # Utility management
```

## Unit of Work Pattern

The `UnitOfWork` pattern coordinates database operations across multiple repositories within a single async transaction. The abstract base lives in `services/unit_of_work.py`; the SQLModel implementation is `SqlModelUnitOfWork`, which is what the API layer wires up via dependency injection.

### Interface

```python
class UnitOfWork(ABC):
    session: AsyncSession

    backup_storage_locations: BackupStorageLocationRepository
    clusters: ClusterRepository
    environments: EnvironmentRepository
    helm_repositories: HelmRepositoryRepository
    helm_charts: HelmChartRepository
    component_configs: ComponentConfigRepository
    application_drivers: ApplicationDriverRepository
    application_driver_versions: ApplicationDriverVersionRepository
    application_instances: ApplicationInstanceRepository
    actions: ActionRepository
    utilities: UtilityRepository
    tasks: TaskRepository
    deployments: DeploymentRepository
    deployed_services: DeployedServiceRepository
    backups: BackupRepository
    restores: RestoreRepository
    backup_schedules: BackupScheduleRepository
    pod_statuses: PodStatusRepository
    deployment_statuses: DeploymentStatusRepository

    async def __aenter__(self) -> "UnitOfWork": ...
    async def __aexit__(self, type_, value, traceback) -> bool | None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...
```

`__aexit__` calls `rollback()` automatically when the `async with` block exits with an exception; otherwise services must call `await uow.commit()` explicitly.

### Usage Pattern

```python
async def some_operation(uow: UnitOfWork) -> Result:
    async with uow:
        entity = await uow.repository.get(id)
        entity.update(...)
        await uow.repository.save(entity)
        await uow.commit()
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
| `create_environment(name, cluster_id, uow, config=None)` | Create environment in cluster (name unique per cluster). Computes and persists capabilities. |
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
| `delete_deployment(deployment_id, uow)` | Request platform-driven teardown — see lifecycle below |

**Deployment Flow:**

1. Validate configuration
2. Find matching application driver version
3. Create deployment with components
4. Generate instance from deployment
5. Apply state via reconciliation
6. Return task for tracking

**Deployment Lifecycle (incl. tombstoning):**

<!-- Extracted from specs/008-deployment-deletion on 2026-05-02 -->

The platform-driven delete flow is intentionally **state-driven, not orchestration-driven** — no Prefect flow, no long-running task. The mutation is thin and every state transition is observed off the existing reconciliation cadence:

1. **Resolver** — `deleteDeployment(id)` calls `services.deployment.delete_deployment(uow)`, which:
   - Guards against `RESTORING` (raises `DeploymentRestoringError` → `DEPLOYMENT_RESTORING`).
   - Returns the existing in-flight `DELETE_DEPLOYMENT` task if the row is already `DELETING` (idempotent).
   - Raises `DeploymentNotFoundError` if the row is unknown OR `deleted_at IS NOT NULL` (intentional conflation, see ADR-017).
   - Otherwise patches `spec.deletionRequested = true` on the cluster-side `StyrminDeployment` CR via `kr8s` and creates a born-complete `DELETE_DEPLOYMENT` task (`status=success`, no `prefect_flow_run_id`) in the same UnitOfWork.
2. **Operator** — a `@kopf.on.update(field="spec.deletionRequested", new=True)` handler observes the flip and runs `_teardown_owned_resources` in reverse order (Services → HelmRelease → NetworkPolicies/Secrets), then issues a namespace delete.
3. **Reporter (active CR path)** — while teardown is in progress, the operator reports `displayState: Deleting`; the agent's status reporter (`agent/status/reporter.py`) maps it to `DeploymentState.DELETING`. The DB row's `deleted_at` is still NULL — `DELETING` rows remain visible in the default deployment list.
4. **Reporter (terminal transition)** — the `StyrminDeployment` CR is `scope: Namespaced` and lives in the deployment's own namespace, so deleting the namespace deletes the CR with it (see `dev/knowledge/agent/operator.md` § "Namespace co-location"). When the reporter sees DB `status == "deleting"` AND no CR present in the cluster, it synthesises a final `displayState: Deleted` report. The reporter is the **sole writer** of `Deployment.deleted_at`: it stamps `deleted_at = now()` atomically with the `DELETED` state flip in the same UnitOfWork commit, so readers cannot observe `status == DELETED` with `deleted_at IS NULL`.
5. **Janitor** — a separate `@kopf.timer` in `operator/janitor.py` reaps CRs that reached `phase: Deleted` more than `DELETED_CR_TTL_HOURS` (default 6h) ago. CRs stuck in `Deleting` are NEVER auto-reaped — they remain visible until human action resolves them.

A row with `deleted_at IS NOT NULL` is **tombstoned**: the cluster-side workload is gone, but the row, its timeline (Tasks), and any associated backups remain queryable. `Environment.deployments(includeDeleted: false)` excludes tombstoned rows by default; `deployment(id)` is unfiltered so direct-id lookups always succeed (forensic interface).

Name uniqueness is per `(environment_id, name)` and ignores tombstoned rows — see ADR-018 / `dev/knowledge/backend/data-models.md`.

### Application Drivers Service (`application_drivers.py`)

Read-side accessors for application drivers stored in the database.

| Function | Description |
|----------|-------------|
| `get_application_drivers(uow)` | List all application drivers |
| `get_application_driver(driver_id, uow)` | Fetch a driver by ID |

### Applications Service (`applications.py`)

Driver loading and application instantiation. The "loaders" pull a driver spec from a source (Git, local directory, or in-memory object), validate it, register its actions with Prefect, and persist the resulting `ApplicationDriver` / `ApplicationDriverVersion` rows.

| Function | Description |
|----------|-------------|
| `load_application_driver_from_object(driver_spec, uow, ...)` | Load a driver from an in-memory `DriverSpec` |
| `load_application_driver_from_git_repository(repository_url, branch, uow, ...)` | Clone a driver from Git and load it |
| `load_application_driver_from_local_directory(path, uow, ...)` | Load a driver from a local filesystem path |
| `instantiate_application(...)` | Instantiate an application from a loaded driver |

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

Renders Helm chart and repository specifications using Jinja2 templates loaded by `_environment.py`.

```python
def render_helm_repository_spec(
    repository_id: UUID,
    repository_url: str,
    repository_type: str = "oci",
) -> dict:
    """Render a Helm Repository specification."""

def render_helm_chart_spec(
    helm_chart_id: UUID,
    name: str,
    version: str,
    repository_id: UUID,
) -> dict:
    """Render a Helm Chart specification."""
```

These produce dicts ready to be embedded in a `HelmRelease` CRD spec. Driver values templates are rendered separately during context resolution.

## Workflow Services (`services/workflow/`)

This package wraps Prefect for the rest of the backend.

- `services/workflow/__init__.py` defines the abstract `StyrminWorkflowExecutor`.
- `services/workflow/worker.py` defines `WorkflowWorkerExecutor(StyrminWorkflowExecutor)`, the concrete implementation that submits flow runs via `arun_deployment` and waits for results.

## Utilities Service (`services/utilities/`)

Manages infrastructure utilities (e.g., Ingress controllers).

```python
def initialize_utilities():
    """Initialize built-in utilities on startup"""
```

## Exception Hierarchy

All service-layer exceptions inherit from `ServiceError`, which carries an `error_code` (string) and a `default_message` and is mapped to GraphQL extensions by the `StructuredErrorExtension` middleware. Defined in `services/exceptions.py`:

```text
ServiceError (base)
├── NoInstanceError
├── ServiceUnexpectedError
├── InvalidContextError
├── ApplicationDriverNotFoundError
├── ApplicationDriverVersionNotFoundError
├── ApplicationDriverVersionAlreadyExistsError
├── ClusterLimitReachedError
├── ClusterAlreadyExistsError
├── ClusterNotFoundError
├── EnvironmentAlreadyExistsError
├── EnvironmentNotFoundError
├── InvalidChartValuesError
├── ChartValuesTemplateRenderingError
├── InstanceNotFoundError
├── InconsistentStateError
├── InvalidVersionError
├── InvalidVersionSyntaxError
├── UnupgradableApplicationInstanceError
├── TaskNotFoundError
├── UnknownTaskStateError
├── DeploymentNotFoundError
├── DeploymentNameValidationError
├── DeploymentNameConflictError
├── IngressControllerNotHealthyError
├── InternalDeploymentError
├── ServiceNameConflictError
├── InvalidServiceOverrideError
├── BackupNotFoundError
├── BackupAlreadyInProgressError
├── BackupDuringUpgradeError
├── BackupDeletionError
├── RestoreNotFoundError
├── RestoreAlreadyInProgressError
├── BackupScheduleNotFoundError
├── BackupScheduleAlreadyExistsError
├── AmbiguousIdentifierError
├── BackupStorageLocationNotFoundError
├── BackupStorageLocationAlreadyExistsError
├── BackupStorageLocationInUseError
├── InvalidSchedulingConfigError
├── UnknownComponentInConfigError
├── UnresolvableAffinityReferenceError
└── SchedulingPatchRenderingError
```

## Key Files

| File | Purpose |
|------|---------|
| [services/unit_of_work.py](backend/styrmin_backend/services/unit_of_work.py) | Repository coordination |
| [services/deployment.py](backend/styrmin_backend/services/deployment.py) | Deployment orchestration |
| [services/applications.py](backend/styrmin_backend/services/applications.py) | Driver management |
| [services/reconciliation/remediation.py](backend/styrmin_backend/services/reconciliation/remediation.py) | State reconciliation |
| [services/driver/provider.py](backend/styrmin_backend/services/driver/provider.py) | Git-based driver loading |
