---

description: "Tasks for 029: run the actions of driver versions loaded from a local directory"
---

# Tasks: Run the Actions of Driver Versions Loaded from a Local Directory

**Input**: Design documents from `specs/029-local-driver-actions/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/action-registration.md](contracts/action-registration.md), [contracts/local-driver-check.md](contracts/local-driver-check.md), [contracts/hook-resolution.md](contracts/hook-resolution.md), [contracts/errors.md](contracts/errors.md), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution §V requires unit tests for new behaviour and an E2E test of the user-visible flow, observed to pass locally with recorded evidence. No GraphQL schema change, so no propagation test. The plan's "Testing Strategy" table maps each requirement to its tests.

**Organization**: Phase 2 holds what every story needs: the typed errors, the fingerprint function, the registration key, the action repository method and hook resolution. Then one phase per user story in priority order (US1 P1, US2 P2, US3 P3), then documentation and verification. All three stories ship in one change.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US3 (spec user stories)
- Paths are relative to the repository root

## Working rules (apply to every task)

- This worktree sits inside the emdash pnpm workspace: run `export npm_config_ignore_workspace=true` before `uv run invoke lint` and `git commit`.
- `uv run invoke lint` ends with a generated-types check that runs `git checkout --` on unstaged generated files: stage changes before running it. No generated file should change in this feature (no GraphQL change); if one does, stop and find out why.
- Tests assert what users view: which actions ran, which step failed, and the text of its error ([contracts/errors.md](contracts/errors.md), "Must contain"). They do not assert how a flow is registered, except where the registration is the observable result (FR-001).
- Use the glossary terms of `CONTEXT.md` in code, comments and docs: driver version, driver directory, action, hook, mode, step, task, provenance fingerprint.

## E2E run rules (apply to every E2E task)

- Build the server image before each session that tests changed backend code: `docker compose build server`. The new fixture driver must be in the image (`/source/backend/tests/e2e/fixtures/drivers/local-actions`).
- One pytest session per run. Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |`, and stop the run by its PID, not with `pkill -f`.
- Record each passing run in `specs/029-local-driver-actions/e2e-evidence.md`: the pytest node IDs, the exact command, ISO 8601 start and end times, the vCluster name and kubeconfig path, and the verbatim `PASSED` lines (Constitution §V).
- Before claiming an E2E run is blocked, read `backend/tests/e2e/conftest.py` and check the real prerequisites only: the Docker daemon, `vcluster` on `PATH`, the lockfile, disk space (AGENTS.md).

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync`, then `uv run pytest backend/tests/unit/services/driver backend/tests/unit/workflows backend/tests/unit/services/reconciliation/test_remediation.py backend/tests/unit/agent/tasks/test_run_deployment_or_fail.py backend/tests/unit/agent/tasks/test_apply_state_flow.py backend/tests/unit/services/test_update_deployment_noop.py backend/tests/unit/services/test_applications_upsert_idempotent.py backend/tests/unit/services/test_application_services.py backend/tests/functional/test_user_action_registration.py -q`, and note the results in your working notes as the baseline (no file change)

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the typed errors, the fingerprint at a path, the registration key, the action repository method and hook resolution.

**⚠️ No user story work can begin until this phase is complete.**

- [X] T002 [P] In `backend/styrmin_backend/services/driver/exceptions.py` add `DriverFilesNotFoundError`, `DriverFingerprintMismatchError` and `ActionNotRegisteredError`, each a `DriverError` subclass with the keyword-only constructor, `error_code`, `default_message`, `error_metadata` and message text of [contracts/errors.md](contracts/errors.md). `ActionNotRegisteredError` stores `hook` and `mode` as attributes (used by T029 and T033). Keep the module importable with an empty environment (no settings, no database import)
- [X] T003 [P] Create `backend/tests/unit/services/driver/test_action_errors.py`: for each error, build one with sample values and assert every "Must contain" part of [contracts/errors.md](contracts/errors.md) is in `str(error)`, that `error_metadata` holds the listed keys, and that the fingerprint error shows the first 7 characters of both hashes; for `ActionNotRegisteredError`, check the three `load_command` forms (local; git from the root; git with `--driver-directory`) when passed in
- [X] T004 In `backend/styrmin_backend/services/driver/hash.py` add `compute_driver_directory_fingerprint(directory, *, spec_file, values_template, actions_file, include_actions) -> str` as in [contracts/local-driver-check.md](contracts/local-driver-check.md#fingerprint-at-a-path) (values template read as `b""` when missing; `FileNotFoundError` for a missing spec file, or a missing actions file with `include_actions`). In `backend/styrmin_backend/services/driver/loaders.py` make the local loader compute `content_hash` with it (`include_actions=bool(spec.actions)`), so both places share one function (research R-004)
- [X] T005 [P] In `backend/tests/unit/services/driver/test_hash.py` add: the function equals the `content_hash` that `get_local_driver_loader(<dir>).load_driver()` returns for `driver/examples/simple-app` and for `backend/tests/unit/services/driver/fixtures/local_driver_directory`; editing `actions.py`, the values template or the spec file in a `tmp_path` copy changes the value; a missing values template hashes like an empty one; a missing spec file, and a missing `actions.py` with `include_actions=True`, raise `FileNotFoundError`
- [X] T006 [P] In `backend/styrmin_backend/services/driver/labels.py` add `action_directory_of(*, source_type: str, source_path: str | None) -> str | None` ([contracts/action-registration.md](contracts/action-registration.md#registration-key)): `source_path` for `"git"` and `"local"`, `None` otherwise; leave `driver_directory_of` unchanged. In `backend/tests/unit/services/driver/test_labels.py` cover git root (`None`), git driver directory, local path and `"internal"`
- [X] T007 [P] In `backend/styrmin_backend/repository/action.py` add the abstract `ActionRepository.list_by_driver_version(driver_version_id: UUID) -> list[Action]` and its `SQLModelActionRepository` implementation (filter on `application_driver_version_id`, order by `name`). Add the same method to the fake action repository in `backend/tests/unit/services/fakes.py`. Create `backend/tests/unit/repository/test_action_repository.py` with the in-memory database setup of `backend/tests/unit/repository/conftest.py`: two driver versions with actions; the method returns only the actions of the given version, ordered by name, and `[]` for a version without actions
- [X] T008 [P] In `backend/styrmin_backend/domain/steps.py` add `hook_step(hook: HookKind, mode: str) -> StepDefinition` returning `SETUP_PRE_HOOK`, `SETUP_POST_HOOK`, `UPGRADE_PRE_HOOK`, `UPGRADE_CORE_HOOK` or `UPGRADE_POST_HOOK`, and raising `ValueError` for any other pair. Add a parametrised unit test in `backend/tests/unit/steps/test_hook_step.py`
- [X] T009 Create `backend/styrmin_backend/services/driver/hooks.py` per [contracts/hook-resolution.md](contracts/hook-resolution.md#functions) and [data-model.md](data-model.md#value-objects-new-service-layer):
  - `ActionRegistrationKey` (frozen dataclass) with `key_for_version(driver_version, application_name)` and `key_for_driver_object(driver_object)` (local: `source.path`; git: `source.driver_directory`; fingerprint from `short_fingerprint`; directory from `action_directory_of`);
  - `UpgradeHookFlows`;
  - `load_command_for(driver_version)` returning the three forms of [contracts/errors.md](contracts/errors.md#actionnotregisterederror-fr-005);
  - `resolve_hook_flow`, `resolve_setup_hooks` and `resolve_upgrade_hooks`, which read declared actions with `uow.actions.list_by_driver_version`, call `prefect_manager.get_user_action_deployment_id(..., fingerprint=key.fingerprint, driver_directory=key.directory)`, and raise `ActionNotRegisteredError` with `format_driver_version_label(...)` and every declared action name of the pair.

  Depends on T002, T006, T007
- [X] T010 [P] Create `backend/tests/unit/services/driver/test_hooks.py` with a fake `PrefectManager` and the fake unit of work: the truth table of [contracts/hook-resolution.md](contracts/hook-resolution.md#functions) (no declared action → `None` without a lookup; declared and found → the id; declared and not found → `ActionNotRegisteredError` naming every action of the pair); `resolve_upgrade_hooks` returns `None` when no `upgrade`/`core` action is declared and does not look up `pre`/`post`; a local version's lookup passes `driver_directory=<source_path>` and its short `content_hash`; a git root version passes `driver_directory=None`. Depends on T009

**Checkpoint**: the shared pieces exist and are tested; nothing calls them yet.

---

## Phase 3: User Story 1 - Deploy and upgrade an application from a driver loaded from a local directory (Priority: P1) 🎯

**Goal**: a local driver version registers its actions (FR-001), and each action runs the `actions.py` at the version's path in the action's image, after the check of the files (FR-002). Hooks find the registrations of local versions.

**Independent Test**: T021. Load the `local-actions` fixture driver from `/source/backend/tests/e2e/fixtures/drivers/local-actions`, deploy `0.1.0`, upgrade to `0.2.0`. Expected: three registrations, the `hook:setup:pre`, `hook:setup:post` and `hook:upgrade:core` steps succeeded, and each marker is in its action's flow run logs.

### Run a local action from its path

- [X] T011 [US1] Create `backend/styrmin_backend/workflows/local_driver.py` with the pull step `check_local_driver(directory, content_hash, spec_file, values_template, actions_file) -> dict[str, str]` of [contracts/local-driver-check.md](contracts/local-driver-check.md#the-pull-step):
  - raise `DriverFilesNotFoundError` for a missing directory, spec file or actions file;
  - compute `compute_driver_directory_fingerprint(..., include_actions=True)` and raise `DriverFingerprintMismatchError` when it differs;
  - log one `INFO` line with the path and the short fingerprint, and return `{"directory": directory}`;
  - on the error paths only, resolve the image with a helper `_action_image()`: the flow run from `PREFECT__FLOW_RUN_ID`, its deployment's `job_variables["image"]`, else its work pool's base job template `variables.properties.image.default`, else the fallback texts of the contract. A failure to read Prefect never replaces the original error.

  Depends on T002, T004
- [X] T012 [US1] In `backend/styrmin_backend/workflows/models.py` add `LocalDriverActionWorkflowDefinition(WorkflowDefinition)` with `directory`, `content_hash`, `spec_file`, `values_template` and `actions_file`, per [contracts/action-registration.md](contracts/action-registration.md#workflow-definition-of-a-local-action):
  - `entrypoint` returns `f"{module}:{function}"`;
  - `to_deployment()` adds the single pull step `{"styrmin_backend.workflows.local_driver.check_local_driver": {...}}`;
  - `get_function()` runs the same checks as `check_local_driver` (call its check logic, not Prefect) before it imports the function from `<directory>/<module>`.
- [X] T013 [US1] In `backend/styrmin_backend/services/user.py` make `ActionsWorkflowBuilder.__init__(self, source: GitSource | LocalSource, commit_sha: str | None = None, content_hash: str | None = None)` and build a `LocalDriverActionWorkflowDefinition` for a `LocalSource` (`directory=source.path`, `content_hash` required, the three file names from `config.SETTINGS.driver`), keeping the `GitSourceWorkflowDefinition` path unchanged
- [X] T014 [P] [US1] Create `backend/tests/unit/workflows/test_local_driver_check.py` (success paths only; US2 adds the error paths): for a `tmp_path` copy of `backend/tests/e2e/fixtures/drivers/local-actions` (T020; until it exists, use `driver/examples/simple-app`), `check_local_driver` returns `{"directory": <path>}` and logs the `INFO` line; `LocalDriverActionWorkflowDefinition.to_deployment()` has entrypoint `actions.py:<function>`, exactly one pull step with the five inputs, and `job_variables == {"image": ...}` only when the action sets `image:`; the builder with a `LocalSource` returns that definition; Prefect's `run_steps` on the pull step returns the directory, and `load_flow_from_entrypoint("actions.py:pre_setup")` then succeeds from it

### Register local actions on load

- [X] T015 [US1] In `backend/styrmin_backend/services/applications.py` add `ensure_action_registrations(driver_object, prefect_manager) -> int` per [contracts/action-registration.md](contracts/action-registration.md#ensure_action_registrations), using `ActionRegistrationKey.key_for_driver_object` (T009):
  - refuse with `DriverLoadingError` a `LocalSource` path that contains `{` or `}` when the driver declares actions (research R-005);
  - look up each declared hook and mode pair, and register every action of each pair that has no flow;
  - for a `GitSource`, call `register_token` only when at least one action is registered.

  In `load_application_driver_from_object`, replace the git-only registration block: call `ensure_action_registrations` for a new version after the service and component validation and just before the insert (critique E3). Pass `content_hash=driver_object.content_hash` to the builder for local sources. Update the comments that say only git drivers register actions
- [X] T016 [P] [US1] Create `backend/tests/unit/services/test_local_action_registration.py` with a fake `PrefectManager`:
  - a new local version with three actions registers three workflows with `driver_directory=<path>` and `fingerprint=<content_hash[:7]>`, and no token;
  - a git version still registers its token and its workflows;
  - a local path with `{` is refused for a driver with actions and accepted for one without;
  - a load refused by service validation registers nothing;
  - a pair whose lookup already finds a flow is not registered again.
- [X] T017 [US1] In `backend/tests/functional/test_user_action_registration.py` (real Prefect through `prefect_test_harness`) add:
  - each of the five bundled drivers loaded with `get_local_driver_loader(<repo>/driver/examples/<name>)` and `ensure_action_registrations` creates three deployments with the tags `fingerprint/<hash7>` and `directory/<path>` and the check pull step (FR-001, SC-001 registration);
  - two `tmp_path` copies of one driver at two paths create two sets of deployments that the lookup tells apart (FR-002).

### Hooks find local registrations

- [X] T018 [US1] In `backend/styrmin_backend/services/reconciliation/remediation.py` make `InstanceCreationStrategy.execute` call `resolve_setup_hooks` and `InstanceUpdateStrategy._handle_upgrade` call `resolve_upgrade_hooks` (T009) instead of `get_user_action_deployment_id`; `None` from `resolve_upgrade_hooks` keeps the fall-back to `_handle_update`, and `ActionNotRegisteredError` propagates ([contracts/hook-resolution.md](contracts/hook-resolution.md#callers)). Pass the strategy's `self.uow`. Remove the now-unused imports. In `backend/styrmin_backend/services/applications.py` delete `instantiate_application`, and delete its four tests in `backend/tests/unit/services/test_application_services.py` (research R-007); fix the docstring of `backend/styrmin_backend/workflows/catalogue.py` around line 142 that names it
- [X] T019 [P] [US1] Update `backend/tests/unit/services/reconciliation/test_remediation.py` for T018 (stub `uow.actions.list_by_driver_version` in the existing fixtures) and add:
  - a local driver version's create and upgrade lookups receive `driver_directory=<source_path>`;
  - a create whose `setup`/`pre` action is declared and not registered raises `ActionNotRegisteredError`;
  - an upgrade whose target declares no `upgrade`/`core` action falls back to an update;
  - an upgrade whose `upgrade`/`core` action is declared and not registered raises, and does not fall back.

### E2E (US1)

- [ ] T020 [P] [US1] Create the fixture driver `backend/tests/e2e/fixtures/drivers/local-actions/`:
  - `driver.styrmin.yml`: name `local-actions`, `supported_versions: ">=0.1,<1.0"`, `helm.main.location: http://chart-server.default.svc.cluster.local:8080/simple-app`, version `0.1.0`, and the components and services of `backend/tests/e2e/fixtures/drivers/failing-actions/driver.styrmin.yml`;
  - actions `pre_setup` (setup/pre), `post_setup` (setup/post) and `upgrade` (upgrade/core);
  - `values.j2.yml` copied from `failing-actions`;
  - `actions.py`, whose three `@flow` functions only log `LOCAL-ACTIONS-MARKER <action> code=A`. Take each signature from the hook's parameters: `context` for setup; for `upgrade`, see `driver/examples/simple-app/actions.py`.

  Add a header comment saying the file must be in the Styrmin image.
- [ ] T021 [US1] Create `backend/tests/e2e/test_local_driver_actions.py` with `pytestmark = [pytest.mark.ci, pytest.mark.shard_general]` and `@pytest.mark.api_only(reason="The change is in which actions run; the deploy and upgrade UI flows are covered by test_deploy_app")` on each test. Move `_kubectl_cp` from `backend/tests/e2e/test_driver_reload_identity.py` into `backend/tests/e2e/helpers/drivers.py` and import it in both modules. Add a module-scoped fixture that:
  - depends on `chart_server`, `simple_app_image` and `simple_app_image_v2`;
  - loads `/source/backend/tests/e2e/fixtures/drivers/local-actions` with `client.drivers.load_local_version`;
  - creates a deployment at `0.1.0` in the scenario environment, pinned to that driver version.

  Then add `test_local_driver_actions_run_on_create_and_upgrade`, which asserts:
  - Prefect holds three deployments tagged `directory//source/backend/tests/e2e/fixtures/drivers/local-actions`;
  - the create task's `hook:setup:pre` and `hook:setup:post` steps succeeded;
  - after `update_version(..., "0.2.0", driver_version_id=<pinned>)`, the task's `hook:upgrade:core` step succeeded and the deployment runs `0.2.0`;
  - the flow run logs of the three actions contain their markers. Read logs with the Prefect client the way `test_driver_version_reselection.py` reads deployments.

  Keep the deployment for US3 (T034).
- [ ] T022 [US1] Run the US1 E2E per the E2E run rules: `docker compose build server`, then `sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade" -v -s --pdb 2>&1 | tee /tmp/029-us1.log`; fix failures; record the passing run in `specs/029-local-driver-actions/e2e-evidence.md`

**Checkpoint**: a local driver version's setup and upgrade actions run. US1 is usable on its own.

---

## Phase 4: User Story 2 - A changed or missing local driver fails with an error instead of running old code (Priority: P2)

**Goal**: the check's errors (FR-003, FR-004) reach the hook step with their full text, so the author knows what to do (SC-003).

**Independent Test**: T027. A driver whose action's `image:` holds an edited copy fails `hook:setup:pre` with the fingerprint error, and a driver copied only into the server pod fails with the missing-files error.

- [ ] T023 [US2] In `backend/styrmin_backend/agent/tasks/utils.py` change `run_deployment_or_fail` per [contracts/local-driver-check.md](contracts/local-driver-check.md#how-the-error-reaches-the-hook-step) (research R-002):
  - for a crashed flow run, read its first `ERROR` log with `client.read_logs(LogFilter(flow_run_id=..., level=LogFilterLevel(ge_=40)), limit=1, sort=LogSort.TIMESTAMP_ASC)`;
  - cut the log to 4,000 characters, and raise `Deployment flow run <id> crashed: <log> (<state message>)`;
  - when the log is absent or the read fails, log a warning and keep today's message.

  The failed-state branch is unchanged.
- [ ] T024 [P] [US2] In `backend/tests/unit/agent/tasks/test_run_deployment_or_fail.py` add, with a fake Prefect client:
  - a crashed run with an `ERROR` log puts the log text and the state message in the error;
  - a crashed run without one keeps today's text;
  - a read that raises keeps today's text;
  - a 10,000-character log is cut to 4,000;
  - a failed run is unchanged.
- [ ] T025 [P] [US2] In `backend/tests/unit/workflows/test_local_driver_check.py` add the error paths, and check every "Must contain" part of [contracts/errors.md](contracts/errors.md):
  - a missing directory and a missing `actions.py` raise `DriverFilesNotFoundError` naming what is missing;
  - an edited `actions.py`, values template or spec file raises `DriverFingerprintMismatchError`;
  - `_action_image()` returns the deployment's `job_variables` image, else the work pool default, else the fallback text, with a fake Prefect client and `PREFECT__FLOW_RUN_ID` set;
  - `LocalDriverActionWorkflowDefinition.get_function()` raises the same errors before it imports;
  - a subprocess run with an empty environment (`env={}` plus `PATH`) imports `styrmin_backend.workflows.local_driver` and exits 0 (critique E1).
- [ ] T026 [US2] In `backend/tests/e2e/test_local_driver_actions.py` add a module-scoped fixture `local_actions_check_image`:
  - choose a per-session path `/tmp/local-actions-check-<session hex>`;
  - write a variant of the fixture driver named `local-actions-check` whose three actions set `image: local-actions-check:<session hex>`;
  - build that image with `docker build` `FROM` the Styrmin image under test (`registry.opsmill.io/opsmill/styrmin:<STYRMIN_IMAGE_VER or latest>`, the tag that `styrmin_deployment` installs), `COPY` the variant with an edited `actions.py` (`code=B`) to the per-session path;
  - remove the image at teardown.
- [ ] T027 [US2] In `backend/tests/e2e/test_local_driver_actions.py` add `test_changed_local_driver_fails_with_the_fingerprint_error`. It copies the unedited variant (`code=A`) into the server pod at the per-session path with `_kubectl_cp`, loads it, and creates a deployment pinned to it. Assert:
  - the task fails;
  - its `hook:setup:pre` step error contains the path, `local-actions-check:<session hex>`, both short fingerprints and "Rebuild the image";
  - no marker with `code=B` or `code=A` is logged.

  Add `test_driver_missing_from_the_action_image_fails_with_the_missing_files_error`. It copies `local-actions-check` without `image:` into the server pod at a second per-session path, loads it, and creates a pinned deployment. Assert that the `hook:setup:pre` step error names the path and the default image. Delete both deployments at the end
- [ ] T028 [US2] Run the US2 E2E per the E2E run rules (`docker compose build server` first if backend code changed since T022): `sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py" -k "fingerprint_error or missing_files_error" -v -s --pdb 2>&1 | tee /tmp/029-us2.log`; record the passing run in `specs/029-local-driver-actions/e2e-evidence.md`

**Checkpoint**: a changed or missing local driver fails with an error that names the path, the image and the fingerprints.

---

## Phase 5: User Story 3 - A hook whose action is not registered fails, and loading the driver again repairs it (Priority: P3)

**Goal**: a missing registration fails the hook step (FR-005); a repeated load registers what is missing (FR-006); the same upgrade can be requested again (FR-007).

**Independent Test**: T034. After the US1 version's Prefect deployments are deleted, the upgrade request returns a failed task with a failed `hook:upgrade:core` step, and the deployment keeps `0.2.0`. After the driver is loaded again, the same request runs the upgrade action.

- [ ] T029 [US3] In `backend/styrmin_backend/agent/tasks/orchestration.py` (`apply_state`) catch `ActionNotRegisteredError` from `_plan_remediation`: end the plan step without an error, open `steps.hook_step(exc.hook, exc.mode)` with `open_task_step`, end it with `error=format_exception(exc)`, and re-raise ([contracts/hook-resolution.md](contracts/hook-resolution.md#recording-in-apply_state-r-008)); other exceptions keep today's handling
- [ ] T030 [P] [US3] In `backend/tests/unit/agent/tasks/test_apply_state_flow.py` add: planning that raises `ActionNotRegisteredError` for `setup`/`pre` ends the plan step without an error, records a failed `hook:setup:pre` step with the error text, and re-raises; another exception still fails the plan step
- [ ] T031 [US3] In `backend/styrmin_backend/services/applications.py` call `ensure_action_registrations` on the existing-version paths of `load_application_driver_from_object` (both the info-column refresh branch and the plain return), before each `return` (FR-006, [contracts/action-registration.md](contracts/action-registration.md#ensure_action_registrations))
- [ ] T032 [P] [US3] Add tests for T031:
  - In `backend/tests/unit/services/test_local_action_registration.py`: loading an existing version whose pairs all resolve makes no `register_user_action` call; when one pair resolves and another does not, only the actions of the missing pair are registered.
  - In `backend/tests/functional/test_user_action_registration.py`: load a local driver, delete its deployments through the Prefect client, load it again, and the three deployments exist again.
- [ ] T033 [US3] In `backend/styrmin_backend/services/deployment.py` (`update_deployment_version`) add the request check of [contracts/hook-resolution.md](contracts/hook-resolution.md#request-check-in-update_deployment_version) (research R-009):
  - Place it after the request's validations and before `_ensure_ingress_controller`, and check that nothing above it writes to the session.
  - It runs when the deployment has an active instance whose `application_version` differs from the target version.
  - On `ActionNotRegisteredError` from `resolve_upgrade_hooks(target_driver_version, ...)`, leave the deployment unchanged and save `Task.create(type=TaskType.UPGRADE_INSTANCE, deployment_id=..., status=TaskStatus.FAILED, started_by_step_id=...)` with `message=str(exc)`.
  - Record `steps.hook_step(exc.hook, exc.mode)` with `open_step` and `fail_step` (error `format_exception(exc)`), commit, and return the task.
- [ ] T034 [P] [US3] Create `backend/tests/unit/services/test_update_version_hook_check.py`, following the setup of `backend/tests/unit/services/test_update_deployment_noop.py`:
  - an upgrade to a target whose `upgrade`/`core` action is not registered returns a `failed` task of type `upgrade_instance` with no flow run and a failed `hook:upgrade:core` step whose error names the action;
  - the deployment's version, driver binding, status and active instance are unchanged, and `apply_state` is not called;
  - `started_by_step_id` is kept on the task;
  - a driver-only change at the same application version runs no check;
  - a target that declares no `upgrade`/`core` action passes;
  - an equivalence test (critique X1): for a version increase, a decrease, a driver-only change and no change, the check runs exactly when `Comparator(current_instance, new_instance).compare()` yields an `ApplicationVersionChange`.
- [ ] T035 [US3] In `backend/tests/e2e/test_local_driver_actions.py` add `test_missing_registration_fails_and_loading_again_repairs_it`, using the US1 deployment at `0.2.0`:
  - delete the Prefect deployments tagged `directory//source/backend/tests/e2e/fixtures/drivers/local-actions`;
  - call `update_version(..., "0.1.0", driver_version_id=<pinned>)` and assert:
    - the returned task failed and its `hook:upgrade:core` step error names `local-actions`, the hook, the mode, `upgrade` and "Load the driver again";
    - the deployment still reports `0.2.0`;
  - load the driver again and assert the three deployments exist;
  - send the same `update_version` call again and assert:
    - a new task succeeds with a succeeded `hook:upgrade:core` step;
    - the `upgrade` marker is logged;
    - the deployment runs `0.1.0`.

  Delete the deployment at the end
- [ ] T036 [US3] Run the US3 E2E per the E2E run rules: `sleep infinity | uv run pytest "backend/tests/e2e/test_local_driver_actions.py::test_local_driver_actions_run_on_create_and_upgrade" "backend/tests/e2e/test_local_driver_actions.py::test_missing_registration_fails_and_loading_again_repairs_it" -v -s --pdb 2>&1 | tee /tmp/029-us3.log`; record the passing run in `specs/029-local-driver-actions/e2e-evidence.md`

**Checkpoint**: no declared action is skipped without an error, and a repeated load repairs a version.

---

## Phase 6: Documentation (Constitution §VII)

**Purpose**: every page in the plan's documentation table, in the same change.

- [ ] T037 [P] Update `docs/docs/drivers/loading-drivers.md` ("From a local directory" and "Reloading a local driver while you iterate"):
  - the actions of a local driver run from the same path in the action's image, so the image must hold the driver there;
  - what a custom `image:` must hold: the driver at the path, Prefect 3.6.9 or later, and a `styrmin_backend` with the check step;
  - the three errors with an example of each and how to fix each: rebuild the image or load again; put the driver in the image; load again and request the change again, and delete and create again a failed create;
  - loading a driver again registers its missing actions;
  - a local path with `{` or `}` is refused for a driver with actions;
  - how to recover when an action's check fails during an upgrade (spec Edge Cases);
  - actions must not log secrets, because the first error log of a crashed action appears on its hook step.
- [ ] T038 [P] Update `dev/guides/driver-iteration.md`:
  - after editing an action on the dev stack, run `docker compose build` and load the driver again, because action Jobs read the image and not the bind mount;
  - fix line ~69: the values template name comes from `STYRMIN_DRIVER_VALUES_TEMPLATE`, not from `spec.helm.main.values_template`;
  - fix line ~76: each part is framed as its name, a zero byte and an 8-byte big-endian length;
  - fix line ~53: a repeated load registers the actions that hooks cannot resolve.
- [ ] T039 [P] Update `dev/knowledge/backend/hooks-and-actions.md`:
  - the registration pipeline for local and git versions;
  - the check pull step and its errors;
  - `action_directory_of` in the lookup section;
  - hook resolution and `ActionNotRegisteredError`;
  - the hook step recorded by `apply_state`;
  - the request check in `update_deployment_version`;
  - the first error log of a crashed action in the hook step error, and that every signed-in user can read it.

  Replace "local loads register no actions" and the `driver_directory_of` caller list
- [ ] T040 [P] Update `dev/knowledge/backend/data-models.md` (line ~166: the Prefect action lookup reads `action_directory_of`), `dev/knowledge/backend/orchestration-flows.md` (line ~491: `GitSourceWorkflowDefinition` or `LocalDriverActionWorkflowDefinition`), `dev/knowledge/backend/services.md` (line ~347: a repeated load registers missing actions) and `dev/knowledge/backend/api.md` (`loadLocalApplicationDriverVersion` row: registers actions, also for an existing version; refuses a path with `{` or `}` for a driver with actions)
- [ ] T041 [P] Update `driver/DRIVERS.md` "Actions" section, next to the Prefect 3.6.9 rule: for a driver loaded from a local directory, the action's `image` must hold the driver at the same path and a `styrmin_backend` with the check step
- [ ] T042 [P] Create `dev/adr/0081-local-driver-actions-run-from-the-path-in-the-job-image.md` in the format of `dev/adr/0080-action-deployments-keyed-by-driver-directory.md`:
  - the decisions of the spec's "Decisions and Rejected Alternatives";
  - research R-001 (pull step), R-002 (crash log), R-003 (key), R-005 (brace refusal), R-007 and R-008 (hook resolution and recording) and R-009 (request check), with the rejected alternatives;
  - a Confirmation section naming the tests of T014, T017, T021, T025, T027, T034 and T035.

  Add its entry to the ADR index in `dev/README.md`
- [ ] T043 [P] Add an amendment note dated 2026-10-19 to `dev/adr/0053-driver-version-provenance-fingerprint.md`, after the paragraph that says a repeated load does not register actions again and that a historical deployment resolves its actions to its bytes: a repeated load now registers missing actions, and a local version's action checks the files at its path against its fingerprint (link ADR-081)
- [ ] T044 [P] Update `CONTEXT.md`. **Action**: actions of a local driver version run from its path in the action's image after a provenance fingerprint check; a declared action without a registered flow fails its hook. **Provenance fingerprint**: also checked in a local action's Job. Keep the "_Avoid_" lines
- [ ] T045 [P] Run `uv run towncrier create -c "<text>" 372.fixed.md` to create `changelog/372.fixed.md`, following `dev/guidelines/changelog.md`. The text says that:
  - the actions of drivers loaded with `load-local-version` now run, and a declared action without a registered flow fails its hook instead of being skipped;
  - operators should load their local drivers again;
  - deployments created from them before the fix never ran their setup actions.

---

## Phase 7: Polish and Verification

- [ ] T046 Stage all changes, then run `export npm_config_ignore_workspace=true && uv run invoke format lint`; fix every finding
- [ ] T047 Run the backend unit and functional suites: `uv run invoke test` (or `uv run pytest backend/tests/unit backend/tests/functional -q`); every test passes
- [ ] T048 Run the whole new E2E module in one session per the E2E run rules, after `docker compose build server`: `sleep infinity | uv run pytest backend/tests/e2e/test_local_driver_actions.py -v -s --pdb 2>&1 | tee /tmp/029-e2e.log`; record the run in `specs/029-local-driver-actions/e2e-evidence.md`
- [ ] T049 Re-run the E2E tests whose path changed, in one session: `sleep infinity | uv run pytest backend/tests/e2e/test_driver_reload_identity.py backend/tests/e2e/test_driver_version_reselection.py backend/tests/e2e/test_task_steps.py backend/tests/e2e/test_deploy_app.py -k "not ui-chromium" -v -s --pdb 2>&1 | tee /tmp/029-regression.log`; record the run in `specs/029-local-driver-actions/e2e-evidence.md`; any test that relied on a skipped hook is a finding to fix, not to skip (SC-002)
- [ ] T050 Run the quickstart sections 1, 2 and 4 ([quickstart.md](quickstart.md)); on the dev stack, run the section 3 scenarios that the available cluster supports, at least the Semaphore registration and the `simple-app` scenarios, and note in `specs/029-local-driver-actions/e2e-evidence.md` which scenarios ran and which did not
- [ ] T051 Write `specs/029-local-driver-actions/follow-ups.md` with a title and a short body for each follow-up issue that research lists (the Prefect upstream issue, the shared driver volume, `upgrade`/`pre` and `upgrade`/`post` without `upgrade`/`core`, running an upgrade again after its action failed, the note on #10), for the maintainer to open; do not open issues

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 → Phase 2 → Phases 3 to 5 → Phase 6 → Phase 7.
- Phase 6 can start once the behaviour it documents is in the branch: T037 to T041 after T015, T018, T023, T029 and T033; T042 to T045 at any time after Phase 2.

### User Story Dependencies

- US1 (Phase 3) depends on Phase 2.
- US2 (Phase 4) depends on T011 and T012 (the check and the workflow definition) and, for its E2E, on T021's module and helpers.
- US3 (Phase 5) depends on T015 (`ensure_action_registrations`) and T018 (hook resolution in the remediations); its E2E T035 reuses the deployment of T021.

### Within Each Story

- US1: T011 → T012 → T013 → T014; T013 → T015 → T016, T017; T018 → T019; T020 → T021 → T022.
- US2: T023 → T024; T025 after T011 and T012; T026 → T027 → T028.
- US3: T029 → T030; T031 → T032; T033 → T034; T035 after T031 and T033 → T036.

### Parallel Opportunities

- Phase 2: T002, T004, T006, T007 and T008 touch different files; T003 after T002; T005 after T004; T009 after T002, T006 and T007; T010 after T009.
- Phase 3: T014, T016, T017 and T019 are separate test files; T020 can start with Phase 3.
- Phase 4: T024 and T025 in parallel.
- Phase 5: T030, T032 and T034 in parallel.
- Phase 6: T037 to T045 in parallel.

---

## Parallel Example: Phase 2

```text
In parallel:
  T002 backend/styrmin_backend/services/driver/exceptions.py
  T004 backend/styrmin_backend/services/driver/hash.py and loaders.py
  T006 backend/styrmin_backend/services/driver/labels.py
  T007 backend/styrmin_backend/repository/action.py
  T008 backend/styrmin_backend/domain/steps.py
Then: T003, T005 (tests); T009 → T010
```

## Parallel Example: User Story 1 tests

```text
After T015 and T018:
  T014 backend/tests/unit/workflows/test_local_driver_check.py
  T016 backend/tests/unit/services/test_local_action_registration.py
  T017 backend/tests/functional/test_user_action_registration.py
  T019 backend/tests/unit/services/reconciliation/test_remediation.py
```

---

## Implementation Strategy

1. Phases 1 and 2: the shared pieces with their unit tests.
2. Phase 3 (US1): register and run local actions, switch the remediations to hook resolution, then run T022 as soon as the module can run. This alone fixes the defect of #372 for drivers whose files match the image.
3. Phase 4 (US2): the crash log in the hook step error and the two failure scenarios.
4. Phase 5 (US3): the hook step recorded by `apply_state`, registration on a repeated load, the request check, and the repair scenario.
5. Phase 6: documentation, the ADR, the CONTEXT entries and the changelog fragment in the same change (Constitution §VII).
6. Phase 7: lint, the unit and functional suites, the whole E2E module and the regression modules with recorded evidence. The feature is not done until T048 and T049 have recorded `PASSED` lines.
