# Feature Specification: Steps and Failure Causes for Tasks, Backups and Restores

**Feature Branch**: `fac/feat-background-task-visibility-i4lwl`

**Created**: 2026-10-06

**Status**: Draft

**Input**: PRD "Steps and failure causes for tasks, backups and restores" — [opsmill/styrmin#2 (comment)](https://github.com/opsmill/styrmin/issues/2#issuecomment-6012882649). Seed issue: [#2](https://github.com/opsmill/styrmin/issues/2). Related: [#374](https://github.com/opsmill/styrmin/issues/374) (the Job is never removed), [#381](https://github.com/opsmill/styrmin/issues/381) and [#397](https://github.com/opsmill/styrmin/pull/397) (action tokens for upgrade hooks), [#383](https://github.com/opsmill/styrmin/issues/383) (concurrent version updates), [#396](https://github.com/opsmill/styrmin/issues/396) (unauthenticated agent paths).

## Context

When a user creates, updates or upgrades a **deployment**, they view a status badge that changes between `PENDING`, `RUNNING`, `SUCCESS` and `FAILED`, and one message. Most deployment work happens in the **operator** after the Prefect flow has ended. So a **task** can show `SUCCESS` while the HelmRelease fails a few minutes later. In that case the deployment shows only a generic message: "Deployment did not reach Ready within 300s".

The output of commands that **actions** run, such as a database migration, is not stored anywhere. Retries and rollbacks by the operator and by FluxCD are not visible. To find the cause of a failure, users need Prefect, `kubectl` or server logs.

This feature gives each task in the deployment timeline an ordered list of **steps**. The list covers the work in the Prefect flow (hook runs and the StyrminDeployment CRD write) and the work in the operator (prerequisites, HelmRelease, services, and waiting for Ready). Each step shows its status, when it started and ended, how many attempts it took, the error of each failed attempt and, for a failed command, the end of its output. The HelmRelease step shows the reason FluxCD gives and when FluxCD rolled back the release. Each task shows a **task result** that is calculated from its steps. Restores and backups of one deployment get the same step list in a second phase.

The glossary entries for **Step** and **Task result** are drafted in this branch's [CONTEXT.md](../../CONTEXT.md).

## User Scenarios & Testing *(mandatory)*

The primary actor is **any signed-in user, including `READ_ONLY`**, who opens a deployment to find out where and why an operation stopped. The secondary actors are the **platform engineer** who runs `styrminctl` in CI or a terminal, the **SDK user** whose scripts report failures, and the **driver author** whose hook runs become steps without changes to their driver.

### User Story 1 - View the ordered steps of a deployment task (Priority: P1)

Any signed-in user opens a deployment and, for any task type in the timeline, views the ordered steps of that task with their status and duration. The task types are create, update, upgrade, stop components, start components, run a job, and delete. The steps cover each run of a hook **mode**, the StyrminDeployment CRD write, each operator phase (prerequisites, HelmRelease, services, waiting for Ready), the command of `run_job`, and each deletion phase. A task that ran before this feature shows "no steps recorded for this task" instead of an empty list.

**Why this priority**: Users cannot tell where a create, update or upgrade stopped. The ordered step list is the base that every other story builds on (PRD user stories 1, 2, 18, 19).

**Independent Test**: Upgrade a deployment whose driver declares upgrade hooks. Open the deployment page and confirm the upgrade task lists every hook-mode run, the CRD write and every operator phase in start-time order, each completed step with a duration. Open a task that ran before the feature and confirm the "no steps recorded" notice.

**Acceptance Scenarios**:

1. **Given** a user upgraded a deployment and the upgrade completed, **When** any signed-in user, including a `READ_ONLY` user, opens the deployment page, **Then** they view the upgrade with every step in start-time order and a duration for each completed step.
2. **Given** a driver with `pre`, `core` and `post` upgrade actions and no driver changes for this feature, **When** a user upgrades a deployment of that driver, **Then** each run of each hook mode appears as one step.
3. **Given** a user runs a job on a deployment, **When** they open the deployment page, **Then** the `run_job` task shows one step for the job's command.
4. **Given** a user deletes a deployment, **When** they view its timeline, **Then** the delete task shows one step per deletion phase.
5. **Given** a task that ran before this feature, **When** a user opens it, **Then** it shows "no steps recorded for this task".

---

### User Story 2 - View the cause of a failed step (Priority: P1)

A user whose task failed views which step failed and why: the error of each failed attempt, FluxCD's reason when the HelmRelease is not Ready, the fact that FluxCD rolled back the release, and the end of a failed command's output. The user does not need Prefect, `kubectl` or server logs.

**Why this priority**: Naming the cause of a failure from the deployment page is SC-001, the headline outcome of the PRD (PRD user stories 3, 4, 5, 6, 7).

**Independent Test**: Cause each of the four SC-001 failure types in turn (a hook action raises an error; a command run by an action exits with an error; the HelmRelease does not become Ready because an image cannot be pulled; the operator cannot create a prerequisite). For each, open the deployment page and confirm the failed step and its cause are visible.

**Acceptance Scenarios**:

1. **Given** a user started an upgrade and the HelmRelease did not become Ready, **When** any signed-in user opens the deployment page, **Then** they view the upgrade with the task result `FAILED` and the HelmRelease step marked as failed with FluxCD's reason.
2. **Given** FluxCD rolled back a failed upgrade, **When** a user views the HelmRelease step, **Then** the step says that FluxCD rolled back the release and when.
3. **Given** a database migration command run by an upgrade action exited with an error, **When** a user views the failed hook step, **Then** they view the end of the command's output, including after the Job is removed.
4. **Given** a job run by `run_job` exited with an error, **When** a user views the job's step, **Then** they view the end of the job's output.
5. **Given** a hook action raised an error, **When** a user views the failed hook step, **Then** they view the error message.
6. **Given** the operator could not create a prerequisite and retried, **When** a user views the prerequisites step, **Then** it is one step with the number of attempts and the error of each failed attempt.

---

### User Story 3 - View a task result that includes the operator's work (Priority: P1)

Each task in the timeline shows a task result calculated from its steps: `RUNNING`, `FAILED`, `SUCCEEDED` or `SUPERSEDED`. A task is not shown as succeeded while its HelmRelease failed. When a later task interrupts the operator phases of an earlier task, the earlier task shows that it was superseded and by which task. Tasks that an upgrade hook started link to the upgrade, and the upgrade links back to them.

**Why this priority**: Today a task shows `SUCCESS` while the HelmRelease fails after the task ended. A result that includes the operator's work removes that false signal (PRD user stories 8, 9, 10).

**Independent Test**: Upgrade a deployment whose upgrade hook starts other tasks (for example `stop_components`, `upgrade_deployment_version`, `start_components`). Confirm the upgrade lists the started tasks with their task results and links, and each started task links back. Start a second update while a first is in its operator phases and confirm the first task's result is `SUPERSEDED` with a link to the second.

**Acceptance Scenarios**:

1. **Given** a task whose Prefect flow succeeded and whose HelmRelease then failed, **When** a user views the timeline, **Then** the task result is `FAILED` while `Task.status` still reports the Prefect flow outcome.
2. **Given** an upgrade whose hook started three tasks, **When** a user views the upgrade, **Then** the hook step lists the three tasks with their task results and links, and each started task links back to the upgrade.
3. **Given** a task that the upgrade hook started has failed, **When** a user views the upgrade, **Then** the upgrade's task result is `FAILED`.
4. **Given** a user started a second update while the first was still in its operator phases, **When** a user views the first task, **Then** its interrupted steps are superseded with a link to the second task, its task result is `SUPERSEDED`, and the superseded steps do not count as failed.
5. **Given** a deployment reached `RUNNING` or `FAILED`, **When** a user views its tasks, **Then** none has the task result `RUNNING`, unless the agent has stopped reporting.

---

### User Story 4 - Follow a running task without reloading (Priority: P1)

A user who watches a running task views each step change within 15 seconds, without a manual reload. When the server has received no agent report for the deployment for more than 60 seconds, the running operator-phase step shows "no report from the agent since <time>". The message disappears when reports start again.

**Why this priority**: Users need to tell a slow phase from a stuck one, and a stuck phase from a lost agent (PRD user stories 2, 11, 12).

**Independent Test**: Start an upgrade and watch the deployment page; confirm each new step appears within 15 seconds. Stop the agent while an operator-phase step is running; confirm the "no report from the agent since" message appears after 60 seconds and disappears when the agent reports again.

**Acceptance Scenarios**:

1. **Given** a task is running, **When** a step starts, ends or records an attempt, **Then** the deployment page shows the change within 15 seconds without a reload.
2. **Given** an operator-phase step is running and the server has received no agent report for the deployment for more than 60 seconds, **When** a user views the step, **Then** it shows "no report from the agent since <time>" and stays running.
3. **Given** the message above is shown, **When** the agent reports again, **Then** the message disappears.

---

### User Story 5 - Read steps and failure causes from the SDK and `styrminctl` (Priority: P1)

A platform engineer reads a task's steps and task result from the SDK, prints the step list with `styrminctl tasks get`, and sees the failed step and its error in the `failed` line of `styrminctl deployments apply --wait`.

**Why this priority**: CI logs and scripts must explain a failure without a browser (PRD user stories 13, 14, 15).

**Independent Test**: Cause an upgrade to fail. Call the SDK to read the task and confirm it returns the steps and the task result. Run `styrminctl tasks get <id>` and confirm it prints each step with status, duration and error. Run `styrminctl deployments apply --wait` against a change that fails and confirm the `failed` line names the failed step and its error.

**Acceptance Scenarios**:

1. **Given** a task with steps, **When** an SDK user reads the task, **Then** the SDK returns the ordered steps and the task result.
2. **Given** a task with steps, **When** a platform engineer runs `styrminctl tasks get`, **Then** the output lists each step with its status, duration and error.
3. **Given** `styrminctl deployments apply --wait` waits on a task that fails, **When** the command prints its `failed` line, **Then** that line names the failed step and its error.

---

### User Story 6 - View the steps of a restore or backup of one deployment (Priority: P2)

Any signed-in user opens a restore of one deployment and views its steps: delete the namespace, run the Velero restore, run the recovery. For a backup of one deployment, the user views the start time, the end time and the result of each **component**.

**Why this priority**: Restores and backups share the diagnosis problem, but the PRD places them in a second phase after deployment tasks (PRD user stories 16, 17).

**Independent Test**: Start a restore whose Velero restore fails; open the restore and confirm each restore step appears in order with its duration and the Velero restore step is marked as failed with its error. Start a backup of a deployment with several components and confirm each component shows its start time, end time and result.

**Acceptance Scenarios**:

1. **Given** a user started a restore and the Velero restore failed, **When** any signed-in user opens the restore, **Then** they view each restore step in order with its duration, and the Velero restore step marked as failed with its error.
2. **Given** a user started a backup of a deployment with several components, **When** any signed-in user opens the backup, **Then** they view the start time, the end time and the result of each component.
3. **Given** a backup or restore ran before this feature, **When** a user opens it, **Then** its existing status and component statuses are unchanged and the step list shows "no steps recorded".

---

### Edge Cases

- **An upgrade hook starts other tasks.** For example, `stop_components`, `upgrade_deployment_version` and `start_components` each create their own task. They stay separate entries in the timeline, link to the upgrade, and the upgrade links to them (FR-008).
- **A later task interrupts the operator phases of an earlier task.** The interrupted steps become superseded. The earlier task is `SUPERSEDED` if it did not start the later task, and `FAILED` if a task that it started has failed (FR-006, FR-007).
- **Tasks started by the same hook interrupt each other.** For example, the `upgrade_deployment_version` task writes the StyrminDeployment before the operator has finished the `stop_components` task. The `stop_components` task then shows `SUPERSEDED`, with a link to the task that interrupted it. The upgrade's own result treats the work of all the tasks its hook started as its own: only an interruption by a task outside that group makes the upgrade `SUPERSEDED` (FR-006, FR-008).
- **The operator or FluxCD retries a phase.** The operator retries after 30 seconds, and FluxCD retries an install or an upgrade up to 3 times. The step stays one step, with the number of attempts and each error (FR-002).
- **FluxCD rolls back a failed upgrade.** This is FluxCD's default ([FluxCD documentation](https://fluxcd.io/flux/components/helm/helmreleases/#upgrade-remediation)). The HelmRelease step says so (FR-004).
- **The agent stops reporting** because of a pod restart, an unreachable cluster or a network failure. The running step shows the time of the last report after 60 seconds, and stays running (FR-009).
- **A Job is removed after it fails** ([#374](https://github.com/opsmill/styrmin/issues/374)). The output must be read before the Job is removed (FR-003).
- **A failed command prints more output than Styrmin keeps.** Styrmin keeps the end of the output up to the limit in FR-003 and the step shows that earlier output was cut.
- **A task ran before this feature.** It shows a notice instead of an empty list (FR-010).
- **Command output contains a secret.** Every signed-in user can view it. The team accepted this risk (see Assumptions).
- **A step write arrives for a task, backup or restore that does not exist, or for a step that does not exist.** The write is rejected with a typed error and no step is created.
- **The deployment is deleted.** Its tasks, and their steps, stay in the history of the tombstoned deployment.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST record an ordered list of steps for every task type in the deployment timeline (create, update, upgrade, stop components, start components, run a job, delete):
  - one step per run of a hook mode;
  - one step for writing the StyrminDeployment CRD;
  - one step per operator phase: prerequisites, HelmRelease, services, and waiting for Ready;
  - for `run_job`, one step for the job's command;
  - for a delete, one step per deletion phase.

  Steps are ordered by start time.
- **FR-002**: Each step MUST have:
  - a name;
  - a status, which is one of pending, running, succeeded, failed or superseded;
  - a start time and an end time;
  - a number of attempts;
  - the error message of each failed attempt.
- **FR-003**: When a command run by an action or by `run_job` fails, the system MUST store the end of its output on the step, before the Job is removed. The system keeps at most the last 200 lines and at most 64 KiB of that output, and the step MUST show when earlier output was cut. [CLAUDE RECOMMENDED – based on the PRD's open question about the output size: a Python stack trace from a failed migration fits in 200 lines, and 64 KiB bounds the size of one stored step]
- **FR-004**: The HelmRelease step MUST show FluxCD's reason while the HelmRelease is not Ready. It MUST also show when FluxCD rolled back the release.
- **FR-005**: While a task runs, the deployment page MUST show a step change within 15 seconds, without a manual reload.
- **FR-006**: The system MUST calculate the task result on each read, and MUST NOT store it. The rules:
  - `RUNNING` while any step is running or not started, or while any task that the task's hook started is running;
  - `FAILED` when any step, or any task that its hook started, has failed;
  - `SUCCEEDED` when all steps have succeeded;
  - `SUPERSEDED` when a task that it did not start interrupted its operator phases.
- **FR-007**: A step that a later task interrupts MUST get the status superseded, with a link to that later task. A superseded step MUST NOT count as failed.
- **FR-008**: A hook step MUST list the tasks that it started, with their task results and links. Each started task MUST link back to the task that started it.
- **FR-009**: When the server has received no agent report for the deployment for more than 60 seconds, a running operator-phase step MUST show "no report from the agent since <time>". The message MUST disappear when reports start again.
- **FR-010**: A task that ran before this feature MUST show "no steps recorded for this task".
- **FR-011**: Users with any role, including `READ_ONLY`, MUST be able to view steps, errors and command output.
- **FR-012**: The SDK MUST return the steps and the task result of a task. `styrminctl tasks get` MUST print the step list with status, duration and error. The `failed` line of `styrminctl deployments apply --wait` MUST name the failed step and its error.
- **FR-013 (P2)**: A restore of one deployment MUST show its steps: delete the namespace, run the Velero restore, run the recovery. A backup of one deployment MUST show the start time, the end time and the result of each component. Their existing status and component statuses MUST stay unchanged.
- **FR-014**: Prefect flows and actions MUST write steps and command output with the **action token**, through a mutation that requires `READ_WRITE`. `run_job` MUST receive an action token in the same way that `apply_state` creates one. The feature MUST NOT add a mutation that accepts unauthenticated calls.
- **FR-015**: `Task.status` MUST keep its current meaning, which follows only the Prefect flow run, because driver actions wait on it.
- **FR-016**: Steps MUST be kept as long as their task, backup or restore exists, and MUST be deleted with that record. [CLAUDE RECOMMENDED – based on the PRD's open question about retention and on [ADR-028](../../dev/adr/0028-deployment-history-derived-from-existing-data.md), which keeps the tasks of tombstoned deployments]
- **FR-017**: A write to a step that does not exist, or for a task, backup or restore that does not exist, MUST be rejected with a typed error and MUST NOT create a step. [CLAUDE RECOMMENDED – based on Constitution §IV]
- **FR-018**: Recording a step MUST NOT change reconciliation: no new driver capability, no new component, and no change to how desired and current state are compared. Each run of a hook mode becomes a step without changes to drivers.
- **FR-019**: Each task in the deployment timeline MUST show its type: create, update, upgrade, stop components, start components, run a job or delete. [CLAUDE RECOMMENDED – based on User Story 1 and the PRD's P1 journey, which name these types; today every task that a reconcile runs is stored with the type `noop` and shown as "No-op"]

### Key Entities *(include if feature involves data)*

- **Step** *(new)*: one unit of work inside a task, a backup or a restore. Created when the work starts and updated on each attempt and at the end. Holds a name, a status, a start time, an end time, a number of attempts with the error of each failed attempt, the end of a failed command's output, the task that superseded it, and the time of the last agent report for operator-phase steps. A step belongs to exactly one task, backup or restore, and is deleted with that record.
- **Task result** *(new, calculated)*: calculated from steps on each read and never stored, in the same way as the environment backup status in [ADR-055](../../dev/adr/0055-environment-backup-parent-records.md). Values: `RUNNING`, `FAILED`, `SUCCEEDED`, `SUPERSEDED`.
- **Task** *(extended)*: gains steps, a task result, a link to the task whose hook started it, and the list of tasks its hooks started. `Task.status` is unchanged.
- **Backup** and **Restore** *(extended, P2)*: gain steps. Their existing status and `componentStatuses` are unchanged.
- **DeploymentStatus** *(unchanged)*: still holds only the latest CRD status report. The phase history is recorded as steps instead.
- **Deployment**, **Instance** and **Application driver** *(unchanged)*: the CRD's `instanceId` links an operator report to the task that rolled out that **instance**.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For each of these four failure types, a user can name the failed step and its cause from the deployment page alone, without Prefect, `kubectl` or server logs:
  - a hook action raises an error;
  - a command run by an action exits with an error;
  - the HelmRelease does not become Ready, for example because an image cannot be pulled;
  - the operator cannot create a prerequisite.

  Target: 4 out of 4.
- **SC-002**: While a task runs, the user views each step change within 15 seconds.
- **SC-003**: After a deployment reaches `RUNNING` or `FAILED`, none of its tasks has the task result `RUNNING`, except when the agent has stopped reporting.
- **SC-004**: A `READ_ONLY` user views the same steps, errors and command output as an `ADMIN` user.
- **SC-005 (P2)**: For a restore whose Velero restore fails, a user can name the failed restore step and its error from the restore view alone.

## Assumptions

- Every signed-in user, including `READ_ONLY`, can view command output. The team accepts that the output can contain secret values that are otherwise hidden. The driver-author documentation states that action commands must not print secrets.
- [#381](https://github.com/opsmill/styrmin/issues/381) is fixed by [#397](https://github.com/opsmill/styrmin/pull/397), so driver upgrade hooks can call the API with an action token.
- FluxCD rolls back failed upgrades by default.
- The agent reports every 5 seconds, and the deployment page refreshes every 10 seconds. The 15 seconds of FR-005 and SC-002 start when a flow, an action or the operator records the change. The operator checks FluxCD every 60 seconds, so a change that FluxCD makes is recorded up to 60 seconds later. [CLAUDE RECOMMENDED – based on the operator's 60-second timer in `config.py`]
- FluxCD's reason travels to the server in the existing StyrminDeployment conditions, so the input of the agent's status report does not change.
- The parts of the backup and restore flows that run with database access write their steps directly. The restore steps and the per-component backup work run in the cluster, so those parts write their steps with an action token, like every other Prefect flow (FR-014). [CLAUDE RECOMMENDED – based on where the code runs today; the PRD expected all backup and restore steps to be written directly; see [research.md](research.md) D13]

## Out of Scope

- Prefect flow log lines (PRD P3), together with a decision on who is allowed to view them.
- Environment backups and environment restores as their own step lists. Their constituent backups and restores show steps through User Story 6.
- Environment clones, which already store their own list of events.
- Server push, and live step changes in the CLI.
- New retries or rollbacks. The feature shows only the ones that happen today.
- Authentication for the status reporter and the flow-run callback ([#396](https://github.com/opsmill/styrmin/issues/396)).
- Limiting action tokens to one deployment.
- The seed issue's time-to-resolution metric. No baseline is known, so SC-001 replaces it.

## Dependencies

- Action tokens from [#397](https://github.com/opsmill/styrmin/pull/397) (ADR-059), extended to `run_job`.
- The agent's status reporter and its `reportDeploymentStatuses` path, which carries operator phases and conditions.
- The deployment timeline from [ADR-028](../../dev/adr/0028-deployment-history-derived-from-existing-data.md).
- The coexistence of the CRD phase and the task callback from [ADR-019](../../dev/adr/0019-crd-phase-and-task-callback-coexist.md).
- The operator's readiness check. Today the operator reports an update or upgrade as ready without waiting for FluxCD to apply the new HelmRelease, so a HelmRelease failure after an update is not visible ([`operator/handlers/styrmin_deployment.py`](../../backend/styrmin_backend/operator/handlers/styrmin_deployment.py), [`dev/knowledge/agent/operator.md`](../../dev/knowledge/agent/operator.md)). User Story 2 acceptance scenario 1, FR-004 and SC-003 depend on the operator judging the HelmRelease that FluxCD is applying now. As a result, a deployment reaches `RUNNING` after an update only when FluxCD reports the new release Ready, and a failed update ends `FAILED`. [CLAUDE RECOMMENDED – based on the operator code on `develop`; see [research.md](research.md) D5]

## Governance Gates Crossed

- Database schema or migration change: step records, and the link from a task to the task that started it.
- GraphQL schema modification: the new types, fields and the step-writing mutation.
- Authentication or authorization change: a new `READ_WRITE` mutation called with the action token, and an action token for `run_job`.
- No new dependency and no CI/CD workflow change are expected.

The PRD records these gates as discussed and accepted during the grilling session of 2026-10-05 and 2026-10-06.
