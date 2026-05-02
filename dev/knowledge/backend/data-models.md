# Backend Data Models Documentation

## Overview

The backend uses two types of models:

1. **Database Models** (`db/models.py`) - SQLModel ORM models for persistence
2. **Domain Models** (`domain/models.py`) - Pydantic models for business logic
3. **Context Models** (`context/models/`) - Pydantic models for deployment context

## Database Models

Located in `styrmin_backend/db/models.py`, these are SQLModel classes that map to database tables.

### Base Model

```python
class StyrminModel(SQLModel):
    id: UUID = Field(primary_key=True, default_factory=uuid4)
    created_on: datetime | None  # Auto-set on creation
    updated_on: datetime | None  # Auto-updated on modification
```

### Entity Relationship Diagram

```text
┌─────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│     Cluster     │──1:N─│   Environment    │──1:N─│   Deployment     │
└─────────────────┘      └──────────────────┘      └────────┬─────────┘
                                ▲                           │
                                │ N:1 (optional)            │
                  ┌─────────────┴────────────┐              │
                  │ BackupStorageLocation    │              │
                  └──────────────────────────┘              │
                                                            │
                ┌───────────────────┬───────────────────┬───┴────────────┬─────────────────────┐
                │                   │                   │                │                     │
          ┌─────▼─────┐       ┌─────▼─────┐       ┌────▼────────┐  ┌────▼────────┐    ┌───────▼────────┐
          │ Component │       │   Task    │       │ApplicationIns│  │ PodStatus   │    │DeploymentStatus│
          └───────────┘       └───────────┘       │    tance     │  │ (observed)  │    │  (observed)    │
                                                  └──────────────┘  └─────────────┘    └────────────────┘

┌─────────────────┐      ┌──────────────────────┐      ┌───────────────┐
│ApplicationDriver│──1:N─│ApplicationDriverVersion│──1:N─│    Action     │
└─────────────────┘      └─────┬─────────┬──────┘      └───────────────┘
                               │         │
                               │ 1:N     │ N:1
                               ▼         ▼
                       ┌─────────────┐ ┌─────────────┐      ┌─────────────────┐
                       │ComponentCfg │ │  HelmChart  │──N:1─│ HelmRepository  │
                       └─────────────┘ └─────────────┘      └─────────────────┘
```

`ApplicationDriverVersion` references a single `HelmChart` (N:1) and owns its own `ComponentConfig` rows (1:N). The chart and repository have no direct link to `ComponentConfig`.

### Infrastructure Models

#### Cluster

```python
class Cluster(StyrminModel, table=True):
    name: str = Field(unique=True)
    config: dict | None = Field(sa_column=Column(JSON))
    capabilities: dict | None = Field(sa_column=Column(JSON))  # Computed, hierarchical

    environments: list["Environment"]  # Relationship
```

#### Environment

```python
class Environment(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("name", "cluster_id"),)

    name: str  # Unique per cluster (not globally)
    config: dict | None = Field(sa_column=Column(JSON))
    capabilities: dict | None = Field(sa_column=Column(JSON))  # Computed, environment-scoped

    cluster_id: UUID = Field(foreign_key="cluster.id")
    cluster: Cluster  # Relationship
    deployments: list["Deployment"]  # Relationship
```

### Application Driver Models

#### ApplicationDriver

```python
class ApplicationDriver(StyrminModel, table=True):
    name: str = Field(unique=True)

    versions: list["ApplicationDriverVersion"]  # Relationship
```

#### ApplicationDriverVersion

```python
class ApplicationDriverVersion(StyrminModel, table=True):
    version: str
    application_supported_versions: str          # Semver specifier
    default_version: str | None = None           # Default app version when unspecified
    source_type: str = "git"                     # "git", "local", ...
    source_repository: str
    source_branch: str | None = None
    source_path: str | None = None               # Path within the source repo/dir
    components: dict | None = Field(sa_column=Column(JSON))
    parameters: list | None = Field(sa_column=Column(JSON))
    services: list | None = Field(sa_column=Column(JSON))

    application_driver_id: UUID
    helm_chart_id: UUID

    component_configs: list[ComponentConfig]    # Relationship
    actions: list[Action]                        # Relationship
    deployments: list["Deployment"]              # Relationship
```

