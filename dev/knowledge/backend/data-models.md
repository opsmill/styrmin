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

Not drawn: each `Step` row belongs to exactly one `Task`, `Backup` or `Restore` (N:1), and a `Task` can point at the `ApplicationInstance` it rolls out and at the `Step` that started it. See [Step](#step).

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
    # Identity is the tuple (application_driver_id, source_type,
    # source_repository, source_branch, source_path, version,
    # content_hash, source_commit_sha) -- enforced by the
    # uq_application_driver_version_identity UNIQUE index with
    # postgresql_nulls_not_distinct=True (so NULL fingerprints
    # compare equal). See specs/013-driver-fingerprint.

    version: str
    application_supported_versions: str          # Semver specifier
    default_version: str | None = None           # Default app version when unspecified
    source_type: str = "git"                     # "git", "local", ...
    source_repository: str
    source_branch: str | None = None
    source_path: str | None = None               # Path within the source repo/dir

    # Provenance fingerprint (spec 013). Exactly one is non-null on rows
    # created by the load path; the discriminator is ``source_type``.
    content_hash: str | None = None              # SHA-256 hex over canonical
                                                 # driver bytes (local source)
    source_commit_sha: str | None = None         # Resolved git commit SHA at
                                                 # the loaded ref (git source)

    components: dict | None = Field(sa_column=Column(JSON))
    parameters: list | None = Field(sa_column=Column(JSON))
    services: list | None = Field(sa_column=Column(JSON))

    application_driver_id: UUID
    helm_chart_id: UUID

    # cascade="all, delete-orphan" on both child relations (spec 013):
    # deleting an ApplicationDriverVersion atomically removes its
    # Action and ComponentConfig rows. ``deployments`` is intentionally
    # NOT cascaded -- deployments outlive their driver version.
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

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

`config` holds the component definition from the driver specification file
(`components.<name>`), including the optional **component container**
(`config["container"]`, a DNS-1123 label validated at driver registration). The definition is
copied into each deployment's `Component.config` on deploy and on a driver-version switch, so a
deployment's component container always follows its pinned driver version. The container has
no column of its own: it rides the existing JSON, read through `ComponentConfig.container` and
`Component.container` ([ADR-057](../../adr/0057-post-render-component-overrides.md) §1). Rows
stored before 017 carry no `container` key and count as containerless.

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

A deployment with `deleted_at IS NOT NULL` is **tombstoned**: the cluster-side workload (HelmRelease, services, namespace) has been torn down by the operator, but the platform record is retained so the timeline, backups, and audit trail remain queryable. The default `deployments(includeDeleted: false)` GraphQL filter excludes tombstoned rows from the deployment list while keeping `DELETING` rows visible (their `deleted_at` is `NULL` until the terminal transition). The list also excludes internal deployments unless the caller passes `includeInternal: true`.

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
    instance_id: UUID | None         # FK applicationinstance.id, ON DELETE SET NULL, indexed
    started_by_step_id: UUID | None  # FK step.id, ON DELETE SET NULL, indexed
```

- `status` follows only the Prefect flow run (through the `callback` mutation) and is what driver actions wait on. A `delete_deployment` task runs no flow: it is created with `status` `success`. `status` is not the result users view; see "Task result" below.
- `instance_id` is the instance the task rolls out. The `apply_state` service function sets it for every reconcile task, so operator reports, which carry the CR's `status.instanceId`, find their task. Several tasks can roll out the same instance; a report then goes to the newest of them (`find_by_instance` orders by `created_on`, newest first). Tasks that roll out no instance (`run_job`, `delete_deployment`) and tasks created before this column existed have `NULL`.
- `started_by_step_id` is the hook step whose driver action started the task through `stopComponents`, `startComponents` or `updateDeploymentVersion` (see [hooks-and-actions.md](hooks-and-actions.md#tasks-started-by-a-hook-step)). The foreign key is created with `use_alter=True`, because `step.task_id` points back at `task`.

#### Step

<!-- Extracted from specs/019-task-steps on 2026-10-06 -->

One unit of work inside a task, a backup or a restore: a run of a hook mode, a resource write, an operator phase, a command, a restore stage, or the backup of one component. The step recorder (`services/steps/recorder.py`) is the only code that creates or changes rows. See [ADR-060](../../adr/0060-steps-and-derived-task-result.md).

```python
class Step(StyrminModel, table=True):
    # Exactly one parent is set (check ck_step_one_parent); each FK is ON DELETE CASCADE.
    task_id: UUID | None
    backup_id: UUID | None
    restore_id: UUID | None

    key: str                          # Stable within the parent, e.g. "operator:helmrelease"
    name: str                         # What users view, e.g. "Install or upgrade the HelmRelease"
    kind: StepKind
    status: StepStatus

    started_at: datetime | None
    ended_at: datetime | None
    attempt_count: int = 0
    errors: list[dict] | None         # JSON: [{"attempt", "message", "occurred_at"}], oldest first

    detail: str | None                # FluxCD's current reason and message (HelmRelease step)
    rolled_back_at: datetime | None   # Newest FluxCD rollback of the HelmRelease step
    rollback_message: str | None

    output: str | None                # TEXT: end of a failed command's output
    output_truncated: bool = False    # server_default false

    superseded_by_task_id: UUID | None  # FK task.id, ON DELETE SET NULL, indexed
```

- Three partial unique indexes, `uq_step_task_id_key`, `uq_step_backup_id_key` and `uq_step_restore_id_key`, make `(parent, key)` unique for each parent type. The recorder opens a step with `INSERT … ON CONFLICT DO NOTHING`, so opening the same step twice is harmless.
- Deleting a task, backup or restore deletes its steps. Steps live as long as their parent; there is no separate retention.
- `StepStatus` and `StepKind` are PostgreSQL enum types that store the upper-case member names (`PENDING`, `OPERATOR_PHASE`), like the other `SQLModelEnum` columns.
- State rules: `succeeded` and `superseded` are final. `failed` is final except for `OPERATOR_PHASE` steps, which can run again or succeed with a new attempt. The recorder logs and ignores a forbidden transition, and never sets `ended_at` before `started_at`.
- Reads order steps by `started_at` with nulls last, then `created_on`.
- The `step` table, the two `task` columns and the enum types ship in the Alembic revision `e2f3a4b5c6d7` (`e2f3a4b5c6d7_add_steps.py`). The downgrade drops the `task` columns and their foreign keys first, then the table and the enum types.

Step keys and names are defined in `domain/steps.py`; [orchestration-flows.md](orchestration-flows.md#remediation-flow-steps) and [backup-restore.md](backup-restore.md#backup-and-restore-steps) list them.

#### Task result

The task result (`RUNNING`, `FAILED`, `SUCCEEDED`, `SUPERSEDED`) is calculated from the steps and `Task.status` on every read (`services/steps/results.py`) and never stored. It covers the task's family: the task and every task that its steps started, at any depth. The first rule that matches gives the result:

1. `RUNNING` when the `Task.status` of a family member is `pending` or `running`, or a step of the family is running, or is pending and its own task has no failed step.
2. `FAILED` when the `Task.status` of a family member is `failed`, or a step of the family failed.
3. `SUPERSEDED` when a step of the family was superseded by a task outside the family.
4. `SUCCEEDED` otherwise.

`Task.status` counts in addition to the steps, because a flow can fail, or still run, between two steps (for example, `apply_state` fails after "Plan the changes" succeeded and before the remediation flow records a step). A member whose flow succeeded (`success`) counts by its steps only, so the operator-phase steps keep a task `RUNNING` after its flow ended. A family member without steps counts by its `Task.status` only. See [ADR-060](../../adr/0060-steps-and-derived-task-result.md).

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
- `component_name` is populated by the agent reading the `styrmin/component` label off pod metadata. It is recorded as-is — see [ADR-007](../../adr/0007-pod-status-records-observed-state-not-declared-state.md) for why the server does not validate it against declared `Component` rows.
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
  - `displayState` — the operator's user-facing state (`Deploying`, `Running`, `Restoring`, `Error`, `Deleting`, `Deleted`). Mapped to a `DeploymentState` and written to the parent `Deployment.status` (sole source of truth for that column). A `Running` report is not written while the task that rolls out the reported instance, or the task whose hook step started it, is pending or running (#405). On the terminal `Deleted` transition, the status reporter atomically stamps `Deployment.deleted_at = now()` — that is the ONLY code path that writes `deleted_at`.
  - `instanceId` — the CR's `status.instanceId` at poll time: the instance whose spec the operator last handled. The status reporter falls back to `spec.instanceId` for a CR that no operator handler has touched since the upgrade that added the field. Used as a stale-instance guard: if it does not match `deployment.active_application_instance_id`, the `Deployment.status` update is skipped so a superseded instance cannot overwrite the status of the new one rolling out. The operator phase history (`services/steps/operator_history.py`) also uses it to find the task whose operator-phase steps the report moves (`Task.instance_id`).

### Status Enums

> **Source of truth**: `backend/styrmin_backend/db/models.py` (DB) and `backend/styrmin_backend/domain/models.py` (domain). When you add, rename, or remove a value in either of those files, update this snippet too — propagation tests catch wire-format drift but not stale documentation.

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
    NOOP = "noop"                                # Default of apply_state; reconcile tasks created before spec 019
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

class StepStatus(str, Enum):
    PENDING = "pending"        # Expected, not started
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"  # A later task interrupted it

class StepKind(str, Enum):
    PLAN = "plan"
    HOOK = "hook"
    RESOURCE_WRITE = "resource_write"
    OPERATOR_PHASE = "operator_phase"  # The only kind the operator phase history changes
    COMMAND = "command"
    RESTORE = "restore"
    BACKUP_COMPONENT = "backup_component"
```

`TaskResult` (`RUNNING`, `FAILED`, `SUCCEEDED`, `SUPERSEDED`) and `StepEvent` (`STARTED`, `SUCCEEDED`, `FAILED`, `OUTPUT`) exist only in `domain/models.py` and the GraphQL schema; neither is stored.

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

## Auth & Authorization

The `user`, `group`, `user_group`, and `session` tables ship in #179 (see [ADR-016](../../adr/0016-authentication-and-sessions.md) and [ADR-017](../../adr/0017-authorization-model.md) for column-level schema and rationale). Feature 011 introduces **no** schema changes; the notes below describe how the admin mutation surface consumes the existing tables.

### Effective role

Authorization checks MUST consume `User.effective_role`, not `User.role`. The effective role is computed as:

```python
effective_role = max(user.role, max((g.role for g in user.groups), default=Role.READ_ONLY))
```

A user with direct role `READ_WRITE` who belongs to a group whose role is `ADMIN` has effective role `ADMIN`. The frontend `<IfRole>` gate and the backend `RequiresRole` check both read `effective_role`. Raw `role` is only meaningful as one of the inputs to that computation; reading it directly skips the group-conferred path and is a bug.

### User lifecycle when FK references exist

The user lifecycle prioritises **deactivation over deletion** whenever attribution history must be preserved:

- `updateUser(setActive: false)` is always permitted (subject to the last-admin guard). It invalidates all of the target's sessions in the same transaction and stops them logging back in, but leaves the row intact so `deployment.created_by_user_id` and similar FKs remain resolvable.
- `deleteUser(userId)` only succeeds when **no** FK references point to the user. If any do, the mutation rejects with `USER_HAS_REFERENCES` and the admin is expected to use `updateUser(setActive:false)` instead. The presence of `Deployment.created_by_user_id` referencing the target is the dominant trigger in practice.

The last-admin invariant applies to **both** lifecycle paths: deactivating, deleting, demoting, or removing-from-admin-group any user that is the sole remaining active admin (including the admin acting on themselves) raises `LAST_ADMIN`. See [`services.md` → Authorization helpers](services.md) for the pure-function guard.

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
    instance_id: UUID | None
    started_by_step_id: UUID | None

    @classmethod
    def create(cls, type: TaskType, deployment_id: UUID, ...) -> Task: ...
```

### Step (Domain)

`Step` mirrors the table, with the three parent ids grouped in a frozen `StepParent` (a validator requires exactly one) and `errors` as a list of `StepError(attempt, message, occurred_at)`. `StepParent.of_task`, `of_backup` and `of_restore` build a parent from one id.

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

<!-- Extracted from specs/001-external-dns-endpoints-type on 2026-05-17 -->

All four config classes inherit from `BaseConfigSection`, which holds the shared operator-tunable fields. The inheritance graph is:

```text
BaseConfigSection                      # shared field set + ConfigDict(extra="forbid")
├── ClusterConfig
├── EnvironmentConfig
└── DeploymentConfig                   # multi-inherits ClusterConfig + EnvironmentConfig
    └── ResolvedConfig                 # output of the Cluster → Environment → Deployment merge
```

`BaseConfigSection` carries the external-routing and platform-tunable knobs (representative subset):

| Field | Type | Notes |
|-------|------|-------|
| `ingress_class` | `str \| None` | e.g. `"traefik"` |
| `fqdn_suffix` | `str \| None` | DNS zone for FQDN construction; see [ADR-022](../adr/0022-compute-service-fqdns-at-runtime.md) |
| `external_url_scheme` | `Literal["http", "https"] \| None` | |
| `external_url_port` | `int \| None` | validated 1..65535 |
| `external_dns_endpoints_type` | `Literal["NodeExternalIP", "ClusterIP"] \| None` | drives the `external-dns.alpha.kubernetes.io/endpoints-type` annotation; required for IPv6/dual-stack clusters with Cloudflare |
| `db_size` | `str \| None` | |
| `scheduling` | `SchedulingConfig \| None` | nested object with affinity / tolerations / resource requirements |

The merge (`_resolve_instance_config` in `context/resolvers.py`) uses generic `**model_dump(exclude_none=True)` dict-spread with deepest-wins precedence: Cluster value → Environment value (if set) → Deployment value (if set). Any new field added to `BaseConfigSection` propagates through this merge automatically — see [ADR-029](../adr/0029-config-additions-via-baseconfigsection-no-migration.md) for the no-migration / no-GraphQL-change pattern that backs additive config work, and [`dev/guidelines/backend/python.md` → Rendering Kubernetes manifests](../../guidelines/backend/python.md#no-runtime-defaults-for-optional-emitted-annotations) for the "emit only when set" discipline that preserves byte-identical output for existing deployments.

```python
class ClusterConfig(BaseConfigSection):
    # Cluster-level: standard_storage, plus the BaseConfigSection fields above

class EnvironmentConfig(BaseConfigSection):
    # Environment-level: ip_whitelist, dedicated_ingress, env_vars, plus BaseConfigSection

class DeploymentConfig(ClusterConfig, EnvironmentConfig):
    # Deployment-level: components, service_name_overrides, plus everything inherited

class ResolvedConfig(DeploymentConfig):
    # Merged configuration the renderer actually reads from
```

#### DedicatedIngressConfig

`dedicated_ingress` turns on the dedicated ingress controller for an environment (the internal `styrmin-ingress-controller` deployment). The environment value wins over the cluster value.

- An absent or `null` key turns it off. No controller is deployed, and the agent sets `spec.ingressClassName` and the `kubernetes.io/ingress.class` annotation on the application Ingress to the resolved `ingress_class`.
- Any object, including `{}`, turns it on with the default values: `implementation: traefik`, `type: ingress`, `service.type: LoadBalancer`. The agent sets the `kubernetes.io/ingress.class` annotation to the implementation name and removes `ingress_class` from the values-template context.

The controller check (`_resolve_dedicated_ingress` in `services/deployment.py`), the agent and the capability derivation all apply this rule. `createCluster` stores no default value. Earlier versions stored `{}`, which the controller check read as off and the agent read as on ([#409](https://github.com/opsmill/styrmin/issues/409)). The Alembic revision `f3a4b5c6d7e8` removes that `{}` from clusters. It keeps `{}` on environments, because an operator set it there.

#### IngressServiceConfig

<!-- Extracted from specs/001-ingress-ipfamily-nodeport on 2026-05-17 -->

Nested under `EnvironmentConfig.dedicated_ingress.service` (and the equivalent path in cluster/deployment config when an operator overrides dedicated ingress at those layers). Travels through the same JSON-blob path as the rest of `dedicated_ingress` — no DB / GraphQL surface of its own.

| Field | Type | Notes |
|-------|------|-------|
| `type` | `Literal["ClusterIP", "NodePort", "LoadBalancer"] \| None` | Kubernetes Service type |
| `annotations` | `dict[str, str] \| None` | extra Service annotations |
| `load_balancer_ip` | `str \| None` | pinned LB IP when `type == "LoadBalancer"` |
| `external_traffic_policy` | `Literal["Local", "Cluster"] \| None` | source-IP preservation knob |
| `ip_families` | `list[Literal["IPv4", "IPv6"]] \| None` | maps to `service.ipFamilies` in the Traefik chart |
| `ip_family_policy` | `Literal["SingleStack", "PreferDualStack", "RequireDualStack"] \| None` | maps to `service.ipFamilyPolicy` |
| `node_port` | `int \| None` | per-entrypoint pin (`ports.web.nodePort` + `ports.websecure.nodePort`); only valid when `type == "NodePort"` |

Two cross-field invariants are enforced at Pydantic-parse time:

- `@field_validator("ip_families")` — list must be non-empty and contain no duplicates.
- `@model_validator(mode="after")` — `node_port` is only accepted when `type == "NodePort"`. The `ValidationError` names both fields so the operator can correct either side.

Existing models in the same file follow the same idiom (`DeploymentReference._require_one_identifier`, `WeightedAffinityTerm._weight_range`, `ResourceSpec._validate_quantities`). All new fields are rendered with `{% if … %}` guards in the chart-values template — when unset, the chart sees the key as absent (not `null`), preserving byte-identical output for existing deployments per the [emit-only-when-set rule](../../guidelines/backend/python.md#no-runtime-defaults-for-optional-emitted-annotations).

#### SchedulingConfig

<!-- Extracted from specs/001-pod-scheduling-config on 2026-05-17 -->

Top-level scheduling shape used at Environment, Deployment, and Component scopes (Cluster scope is intentionally unused — see [ADR-033](../adr/0033-scheduling-merge-semantics.md)). Lives on `BaseConfigSection.scheduling`.

```python
class SchedulingConfig(BaseModel):
    affinity: AffinityConfig | None = None        # podAffinity / podAntiAffinity / nodeAffinity, each with required + preferred
    tolerations: list[Toleration] | None = None
    topology_spread: list[TopologySpreadConstraint] | None = None
    resources: ResourceSpec | None = None          # requests + limits (see below)
    node_selector: dict[str, str] | None = None
    runtime_class: str | None = None               # DNS-1123 subdomain validated; no rollout-time check — unknown classes surface as Pending pods at scheduling time
    inject: PostRenderInjection | None = None      # per-feature opt-out booleans
```

**Merge precedence**: Environment → Deployment → Component, walking levels in order. Most fields follow deepest-wins; affinity and topology-spread have richer merge semantics (see [ADR-033](../adr/0033-scheduling-merge-semantics.md)). The resolver records per-field source in a parallel `provenance: dict[str, "environment" | "deployment" | "component"]` map (see [ADR-036](../adr/0036-scheduling-provenance-map.md)).

**ResourceSpec** has `requests` and `limits`, each shaped:

```python
class ResourceQuantitySet(BaseModel):
    cpu: str | None = None                # first-class, autocompleted, quantity-validated
    memory: str | None = None
    ephemeral_storage: str | None = None
    extended: dict[str, str] = {}         # hugepages, nvidia.com/gpu, vendor resources; quantity-validated keys
```

See [ADR-032](../adr/0032-resourcespec-first-class-plus-extended-map.md) for the first-class / extended split.

**PostRenderInjection** carries six independent booleans defaulting to `True`: `pod_affinity`, `node_affinity`, `topology_spread`, `resources`, `tolerations`, `runtime_class`. A `False` value tells the post-renderer to leave that feature untouched. Opt-out is expressible at deployment and component scopes (not environment); component-level takes precedence over deployment-level. See [ADR-035](../adr/0035-post-render-injection-toggles-and-kind-list.md) for the toggle semantics and the static pod-template-bearing kind list the injection patches target (`Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `ReplicaSet`).

