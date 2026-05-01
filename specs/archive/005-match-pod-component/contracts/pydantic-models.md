# Pydantic Models Contract (Agent Wire)

The agent's pod-status payload is defined by `backend/styrmin_backend/agent/status/models.py`. The changes below are the only surface-area edits in that file.

## `PodStatusData`

```python
class PodStatusData(BaseModel):
    """Matches GraphQL ``PodStatusInput``."""

    model_config = ConfigDict(populate_by_name=True)

    pod_name: str = Field(alias="podName")
    namespace: str
    phase: PodPhase
    ready: bool
    restart_count: int = Field(alias="restartCount")
    container_statuses: list[dict] | None = Field(default=None, alias="containerStatuses")
    node_name: str | None = Field(default=None, alias="nodeName")
    started_at: str | None = Field(default=None, alias="startedAt")
    component_name: str | None = Field(default=None, alias="componentName")  # NEW
```

### Serialization

```python
report.model_dump(by_alias=True)
# {
#   "podName": "...", "namespace": "...", ...
#   "componentName": "api"   # or null when absent
# }
```

### Validation invariants

- `component_name = None` is valid and is the default.
- `component_name = ""` parses as `""` (Pydantic does not coerce). The agent normalizes to `None` *before* constructing `PodStatusData`, so the wire never carries empty strings — see `data-model.md` §5. Tests must assert this normalization.

## No other model changes

`DeploymentPodStatusReport`, `ReportPodStatusesResponse`, `CrdConditionData`, etc. — unchanged.

## SDK regeneration target

After `uv run invoke generate`, expect updated Pydantic types in:
- `python_sdk/src/styrmin_sdk/graphql/_generated/get_pod_statuses.py` — `GetPodStatusesPodStatuses` gains `component_name: str | None = Field(alias="componentName")`.
- `python_sdk/src/styrmin_sdk/graphql/_generated/get_deployment_pod_statuses.py` — same.
- `python_sdk/src/styrmin_sdk/graphql/_generated/input_types.py` (or wherever the `PodStatusInput` model lives) — gains the same field.
