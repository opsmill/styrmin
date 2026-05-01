# Data Model: Deployment Deletion

## Database (PostgreSQL via SQLModel)

### `deployment` table

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `deleted_at` (NEW) | `timestamptz` | YES | `NULL` | Set **only** on `status` transition into `DELETED` by the status reporter, inside the same UnitOfWork as the status update. Indexed (`btree`) to keep the default-list filter fast. |

Existing columns unchanged. Existing relationships (`backups`, `tasks`, `pod_statuses`, `deployed_services`, `application_instances`, `crd_status`, `components`) **must not** add cascade-delete rules for this feature — backups and timeline data are intentionally retained against tombstoned deployments.

#### `DeploymentState` enum (additions)

```python
class DeploymentState(str, Enum):
    PENDING    = "pending"
    DEPLOYING  = "deploying"
    RUNNING    = "running"
    RESTORING  = "restoring"
    FAILED     = "failed"
    DELETING   = "deleting"   # NEW — teardown in progress
    DELETED    = "deleted"    # NEW — terminal, requires deleted_at IS NOT NULL
```

**Invariants** (enforced at the service / status-reporter layer; not as DB CHECK constraints, to keep migrations cheap):

1. `status == DELETED` ⇔ `deleted_at IS NOT NULL`
2. Transitions into `DELETED` go through `DELETING`. The status reporter is the single writer of both transitions.
3. `DELETED` is terminal — no path back to any other state.

### `task` table

#### `TaskType` enum (additions)

```python
class TaskType(str, Enum):
    NOOP              = "noop"
    CREATE_INSTANCE   = "create_instance"
    DELETE_INSTANCE   = "delete_instance"
    UPDATE_INSTANCE   = "update_instance"
    UPGRADE_INSTANCE  = "upgrade_instance"
    STOP_COMPONENTS   = "stop_components"
    START_COMPONENTS  = "start_components"
    RUN_JOB           = "run_job"
    DELETE_DEPLOYMENT = "delete_deployment"   # NEW
```

`DELETE_DEPLOYMENT` tasks are **born `TaskStatus.SUCCESS`** with `prefect_flow_run_id IS NULL`. They exist solely as audit / timeline records.

### Migration

Single Alembic migration `<revision>_deployment_deletion.py`:

1. `op.add_column("deployment", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))`.
2. `op.create_index("ix_deployment_deleted_at", "deployment", ["deleted_at"])`.
3. Extend `DeploymentState` enum with `DELETING`, `DELETED` (Postgres `ALTER TYPE ... ADD VALUE IF NOT EXISTS`).
4. Extend `TaskType` enum with `DELETE_DEPLOYMENT`.
5. **No backfill** — existing rows have `deleted_at = NULL` and `status` unchanged; semantics are preserved.

The migration runs cleanly on a non-empty database without any data backfill or downtime windows.

## Domain Layer (`backend/styrmin_backend/domain/models.py`)

Mirror the new enum values and the `deleted_at` field on the domain `Deployment` model. The domain model is the source of truth that flows up to the GraphQL definition layer.

```python
class DeploymentState(str, Enum):
    ...  # mirror DB enum
    DELETING = "deleting"
    DELETED  = "deleted"

class TaskType(str, Enum):
    ...
    DELETE_DEPLOYMENT = "delete_deployment"

@dataclass
class Deployment:
    ...
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.status == DeploymentState.DELETED

    def can_be_deleted(self) -> bool:
        # See R5 in research.md for the full state-guard table.
        return self.status not in {DeploymentState.RESTORING, DeploymentState.DELETED}
```

## CRD (`StyrminDeployment`, `helm/agent/crds/styrmin.io_styrmindeployments.yaml`)

### `spec.deletionRequested` (NEW)

