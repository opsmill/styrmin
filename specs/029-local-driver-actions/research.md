# Research: Run the Actions of Driver Versions Loaded from a Local Directory

**Spec**: [spec.md](spec.md) | **Date**: 2026-10-19 | **Code base**: `develop` at `a5ec9446` (v0.1.50)

Each decision below states what was chosen, why, and the alternatives that were rejected. Facts about Prefect come from the installed Prefect 3.8.6 (`.venv/lib/python3.14/site-packages/prefect`), the version that Styrmin pins in the server, the task manager image (`docker-compose.yml`) and the action images.

**Amendment (implementation, 2026-10-19)**: this research assumed that each action runs as a Kubernetes Job in its `image:`. The E2E tests showed that this is false. The agent runs a Prefect `ProcessWorker` on `user-work-pool` (`backend/styrmin_backend/entrypoint/combined.py`), so every action runs as a process in the Styrmin agent pod, and an action's `image:` has no effect. Where a decision below says "the action's Job" or "the Job's image", read "the agent pod" or "the image the agent runs". The decisions themselves hold: the pull step (R-001), the crash log (R-002), the key (R-003), the shared fingerprint (R-004) and the brace refusal (R-005). R-006 and R-013 carry their own notes.

## R-001: How an action of a local driver version runs the `actions.py` at its path

**Facts**:

- A git action's Prefect deployment has the entrypoint `actions.py:<function>` and the pull steps `git_clone`, then `set_working_directory` for a driver directory ([ADR-079](../../dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md)).
- `load_flow_from_flow_run` (`prefect/flows.py:3293-3313`) runs the deployment's pull steps, changes the working directory to the `directory` output of the last step that returned one, and only then imports the entrypoint.
- A pull step is any importable function: `run_step` (`prefect/deployments/steps/core.py:142-177`) imports it by its fully qualified name with `import_object`. This is Prefect's documented extension point for pull steps (`prefect_aws.deployments.steps.pull_from_s3` uses it).
- `WorkflowDefinition.to_deployment` (`workflows/models.py:116-131`) already sets `job_variables={"image": ...}` when the action sets `image:`.

**Decision**: a local action's Prefect deployment has the entrypoint `actions.py:<function>`, as for git, and one pull step: `styrmin_backend.workflows.local_driver.check_local_driver`. The step computes the provenance fingerprint of the driver files at the version's `source_path`, raises a typed error when the files are missing or differ (R-002, R-004), and otherwise returns `{"directory": <source_path>}`. Prefect then changes into the path and imports `actions.py` from it, so Prefect's script loader puts the driver directory on `sys.path`, as for a git driver directory (ADR-079). The action's `image:` reaches the Job through the existing `job_variables`.

**Rationale**: the check runs before Prefect imports `actions.py`, so a changed or missing file is never imported or run (FR-003). The action runs with the same entrypoint, working directory and import path as a git action, so a driver behaves the same whether it was loaded from git or from a local directory. The pull step uses an extension point that Prefect provides for this purpose.

**Alternatives rejected**:

- An absolute entrypoint (`/styrmin/drivers/infrahub/actions.py:pre_setup`) with no pull step: nothing runs before Prefect imports the file, so FR-003 cannot be met.
- Prefect's built-in `set_working_directory` step after a separate check step: one more step with no added behaviour, because the check step can return the directory itself.
- A Styrmin wrapper flow as the entrypoint, which checks the files, imports `actions.py` and calls the action: the action would run as a child flow run, with its logs in another run, and the wrapper would need to forward each hook's parameters (`context`, `deployment_id`, `target_version`) through `**kwargs`. Local and git actions would then run in two different ways.
- Storing the action code with the driver version: rejected by the PRD.

## R-002: How the error of the check reaches the hook step

**Facts**:

