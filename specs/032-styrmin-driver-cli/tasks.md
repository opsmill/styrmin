---

description: "Task list for 032-styrmin-driver-cli"
---

# Tasks: Check, Render and Compare an Application Driver on the Author's Machine with `styrmin-driver`

**Input**: Design documents from `specs/032-styrmin-driver-cli/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md), [contracts/internal-interfaces.md](contracts/internal-interfaces.md), [quickstart.md](quickstart.md)

**Tests**: Included. The spec's "Testing Decisions" section and constitution section V require unit tests and one E2E node. Within each story, write the tests first and check that they fail before the implementation.

**Organization**: Phase 2 is the move of the driver format code to the SDK (pull request 1, research R-020). It changes no behaviour and blocks every story. Phases 3 to 6 are pull request 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task).
- **[Story]**: the user story of the task (US1, US2, US3).
- Paths are from the repository root. `SDK/` means `python_sdk/src/styrmin_sdk/driver_format/`. `BE/` means `backend/styrmin_backend/`.

## How to move a module (applies to every task of Phase 2)

1. Create the SDK file with the content of the backend file, unchanged except for its imports, which point to `styrmin_sdk.driver_format.*`.
2. Replace every `from loguru import logger` by `logger = logging.getLogger(__name__)` with `import logging` (research R-012). Keep the log messages.
3. Keep a function-level import where a module-level import would create an import cycle (for example `config.py` importing `InvalidReplicaCountError`).
4. Replace the backend file by a module that re-exports every public name and every private name that another backend module or test imports (for example `_ENV_VAR_NAME_RE`), with an explicit `__all__` (research R-002). Grep `backend/` for `from styrmin_backend.<old path> import` to find the names.
5. Change no message, no error class, no default and no behaviour.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The SDK package, its dependencies and its lint target.

- [X] T001 Create the package `python_sdk/src/styrmin_sdk/driver_format/` with `__init__.py` (a docstring that says this package holds the driver format code that the server, the agent and `styrmin-driver` share, and points to ADR-0089), and the empty subpackages `models/`, `models/resources/`, `models/structure/`, `reading/`, `context/`, `context/models/`, `context/validation/`, `context/validation/env_vars/`, `context/validation/container_overrides/`, `context/validation/image_overrides/`, `context/validation/replicas/` and `context/validation/parameters/`, each with an `__init__.py`. Create `python_sdk/tests/driver_format/__init__.py`.
- [X] T002 Add `jinja2>=3.1` and `packaging>=24` to `[project].dependencies` in `python_sdk/pyproject.toml`, and `styrmin-sdk` to `[project].dependencies` in `backend/pyproject.toml` (the root `[tool.uv.sources]` at `pyproject.toml:124-127` already maps it to the workspace). Run `uv lock`, check with `git diff uv.lock` that no `[[package]]` entry is added (only dependency lists change), and run `uv lock --check` (research R-017).
- [X] T003 [P] Add `per-file-target-version = { "python_sdk/**/*.py" = "py312" }` to the root `[tool.ruff]` section of `pyproject.toml` (research R-011, amended). Run `uv run ruff check python_sdk` and `uv run invoke lint`, and fix nothing in existing SDK code unless ruff reports Python 3.12 syntax errors.
- [X] T004 [P] Create `python_sdk/tests/driver_format/conftest.py` with an autouse fixture that replaces `socket.socket.connect`, `socket.socket.connect_ex` and `socket.create_connection` with a function that raises `RuntimeError("network access is not allowed in styrmin-driver tests")`, using `monkeypatch` (research R-014, FR-013).

---

## Phase 2: Foundational — move the driver format code to the SDK (pull request 1)

**Purpose**: One copy of the code that reads, checks and renders a driver, used by the backend (FR-015), with no behaviour change (FR-016). Research R-001, R-002, R-011, R-012; [contracts/internal-interfaces.md](contracts/internal-interfaces.md).

**⚠️ CRITICAL**: No user story can start until this phase passes the whole backend suite.

### Errors

- [X] T005 Move `ServiceError` (`BE/services/exceptions.py:8-19`) to `SDK/errors.py`, and import it in `BE/services/exceptions.py` from there, so that every backend error keeps it as its base. In the same task move `CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL`, `ENV_VARS_MIGRATION_GUIDE_URL`, `RetiredTemplateFilter`, `retired_filter_load_message` and `RetiredTemplateFilterError` (`BE/services/exceptions.py:971-1050`), and `InvalidSchedulingConfigError`, `UnclonedDeploymentReferenceError`, `UnknownComponentInConfigError` and `UnresolvableAffinityReferenceError` (used by `BE/context/exceptions.py` and `BE/context/resolvers.py:32`), to `SDK/errors.py`. `BE/services/exceptions.py` re-exports them. *Done with one change*: only `UnknownComponentInConfigError` moved, because `BE/context/resolvers.py:32` raises it; `InvalidSchedulingConfigError`, `UnclonedDeploymentReferenceError` and `UnresolvableAffinityReferenceError` are only re-exported by `BE/context/exceptions.py`, so they stay in the backend and that module re-exports them as before.
- [X] T006 Move `DriverError`, `DriverDefinitionError`, `ParsingError`, `ValidationError`, `DeserializationError`, `DriverLoadingError` and `MissingDriverSpecificationError` (`BE/services/driver/exceptions.py:8-39`) to `SDK/errors.py`. `BE/services/driver/exceptions.py` re-exports them and keeps `DriverFilesNotFoundError`, `DriverFingerprintMismatchError` and `ActionNotRegisteredError`, which now subclass the re-exported `DriverError`.
- [X] T007 Move `ChartValuesTemplateRenderingError` and `InvalidChartValuesError` from `BE/agent/service/kubernetes/resources/builders/exceptions.py:1-5` to `SDK/errors.py`, keeping them plain `Exception` subclasses with the same names; `builders/exceptions.py` re-exports them. Do not touch the `ServiceError` classes of the same names at `BE/services/exceptions.py:121-128` (contracts/internal-interfaces.md, "Two classes per renderer error name").
- [X] T008 [P] Move whole exception modules (procedure above): `BE/services/env_vars/exceptions.py` to `SDK/context/validation/env_vars/exceptions.py`, `BE/services/container_overrides/exceptions.py` to `SDK/context/validation/container_overrides/exceptions.py`, `BE/services/image_overrides/exceptions.py` to `SDK/context/validation/image_overrides/exceptions.py`, `BE/services/replicas/exceptions.py` to `SDK/context/validation/replicas/exceptions.py`, and `BE/services/parameters/exceptions.py` to `SDK/context/validation/parameters/exceptions.py`.

### Context model and its validators

- [X] T009 [P] Move the validators that the context model calls: `BE/services/backup/ttl.py` to `SDK/context/validation/backup_ttl.py`, `BE/services/env_vars/validator.py` to `SDK/context/validation/env_vars/validator.py`, `BE/services/container_overrides/validator.py` to `SDK/context/validation/container_overrides/validator.py`, and `BE/services/image_overrides/reference.py` to `SDK/context/validation/image_overrides/reference.py`. The backend re-exports include `_ENV_VAR_NAME_RE`, which `BE/services/driver/models/resources/env_vars.py:22` imports.
- [X] T010 Move the context models `BE/context/models/{contexts,config,components,helm,services,input}.py` to `SDK/context/models/`. In `config.py`, point the function-level imports (lines 446, 520, 539, 594, 612, 621, 632, 705) to the SDK modules of T008 and T009. Leave `BE/context/models/capabilities.py` in the backend. Depends on T008, T009.
- [X] T011 Move `BE/context/{resolvers,validators,fqdn,exceptions}.py` to `SDK/context/`. `SDK/context/__init__.py` exports `resolve_global_context`. *Done with one change*: `SDK/context/__init__.py` stays empty and callers import `styrmin_sdk.driver_format.context.resolvers`, which keeps the package import light. `BE/context/__init__.py` keeps `from .resolvers import resolve_global_context`. Leave `BE/context/namespace_labels.py` in the backend. Depends on T010.
- [X] T012 [P] Move `get_kubernetes_reference` (`BE/agent/service/kubernetes/utils.py:5-8`) and `get_chart_name_from_chart_url` and `get_chart_repository_from_chart_url` (`BE/services/utils.py:17-44`) to `SDK/context/naming.py`; both backend modules import and re-export them. Do not move the rest of `BE/agent/service/kubernetes/utils.py`, which uses Python 3.14 syntax (line 22).
- [X] T013 Move `BE/services/parameters/validator.py` to `SDK/context/parameters.py`; `BE/services/parameters/validator.py` re-exports. Depends on T008 and T015 (it imports `DriverParameterDefinition`).
- [X] T014 Extract the loop of `BE/services/context.py:238-273` into `build_service_entries` in `SDK/context/service_entries.py`. Input: a list of service rows as plain values (`driver_service_name`, `resolved_name`, `port`, `kind`, `deployment_id`, `component`), the current deployment's `app_name` and ID, the environment name and the FQDN suffix. Output: the `services` dict, the `deployed_services` list, and whether the deployment owns a service. `generate_context_from_deployment` calls it with the rows of `uow.deployed_services.get_by_environment_id` and keeps appending `UtilityContext(kind=SERVICE_DISCOVERY)` as today. Depends on T011.

### Driver model, reading, checks and rendering

- [X] T015 Move the driver model `BE/services/driver/models/__init__.py`, `models/resources/{__init__,_shared,actions,backup,code,driver,env_vars,parameters,services}.py` and `models/structure/{__init__,directory,resource,source}.py` to `SDK/models/` with the same layout. In `SDK/models/structure/directory.py`, replace the reads of `config` (lines 3, 26, 31, 37) by a `DriverFileNames` model (`spec_file="driver.styrmin.yml"`, `values_template="values.j2.yml"`, `actions_code="actions.py"`) that the directory map takes as a parameter. The backend's `directory.py` re-exports and adds `driver_file_names_from_settings()`, which reads `spec_file`, `values_template` and `actions_code_file` from `DriverSettings` (`BE/config.py:148-159`, environment prefix `STYRMIN_DRIVER_`). Depends on T010 (`ReplicaDeclaration`).
- [X] T016 Move `BE/services/driver/parsers.py` to `SDK/reading/parsers.py` and `BE/services/driver/deserializers.py` to `SDK/reading/deserializers.py`. Move `ResourceFileLoader` and `get_resource_file_loader` (`BE/services/driver/loaders.py:154-243`) to `SDK/reading/files.py`. Move the base class `DriverProvider` (`BE/services/driver/provider.py:29`) and `LocalDriverProvider` (`:247`) to `SDK/reading/local.py`; `GitDriverProvider`, dulwich and loguru stay in `provider.py`, which imports the base class from the SDK. `DriverLoader` and `get_local_driver_loader` stay in `BE/services/driver/loaders.py` and pass `driver_file_names_from_settings()`. Depends on T015.
- [X] T017 Move `BE/services/driver/validators.py` to `SDK/checks.py` (all of it: `Validator`, `JinjaTemplateValidator`, `UserActionsValidator`, `BackupConfigValidator`, `validate_driver_backup_configs`, `validate_driver_backup_configs_for_spec`, `validate_driver_env_var_docs`, `build_user_actions_validator`, `get_validator`). Its function-level import of `get_jinja_environment` (line 65) points to `SDK/rendering.py`. `BE/services/driver/validators.py` re-exports. Depends on T015, T018.
- [X] T018 Move `split_string`, `component_env_vars`, `component_command`, `component_args`, `get_jinja_environment` and `SilentUndefined` (`BE/agent/service/kubernetes/resources/builders/application.py:74-177`) to `SDK/rendering.py`, with `to_fqdn_label` from `SDK/context/fqdn.py`. Add `render_values(values_template: str, context: GlobalContext) -> dict` with the body of `render_value_template` (lines 224-285), without the Prefect decorator. In `application.py`, import and re-export these names (`BE/agent/service/kubernetes/resources/utilities/ingress.py:15` imports `get_jinja_environment` from there), and keep `render_value_template` as a `@task` static method that returns `render_values(...)`. Depends on T007, T011.

### Logging, tests and documentation of the move

- [X] T019 Add `BE/logging_bridge.py` with `install_sdk_log_forwarding()`, which adds to the standard-library logger `styrmin_sdk` a handler that forwards each record to loguru with its level and message (research R-012). Call it in every process entry point that adds a loguru sink: grep `logger.add(` in `BE/` (today `BE/server/app.py:50`), and in `BE/cli/agent.py` next to `logging.basicConfig` (line 38). Add `backend/tests/unit/test_logging_bridge.py`: a warning logged on `styrmin_sdk.driver_format.context.models.components` reaches a loguru sink. *Done with one change*: `BE/__init__.py` installs the handler when the package is imported, so every backend process and every backend test that captures loguru warnings (for example `backend/tests/unit/services/env_vars/test_validator.py`) gets it, without a call in each entry point. The handler sets `propagate = False` on the `styrmin_sdk` logger so a root handler does not print the records again.
- [X] T020 Run `uv run invoke test`. In the test files under `backend/tests/`, fix each failure caused by a `patch(...)` target that names an attribute of a moved backend module by patching the SDK module instead (research R-002, "Risk"). Do not change an expected message or value. *Result*: no patch target needed a change; 5773 passed, 8 skipped, 1 failed. The failure, `tests/unit/services/telemetry/test_sender.py::test_send_report_returns_false_when_the_connection_is_refused` (7.8 s against a 2 s limit), fails the same way on a clean checkout of `HEAD` on this machine, so it is not caused by the move.
- [X] T021 [P] Add `python_sdk/tests/driver_format/test_no_backend_imports.py`: run `sys.executable -c "import styrmin_sdk.driver_format.checks, styrmin_sdk.driver_format.rendering, styrmin_sdk.driver_format.context; import sys; print(sorted(sys.modules))"` in a subprocess, and assert that no module name starts with `styrmin_backend`, `prefect`, `dulwich`, `loguru`, `sqlmodel` or `pydantic_settings`.
- [X] T022 [P] Add a test to `backend/tests/unit/services/driver/test_loaders.py`: with `STYRMIN_DRIVER_SPEC_FILE` (`DriverSettings.spec_file`, `BE/config.py:148-157`) set to another file name, `get_local_driver_loader(path).load_driver()` reads that file (FR-016).
- [X] T023 [P] Write `dev/adr/0089-driver-format-code-in-the-sdk.md` in the format of `dev/adr/0081-*.md` (Status, Date, Decision-makers, Source, Related; Context, Decision, Consequences, Alternatives). Decision-makers: proposed by Fatih Acar on Slack on 2026-10-28, recorded in the brief of #23. Content from research R-001, R-002, R-011, R-012 and R-020.
- [X] T024 [P] Update `dev/knowledge/architecture.md` (where the driver format code and the context model live, and that the backend depends on the SDK) and `python_sdk/AGENTS.md` (a "Driver format" section and rows in the "File Structure" table for `driver_format/`).
- [X] T025 [P] Add `changelog/23.housekeeping.md` with `uv run towncrier create -c "Moved the code that reads, checks and renders an application driver, and the context model, from the backend to the SDK package. Styrmin's behaviour does not change." 23.housekeeping.md` (`dev/guidelines/changelog.md`).
- [X] T026 Checkpoint for pull request 1: run `uv run invoke format lint`, `uv run invoke test`, `uv run pytest -v python_sdk/tests` and `uv run pytest -v cli/tests`, and run `backend/tests/e2e/test_deploy_app.py` locally with `--pdb` (`AGENTS.md`, "Running with --pdb"). Before opening the pull request, ask the user to confirm that it ships without a new E2E test, naming the existing E2E tests that load and deploy the example drivers (for example `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app`) (`AGENTS.md`, "Ask First"). *Result*: the checks and the E2E run are recorded in [e2e-evidence.md](e2e-evidence.md); the user's confirmation is still to be asked, before the pull request is opened.

**Checkpoint**: The backend runs on the SDK code with no behaviour change. User story work can start.

---

## Phase 3: User Story 1 - Check a driver before loading it (Priority: P1) 🎯 MVP

**Goal**: `styrmin-driver check <dir>` runs the load's checks and a render with the example context, reports the errors it finds with their file and line, and exits with 0 or 1.

**Independent Test**: [quickstart.md](quickstart.md) scenarios 1 and 2: the eight example drivers pass; a driver with an undefined variable on line 12 and a missing action function gets both errors and exit code 1.

### Tests for User Story 1

- [X] T027 [P] [US1] Write `python_sdk/tests/driver_format/test_check_examples.py`: for each directory of `driver/examples/` (found from the test file's path), `main(["check", path])` returns 0 (SC-001). For `generic-app` and `infrahub-mcp`, the report holds one placeholder warning; for every driver except `semaphore`, one application-version warning.
- [X] T028 [P] [US1] Write `python_sdk/tests/driver_format/test_check_errors.py`, building each driver in `tmp_path` from a copy of `driver/examples/simple-app`. One test each for:
  - an undefined variable on line 12 of `values.j2.yml`: `values.j2.yml:12: error: undefined variable 'parameters.admn_email'` (FR-007);
  - an action whose function is missing from `actions.py`: the line of its `location` key in `driver.styrmin.yml` and the message `Missing entrypoint for action <name>: <function>` (FR-001);
  - both together: two error lines, the summary `2 errors`, exit code 1, and exit code 0 after both fixes (user story 1, scenarios 1 and 2);
  - an invalid field and a missing action function together: both reported (FR-009);
  - an unclosed `{% if %}`: file and line (FR-008);
  - a retired filter: its line and the load's message;
  - an `actions.py` with a syntax error: its line (research R-016);
  - an invalid `spec.info.icon`: a warning and exit code 0 (FR-010);
  - a directory without `driver.styrmin.yml`: exit code 1; a path that does not exist: exit code 2 (FR-012);
  - rendered text that is not valid YAML: exit code 1 (research R-018);
  - SC-003: one test per invalid case of the backend's driver tests, each asserting that the message after `error:` and one space equals the load's message without the wrapping prefix (research R-015). The cases are those of `backend/tests/unit/services/driver/`: `test_component_container.py::test_malformed_container_fails_registration`; `test_component_replicas.py::test_singleton_with_more_than_one_replica_fails_registration`, `::test_invalid_replicas_fails_registration_with_field_path`, `::test_non_bool_singleton_fails_registration_with_field_path`; `test_container_overrides_block_rejected.py` (three tests); `test_driver_info.py::test_loader_error_lists_one_line_per_invalid_field`; `test_deserializer.py::test_deserialize_invalid_driver_spec` (each case); `test_env_var_doc_validator.py::TestRegistrationAbortsOnBadDoc` (two tests); `test_validators.py::test_jinja_template_validator_with_invalid_template`, `::test_jinja_template_validator_rejects_retired_filters`, `::test_user_actions_validations_with_missing_func`; and the parameter and service rules of `test_driver_parameters.py` and `test_service_definitions.py` applied through a full `driver.styrmin.yml`. *Done with one change*: the SC-003 cases are in `backend/tests/unit/services/driver/test_styrmin_driver_matches_load.py`, because they compare `check` with the real server load (`get_local_driver_loader`), and the SDK tests do not import the backend. 29 cases pass.
- [X] T029 [P] [US1] Write `python_sdk/tests/driver_format/test_rendering_check_mode.py`:
  - the eight-line template of research R-003 reports the five names and lines of the prototype, and nothing for `is defined`, `default()`, `tojson` and `.items()`;
  - research R-004: `instance.config.fqdn_suffix`, `external_url_scheme or "https"` and `external_url_port` without a value give no error; `instance.config.fqdn_sufix` and `parameters.helth_path` give errors;
  - for each example driver, `render_values(..., mode="check")` with its example context gives the same values as `mode="silent"`.
- [X] T030 [P] [US1] Write `python_sdk/tests/driver_format/test_example_context.py` for `build_example_context`: on `simple-app`, the context validates against `GlobalContext`, has the top-level keys of research R-007, `utilities` holds `ingress` and `service-discovery`, and its services match `spec.services`; two calls give equal contexts (fixed IDs); on `generic-app`, `parameters.image_repository == "example-image_repository"` and one placeholder is returned; an `enum` parameter without a default gets the first of its `values`; the application version is `default_version` for `semaphore` and the lower bound of `supported_versions` (`0.1`) for `simple-app`.

### Implementation for User Story 1

- [X] T031 [US1] In `SDK/checks.py`, add `find_missing_entrypoints(code: str, actions) -> list[ActionDefinition]` and `find_retired_filters(template: str) -> list[tuple[str, int]]`. Make `UserActionsValidator.validate` and `JinjaTemplateValidator.validate` use them and raise for the first item, with today's messages, so the load does not change (research R-015). `backend/tests/unit/services/driver/test_validators.py` passes unchanged.
- [X] T032 [US1] In `SDK/rendering.py`, add a `mode` parameter to `render_values` (`"silent"`, the default, or `"check"`) and a `RenderResult` (values, text, undefined uses as `(line, name)`). In check mode, wrap the dump of the context in `dict` subclasses that know their path and the field names of the model they come from, and render with the recording `Undefined` subclass of research R-003 and R-004 (template line from the frame that holds `__jinja_template__`; a known field without a value renders as `SilentUndefined` and is not recorded). Silent mode returns today's output. *Done with one change*: the check mode is a second function, `render_values_checked(values_template, context) -> RenderResult`, so that `render_values` keeps its signature and return type.
- [X] T033 [US1] Write `SDK/example_context.py` with `build_example_context(spec, template_text) -> tuple[GlobalContext, list[Placeholder]]`, following the table of research R-007 and the placeholders of R-006: a `ContextInput` filled from the driver model, fixed UUID constants, empty configurations, `utilities` with `ingress`, service entries from `build_service_entries`, then `resolve_global_context`. Return a warning item when the application version is not `default_version`.
- [X] T034 [US1] Write `SDK/diagnostics.py` with `Diagnostic` and `CheckReport` ([data-model.md](data-model.md)) and `run_checks(root, file_names=DriverFileNames(), context=None) -> CheckReport`: run every check of the table of research R-015 and collect every problem; map each Pydantic error location of `driver.styrmin.yml` to a line with `yaml.compose` (R-005); strip the load's wrapping prefixes; report an `actions.py` `SyntaxError` with its line (R-016); turn `Info.warnings` into warnings; when the model and the template syntax are valid, render with `mode="check"` and report undefined uses and values that are not valid YAML (R-018). Sort by file, line, then check order.
- [X] T035 [US1] Write `SDK/cli.py` with `main(argv: list[str] | None = None) -> int` using `argparse`, with sub-parsers for `check`, `render`, `diff` and `context` (only `check` works in this task), `--help` and `--version` (the `styrmin-sdk` package version from `importlib.metadata`). *Done*: all four commands are implemented in this task; their tests are in the story phases. Catch `SystemExit` from `parse_args` and return its code (2 for usage errors). `check` writes one line per diagnostic and the summary line to standard output in the format of [contracts/cli.md](contracts/cli.md), and returns 1 when a diagnostic is an error, 2 when the directory does not exist or is not a directory, and 0 otherwise.
- [X] T036 [US1] Add `[project.scripts]` with `styrmin-driver = "styrmin_sdk.driver_format.cli:main"` to `python_sdk/pyproject.toml`; run `uv sync` and check that `uv run styrmin-driver --help` exits with 0. Add `styrmin_sdk.driver_format.cli` to the imports of `test_no_backend_imports.py` (T021).

**Checkpoint**: [quickstart.md](quickstart.md) scenarios 1, 2 and 5 (the `check` lines) pass.

---

## Phase 4: User Story 2 - View the rendered Helm values and the context a template can use (Priority: P2)

**Goal**: `render` writes only the Helm values; `context` prints the example context; a context file changes only the values it sets.

**Independent Test**: [quickstart.md](quickstart.md) scenario 3, and the E2E node `test_styrmin_driver_matches_helm_release`.

### Tests for User Story 2

- [X] T037 [P] [US2] Write `python_sdk/tests/driver_format/test_context_file.py` (research R-008): a file that sets one parameter changes only that parameter; a nested mapping merges; a list replaces; a mistyped top-level key and a mistyped nested key each give exit code 2 and the key path; a file that is not valid YAML, and a file whose top level is a list, give exit code 2; a JSON file in the shape of a `StyrminDeployment` `spec.context` is accepted; a context file that sets `app.helm.chart.values_template` gets a warning and does not change what is rendered.
- [X] T038 [P] [US2] Write `python_sdk/tests/driver_format/test_cli_render_context.py`: `render` on `generic-app` writes to standard output text that `yaml.safe_load` parses into the values and nothing else, with exit code 0; `render` with an undefined variable writes nothing to standard output, the error to standard error, and exits with 1 (FR-017); `context` on `simple-app` writes YAML that validates against `GlobalContext` (FR-005); `context` on `generic-app` writes the placeholder warning to standard error; `check --context` applies the file.

### Implementation for User Story 2

- [X] T039 [US2] Add `merge_context_file(example: GlobalContext, data: object, template_text: str) -> GlobalContext` to `SDK/example_context.py` (research R-008): require a mapping, merge recursively into `example.model_dump(mode="json", exclude_none=True)` (mappings merge, other values replace), set `app.helm.chart.values_template` to `template_text` with a warning when the file set another value, and validate with `GlobalContext.model_validate`. Raise an error that carries one `(key path, message)` per Pydantic error.
- [X] T040 [US2] Implement the `render` command in `SDK/cli.py`: run the checks that the render needs (driver model, template syntax, retired filters; not `actions.py`), build the example context, merge `--context` when given, render with `mode="check"`, and write `yaml.safe_dump(values, sort_keys=False)` to standard output. Diagnostics go to standard error. Exit codes per [contracts/cli.md](contracts/cli.md).
- [X] T041 [US2] Implement the `context` command in `SDK/cli.py`: build the example context, merge `--context` when given, and write `yaml.safe_dump(context.model_dump(mode="json", exclude_none=True), sort_keys=False)` to standard output; warnings go to standard error.
- [X] T042 [US2] Add `--context <file>` to `check` in `SDK/cli.py`: the render step of `run_checks` uses the merged context. A context file error gives exit code 2.
- [X] T043 [US2] Add `test_styrmin_driver_matches_helm_release` to `backend/tests/e2e/test_deploy_app.py` (research R-013), with `@pytest.mark.ci` and `@pytest.mark.api_only(reason="reads the StyrminDeployment and HelmRelease of the session deployment and runs styrmin-driver; no UI flow")`; the module's `shard_general` marker applies. It uses `deployed_simple_app` and `vcluster`, reads `spec.context` of the `StyrminDeployment` (as `backend/tests/e2e/test_deployment_env_vars.py:414-426`) and `spec.values` of the HelmRelease (as `backend/tests/e2e/test_task_steps.py:341-349`), writes the context to `tmp_path`, runs `styrmin-driver render driver/examples/simple-app --context <file>` as a subprocess and asserts that the parsed output equals `spec.values` (SC-004); runs `styrmin-driver context driver/examples/simple-app` and asserts that every key path of `spec.context` exists in it, leaving out paths under `cluster.config`, `environment.config`, `deployment.config` and `instance.config` if the session environment sets configuration (FR-006, R-013 "Not known"); and runs `docker run --rm <image> styrmin-driver check /styrmin/drivers/simple-app`, with the image name built from `STYRMIN_IMAGE_NAME` and `STYRMIN_IMAGE_VER` as `docker-compose.yml:13` does, and asserts exit code 0 (FR-014).
- [X] T044 [US2] Run the E2E node locally: `sleep infinity | uv run pytest "backend/tests/e2e/test_deploy_app.py::test_styrmin_driver_matches_helm_release" -v -s --pdb 2>&1 | tee "$TMPDIR/e2e.log"`. Record in `specs/032-styrmin-driver-cli/e2e-evidence.md` the node ID, the command, the ISO 8601 time of the passing run, the cluster identifier and kubeconfig path, and the `PASSED` line (constitution section V), and whether the session environment sets configuration (T043).

**Checkpoint**: [quickstart.md](quickstart.md) scenarios 3 and 6 pass; SC-004 is shown on a cluster.

---

## Phase 5: User Story 3 - Compare the rendered values with a saved file (Priority: P3)

**Goal**: `diff` shows the values that changed and exits with 1, or exits with 0 when nothing changed.

**Independent Test**: [quickstart.md](quickstart.md) scenario 4.

### Tests for User Story 3

- [X] T045 [P] [US3] Write `python_sdk/tests/driver_format/test_diff.py`: same values give exit code 0 and no output; reordered keys, other indentation and other quoting give 0; `"8080"` against `8080` gives 1 and a diff that shows both; a changed template value gives 1 and a unified diff with the headers `--- <base file>` and `+++ rendered <dir>`; a base file that does not exist, or is not valid YAML, gives exit code 2; a missing `--base` gives exit code 2.

### Implementation for User Story 3

- [X] T046 [US3] Write `SDK/diff.py` with `compare_values(base: object, rendered: object, base_label: str, rendered_label: str) -> list[str]`: write both with `yaml.safe_dump(sort_keys=True, default_flow_style=False)` and return the lines of `difflib.unified_diff` (empty when equal) (research R-009).
- [X] T047 [US3] Implement the `diff` command in `SDK/cli.py`: `--base` required, `--context` optional; render as `render` does; read the base file with `yaml.safe_load` (exit code 2 when it cannot be read or parsed); write the diff to standard output; return 1 when the diff is not empty, else 0.

**Checkpoint**: All three stories pass their quickstart scenarios.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T048 [P] Write `python_sdk/tests/driver_format/test_cli_exit_codes.py`: for each of `check`, `render`, `diff` and `context`, one case for exit code 0, one for 1 (where the command can return 1) and one for 2 (a missing directory, an unknown option, an unreadable context file); `--help` and `--version` exit with 0 (FR-012).
- [X] T049 [P] Update `docs/docs/drivers/creating-a-driver.md`, step 9 "Load and test" (line 653): before the load, run `uv run styrmin-driver check <dir>` and `uv run styrmin-driver render <dir>`, with a link to the reference page.
- [X] T050 [P] Write `docs/docs/reference/styrmin-driver.md` by hand, in the structure of `docs/docs/reference/styrminctl.md` (front matter `title`, `sidebar_position`, `description`): how to run it from a clone and from the image (with a volume mount for a driver outside `/styrmin/drivers`), one section per command with its options and output, the exit codes, the message format, the example context with its placeholders and the rule for fields without a value, and the context file merge. Content from [contracts/cli.md](contracts/cli.md) and research R-004, R-006 to R-009.
- [X] T051 [P] Add `reference/styrmin-driver` to the `Reference` category in `docs/sidebars.ts` (lines 53-62), after `reference/styrminctl`, and a row to the "Reference pages" table of `docs/docs/reference/index.md` (lines 19-24).
- [X] T052 [P] Add the entries **Driver CLI / styrmin-driver** and **Example context** to `CONTEXT.md`, in the wording of the brief, with two additions: a field of the context model without a value is not an undefined variable (FR-007), and the example context uses placeholders for parameters without a default and for a missing `default_version` (FR-002, research R-007). Add the brief's sentence to **SDK / styrmin-sdk**.
- [X] T053 [P] Add the command and its modules to `python_sdk/AGENTS.md` (`cli.py`, `diagnostics.py`, `example_context.py`, `diff.py`, the `[project.scripts]` entry).
- [X] T054 [P] Add `changelog/23.added.md` with `uv run towncrier create -c "Added styrmin-driver, a command installed with the SDK and present in the Styrmin image, that checks, renders and compares an application driver on the author's machine with no server, database or cluster." 23.added.md`.
- [X] T055 Build the documentation site: `cd docs && pnpm install && pnpm build`. *Correction*: `.github/workflows/ci.yml:144` builds the frontend; no CI job builds the docs, so this build runs locally only.
- [X] T056 Run [quickstart.md](quickstart.md) scenarios 1 to 7 and record each outcome, with the time of scenario 7 (SC-002), in `specs/032-styrmin-driver-cli/e2e-evidence.md`.
- [X] T057 Run `uv run invoke format lint`, `uv run invoke test`, `uv run pytest -v python_sdk/tests`, `uv run pytest -v cli/tests` and `uv lock --check`, and add the result of each command to `specs/032-styrmin-driver-cli/e2e-evidence.md`.
- [ ] T058 Before each pull request: compare a Trivy filesystem scan of the branch with one of `develop`, because the change adds dependencies to `python_sdk/pyproject.toml` and `backend/pyproject.toml` (research R-017), run the code review and the security review in agents other than the author, and add their sections to the pull request description, per the maintainer's pull request checklist. *Not done*: no commit, push or pull request was made; each needs the user's approval first.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: no dependency.
- **Phase 2 (Move)**: depends on T001 to T003. Blocks every story. Ships as pull request 1 after T026.
- **Phase 3 (US1)**: depends on Phase 2. The MVP.
- **Phase 4 (US2)**: depends on Phase 2, and on T033 (`build_example_context`), T034 (`run_checks`) and T035 (`cli.py`) of US1.
- **Phase 5 (US3)**: depends on T040 (`render`), because `diff` renders as `render` does.
- **Phase 6 (Polish)**: depends on the stories it documents; T048 depends on T047.

### Order inside Phase 2

```text
T005 → T006, T007
T008, T009 (parallel) → T010 → T011 → T014
T012 (parallel with T010)
T010 → T015 → T013, T016
T007, T011 → T018 → T017
T017, T018 → T019 → T020 → T026
T021, T022, T023, T024, T025 (parallel, after T018)
```

### Inside each story

Tests first and failing, then: `checks.py` and `rendering.py` → `example_context.py` → `diagnostics.py` → `cli.py`.

## Parallel Examples

### Phase 2

```text
T008 Move the five exception modules
T009 Move the four validators
T012 Move get_kubernetes_reference and the chart URL helpers
```

### User Story 1

```text
T027 test_check_examples.py
T028 test_check_errors.py
T029 test_rendering_check_mode.py
T030 test_example_context.py
```

### User Story 2

```text
T037 test_context_file.py
T038 test_cli_render_context.py
```

### Polish

```text
T049 creating-a-driver.md step 9
T050 reference page
T051 sidebar and index
T052 CONTEXT.md
T053 python_sdk/AGENTS.md
T054 changelog fragment
```

## Implementation Strategy

### Pull request 1 (Phases 1 and 2)

The move, with no user-visible change. Its evidence is the unchanged backend suite and the E2E tests that load and deploy drivers (T026).

### MVP (Phase 3)

`styrmin-driver check`. Stop and validate with quickstart scenarios 1 and 2: an author can check a driver before loading it.

### Incremental delivery (pull request 2)

1. US1: `check` (MVP).
2. US2: `render`, `context`, context files, and the E2E node (SC-004).
3. US3: `diff`.
4. Polish: documentation, glossary, changelog, the exit-code matrix, the quickstart run.