#### Action

```python
class Action(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("name", "application_driver_version_id"),)

    name: str                                    # Unique per driver version (not globally)
    description: str
    location: str                                # Path to action code
    image: str | None
    hook: str | None                             # "setup" or "upgrade"
    mode: str | None                             # "pre", "core", or "post"

    application_driver_version_id: UUID
```

#### ComponentConfig

```python
class ComponentConfig(StyrminModel, table=True):
    name: str
    config: dict = Field(sa_column=Column(JSON))

    application_driver_version_id: UUID
```

### Helm Models

#### HelmRepository

```python
class HelmRepository(StyrminModel, table=True):
    url: str = Field(unique=True)

    helm_charts: list["HelmChart"]  # Relationship
```

#### HelmChart

```python
class HelmChart(StyrminModel, table=True):
    name: str
    version: str
    values_template: str  # Jinja2 template

    repository_id: UUID
```

### Deployment Models

#### Deployment

```python
class Deployment(StyrminModel, table=True):
    name: str = Field(unique=True)
    application_version: str
    config: dict | None = Field(sa_column=Column(JSON))
    parameters: dict | None = Field(sa_column=Column(JSON))
    internal: bool = Field(default=False)         # True for system deployments (e.g. ingress controller)
    status: DeploymentState
    deleted_at: datetime | None  # set ONLY on the DELETED transition (soft-delete tombstone)

    application_driver_version_id: UUID
    environment_id: UUID
    active_application_instance_id: UUID | None

    components: list[Component]                   # Relationship
    application_instances: list["ApplicationInstance"]  # Relationship
    deployed_services: list["DeployedService"]    # Relationship
    tasks: list["Task"]                           # Relationship
```

A deployment with `deleted_at IS NOT NULL` is **tombstoned**: the cluster-side workload (HelmRelease, services, namespace) has been torn down by the operator, but the platform record is retained so the timeline, backups, and audit trail remain queryable. The default `deployments(includeDeleted: false)` GraphQL filter excludes tombstoned rows from the deployment list while keeping `DELETING` rows visible (their `deleted_at` is `NULL` until the terminal transition).

**Name uniqueness scope**: `(environment_id, name)` only — and only among non-tombstoned rows. The DB-level gate is a partial unique index `uq_deployment_env_name_active` predicated on `deleted_at IS NULL`. This means: (a) the same name can be reused across different environments, (b) deleting `ansible` frees the name for a fresh `ansible` in the same env, and (c) the constraint is the authoritative race-free guard — service-layer name-conflict checks (`uow.deployments.get_by_name(name, environment_id)`) are best-effort pre-flights that map a constraint violation to a typed `DeploymentNameConflictError` instead of letting an `IntegrityError` bubble up.

#### ApplicationInstance

```python
class ApplicationInstance(StyrminModel, table=True):
    name: str = Field(unique=True)
    application_version: str
    status: InstanceStatus
    context: dict | None = Field(sa_column=Column(JSON))  # Serialized GlobalContext

    deployment_id: UUID
    application_driver_version_id: UUID
```

#### Component

```python
class Component(StyrminModel, table=True):
    name: str
    enabled: bool = True
    config: dict = Field(sa_column=Column(JSON))

    deployment_id: UUID
```

#### Task

```python
class Task(StyrminModel, table=True):
    status: TaskStatus
    type: TaskType
    message: str | None
    prefect_flow_run_id: UUID | None

    deployment_id: UUID
```

#### Utility

```python
class Utility(StyrminModel, table=True):
    kind: str                                    # e.g., "ingress", "service-discovery"
    resource_template: str = Field(default="")   # Jinja2 template producing K8s manifest(s)
```

### Observed State Models

These records capture *observed* runtime state — what the agent sees in the cluster — as opposed to the *declared* intent expressed by `Deployment` / `Component`. They are written by the agent's status reporter on each poll cycle (~5 s) and are intentionally decoupled from declared state: the server records what was observed and does not validate it against the deployment's current configuration. Drift between observed values and declared values is expected (rollouts, renames) and is not an error.

#### PodStatus