**Affinity-by-deployment-reference**: scheduling rules that reference another deployment by platform-id are expanded at resolve time into a `labelSelector` against the `styrmin/deployment_id` pod label that the `TemplateLabelPatch` pipeline stamps on every platform-managed pod-template-bearing resource. See [ADR-034](../adr/0034-affinity-by-deployment-reference-via-label.md).

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

### ServiceReference

<!-- Extracted from specs/001-service-fqdn-context on 2026-05-17 -->

Template-facing model for a service in the deployment context. Accessed by driver templates as `{{ services['name'].primary_fqdn }}`.

```python
class ServiceReference(BaseModel):
    host: str
    port: int
    kind: str                              # http / https / tcp / udp
    url: str                               # computed from kind + host + port
    primary_fqdn: str | None = None        # UUID-based: {sanitized-app}-{deployment-id}.{suffix}
    human_readable_fqdn: str | None = None # env-based: {sanitized-host}-{sanitized-env}.{suffix}
```

Both FQDN fields default to `None` when `ResolvedConfig.fqdn_suffix` is unset. When set, every label component is RFC 1035–safe (lowercase, alphanumeric/hyphen, ≤63 chars). FQDNs are **computed**, not persisted — there is no DB column. See [ADR-022](../adr/0022-compute-service-fqdns-at-runtime.md).

## Key Files

| File | Purpose |
|------|---------|
| [db/models.py](backend/styrmin_backend/db/models.py) | Database ORM models |
| [domain/models.py](backend/styrmin_backend/domain/models.py) | Business logic domain models |
| [domain/steps.py](backend/styrmin_backend/domain/steps.py) | Step keys, names and kinds; output limits (200 lines, 64 KiB) |
| [repository/steps.py](backend/styrmin_backend/repository/steps.py) | Step data access (`insert_if_absent`, ordered lists, open operator-phase steps of a deployment) |
| [services/steps/results.py](backend/styrmin_backend/services/steps/results.py) | Task result calculation |
| [db/migrations/versions/e2f3a4b5c6d7_add_steps.py](backend/styrmin_backend/db/migrations/versions/e2f3a4b5c6d7_add_steps.py) | Alembic revision for `step`, `task.instance_id` and `task.started_by_step_id` |
| [context/models/contexts.py](backend/styrmin_backend/context/models/contexts.py) | Deployment context models |
| [context/models/config.py](backend/styrmin_backend/context/models/config.py) | Configuration models |
| [context/models/helm.py](backend/styrmin_backend/context/models/helm.py) | Helm-related models |
