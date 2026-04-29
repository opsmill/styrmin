# Phase 1 Data Model: Match Pod Statuses to Driver Components

This feature adds **one field** at three layers; everything else is unchanged.

## 1. Database (`backend/styrmin_backend/db/models.py`)

`PodStatus` table gains:

```python
component_name: str | None = Field(default=None, nullable=True)
```

- **Type**: `VARCHAR` (no length cap — Kubernetes label values are at most 63 chars, but we don't need to enforce it; SQLModel's default `AutoString` is fine).
- **Nullability**: `NULL` allowed and is the default.
- **Default**: `None` — so existing rows after migration are `NULL` until rewritten by the next poll cycle.
- **No index**: lookups in this table are by `deployment_id` (existing index) or by `(deployment_id, pod_name)` (existing unique constraint). Filtering by component is a future feature; index can be added when it has a real query that needs it.
- **No foreign key** to `component.id`: per `research.md` §2, observed runtime state is recorded as-is.

### Alembic migration

Single revision, `add_component_name_to_pod_status`:

```python
def upgrade() -> None:
    op.add_column(
        "podstatus",
        sa.Column("component_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("podstatus", "component_name")
```

`down_revision` chains from the most recent existing revision (`f6a7b8c9d0e1_drop_available_runtime_classes` at time of writing — verify before committing).

## 2. Agent wire model (`backend/styrmin_backend/agent/status/models.py`)

`PodStatusData` gains:

```python
component_name: str | None = Field(default=None, alias="componentName")
```

- **Alias**: `componentName` — required because the field is sent over GraphQL with camelCase, and `PodStatusData` already uses `populate_by_name=True` plus aliased fields (`podName`, `restartCount`, etc.).
- **Default**: `None` — the agent omits the field for pods without the label.
- **Serialization**: `report.model_dump(by_alias=True)` produces `componentName` in the GraphQL payload; this is the existing pattern in `_report_pod_statuses_to_backend`.

## 3. GraphQL schema (`backend/styrmin_backend/api/definitions/pod_status/model.py`)

Both `PodStatus` (output type) and `PodStatusInput` (mutation input) gain:

```python
component_name: str | None = None
```

- Strawberry maps `component_name` → `componentName` in the public schema by default.
- `PodStatus.from_instance(...)` is updated to pass `component_name=instance.component_name`.

After regeneration:

- `schema.graphql` shows `componentName: String` on `type PodStatus` and `componentName: String = null` on `input PodStatusInput`.
- `python_sdk/src/styrmin_sdk/graphql/_generated/...` Pydantic types include `component_name: str | None = Field(alias="componentName")`.

## 4. Service layer (`backend/styrmin_backend/services/pod_status.py`)

`report_pod_statuses` — pass the value through:

```python
pod_status = PodStatus(
    ...
    component_name=pod_data.get("component_name"),
    ...
)
```

- The mutation resolver maps Strawberry input → dict → service. The keys reach the service in snake_case (existing convention; see how `node_name` is already passed). `component_name` follows the same path.
- No phase-style normalization (`_parse_phase`) needed — the field is a free-form string.

## 5. Extraction logic (`backend/styrmin_backend/agent/status/reporter.py`)

Inside `_extract_pod_data(pod)`:

```python
labels = (pod.metadata.labels or {}) if pod.metadata else {}
raw_component = labels.get("styrmin/component")
component_name = raw_component.strip() if raw_component and raw_component.strip() else None
```

- `pod.metadata.labels` may be `None` (k8s clients return `None` for absent map fields). Guard.
- Empty / whitespace values normalize to `None` (`research.md` §3).
- The `styrmin/component` literal matches `_COMPONENT_LABEL` in `services/scheduling/validator.py:27`; we're intentionally not reaching across modules to import that constant — its current home is unrelated to status reporting and pulling it in would create a coupling that doesn't exist today. Define the constant locally in `reporter.py` (or inline once) and treat any future consolidation as a separate cleanup.