```python
class PodStatus(StyrminModel, table=True):
    __table_args__ = (UniqueConstraint("deployment_id", "pod_name"),)

    pod_name: str
    namespace: str
    phase: PodPhase
    ready: bool = False
    restart_count: int = 0
    container_statuses: list[dict] | None
    node_name: str | None
    component_name: str | None  # From the styrmin/component label, observed as-is
    started_at: datetime | None
    last_polled_at: datetime  # Server-set on every upsert

    deployment_id: UUID
```

- One row per `(deployment_id, pod_name)`, refreshed every reporting cycle. Rows are upserted by the `reportPodStatuses` GraphQL mutation, which is invoked by the agent's status reporter (see [`../agent/overview.md`](../agent/overview.md) → Status Reporter). Stale rows (pods no longer present in the agent's snapshot for a deployment) are removed **server-side** by `services/pod_status.py::report_pod_statuses`, which calls `delete_stale` on the repository — the agent only sends the active set.
- `component_name` is populated by the agent reading the `styrmin/component` label off pod metadata. It is recorded as-is — see [ADR-014](../../adr/adr-014-pod-status-records-observed-state-not-declared-state.md) for why the server does not validate it against declared `Component` rows.
- `last_polled_at` is rewritten on every upsert; downstream consumers can use it to detect stale data if the agent stops reporting.

#### DeploymentStatus

```python
class DeploymentStatus(StyrminModel, table=True):
    """Latest StyrminDeployment CRD status snapshot per deployment."""

    phase: str
    message: str | None
    conditions: list[dict] | None
    managed_resource_counts: dict | None
    last_polled_at: datetime

    deployment_id: UUID  # unique=True (one snapshot per deployment)
```

- One row per deployment. Mirrors the latest `StyrminDeployment` CRD `.status` block observed by the agent and written by the `reportDeploymentStatuses` mutation (handler: `services/deployment_status.py`).
- `phase`, `conditions`, `managed_resource_counts` are pass-through views of the CRD — the server does not interpret them.
- The wire payload from the agent carries two additional fields that are **not** persisted on this row but drive other state:
  - `displayState` — the operator's user-facing state (`Deploying`, `Running`, `Restoring`, `Error`, `Deleting`, `Deleted`). Mapped to a `DeploymentState` and written to the parent `Deployment.status` (sole source of truth for that column). On the terminal `Deleted` transition, the status reporter atomically stamps `Deployment.deleted_at = now()` — that is the ONLY code path that writes `deleted_at`.
  - `instanceId` — the `spec.instanceId` from the CRD at poll time. Used as a stale-instance guard: if it does not match `deployment.active_application_instance_id`, the `Deployment.status` update is skipped so a superseded instance cannot overwrite the status of the new one rolling out.

### Status Enums

```python
class DeploymentState(str, Enum):
    PENDING = "pending"
    DEPLOYING = "deploying"
    RUNNING = "running"
    RESTORING = "restoring"
    FAILED = "failed"
    DELETING = "deleting"  # platform-driven teardown in progress
    DELETED = "deleted"    # terminal — Deployment.deleted_at is set

class InstanceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

class TaskType(str, Enum):
    NOOP = "noop"                                # Reconciliation produced no remediation
    CREATE_INSTANCE = "create_instance"
    DELETE_INSTANCE = "delete_instance"
    UPDATE_INSTANCE = "update_instance"
    UPGRADE_INSTANCE = "upgrade_instance"
    STOP_COMPONENTS = "stop_components"
    START_COMPONENTS = "start_components"
    RUN_JOB = "run_job"
    DELETE_DEPLOYMENT = "delete_deployment"  # born-complete audit record

class PodPhase(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"  # Used when the observed phase doesn't match a known value
```

## Domain Models

Located in `styrmin_backend/domain/models.py`, these are Pydantic models used in business logic.

### Instance (Domain)

```python
class Instance(BaseModel):
    id: UUID
    name: str
    application_version: str
    status: InstanceStatus
    deployment_id: UUID
    application_driver_version_id: UUID
    context: GlobalContext

    @classmethod
    def create(cls, ...) -> Instance: ...
```

### Deployment (Domain)

