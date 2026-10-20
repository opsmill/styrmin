# ADR-081: Actions of a Local Driver Version Run from Its Path After a Provenance Fingerprint Check, and a Declared Action Without a Registered Flow Fails Its Hook

**Status**: Accepted
**Date**: 2026-10-19, amended 2026-10-20 after the review of #372
**Decision-makers**: Fatih Acar
**Source**: specs/archive/029-local-driver-actions/spec.md ("Decisions and Rejected Alternatives"),
specs/archive/029-local-driver-actions/research.md (R-001 to R-010);
[issue #372](https://github.com/opsmill/styrmin/issues/372) and its
[PRD](https://github.com/opsmill/styrmin/issues/372#issuecomment-6262219647)
**Related**: [ADR-053](0053-driver-version-provenance-fingerprint.md) (provenance fingerprint),
[ADR-059](0059-driver-action-api-tokens.md) (action token),
[ADR-060](0060-steps-and-derived-task-result.md) (steps and derived task result),
[ADR-079](0079-driver-actions-import-only-from-their-driver-directory.md) (actions run from their
driver directory), [ADR-080](0080-action-deployments-keyed-by-driver-directory.md) (action
deployments keyed by driver directory)

## Context

An operator loads an application driver version from git (`styrminctl drivers load-version`) or
from a local directory on the server (`styrminctl drivers load-local-version`). The user
documentation tells operators to load the bundled drivers from `/styrmin/drivers/<name>` with
`load-local-version`, and the Styrmin image holds them at that path.

Before this decision:

- `load_application_driver_from_object` (`services/applications.py`) registered a Prefect flow for
  each action only when the driver came from git, and `ActionsWorkflowBuilder` accepted only a
  `GitSource`, because the flow clones the repository when it runs.
- A hook looked up the registered flow of each mode, and a lookup that found nothing returned
  `None`: the hook was skipped without an error. An upgrade whose `upgrade`/`core` flow was missing
  fell back to a plain update.
- The five bundled drivers each declare `pre_setup`, `post_setup` and `upgrade`. Loaded from a
  local directory, none of these actions ran, and the task reported `success` (#372).

A local driver version already stores its path (`source_path`) and its provenance fingerprint
(`content_hash`, the SHA-256 of `driver.styrmin.yml`, the values template and, when the driver
declares actions, `actions.py`).

Where actions run: the agent polls the work pool `user-work-pool` with a Prefect `ProcessWorker`
(`entrypoint/combined.py`, `styrmin agent start --work-pool user-work-pool`). Every action, from
git or from a local directory, runs as a process in the agent pod. No Kubernetes Job is created
for an action, and an action's `image:` has no effect. The spec and research R-006 assumed that
each action ran as a Kubernetes Job in its `image:`; the first E2E runs of user story 2 showed
that this is false (`specs/archive/029-local-driver-actions/e2e-evidence.md`, "What the earlier runs of
T028 found"). The decisions below hold for the agent pod in the same way: the agent reads the
driver from the same path as the server.

Facts about Prefect 3.8.6 that shape the decisions:

- A pull step is any importable function. Prefect runs the pull steps before it imports the
  deployment's entrypoint, and changes into the `directory` that the last step returns.
- Before it runs a step, Prefect fills in `{{ ... }}` templates in the step's inputs with
  environment variables, Prefect variables and blocks. The action's environment holds
  `STYRMIN_TOKEN`.
- When a pull step raises, the flow run crashes. Its state message holds only the exit status, and
  Prefect logs nothing in the flow run.

## Decision drivers

- Every declared action of a local driver version runs, as for a git driver version (FR-001,
  FR-002).
- An action never runs a driver specification, values template or `actions.py` that differs from the
  driver version that was loaded (FR-003, FR-004). Modules that `actions.py` imports are not
  covered; see "The check pull step".
- No hook is skipped without an error (FR-005, SC-002).
- A user can fix each failure from the error text alone (SC-003).
- No change to the database schema, the GraphQL schema or the Helm charts, and no new dependency.

## Considered options

1. Refuse or flag a local driver that declares actions.
2. Store the action code with the driver version.
3. Add a Helm value that mounts a shared driver volume into the server and wherever actions run.
4. Run the `actions.py` at the driver version's path, after a check that the files at that path
   have the driver version's provenance fingerprint; fail the hook of a declared action that has
   no registered flow, and register missing actions when the driver is loaded again.

## Decision

We chose option 4. Option 1 blocks the documented way to load the bundled drivers. Option 2 was
rejected in the PRD. Option 3 is a follow-up, listed in [`follow-ups.md`](../../specs/archive/029-local-driver-actions/follow-ups.md) of spec 029 and not yet
opened as an issue: it needs a Helm change, and the bundled drivers are already in the Styrmin
image.

### Registration of the actions of a local driver version (R-003, R-005, R-010)

- `ensure_action_registrations` (`services/applications.py`) registers the actions of git and
  local driver versions. For a new driver version it runs after the service and component
  validations and just before the insert, so a refused load leaves no deployment in Prefect.
- The actions of a local driver version are registered and looked up with
  `driver_directory=<source_path>`, through the ADR-080 tag and name digest.
  `action_directory_of(source_type, source_path)` in `services/driver/labels.py` returns
  `source_path` for `git` and `local`, and `None` otherwise. A git value never starts with `/`. A
  load from a local directory of a driver that declares actions is refused when the path is
  relative, because the agent runs each action from a temporary working folder, where a relative
  path does not lead to the driver. A local value of a driver with actions therefore always starts
  with `/`, and never gets the key of a git driver version. Two local driver versions loaded from
  two paths with the same files keep their own deployments, and each runs the `actions.py` at its
  own path. `driver_directory_of` keeps its meaning for the GraphQL field `driverDirectory`.
- A load whose driver declares actions is refused with `DriverLoadingError` when its local path
  contains `{` or `}`, because Prefect would fill in a template in the path before the check reads
  it, and the check could write a secret, such as the action token, into its error. A driver
  without actions loads from such a path, because it registers no pull step.
- A load from a local directory is also refused when an action's `location` is in another file
  than `actions.py`, because the check hashes only that file of the driver's code.
- A load from git or from a local directory is refused when the driver declares more than one
  action for one hook and mode: they share one registration key, so a second action would replace
  the first, or be skipped by the repair of a repeated load.
- Rejected: a new `path/<source_path>` tag, which every lookup would have to handle as a second
  mechanism; changing `driver_directory_of`, which would change the GraphQL field
  `driverDirectory`; encoding the path in the step input, which hides it in the Prefect UI and
  differs from ADR-079; refusing every local path with braces, which blocks drivers without
  actions for no reason.

### The check pull step (R-001, R-004)

- A local action's Prefect deployment has the entrypoint `actions.py:<function>`, as for git, and
  one pull step: `styrmin_backend.workflows.local_driver.check_local_driver`. Its inputs are the
  path, the full `content_hash` and the three driver file names of the server settings.
- The step raises `DriverFilesNotFoundError` when the path, the specification file or the actions
  file is missing, and `DriverFingerprintMismatchError` when
  `compute_driver_directory_fingerprint` of the files at the path differs from `content_hash`. The
  local loader computes `content_hash` with the same function, so the two cannot drift. Otherwise
  the step returns `{"directory": <path>}`, and Prefect imports `actions.py` from the path.
- The step never imports `actions.py`, so changed or missing files are never run. Git driver
  versions get no check: their flow clones the repository at the recorded commit.
- The check covers the three files of the provenance fingerprint, not the modules that
  `actions.py` imports, such as a `helpers.py` next to it. An edit of such a module at the path
  takes effect in the next action run without a new driver version. The documentation for driver
  authors says so. Rejected: hashing every file of the path, which would change the provenance
  fingerprint of ADR-053 and the identity of every stored local driver version.
- Rejected: an absolute entrypoint with no pull step, because nothing would run before Prefect
  imports the file; Prefect's `set_working_directory` step after a separate check step, which adds
  a step with no added behaviour; a Styrmin wrapper flow that imports and calls the action, which
  would run the action as a child flow run with its logs elsewhere and run local and git actions
  in two ways; comparing only the short fingerprint, because two files can share a 7-character
  prefix; reading the file names from the settings where the action runs, because they are not
  set there.

### The error of a crashed action on its hook step (R-002)

- For a crashed flow run of a driver action, `run_driver_action_or_fail` (`agent/tasks/utils.py`)
  reads the first `ERROR` log of the flow run, cuts it to 4,000 characters, redacts it, and raises
  `Deployment flow run <id> crashed: <first error log> (<state message>)`. When the log is absent
  or cannot be read, the error keeps the state message alone. The other flows that
  `run_deployment_or_fail` starts, such as the orchestration flows and the remediations, keep the
  state message alone, so their logs never reach a task.
- `redact_secrets` replaces with `<redacted>` the action token, the user info of every
  `scheme://` URL, the credential after `Bearer` or `Basic`, and the value after `=` or `:` of a key
  whose name contains `password`, `passwd`, `secret`, `token`, `api_key`, `private_key` or
  `credential`. A secret in any other form is kept.
- Exposure: the hook step's error is readable by every signed-in user who can read the task,
  Read-only users included, on the deployment page, through `styrminctl tasks get` and through the
  GraphQL API, for as long as the task is kept. Before this change, only users with access to the
  Prefect UI or API could read a flow run's logs. The documentation for driver authors (`driver/DRIVERS.md`,
  the driver API reference and "Loading a Driver") and the changelog tell them not to log secrets.
- Because Prefect logs nothing in the flow run when a pull step raises, `check_local_driver` logs
  its error at `ERROR` in the flow run before it raises.
- Rejected: an upstream Prefect change that puts the exception text in the `Crashed` state, which
  is the right fix but reaches only later Prefect releases (a follow-up in [`follow-ups.md`](../../specs/archive/029-local-driver-actions/follow-ups.md)
  proposes it, not yet opened as an issue); a
  `Failed` state proposed by the step before it raises, because which of two final states wins
  depends on Prefect's rules; recording the error on the hook step through `recordStep`, which
  would put two errors on one attempt.

### Where the errors say the action runs (R-006, corrected)

- The errors name the agent pod where the check ran: the pull step passes its host name, which is
  the pod name in Kubernetes. They give the fixes that work there: put the driver at the path in
  the agent pod, or load the driver again with the `styrminctl drivers load-local-version` command
  that the fingerprint error spells out. They name no image.
- On 2026-10-19 the maintainer first kept the earlier texts, which named the action's `image:` or
  the default image of the work pool. On 2026-10-20, after the review of #372, the maintainer
  replaced them, because the action never runs in that image and the texts sent operators to
  rebuild an image that is not used, against SC-003 ("fix each failure from the error text
  alone").
- Rejected: keeping the image and labelling it as not used, which adds a value the operator cannot
  act on; reading the image from the Prefect API, which the earlier texts did and which is no
  longer needed.

### The Job of `execute_commands` (#372 review)

- `execute_commands` names its Job `<release reference>-job`, so every action of a deployment uses
  one Job name. `run_job` deletes the Job of an earlier action before it creates its own, so an
  action can run twice on a deployment. It deletes that Job only when it has ended (the `Complete`
  or `Failed` condition) and when a driver action created it (the label `styrmin.io/action-job=true`,
  or, for a Job that an earlier Styrmin version created, the single container `user-job`).
- A Job that is still running is never deleted: the action fails with `JobStillRunningError`, which
  tells the operator to wait for the Job to end and request the change again. Nothing prevents two
  changes of one deployment from running at the same time, so deleting a running Job could stop the
  migration Job of an overlapping upgrade. The maintainer chose to refuse rather than delete
  (2026-10-20).
- The Job ends at its first failed pod (`backoffLimit: 0`), as `run_job` already reports that pod's
  failure, so the next action does not wait for retries that nobody reads.
- The hook step shows a line that names the deleted Job and how it ended, because the wait for its
  deletion can take up to 120 seconds.
- Rejected: a Job name per action run, which would leave one Job per run in the namespace and need
  a cleanup rule.

### Hook resolution (R-007)

- `services/driver/hooks.py` holds `resolve_setup_hooks` and `resolve_upgrade_hooks`. They read the declared actions with
  `uow.actions.list_by_driver_version`, look up only the declared hook and mode pairs, and raise
  `ActionNotRegisteredError` when a declared pair has no registered flow. The error names the driver
  version, the hook, the mode and the actions, and gives the command that loads the driver again.
- `resolve_upgrade_hooks` returns `None` when the target declares no `upgrade`/`core` action, so the
  change stays a plain update, as before. When it declares one, a missing flow raises and the
  upgrade does not fall back to an update.
- The create and upgrade remediations call these functions. `instantiate_application`, which had
  no caller other than its unit tests, was deleted.
- Rejected: skipping the hook, with or without a warning; porting `instantiate_application`, which
  no path runs; reading the declared actions from the driver files when the hook runs, because the
  files may have changed.

### Recording a missing registration on the hook step (R-008)

- `apply_state` catches `ActionNotRegisteredError` from planning, ends the `plan` step without an
  error, records the step of the error's hook and mode as failed with the error, and re-raises.
- Rejected: failing the `plan` step only, because its name says nothing about hooks.

### Request check before an upgrade (R-009)

- `update_deployment_version` calls `resolve_upgrade_hooks` for the target driver version before it
  writes anything, when the target application version differs from the active instance's. On
  `ActionNotRegisteredError`, it leaves the deployment unchanged and returns a failed
  `upgrade_instance` task with no flow run, whose hook step holds the error. The deployment keeps
  its active instance, so the same request is not a no-op once the driver is loaded again (FR-007).
- Rejected: treating a request for the version of a failed active instance as a change, which
  would change the retry behaviour of every failed upgrade; having the flow restore the previous
  active instance, which would need to restore every field the request wrote; refusing the request
  with a GraphQL error, because FR-005 requires a failed task.

### Repeated loads register missing actions (R-010)

- `ensure_action_registrations` also runs when the identity lookup finds a stored driver version.
  It decides that a flow is missing with the lookup that hooks use, registers only the actions of
  the pairs without a flow, and makes no Prefect write when nothing is missing.
- Rejected: registering every declared action on every load, which would replace deployments that
  hooks use; registering missing actions at server start, which would make server start depend on
  Prefect and on the driver paths.

### Deployments created before this change

Styrmin does not run the setup actions that deployments created from local driver versions before
this change never ran. Setup actions are written to run once on a new deployment, and Styrmin does
not record which hooks were skipped. The changelog tells operators about it.

## Consequences

- Good, because the bundled drivers loaded with `load-local-version` run their setup and upgrade
  actions, as when they are loaded from git.
- Good, because changed or missing driver files fail the hook step with an error that names the
  path and both fingerprints and says how to fix it, instead of running other code.
- Good, because no hook is skipped without an error, and loading the driver again repairs a driver
  version whose registrations are missing. The same upgrade request then starts a new task.
- Bad, because the agent pod must hold each local driver at the same path as the server. A driver
  that only the server container holds fails its actions. A shared driver volume is a follow-up,
  listed in [`follow-ups.md`](../../specs/archive/029-local-driver-actions/follow-ups.md) and not yet opened as an issue.
- Bad, because any edit of the three files at a path makes every driver version loaded earlier from
  that path fail its actions. After a Styrmin upgrade that ships a newer bundled driver, operators
  load the bundled drivers again.
- Bad, because an action's `image:` has no effect: the action runs in the agent pod.
  [`follow-ups.md`](../../specs/archive/029-local-driver-actions/follow-ups.md) lists it as a follow-up, not yet opened as an issue.
- Bad, because the check does not cover the modules that `actions.py` imports.
- Bad, because when the check fails during an upgrade, the failed instance stays active: the same
  request is a no-op, and a request for another driver version at the same application version runs
  as an update without the upgrade action. This is true of every failed upgrade; [`follow-ups.md`](../../specs/archive/029-local-driver-actions/follow-ups.md)
  lists it as a follow-up, not yet opened as an issue.
- Bad, because the hook step's error now holds the first `ERROR` log of a crashed action, which
  every signed-in user who can read the task can read. It is redacted, but only for the forms that
  `redact_secrets` knows, so actions must not write secrets to their logs.
- Related change in the same branch: `deleteDeployment` now deletes a deployment whose create
  failed before its `StyrminDeployment` was written, for example at `hook:setup:pre`, because the
  error of `ActionNotRegisteredError` tells the operator to delete and create again such a
  deployment. A missing `StyrminDeployment` counts as nothing for the operator to tear down, with a
  warning when the deployment is `RUNNING`; a namespace that the create wrote before it failed can
  remain. While the deployment is `PENDING` or `DEPLOYING`, the delete is refused with
  `DeploymentRolloutInProgressError`, whose message names the deployment.

## Confirmation

- `backend/tests/unit/workflows/test_local_driver_check.py`:
  - success paths (T014): `test_check_returns_the_driver_directory_and_logs_the_fingerprint`,
    `test_prefect_runs_the_pull_step_then_imports_the_action_from_the_path`,
    `test_deployment_has_the_entrypoint_and_the_single_check_step`,
    `test_builder_with_a_local_source_builds_a_local_driver_action`;
  - error paths (T025): `test_missing_directory_raises_the_missing_files_error`,
    `test_missing_driver_file_raises_the_missing_files_error`,
    `test_edited_driver_file_raises_the_fingerprint_error`,
    `test_removed_values_template_raises_the_fingerprint_error`,
    `test_get_function_raises_the_missing_files_error_before_it_imports`,
    `test_definition_refuses_a_relative_directory`,
    `test_definition_refuses_a_module_other_than_the_actions_file`,
    `test_check_logs_its_error_in_the_flow_run_before_it_raises`,
    `test_get_function_raises_the_fingerprint_error_before_it_imports`,
    `test_check_module_imports_with_an_empty_environment`.
- `backend/tests/functional/test_user_action_registration.py` (T017, T032), against a real Prefect
  server: `test_local_load_of_a_bundled_driver_registers_its_three_actions`,
  `test_two_paths_with_the_same_driver_files_keep_their_own_actions`,
  `test_loading_a_local_driver_again_registers_its_deleted_actions_again`.
- `backend/tests/unit/services/test_update_version_hook_check.py` (T034):
  `test_upgrade_whose_upgrade_action_has_no_registered_flow_returns_a_failed_task`,
  `test_upgrade_whose_upgrade_action_has_no_registered_flow_leaves_the_deployment_unchanged`,
  `test_the_check_runs_exactly_when_the_flow_takes_the_upgrade_path`.
- `backend/tests/e2e/test_local_driver_actions.py`, run as `[api-chromium]`, with the passing runs
  recorded in `specs/archive/029-local-driver-actions/e2e-evidence.md`:
  - `test_local_driver_actions_run_on_create_and_upgrade` (T021);
  - `test_changed_local_driver_fails_with_the_fingerprint_error` and
    `test_driver_missing_from_the_agent_pod_fails_with_the_missing_files_error` (T027);
  - `test_missing_registration_fails_and_loading_again_repairs_it` (T035).
- `backend/tests/e2e/test_infrahub_local_driver_actions.py`, outside CI: the bundled `infrahub`
  driver loaded from `/styrmin/drivers/infrahub` runs its setup actions on a create and its upgrade
  action, with its migration Job, on an upgrade from 1.6.0 to 1.7.0. Run by hand; the run is
  recorded in `specs/archive/029-local-driver-actions/e2e-evidence.md`.
- Also: `test_local_path_with_a_brace_is_refused_for_a_driver_with_actions`,
  `test_relative_local_path_is_refused_for_a_driver_with_actions`,
  `test_local_action_located_outside_the_actions_file_is_refused` and
  `test_two_actions_for_one_hook_and_mode_are_refused` in
  `backend/tests/unit/services/test_local_action_registration.py`;
  `test_crashed_run_error_holds_its_first_error_log_and_the_state_message`,
  `test_crashed_run_error_has_the_action_token_and_other_secrets_redacted` and
  `test_crashed_run_of_another_deployment_keeps_the_state_message_without_its_logs` in
  `backend/tests/unit/agent/tasks/test_run_deployment_or_fail.py`;
  `test_an_earlier_job_that_is_still_running_is_not_deleted` and
  `test_a_job_that_no_action_created_is_not_deleted` in
  `backend/tests/unit/agent/test_run_job_replaces_earlier_job.py`; the error texts in
  `backend/tests/unit/services/driver/test_action_errors.py`;
  `test_apply_state_flow_fails_the_hook_step_of_an_action_without_a_registered_flow` in
  `backend/tests/unit/agent/tasks/test_apply_state_flow.py`; and
  `backend/tests/unit/services/driver/test_hooks.py`.

## More information

- The registration pipeline, the check pull step, hook resolution and the work pools are described
  in [hooks-and-actions.md](../knowledge/backend/hooks-and-actions.md).
- The errors and how operators fix them are described in
  [Loading a Driver](../../docs/docs/drivers/loading-drivers.md#actions-of-a-driver-loaded-from-a-local-directory).
- The follow-ups of this change are listed in [`follow-ups.md`](../../specs/archive/029-local-driver-actions/follow-ups.md) of spec 029, with the
  follow-ups of `research.md` ("Follow-ups to open after this change ships"). None of them is opened
  as an issue yet.