- When a pull step raises, `load_flow_from_flow_run` logs the original exception at `ERROR` (`run_logger.error(str(e))`, with `e = e.__cause__`) and re-raises (`prefect/flows.py:3306-3309`).
- The engine process then logs "Unexpected exception encountered when trying to load flow" and exits with status 1 (`prefect/engine.py:170-176`).
- The parent `FlowRunExecutor` proposes `Crashed` with the message `Process exited with status code: 1. <explanation>` (`prefect/runner/_flow_run_executor.py:188-203`). The exception text is not in the state message.
- `run_deployment_or_fail` (`agent/tasks/utils.py:42-55`) raises `RuntimeError("Deployment flow run <id> crashed: <state message>")`, and `StepReporter.step` records `format_exception(exc)` on the hook step. So without a change, the hook step would show only the exit status.
- Prefect's queue services drain at process exit through `threading._register_atexit` (`prefect/_internal/concurrency/services.py:119-123`), so the engine's `ERROR` logs reach the API before the process exits and before the parent proposes `Crashed`.
- `PrefectClient.read_logs` accepts a `LogFilter` on `flow_run_id` and `level` and a `LogSort` (`prefect/client/orchestration/_logs/client.py:75-97`).

**Decision**: when the flow run of a deployment ends `Crashed`, `run_deployment_or_fail` reads the first `ERROR` log of that flow run (`level >= 40`, sorted by timestamp, limit 1) and raises `Deployment flow run <id> crashed: <first error log> (<state message>)`. The log text is cut to 4,000 characters. When no such log exists or the logs cannot be read, the message stays as it is today.

**Rationale**: the hook step then records the text of the typed error, which names the path, the image and the fingerprints and says how to fix the problem (FR-003, FR-004, SC-003). The change uses Prefect's public log API. It also helps other crashes before the flow starts, such as an `actions.py` that fails to import, whose hook step today shows only the exit status.

**Alternatives rejected**:

- An upstream change to Prefect, so that the engine proposes `Crashed` with the exception text when the flow cannot be loaded: this is the right fix in Prefect, but it would reach only images built on a later Prefect, and an action's `image:` can hold any Prefect from 3.6.9 on. A follow-up issue proposes it upstream; once released and adopted, the log read can be removed.
- The check step proposes a `Failed` state with its message before it raises: the parent still proposes `Crashed` after the non-zero exit, and which state wins depends on Prefect's orchestration rules for a transition between two final states.
- The check step records its error on the hook step through `recordStep` with the action token: the hook step would then hold two errors for one attempt, and the error that `run_driver_action_or_fail` records would still be the exit status.
- The wrapper flow of R-001: rejected there.

## R-003: Registration key of a local driver version's actions

**Facts**:

- `PrefectManager.register_user_action` (`workflows/manager.py:73-129`) tags each deployment `application/`, `version/`, `hook/`, `mode/`, `fingerprint/` and, with a driver directory, `directory/<driver directory>`, and appends a 12-hex digest of the driver directory to the deployment name ([ADR-080](../../dev/adr/0080-action-deployments-keyed-by-driver-directory.md)).
- `get_user_action_deployment_id` filters on the same tags and, without a driver directory, drops every deployment that carries a `directory/` tag.
- `CONTEXT.md` defines the driver directory of a local load as "the path given on the server". `driver_directory_of` (`services/driver/labels.py:75-89`) returns `None` for a local row only because the GraphQL field `driverDirectory` returns null for local loads.
- A git driver directory is relative (an absolute path is refused before the clone); a local `source_path` is the absolute path given on the server, stored as given (`LocalDriverProvider`, `services/driver/provider.py:247-268`).
- Two local versions loaded from two paths with the same files have the same `content_hash`, so the same short fingerprint.

**Decision**: a local version's actions are registered and looked up with `driver_directory=<source_path>`, through the ADR-080 mechanism unchanged. A new helper, `action_directory_of(source_type, source_path)` in `services/driver/labels.py`, returns `source_path` for `git` and `local` rows and `None` for other source types (`internal`). The hook lookups and the registrations use it. `driver_directory_of` keeps its meaning for the GraphQL field.