```python
class Deployment(BaseModel):
    id: UUID
    name: str
    application_version: str
    config: dict | None
    application_driver_version_id: UUID
    environment_id: UUID
    status: DeploymentState

    # Private attributes
    _components: Dict[str, Component]
    _application_instance: Instance | None

    @property
    def components(self) -> list[Component]: ...
    @property
    def active_instance(self) -> Instance | None: ...

    def add_component(self, component: Component) -> None: ...
    def update_component(self, name: str, enabled: bool) -> None: ...
    def set_active_instance(self, instance: Instance | None) -> None: ...

    @classmethod
    def create(cls, ...) -> Deployment: ...
```

### Component (Domain)

```python
class Component(BaseModel):
    id: UUID
    name: str
    enabled: bool = True
    config: dict

    @classmethod
    def create(cls, name: str, config: dict, enabled: bool = True) -> Component: ...
```

### Task (Domain)

```python
class Task(BaseModel):
    id: UUID
    status: TaskStatus
    type: TaskType
    message: str | None
    prefect_flow_run_id: UUID | None
    deployment_id: UUID

    @classmethod
    def create(cls, type: TaskType, deployment_id: UUID, ...) -> Task: ...
```

## Context Models

Located in `styrmin_backend/context/models/`, these models represent the deployment context passed to Helm templates.

### GlobalContext

```python
class GlobalContext(BaseModel):
    cluster: ClusterContext
    environment: EnvironmentContext
    deployment: DeploymentContext
    instance: InstanceContext
    app: ApplicationContext
    labels: dict[str, Any] = {}
    components: ComponentsContext | None = None
    utilities: list[UtilityContext] = []
    parameters: dict[str, Any] = {}
    services: dict[str, Any] = {}
    deployed_services: list[dict[str, Any]] = []
```

### Context Hierarchy

```text
GlobalContext
├── ClusterContext
│   ├── config: ClusterConfig
│   └── capabilities: dict[str, Any]
├── EnvironmentContext
│   ├── name: str
│   ├── config: EnvironmentConfig
│   └── capabilities: dict[str, Any]
├── DeploymentContext
│   └── config: DeploymentConfig
├── InstanceContext
│   ├── config: ResolvedConfig (merged from all levels)
│   ├── id: UUID | None       (set when the CRD is authored — used for status correlation)
│   ├── deployment_id: UUID
│   ├── namespace: str
│   └── release_reference: str
├── ApplicationContext
│   ├── name: str
│   ├── version: str
│   └── helm: HelmInfo
├── ComponentsContext
├── utilities: list[UtilityContext]
├── parameters: dict[str, Any]
├── services: dict[str, Any]
└── deployed_services: list[dict[str, Any]]
```

### Configuration Models

```python
class ClusterConfig(BaseModel):
    # Cluster-level configuration

class EnvironmentConfig(BaseModel):
    # Environment-level configuration

class DeploymentConfig(BaseModel):
    # Deployment-level configuration

class ResolvedConfig(BaseModel):
    # Merged configuration from all levels
```

### HelmInfo

`HelmInfo` is composed of two nested objects rather than three plain strings:

```python
class ChartInfo(BaseModel):
    id: UUID
    name: str
    version: str
    values_template: str

class RepositoryInfo(BaseModel):
    id: UUID
    url: str

class HelmInfo(BaseModel):
    chart: ChartInfo
    repository: RepositoryInfo
```

### UtilityContext

```python
class UtilityKind(str, Enum):
    INGRESS = "ingress"
    SERVICE_DISCOVERY = "service-discovery"

class UtilityContext(BaseModel):
    kind: UtilityKind
```

`UtilityContext` carries only the kind. The corresponding utility row in the database (`Utility`) holds the `resource_template` used to render manifests; there is no `helm` field on `UtilityContext`.

## Key Files

| File | Purpose |
|------|---------|
| [db/models.py](backend/styrmin_backend/db/models.py) | Database ORM models |
| [domain/models.py](backend/styrmin_backend/domain/models.py) | Business logic domain models |
| [context/models/contexts.py](backend/styrmin_backend/context/models/contexts.py) | Deployment context models |
| [context/models/config.py](backend/styrmin_backend/context/models/config.py) | Configuration models |
| [context/models/helm.py](backend/styrmin_backend/context/models/helm.py) | Helm-related models |
