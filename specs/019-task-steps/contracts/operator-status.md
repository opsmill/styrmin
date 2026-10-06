# Contract: Operator Status and the Phase History

**Feature**: [spec.md](../spec.md) | **Research**: [research.md](../research.md) D4, D5, D6, D7

This contract covers what the operator writes into the StyrminDeployment status, what the status reporter sends, and how the server turns each report into step changes.

## StyrminDeployment status, written by the operator

New and changed fields. The CRD's status schema keeps `x-kubernetes-preserve-unknown-fields: true`; the CRD file documents the new fields for new installs.

| Field | Written when | Value |
|---|---|---|
| `status.instanceId` (new) | Create, update and resume handlers, at the end of the handler, also when the handler raises | The `spec.instanceId` the handler acted on |
| `status.rolloutStartedAt` (new) | Create, update and resume handlers, at the start of a rollout | ISO 8601 time |
| `conditions[HelmReleaseReady]` (changed) | Handlers: `Unknown`, reason `Progressing`, at each rollout. Timer: FluxCD's current-generation `Ready` copied while not Ready; `True` when FluxCD's current-generation `Ready` is `True`. | `status`, `reason`, `message`, `lastTransitionTime` from FluxCD when copied |
| `conditions[HelmReleaseRemediated]` (new) | Timer, when FluxCD's `Remediated` condition is `True` for the current generation | `True`, FluxCD's reason (`RollbackSucceeded`, `UninstallSucceeded`), message and transition time |
| `phase`, `displayState`, `message` (changed) | Timer, when FluxCD's `Remediated` or `Stalled` is `True` for the current generation | `Failed`, `Error`, FluxCD's message |

"Current generation" means the condition's `observedGeneration` equals the HelmRelease's `metadata.generation`, falling back to `status.lastAttemptedGeneration` when the condition has none. This is the rule `_helmrelease_guard_failure` already uses (`operator/reconciler.py:409`).

The readiness timeout counts from `status.rolloutStartedAt`, falling back to `metadata.creationTimestamp`.

The timer writes a condition only when its status, reason or message changes, so a slow rollout does not produce a status write every tick.

## Status report, sent by the status reporter

The GraphQL input `DeploymentStatusReportInput` does not change. One field changes meaning:

| Field | Before | After |
|---|---|---|
| `instanceId` | `spec.instanceId` | `status.instanceId`, falling back to `spec.instanceId` when the status has none |

The stale-instance guard on `Deployment.status` (`services/deployment_status.py`) keeps its code; it now compares the instance the operator acted on.

## Phase history, run by the server for each report

`report_deployment_statuses` calls `apply_operator_report(report, now, uow)` in the same unit of work, after it upserts the `DeploymentStatus` snapshot.

### Finding the task

1. Phase `Deleting` or `Deleted`: the newest `delete_deployment` task of the deployment.
2. Otherwise: the task whose `instance_id` equals the report's `instanceId`.
3. No task, or the task has no operator-phase steps (a task from before this feature, an internal deployment, a legacy CR without `instanceId`): the report changes no step.
4. Steps that are `succeeded` or `superseded` are never changed by a report.

### Moving rollout steps forward

The rollout steps are, in order, `operator:prerequisites`, `operator:helmrelease`, `operator:services`, `operator:ready`.

| Reported phase | Effect |
|---|---|
| `Pending` | None |
| `CreatingPrerequisites` | Prerequisites `running` |
| `CreatingHelmRelease` | Prerequisites `succeeded`; HelmRelease `running` |
| `CreatingServices` | Prerequisites and HelmRelease `succeeded`; services `running` |
| `Ready` | All four `succeeded` |
| `Failed`, or `displayState: Error` with any phase | The first step that is not `succeeded` fails with the CR `message` |
| `Restoring` | None |

- A step moves to `running` only from `pending`, or from `failed` as a new attempt.
- A step's start time is the end time of the step before it.
- End times: prerequisites at the transition time of `NetworkPoliciesReady` or `SecretsReady` (the later), HelmRelease at `HelmReleaseReady`, services at `ServicesReady`, wait for Ready at `Ready`, when those conditions are `True`; the report time otherwise.

### HelmRelease details

While the HelmRelease step is `running` or `failed`:

- `detail` = `"<reason>: <message>"` of `HelmReleaseReady` when its status is not `True`.
- A `HelmReleaseReady` reason that ends with `Failed` (for example `InstallFailed`, `UpgradeFailed`) whose message or transition time differs from the newest recorded error appends that error to the current attempt, and starts the next attempt while the phase stays `CreatingHelmRelease`.
- `HelmReleaseRemediated=True` sets `rolled_back_at` to its transition time and `rollback_message` to its message.

### Pod reasons on failure

When the phase history fails the HelmRelease step or the "Wait for the deployment to be ready" step, it appends the deployment's pods whose containers report a waiting or terminated reason from this list, read from the stored pod statuses:

`ImagePullBackOff`, `ErrImagePull`, `InvalidImageName`, `CrashLoopBackOff`, `CreateContainerConfigError`, `CreateContainerError`, `Error`, `OOMKilled`.

Format: `Pods not ready: <pod> (<container>: <reason>), …`, at most 5 pods.

### Delete steps

| Reported phase | Effect on the delete task |
|---|---|
| `Deleting` | `operator:teardown` `running` |
| `Deleted` | `operator:teardown` `succeeded`, ended at the `Deleted` condition's transition time or the report time |

## Unit tests

- Operator handlers: `status.instanceId` and `status.rolloutStartedAt` written by create, update and resume; `HelmReleaseReady` reset on update; current-generation rule; FluxCD reason copied; `HelmReleaseRemediated` copied; `Stalled` and `Remediated` set `Failed`; timeout from `rolloutStartedAt`; no status write when nothing changed.
- Status reporter: `instanceId` from status, falling back to spec.
- Phase history: each row of the tables above; skipped phases; a failure then a new attempt; FluxCD failures counted as attempts; rollback recorded; pod reasons appended; reports for an unknown instance, a pre-feature task and an internal deployment change nothing; delete reports go to the delete task.