```yaml
spec:
  type: object
  properties:
    ...
    deletionRequested:
      type: boolean
      default: false
      description: |
        Set to true by the Styrmin backend to request teardown of all owned
        resources. The operator reconciles the flip and progresses the CR
        through phase: Deleting -> Deleted. Immutable once true (CEL rule).
  x-kubernetes-validations:
    - rule: "!has(oldSelf.deletionRequested) || oldSelf.deletionRequested == false || self.deletionRequested == true"
      message: "deletionRequested cannot be set back to false once true"
```

CEL details:

- The `!has(oldSelf.deletionRequested)` clause handles CRs created before this field existed (default-false at read time but absent on the original object).
- `oldSelf.deletionRequested == false || self.deletionRequested == true` enforces monotonicity.
- Requires Kubernetes ≥ 1.25 (already the project baseline; no version bump).

### `status.phase` enum (additions)

```yaml
phase:
  type: string
  enum:
    - Pending
    - CreatingPrerequisites
    - CreatingHelmRelease
    - CreatingServices
    - Ready
    - Restoring
    - Failed
    - Deleting          # already present
    - Deleted           # NEW (terminal)
```

### `status.displayState` enum (additions)

```yaml
displayState:
  type: string
  enum:
    - Deploying
    - Running
    - Restoring
    - Error
    - Deleting          # NEW
    - Deleted           # NEW
```

### `status.conditions` — new condition type

The reconciliation handler already emits structured conditions; the only addition for this feature is a new `type: "Deleted"` condition whose `lastTransitionTime` the janitor reads to determine TTL eligibility.

## CRD-side Pydantic models (`operator/crd/schema.py`)

```python
class DeploymentPhase(StrEnum):
    PENDING = "Pending"
    CREATING_PREREQUISITES = "CreatingPrerequisites"
    CREATING_HELM_RELEASE  = "CreatingHelmRelease"
    CREATING_SERVICES = "CreatingServices"
    READY     = "Ready"
    RESTORING = "Restoring"
    FAILED    = "Failed"
    DELETING  = "Deleting"
    DELETED   = "Deleted"   # NEW

class DisplayState(StrEnum):
    DEPLOYING = "Deploying"
    RUNNING   = "Running"
    RESTORING = "Restoring"
    ERROR     = "Error"
    DELETING  = "Deleting"  # NEW
    DELETED   = "Deleted"   # NEW

class ConditionType(StrEnum):
    ...
    DELETED = "Deleted"     # NEW

class StyrminDeploymentSpec(BaseModel):
    ...
    deletion_requested: bool = Field(default=False, alias="deletionRequested")  # NEW
```

## Cluster retention configuration

```python
# operator/config.py (new constant)
DELETED_CR_TTL_HOURS: int = int(os.environ.get("DELETED_CR_TTL_HOURS", "6"))
```

- Read once at module import time (operator boot).
- Per-cluster (per managed cluster); not per-deployment.
- Janitor uses this value as the threshold against `status.conditions[type=Deleted].lastTransitionTime`.

## Timeline event type

`DeploymentTimelineEvent` rendering is driven by the originating `Task.type`. Adding `DELETE_DEPLOYMENT` to the renderer pipeline (string label, icon class) is the only frontend-facing timeline change. The domain model itself doesn't need a new dataclass — it reads from `Task` rows.

## Foreign-key behaviour summary (no changes required)

| Relation | Behaviour on `deleted_at IS NOT NULL` | Why |
|----------|----------------------------------------|-----|
| `Backup -> Deployment` (via `ApplicationInstance`) | survives, queryable | Spec FR-012 retention guarantee |
| `Task -> Deployment` | survives, queryable | Audit trail |
| `DeploymentTimelineEvent -> Deployment` (via Task) | survives, queryable | Audit trail |
| `PodStatus -> Deployment` | survives but truthfully empty over time | Pods are gone with the namespace; rows are stale and harmless |
| `DeployedService -> Deployment` | survives | Read-only — used for historical service introspection |
| `DeploymentStatus -> Deployment` | survives, last `Deleted` snapshot retained until janitor reaps the CR | Forensic dashboard |

No FK cascade rules are added or modified.
