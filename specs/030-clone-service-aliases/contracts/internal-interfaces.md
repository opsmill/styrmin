# Internal Interfaces: A Clone Writes Its Own Service Aliases and Restores None of the Source's

The fix changes no GraphQL schema, CLI command or SDK method. These are the internal interfaces that change. Paths are under `backend/styrmin_backend/`.

## Velero Restore model (`agent/service/kubernetes/velero/resources.py`)

### `VeleroRestore.label_selector: dict[str, Any] | None = None` (new field)

`render()` writes it as `spec.labelSelector` when it is not `None`, and leaves the key out otherwise.

## Restore builder (`agent/service/kubernetes/resources/builders/backup.py`)

### `build_velero_restore(...) -> VeleroRestore` (changed)

Signature unchanged. When `source_namespace != target_namespace`, the result also has:

```python
label_selector = {
    "matchExpressions": [
        {"key": SERVICE_ALIAS_LABEL, "operator": "NotIn", "values": ["true"]}
    ]
}
```

A new module constant names the selector, next to `CROSS_TARGET_EXCLUDED_RESOURCES`, with a one-line comment giving the reason (#530).

## Alias step (`agent/tasks/service_aliases.py`)

### `apply_service_aliases_step(reporter: StepReporter, context: GlobalContext) -> None` (moved, async)

Moved from `agent/tasks/orchestration.py` (`_apply_service_aliases_step`), behaviour unchanged:

1. `context = await with_current_peer_services(context)`;
2. `aliases = compute_service_aliases(context)`, `stale = await find_stale_service_aliases(context)`;
3. returns without a step when both are empty;
4. otherwise runs `apply_service_aliases(aliases=aliases, stale_aliases=stale)` inside `reporter.step(*steps.SERVICE_ALIASES)`, which records the step and re-raises a failure.

Callers: `create_instance_crd`, `update_instance_crd`, `upgrade_instance_crd` (`agent/tasks/orchestration.py`) and `execute_velero_restore_flow` (`workflows/templates/backup.py`).

## Restore flows (`workflows/templates/backup.py`)

### `execute_restore_workflow(restore_id, backup_id, deployment_id, target_namespace, source_deployment_id=None)` (INTERNAL, unchanged)

The signature and the parameters that it sends to the USER flow do not change. For a cross-target restore, it passes `counterpart_crd_body`, which `_build_counterpart_crd_body` renders from the context of the counterpart's active instance and which holds that context under `spec.context`. For an in-place restore, `counterpart_crd_body` stays `None`. Because the USER flow reads the counterpart's context from the body, no second parameter carries it.

### `execute_velero_restore_flow(..., counterpart_crd_body=None) -> dict` (USER, changed)

Signature unchanged. When `counterpart_crd_body` is not `None`, the flow reads the counterpart's context with `GlobalContext.model_validate(counterpart_crd_body["spec"]["context"])` before it deletes the namespace. A body without `spec.context` raises `KeyError`, and a context that does not validate raises `pydantic.ValidationError`; either fails the flow before it changes anything in the cluster. After "Run the recovery" succeeds, for a cross-target restore only:

- calls `apply_service_aliases_step(reporter, context)` with the context read from the body;
- on an exception: stores `recovery = {"recovered": False, "error": "Service alias step failed: <error>"}` in the result variable. It does not call `mark_failed` (research R-004).

The result variable keeps its shape: `{"status": {...}, "recovery": {"recovered": bool, "error": str | None}}`.

## Clone entry fold (`services/backup/clone.py`)

### `CLONE_REASON_RESTORE_FAILED = "the restore failed"` (new constant)

### `failed_restore(restore_id: UUID | None, restores: Mapping[UUID, Restore]) -> Restore | None` (new, pure)

The row of `restore_id` when it is in `restores` and its status is `RestoreStatus.FAILED`; otherwise `None`.

### `resolve_deployment_result(result: CloneDeploymentResult, restores: Mapping[UUID, Restore]) -> CloneDeploymentResult` (new, pure)

Returns `result` unchanged unless `result.outcome` is `cloned` and `failed_restore(result.restore_id, restores)` returns a row. Then it returns a copy with `outcome=failed` and `reason=f"{CLONE_REASON_RESTORE_FAILED}: {error_message}"`, or `CLONE_REASON_RESTORE_FAILED` when the row has no error message.

### `derive_environment_clone_status(...)` (changed internally)

Calls `failed_restore` where it now tests the row inline. The rules, the lenient reading of entries, and the result for every input stay the same.

## GraphQL type (`api/definitions/backup/environment_clone.py`)

### `EnvironmentClone.deployment_results` (changed resolver, same schema)

Projects each readable stored entry through `resolve_deployment_result(entry, self.referenced_restores)` before `EnvironmentCloneDeploymentResult.from_model`. Unreadable entries keep their current projection. The descriptions of `EnvironmentCloneDeploymentResult.outcome` and `reason` say that an entry whose restore failed reads `FAILED` with the restore's error.