**Rationale**: the tag and the name digest keep two local versions with the same files and different paths apart (FR-002). A `directory/` value of a local version starts with `/` and a git value never does, so the two cannot match. A git version loaded from the repository root still drops every deployment with a `directory/` tag, so it never runs a local version's action.

**Alternatives rejected**:

- A new `path/<source_path>` tag: a second mechanism for the same purpose, which every lookup would have to handle.
- Changing `driver_directory_of` to return the local path: it would change the GraphQL field `driverDirectory`, a schema-visible change.

## R-004: The provenance fingerprint at a path, in the loader and in the action's Job

**Facts**:

- `compute_driver_content_hash` (`services/driver/hash.py:33-62`) hashes `driver.styrmin.yml`, the values template (`b""` when the file is missing) and, when the spec declares actions, `actions.py`.
- The three file names come from server settings (`STYRMIN_DRIVER_SPEC_FILE`, `STYRMIN_DRIVER_VALUES_TEMPLATE`, `STYRMIN_DRIVER_ACTIONS_CODE_FILE`; `DriverDirectory` in `services/driver/models/structure/directory.py:19-39`). The driver spec cannot change them (`HelmSettings` has `extra="forbid"`).
- An action Job's environment comes from the user work pool's job template and `action_job_variables`; it does not carry the `STYRMIN_DRIVER_*` settings.

**Decision**: a new function `compute_driver_directory_fingerprint(directory, *, spec_file, values_template, actions_file, include_actions)` in `services/driver/hash.py` reads the files and calls `compute_driver_content_hash`. The local loader and the check step both call it. The registration passes the three file names and the full 64-character `content_hash` to the check step as inputs.

**Rationale**: one function computes the fingerprint in both places, so they cannot drift. Passing the file names keeps the check correct when an operator changed the settings on the server.

**Alternatives rejected**:

- The check step reads the file names from its own settings: they are not set in the Job, so a changed server setting would make every check fail.
- Comparing only the short fingerprint: two files can share a 7-character prefix. The message shows the short forms, which users see in driver version labels.

## R-005: Prefect templates in pull step inputs

**Facts**: before it calls a step, `run_step` replaces `{{ ... }}` placeholders in the inputs with upstream outputs, block documents, Prefect variables and environment variables (`prefect/deployments/steps/core.py:170-173`). The action Job's environment holds `STYRMIN_TOKEN`. ADR-079 refuses `{` and `}` in a git driver directory for this reason.

**Decision**: a load from a local directory whose driver declares actions is refused with `DriverLoadingError` when the path contains `{` or `}`. The check step's inputs are the path, the content hash (hexadecimal) and the three file names from server settings; the image is not an input (R-006).

**Rationale**: a path with a template could make the check step write a secret, such as the action token, into its error, which every signed-in user can read on the step. The refusal matches ADR-079.

**Alternatives rejected**:

- Encoding the path (for example base64) in the step input: it hides the path in the Prefect UI and differs from ADR-079.
- Refusing every local path with braces, also for drivers without actions: such a driver registers no pull step, so the refusal would block loads for no reason.

## R-006: The image that the error names

**Facts**:

- An action's Job runs in the action's `image:` when it sets one (the deployment's `job_variables`), and otherwise in the default image of the work pool `user-work-pool`. The server writes that default from `STYRMIN_K8S_WORKER_IMAGE` at every start (`workflows/catalogue.py:100-102`, `manager.py:215-229`), and Helm sets it to the server image (`helm/styrmin/templates/configmap.yaml:26`).
- The Job's environment holds `PREFECT__FLOW_RUN_ID`, and the Job can read Prefect's API.

**Decision**: when the check fails, it reads the flow run, then the deployment's `job_variables["image"]`, and otherwise the work pool's base job template default image. When a read fails, the message names "the default image of the work pool <name>".

**Rationale**: the check names the image the Job actually runs. A value stored at registration would be stale after a Styrmin upgrade, which is when FR-003 most often fails.

**Alternative rejected**: passing the image as a step input at registration: stale after a Styrmin upgrade, and an `image:` value written by a driver author would be templated (R-005).

**Amendment (implementation, 2026-10-19)**: the rationale does not hold, because the action never runs in the image the check names. It runs in the agent pod. The user decided to keep the text: in a standard install, the work pool's default image is the image the agent runs, so the error is correct unless an action sets `image:`. When the image is unknown, the error says "in the default image of the work pool <name>" or "in the image of this action's Job" ([contracts/errors.md](contracts/errors.md)).

## R-007: Hook resolution in one service function

**Facts**:

- Seven direct lookups exist: two in `instantiate_application` (`services/applications.py:470-613`) and five in `InstanceCreationStrategy` and `InstanceUpdateStrategy._handle_upgrade` (`services/reconciliation/remediation.py`).
- `instantiate_application` has no caller other than four unit tests. Against the real unit of work it would fail: it calls `uow.instances`, builds a database `Task` with `application_instance_id`, and sends parameters that `create_instance_crd` does not accept.
- The declared actions are `Action` rows of the driver version (`db/models.py:226-243`). `SQLModelActionRepository` has only the base methods.
- Nothing forbids two actions with the same hook and mode; the lookup returns the newest deployment, so only one runs.
- The upgrade remediation looks up `upgrade`/`pre` and `upgrade`/`post` only when an `upgrade`/`core` flow is found.

**Decision**:

- A new module `services/driver/hooks.py` holds `resolve_hook_flow(driver_version, hook, mode, *, uow, prefect_manager) -> UUID | None`. It returns `None` when the version declares no action for the hook and mode, returns the registered flow otherwise, and raises `ActionNotRegisteredError` when the version declares an action and the lookup finds none.
- Two helpers build on it: `resolve_setup_hooks` returns the `pre` and `post` flows; `resolve_upgrade_hooks` returns `None` when the version declares no `upgrade`/`core` action, and otherwise resolves `core`, `pre` and `post`. The upgrade rule stays as it is today.
- The remediation strategies call these helpers. `ActionRepository` gets `list_by_driver_version(driver_version_id)`.
- `instantiate_application` and its four unit tests are deleted.

**Rationale**: one function decides what "declared but not registered" means, for the remediations, for the request check (R-009) and for repeated loads (R-010), as FR-006 requires.

**Alternatives rejected**:

- Porting `instantiate_application` to the new function: it would keep code that no path runs and that cannot run against the real unit of work.
- Reading the declared actions from the driver files at run time: the files may have changed (FR-003); the `Action` rows are what the version declared.

## R-008: Recording a missing registration that the `apply_state` flow finds

**Facts**: `apply_state` (`agent/tasks/orchestration.py:351-388`) opens the `plan` step, builds the remediation, fails the plan step with `format_exception(exc)` when planning raises, and re-raises. The hook step keys `hook:setup:pre`, `hook:setup:post`, `hook:upgrade:pre`, `hook:upgrade:core` and `hook:upgrade:post` are defined in `domain/steps.py`. `open_task_step` and `end_step` (`services/steps/internal_flows.py:49-96`) open and end a step from a flow.

**Decision**: `apply_state` catches `ActionNotRegisteredError` from planning, ends the plan step as succeeded, opens the hook step of the error's hook and mode, ends it with `format_exception(exc)`, and re-raises. The flow fails, and the callback sets the task, the deployment and the instance to failed, as for any failed flow.

**Rationale**: FR-005 asks that the hook step record the failure. The user sees which hook could not run and why. Planning itself completed: it found that a hook cannot run.

**Alternative rejected**: failing the plan step only: the error would be on a step whose name says nothing about hooks.

## R-009: Running the same upgrade again after it failed for a missing registration (FR-007)

**Facts**:

- After a failed upgrade, the new instance stays the deployment's active instance, and `update_deployment_version` treats a second request for the same target as a no-op (`_update_is_noop`, `services/deployment.py:465-500`): it returns `None` and starts no task.
- The `apply_state` flow plans the change after the request has committed the deployment and its new instance (#237).
- The flow takes the upgrade path only when the application version changes (`ApplicationVersionChange`); a change of driver version alone runs the update path, which runs no hook.
- `updateDeploymentVersion` is the only way to change a deployment's version. The UI, `styrminctl deployments update-version`, `styrminctl deployments apply` and the `upgrade_deployment_version` action primitive all call it.
- A task can exist without a flow run: `delete_deployment` saves a task with `prefect_flow_run_id=None` and records its steps from server code (`services/deployment.py:1976-1997`, `2163-2170`). `fail_step` (`services/steps/recorder.py:237-269`) accepts a pending step.

**Decision**: `update_deployment_version` checks the hooks before it writes anything. When the target application version differs from the active instance's application version, it calls `resolve_upgrade_hooks` for the target driver version. When that raises `ActionNotRegisteredError`, the function:

1. leaves the deployment unchanged;
2. saves a task of type `upgrade_instance` with status `failed`, no flow run, no instance, `started_by_step_id` from the request, and the error as its message;
3. records the hook step of the error's hook and mode as failed with the error;
4. commits and returns the task.

The flow keeps the check of R-008 for a registration that disappears between the request and the plan.

**Rationale**: the deployment keeps its version and active instance, so the next request for the same upgrade is not a no-op and starts a new task once the driver is loaded again (FR-007, SC-003). The request still returns a failed task whose hook step names the action (FR-005), so the UI, the CLI, the SDK and the action primitive show it as they show any failed upgrade.

**Alternatives rejected**:

- Treating a request for the version of a failed active instance as a change: it would change the retry behaviour of every failed upgrade, and the flow would need the last instance that ran as the current one.
- Having the flow restore the previous active instance: the request also writes the version, the driver binding, the components, the parameters, the configuration and the services, and restoring all of them from the flow is error-prone.
- Refusing the request with a GraphQL error: FR-005 and its PRD verification require a failed task.

## R-010: Registering missing actions on a repeated load (FR-006)

**Facts**: `load_application_driver_from_object` returns early when the identity matches (`services/applications.py:150-173`), before the registration block, for git and local loads. Registration happens before the new row exists (ADR-080). Prefect replaces a deployment with the same flow and name.

**Decision**: a function `ensure_action_registrations` in `services/applications.py` runs on both paths of the load: when the identity lookup finds a version, and, for a new version, after the spec validations of the load and just before the insert, so a refused load leaves no deployment in Prefect (critique E3). For each hook and mode that the driver declares, it calls the hook lookup with the version's key (application, supported versions, short fingerprint, `action_directory_of`). It registers every declared action of each hook and mode whose lookup finds nothing. For a git version, it saves the token block first when it registers at least one action. A load that registers nothing makes no Prefect write.

**Rationale**: the same lookup as hooks decides what is missing, so a load never changes a registration that hooks already find, and a repeated load stays idempotent (Constitution §I). A new version's lookups find nothing, so all its actions are registered, as today.

**Alternative rejected**: registering every declared action on every load: Prefect would replace deployments that hooks already use, and each repeated load would write to Prefect.

## R-011: E2E design

**Facts**:

- Action Jobs in the E2E suite run the image that `docker compose build` builds from the working tree (`backend/tests/e2e/conftest.py:731-843`). It holds `driver/examples` at `/styrmin/drivers` and the `backend/` tree, E2E fixtures included, at `/source/backend` (`docker/Dockerfile:47,62`).
- The server container runs as UID 1000 and the image files belong to root, so a test cannot change a file of the image inside the server pod. The Helm chart offers no extra volume for the server.
- The chart server URL is fixed: `http://chart-server.default.svc.cluster.local:8080` (`conftest.py:487`). The session builds `simple-app:0.1.0` and `simple-app:0.2.0`.
- The vCluster runs with the Docker driver, and kubelet uses images of the host daemon under `IfNotPresent`.
- `test_driver_reload_identity.py` copies a driver into the server pod with `kubectl cp` and loads it locally; it deploys nothing.

**Decision**: a new module `backend/tests/e2e/test_local_driver_actions.py` (`ci`, `shard_general`, `api_only`) with a new fixture driver `backend/tests/e2e/fixtures/drivers/local-actions/`. The driver uses the `simple-app` chart at the fixed chart server URL. Its `pre_setup`, `post_setup` and `upgrade` actions log a marker and do nothing else.

The module depends on the session fixtures `chart_server`, `simple_app_image` and `simple_app_image_v2`, and on the Styrmin image tag that `styrmin_deployment` installs (`latest` locally, `$STYRMIN_IMAGE_VER` in CI), which is the base of the derived image. The user story 2 variants use their own driver name (`local-actions-check`), and every create and version change in the module pins `driver_version_id`, so the latest-wins rule cannot bind a deployment to another variant (critique E7).

- User story 1: load `/source/backend/tests/e2e/fixtures/drivers/local-actions` locally, deploy `0.1.0`, upgrade to `0.2.0`. Assert:
  - three registrations exist;
  - the `hook:setup:pre`, `hook:setup:post` and `hook:upgrade:core` steps succeeded;
  - each marker is in the logs of its action's flow run.
- User story 2:
  - A session fixture builds a derived image `FROM` the Styrmin image under test, with an edited `actions.py` at a path chosen per session, tagged with the session id.
  - The test copies the unedited driver into the server pod at the same path, with `image:` set to the derived image, and loads it. The create fails on `hook:setup:pre` with the fingerprint error, which also proves that the action ran in its `image:`.
  - A second copy, only in the server pod, fails with the missing-files error.
- User story 3: with the user story 1 deployment at `0.2.0`:
  - delete the version's Prefect deployments;
  - request `0.1.0`: the request returns a failed task with a failed `hook:upgrade:core` step, and the deployment stays at `0.2.0`;
  - load the driver again;
  - request `0.1.0` again: the upgrade action runs.

**Rationale**: one module covers the three journeys with two deployments, and the two failures of user story 2 fail before Helm runs. The derived image is the only way to make the files in the action's image differ from the files the server loaded without changing the Helm chart.

**Alternatives rejected**:

- Loading `/styrmin/drivers/simple-app`: it has the same name as the session's git `simple-app`, and the latest-wins rule would bind later deployments of other tests to it.
- Mounting a writable volume over the fixture path in the server pod: it needs a Helm chart change or a patch of the server Deployment, which restarts the server under other tests.
- Running the five bundled drivers in E2E: `infrahub`, `infrahub-enterprise` and `slurpit` need heavy stacks. A functional test registers the actions of all five against a real Prefect server (SC-001 registration), and the quickstart covers running them on the dev stack.

## R-012: Driver versions that declare `upgrade`/`pre` or `upgrade`/`post` without `upgrade`/`core`

**Decision**: no change. Such an upgrade stays a plain update and those actions do not run. No driver in this repository declares this combination. A follow-up issue records it.

## R-013: What a custom action image must hold

**Decision**: the documentation states that an action's `image:` must hold the driver at the same path as the server, Prefect 3.6.9 or later (as for git actions), and a `styrmin_backend` of a release that has the check step. Without the check step, the Job crashes with `ModuleNotFoundError`, which the hook step shows through R-002.

**Amendment (implementation, 2026-10-19)**: an action's `image:` has no effect, so this decision is replaced. The documentation states that the agent pod must hold the driver at the same path as the server, and that the image the agent runs needs Prefect 3.6.9 or later.

## Follow-ups to open after this change ships

The full list, with the follow-ups found during implementation, is in [follow-ups.md](follow-ups.md).

- A Prefect upstream issue: propose `Crashed` with the exception text when a flow cannot be loaded (R-002).
- A shared driver volume for action Jobs, for drivers mounted only into the server (PRD, out of scope).
- Running `upgrade`/`pre` and `upgrade`/`post` actions without an `upgrade`/`core` action (R-012).
- A note on [#10](https://github.com/opsmill/styrmin/issues/10): local driver versions now run their actions.
- Running an upgrade again after its action failed: the failed instance stays active, so the same request is a no-op, and a request for another driver version at the same application version runs as an update (critique P5).
