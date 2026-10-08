# Contract: Flow Step Reporter and Job Output

**Feature**: [spec.md](../spec.md) | **Research**: [research.md](../research.md) D2, D3, D10, D11, D12, D13

The flow step reporter lets a USER Prefect flow or a driver action record steps through `recordStep` ([graphql.md](graphql.md)). It lives in `backend/styrmin_backend/agent/steps/`, with its GraphQL operation in `agent/steps/record_step.graphql` loaded by `load_query`.

## Environment variables

| Variable | Set by | Read by | Value |
|---|---|---|---|
| `STYRMIN_TOKEN` | Existing (ADR-059), now also by `run_job`, `execute_backup_workflow`, `execute_restore_workflow` | Reporter, action primitives, SDK | Action token |
| `STYRMIN_TASK_ID` | `apply_state` (remediation Job), remediation flow (action Jobs), `run_job` (command Job) | Reporter | Task id |
| `STYRMIN_BACKUP_ID` | `execute_backup_workflow` | Reporter | Backup id |
| `STYRMIN_RESTORE_ID` | `execute_restore_workflow` | Reporter | Restore id |
| `STYRMIN_STEP_ID` | Remediation flow, for each driver action Job | `execute_commands`, `stop_components`, `start_components`, `upgrade_deployment_version` | The hook step running the action |

`agent/tasks/utils.py::action_job_variables(token, *, task_id=None, backup_id=None, restore_id=None, step_id=None)` builds the `env` job variable; `run_driver_action_or_fail(step_id=…)` forwards the current Job's token and task id and adds the hook step.

## Reporter interface

```python
reporter = StepReporter.from_env()          # no-op when STYRMIN_TOKEN or the parent is missing

async with reporter.step(key, name, kind) as step:   # STARTED; SUCCEEDED on exit; FAILED on exception, then re-raise
    ...
    step.id                                 # the step id returned by the server, or None in no-op mode

await reporter.record_output(step_id, output, truncated)   # OUTPUT
await reporter.fail_step(key, error, output=None)          # FAILED for a step opened earlier
```

- Each call sends `occurredAt` in the Job's clock.
- A failed call (network error, GraphQL error, missing token) logs a warning and returns. It never raises into the flow (research D2).
- The failure message of a step is the exception's type and message, as Prefect shows it.

## Where the reporter is used

| Flow or function | Steps |
|---|---|
| `create_instance_crd` | `hook:setup:pre`, `resource:styrmindeployment` (namespace and CR write), `resource:service-aliases`, `hook:setup:post` |
| `update_instance_crd` | `resource:styrmindeployment`, `resource:service-aliases` |
| `upgrade_instance_crd` | `resource:styrmindeployment` (CR write and status reset), `hook:upgrade:pre`, `hook:upgrade:core`, `resource:service-aliases`, `hook:upgrade:post` |
| `run_job_command` (new USER flow) | `command` |
| `execute_velero_restore_flow` | `restore:namespace`, `restore:velero`, `restore:recovery` |
| `execute_velero_backup_flow` | `backup:component:<name>` for each component, updated on each poll |
| `execute_commands` (action primitive) | `OUTPUT` on `STYRMIN_STEP_ID` when the Job fails |

Each hook step's id is passed to the action's Job as `STYRMIN_STEP_ID`.

## Steps written directly by INTERNAL code

| Code | Steps |
|---|---|
| `apply_state` flow | `plan` (retries on `TaskNotFoundError` for up to 10 seconds, because the caller may not have committed the task row yet); on a failed remediation flow, fails the task's open flow-kind steps before raising |
| `run_job` flow (INTERNAL wrapper) | On a failed command flow, fails the task's open flow-kind steps before raising |
| `execute_backup_workflow`, `execute_restore_workflow` | On a failed or crashed USER flow, fail the parent's open steps |
| `delete_deployment` service | `resource:delete-request` (succeeded when the CR patch succeeds), then supersede |
| `update_task_state` (callback) | On `FAILED`, fails the task's open flow-kind steps |

## Job output

`agent/service/kubernetes/job_logs.py::read_job_output_tail(namespace, job_name, container) -> JobOutput`

- Lists the Job's pods by label `batch.kubernetes.io/job-name=<job>`, then `job-name=<job>`, and takes the newest by creation time. A failed pod comes before a newer retry that has not ended, because the retry has no output yet.
- Calls `read_namespaced_pod_log(name, namespace, container=…, tail_lines=201, limit_bytes=65537)` and reads the raw bytes, because the client otherwise decodes strictly and parses a one-line JSON log as JSON.
- Returns the text without its first line when 201 lines came back, with `truncated=True`.
- When 65,537 bytes came back, Kubernetes kept the start of the 201 lines, not their end. The reader then asks for half as many lines until the answer fits, so the text always ends with the last line of the output, with `truncated=True`. Styrmin keeps at most the last 64 KiB of one line that is longer than that.
- Raises `JobOutputUnreadableError` with the reason when no pod exists or an API call fails (constitution IV: no union return for errors). `JobFailedError` then says "The output could not be read: <reason>", and the Job's failure is still raised.

`JobFailedError(message, *, output=None, truncated=False)` carries the output to the caller, which records it with `OUTPUT` before it re-raises.

Callers:

- `agent/service/kubernetes/primitives.py::run_job` (used by `execute_commands`): container `user-job`.
- `run_kubernetes_job` (used by `run_job_command`): container `prefect-job`.

Both read the output before they raise, so a later Job cleanup ([#374](https://github.com/opsmill/styrmin/issues/374)) cannot remove it first.

## PodVolumeBackup reading (backup steps)

- `VeleroClient.list_pod_volume_backups(namespace, backup_name)` lists `podvolumebackups.velero.io` with label `velero.io/backup-name=<name>`.
- Each item gives `spec.pod.name`, `spec.volume`, `status.phase` (`New`, `InProgress`, `Completed`, `Failed`), `status.startTimestamp`, `status.completionTimestamp`, `status.message`.
- The flow maps pods to components with the pod label `styrmin/component`. A component's step starts at its earliest `startTimestamp`, ends at its latest `completionTimestamp` once all its items are terminal and the Backup has left the `New` and `InProgress` phases (Velero creates `PodVolumeBackup` objects only until then), and fails when any item failed (error: the item's `status.message`). `finish` ends the remaining components with the Backup's result and sends each write that was not recorded again, up to 3 attempts in total.
- `poll_backup_status` gains an optional `on_poll` callback that receives the Backup object after each poll.
- `poll_backup_status` and `poll_restore_status` treat Velero's `FailedValidation` phase as terminal, next to `Completed`, `PartiallyFailed` and `Failed`. The step's error is the joined `status.validationErrors`.
- The agent's ClusterRole gains `get` and `list` on `podvolumebackups` in `velero.io` (`helm/agent/templates/roles.yaml`).

## Unit tests

- Reporter: no-op without token or parent; one call per event with the right variables; `occurredAt` sent; network and GraphQL errors logged, not raised; `step()` records `FAILED` with the exception and re-raises.
- `action_job_variables` and `run_driver_action_or_fail`: variables forwarded and added.
- `read_job_output_tail`: newest pod chosen; line and byte cuts set `truncated`; no pod and API errors raise `JobOutputUnreadableError`.
- `execute_commands`: output recorded on `STYRMIN_STEP_ID` before the error is raised.
- Remediation flows: steps opened in the documented order for each flow, with and without hooks and aliases; a failing hook records `FAILED`.
- Backup step mapping: `PodVolumeBackup` lists to component steps, including a component without items.
