# Contract: Internal Interfaces

**Feature**: [spec.md](../spec.md) | **Research**: [R-001](../research.md#r-001-one-service-function-decides-where-a-restore-lands) to [R-005](../research.md#r-005-the-in-flight-restore-guard-does-not-change), [R-012](../research.md#r-012-e2e-coverage-extends-test_backup_and_restore_lifecycle-the-drivers-lose-the-namespace)

These interfaces are not public. They are listed so that the tasks and the review can check each caller.

## `services/backup/service.py`

```python
@dataclass(frozen=True)
class RestoreTarget:
    deployment: DeploymentEntity
    namespace: str          # get_kubernetes_reference(deployment.id)
    instance_id: UUID | None  # deployment.active_instance.id, or None


async def resolve_restore_target(
    backup: Backup,
    uow: UnitOfWork,
    *,
    target_deployment_id: UUID | None = None,
) -> RestoreTarget:
    """Return the deployment that receives a restore of *backup*, its namespace and its active instance.

    Must be called inside an open ``uow`` transaction.
    In-place (``target_deployment_id is None``): the deployment of ``backup.instance_id``;
    raises BackupNotFoundError when the instance, its deployment link or the deployment is missing.
    Cross-target: the deployment ``target_deployment_id``; raises DeploymentNotFoundError when missing.
    """


async def create_restore(
    backup_id: UUID,
    uow: UnitOfWork,
    name: str | None = None,
    timeout: int = DEFAULT_RESTORE_TIMEOUT,
    environment_restore_id: UUID | None = None,
    target_deployment_id: UUID | None = None,
) -> tuple[Restore, UUID]:
    """Unchanged contract except: no ``target_namespace``, no ``target_instance_id``.

    The row records ``target.namespace`` and ``target.instance_id``.
    Returns ``(restore, target.deployment.id)``; callers read ``restore.target_namespace``.
    """
```

Unchanged: `find_in_flight_restore(uow, deployment_id, target_namespace)`, `has_in_flight_restore(uow, deployment_id)`, `_is_other_deployment_namespace`, `settle_undispatched_restore`, `resolve_backup_target` (still used for backups).

## Callers

| Caller | Before | After |
|--------|--------|-------|
| `Mutation.create_restore` ([`mutation.py`](../../../backend/styrmin_backend/api/schema/mutation.py)) | `create_restore_service(backup_id, target_namespace, target_instance_id, uow)`; dispatch `target_namespace` from the client | `create_restore_service(backup_id=backup_id, uow=uow)`; dispatch `restore.target_namespace` |
| `restore_environment_backup` ([`environment.py`](../../../backend/styrmin_backend/services/backup/environment.py)) | `resolve_backup_target(...)` and a fallback to `styrmin-<snapshot.deployment_id>`, then `create_restore(..., target_namespace=...)` | `create_restore(backup_id=..., uow=..., environment_restore_id=...)`; `_PendingRestoreDispatch.target_namespace = restore.target_namespace` |
| `_dispatch_cross_target_restore` ([`clone.py`](../../../backend/styrmin_backend/workflows/templates/clone.py)) | `target_namespace = f"styrmin-{counterpart id}"`, passed to `create_restore` and to the dispatch | `create_restore(backup_id=..., uow=..., target_deployment_id=counterpart id)`; dispatch `restore.target_namespace` |

`execute_restore_workflow(restore_id, backup_id, deployment_id, target_namespace, source_deployment_id=None)` keeps its signature (R-003).

## E2E scenario drivers

| Interface | Before | After |
|-----------|--------|-------|
| `ScenarioDriver.create_restore` ([`protocol.py`](../../../backend/tests/e2e/drivers/protocol.py)) | `(*, backup_id: str, target_namespace: str) -> RestoreRef` | `(*, backup_id: str) -> RestoreRef` |
| `ApiScenarioDriver.create_restore` ([`api_driver.py`](../../../backend/tests/e2e/drivers/api_driver.py)) | Passes `target_namespace` to the SDK | `client.backups.create_restore(backup_id=backup_id)` |
| `UiScenarioDriver.create_restore` ([`ui_driver.py`](../../../backend/tests/e2e/drivers/ui_driver.py)) | Passes `target_namespace` to the page object | Passes `expected_namespace=f"styrmin-{self._deployment_id}"` |
| `DeploymentDetailPage.create_restore` ([`deployment_detail.py`](../../../backend/tests/e2e/pages/deployment_detail.py)) | `(*, backup_id, target_namespace)`; checks the dialog's read-only field | `(*, backup_id, expected_namespace)`; same check |
