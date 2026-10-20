# Contract: Hook Resolution (FR-005, FR-007)

**Modules**: `services/driver/hooks.py` (new), `services/reconciliation/remediation.py`, `agent/tasks/orchestration.py`, `services/deployment.py`, `repository/action.py`.

## Functions

`resolve_hook_flow`, for one hook and mode, was planned and built, then deleted after the review of #372 because no production code called it; the two functions below resolve each pair with the same rule.

```python
async def resolve_setup_hooks(
    driver_version: ApplicationDriverVersion,
    application_name: str,
    *,
    uow: UnitOfWork,
    prefect_manager: PrefectManager,
) -> tuple[UUID | None, UUID | None]:
    """(pre, post) flows of the setup hook."""


async def resolve_upgrade_hooks(
    driver_version: ApplicationDriverVersion,
    application_name: str,
    *,
    uow: UnitOfWork,
    prefect_manager: PrefectManager,
) -> UpgradeHookFlows | None:
    """None when the version declares no upgrade/core action; otherwise core, pre and post."""
```

Truth table of each hook and mode that the two functions resolve:

| Declared actions for the hook and mode | Lookup result | Returns |
|----------------------------------------|---------------|---------|
| none | not called | `None` |
| one or more | a deployment id | that id |
| one or more | `None` | raises `ActionNotRegisteredError` |

The declared actions come from `uow.actions.list_by_driver_version(driver_version.id)`. The lookup is `prefect_manager.get_user_action_deployment_id` with the key of [action-registration.md](action-registration.md#registration-key).

`resolve_upgrade_hooks` keeps today's rule: `pre` and `post` are resolved only when `core` is declared ([R-012](../research.md#r-012-driver-versions-that-declare-upgradepre-or-upgradepost-without-upgradecore)).

## Callers

| Caller | Before | After |
|--------|--------|-------|
| `InstanceCreationStrategy.execute` | two lookups, `None` skipped the hook | `resolve_setup_hooks`; raises on a missing registration |
| `InstanceUpdateStrategy._handle_upgrade` | lookup of `upgrade`/`core`, `None` fell back to an update | `resolve_upgrade_hooks`; `None` (not declared) falls back to an update; a missing registration raises |
| `instantiate_application` | two lookups | deleted with its four unit tests |

`InstanceUpdateStrategy.execute` lets `ActionNotRegisteredError` propagate; it does not fall back to `_handle_update`.

## Recording in `apply_state` (R-008)

```python
plan_step_id = await open_task_step(task_id, steps.PLAN)
try:
    remediation = await _plan_remediation(...)
except ActionNotRegisteredError as exc:
    await end_step(plan_step_id)
    hook_step_id = await open_task_step(task_id, steps.hook_step(exc.hook, exc.mode))
    await end_step(hook_step_id, error=format_exception(exc))
    raise
except Exception as exc:
    await end_step(plan_step_id, error=format_exception(exc))
    raise
```

`steps.hook_step(hook, mode) -> StepDefinition` (new, `domain/steps.py`) returns `SETUP_PRE_HOOK`, `SETUP_POST_HOOK`, `UPGRADE_PRE_HOOK`, `UPGRADE_CORE_HOOK` or `UPGRADE_POST_HOOK`.

## Request check in `update_deployment_version`

Placement: after the request is validated (target driver version, application version, name, configuration, parameters, service overrides and component configurations, which raise their own errors as today), and before the first call that can write: `_ensure_ingress_controller`, which can create the environment's ingress controller deployment. `_reconcile_services_for_version` and `uow.deployments.save` come later. The implementer confirms that no call between the target resolution and this point writes to the session.

Condition: the deployment has an active instance, and the target application version differs from `deployment.active_instance.application_version`. This is the rule by which the flow takes the upgrade path (`ApplicationVersionChange`).

On `ActionNotRegisteredError` from `resolve_upgrade_hooks(target_driver_version, ...)`:

1. Discard every pending change of the deployment (nothing has been written).
2. Save `Task.create(type=TaskType.UPGRADE_INSTANCE, deployment_id=..., status=TaskStatus.FAILED, started_by_step_id=...)` with `message = str(exc)`.
3. Record `steps.hook_step(exc.hook, exc.mode)` on the task with `open_step` and `fail_step`, error `format_exception(exc)`.
4. Commit and return the task.

The check of `started_by_step_id` (`check_starting_step`) runs before this check, as today.

When `resolve_upgrade_hooks` returns, the function continues unchanged. The resolved ids are not reused; `apply_state` resolves the hooks again when it plans.

## Observable results (tests)

- Create from a version whose `setup`/`pre` registration is missing: the task fails, the `plan` step succeeds, the `hook:setup:pre` step fails with the error (unit and E2E).
- Upgrade request to a version whose `upgrade`/`core` registration is missing: the response is a failed task with a failed `hook:upgrade:core` step; the deployment's version, driver binding, status and active instance are unchanged; no flow run starts (unit and E2E user story 3).
- The clients report that failed task as a failure: `styrminctl deployments update-version` and `styrminctl deployments apply`, with and without `--wait`, print the task id and its message and exit with code 1; the SDK's `apply` returns `action="failed"` and does not wait; the SDK's `update_version` returns the failed task (SDK and CLI unit).
- After the driver is loaded again, the same request starts a new task, and the upgrade action runs (E2E user story 3).
- Upgrade to a version that declares no `upgrade`/`core` action: plain update, as today (unit).
- A git version with all registrations: unchanged behaviour (existing unit and E2E tests).
