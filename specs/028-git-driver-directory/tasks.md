---

description: "Tasks for 028: load an application driver from a driver directory of a git repository"
---

# Tasks: Load an Application Driver from a Driver Directory of a Git Repository

**Input**: Design documents from `specs/028-git-driver-directory/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/graphql-schema.md](contracts/graphql-schema.md), [contracts/sdk-cli-frontend.md](contracts/sdk-cli-frontend.md), [contracts/action-deployments.md](contracts/action-deployments.md), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution §V requires unit tests for new behaviour, a GraphQL propagation test for the new argument, and E2E coverage of the user-visible flow with local PASS evidence for each modified E2E test. The plan's "Coverage of acceptance scenarios" table maps each scenario to its test.

**Organization**: One phase per user story. All four stories are P1 and ship in one change (spec "User Scenarios & Testing"). Phase 2 holds the path rule, the stored value and the GraphQL argument, which every story depends on.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 to US4 (spec user stories)
- Paths are relative to the repository root

## Working rules (apply to every task)

- This worktree sits inside the emdash pnpm workspace: run `export npm_config_ignore_workspace=true` before `uv run invoke generate`, `uv run invoke lint` and `git commit`, and use `pnpm --ignore-workspace` for frontend commands.
- `uv run invoke lint` ends with a generated-types check that runs `git checkout --` on unstaged generated files: stage regenerated files before running it.
- The host Node cannot run the frontend's Vitest: run frontend tests in a `node:22-slim` container (or a portable Node 22 on PATH).
- GraphQL operations live in `.graphql` files only, one operation per file (AGENTS.md).

## E2E run rules (apply to every E2E task)

- Build the server image once before the first session: `docker compose build server`.
- One CI shard per pytest session (`-m "ci and shard_<name>"`), and `api-chromium` and `ui-chromium` in separate sessions.
- Run with `--pdb`. From a non-interactive shell, prefix the command with `sleep infinity |`, and stop the run by PID, not with `pkill -f`.
- Record each passing run in `specs/028-git-driver-directory/e2e-evidence.md`: pytest node IDs, the exact command, ISO 8601 start and end times, the vcluster name and kubeconfig path, and the verbatim `PASSED` lines (Constitution §V).

---

## Phase 1: Setup

**Purpose**: a green baseline before any change.

- [X] T001 Run `uv sync` and `cd frontend && pnpm --ignore-workspace install`, then run `uv run pytest backend/tests/unit/services/driver backend/tests/unit/workflows/test_git_source_commit_pinning.py backend/tests/unit/workflows/test_user_action_registration.py backend/tests/unit/services/reconciliation/test_remediation.py backend/tests/functional/graphql/test_application_driver_version_propagation.py python_sdk/tests/test_drivers.py cli/tests/test_drivers.py -q` and note the results as the baseline (no file change)

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the driver directory path rule (FR-006, FR-007), the value carried from the load to storage (FR-001, FR-002, FR-003, FR-005), and the GraphQL argument (research R-005, R-007, R-008).

- [X] T002 Create `backend/styrmin_backend/services/driver/driver_directory.py` with:
  - `normalise_driver_directory(value: str | None) -> str | None`, applying research R-005 in order: remove surrounding whitespace; refuse a backslash, a NUL character or a leading `/`; split on `/` and drop empty and `.` segments; refuse a `..` segment; return `None` when no segment is left, else the segments joined with `/`. Each refusal raises `DriverLoadingError` (from `services/driver/exceptions.py`) with the message `Driver directory '<given>' is refused: <rule>. Give a path relative to the repository root, such as 'drivers/infrahub'.`, where `<rule>` is one of `it is an absolute path`, `it contains a '..' segment`, `it contains a backslash`, `it contains a NUL character` ([contracts/graphql-schema.md](contracts/graphql-schema.md#errors)). Show the given value with `repr`-safe quoting so a NUL character prints as `\x00`.
  - `resolve_inside(root: Path, relative: str | Path) -> Path | None`: return `(root / relative).resolve()` when it is `root.resolve()` or below it, else `None`.
  - `redact_repository_url(url: str) -> str`: for a URL with `://`, return it without user info (`https://user:token@host/x.git` → `https://host/x.git`) using `urllib.parse.urlsplit`; return any other string unchanged.
  - Module and function docstrings with doctest examples, in the style of `services/driver/labels.py`.
- [X] T003 [P] Create `backend/tests/unit/services/driver/test_driver_directory.py`: a parametrised test over every accepted form in research R-005 (`drivers/infrahub`, `./drivers/infrahub/`, `drivers//./infrahub`, `" drivers/infrahub "` → `drivers/infrahub`; `None`, `""`, `"."`, `"./"`, `"  "` → `None`), a parametrised refusal test (`/etc`, `../x`, `a/../b`, `drivers\\infrahub`, `"a\x00b"`) that checks the `<rule>` part of the message, `resolve_inside` against a `tmp_path` tree with a folder, a symlink to a folder inside, a symlink to `/etc`, and a dangling symlink, and `redact_repository_url` for `https://user:token@github.com/o/r.git`, `https://github.com/o/r.git`, `git://git-server/x.git`, `/tmp/repo`, `git@github.com:o/r.git`
- [X] T004 In `backend/styrmin_backend/services/driver/models/structure/source.py` add `driver_directory: str | None = None` to `GitSource`, with an `Args:` docstring line: "The stored driver directory relative to the repository root; None for the repository root". Do not change `LocalSource`
- [X] T005 In `backend/styrmin_backend/services/driver/provider.py` change `GitDriverProvider.__init__(self, repository, branch, token, driver_directory: str | None = None)` to call `normalise_driver_directory` (so a refused value raises before any clone, FR-007) and pass the result to `GitSource(..., driver_directory=...)`. In `provide()`, after the commit SHA is resolved, compute the driver directory as `tempdir_path` when `driver_directory` is `None`, else `tempdir_path / driver_directory`, and yield it instead of `tempdir_path`. Keep `get_resolved_commit_sha()` unchanged. (The FR-008 and FR-009 checks come in T036.)
- [X] T006 Thread the driver directory to storage:
  - `backend/styrmin_backend/services/driver/loaders.py`: `get_git_driver_loader(repository, branch, token, driver_directory: str | None = None)` passes it to `GitDriverProvider`; update the docstring.
  - `backend/styrmin_backend/services/applications.py`: `load_application_driver_from_git_repository(repository_url, branch, uow, driver_directory: str | None = None)` passes it to `get_git_driver_loader`; in `load_application_driver_from_object`, the `GitSource` branch sets `source_path = driver_object.source.driver_directory` (was `None`), so the identity lookup, the IntegrityError re-fetch and the new row all use it. Update both docstrings.
- [X] T007 In `backend/styrmin_backend/api/schema/mutation.py` add `driver_directory: str | None = None` to `load_remote_application_driver_version` after `info` (a parameter with a default cannot come before `info`, which has none; Strawberry names the argument `driverDirectory`) and pass it to `load_application_driver_from_git_repository`. Run `uv run styrmin export graphql-schema schema.graphql` and check that `git diff schema.graphql` adds only `driverDirectory: String = null` to `loadRemoteApplicationDriverVersion`
- [X] T008 [P] In `backend/tests/unit/services/driver/test_loaders_git_commit_sha.py` let `_FakeGitProvider` take a `driver_directory` and put it on its `GitSource`, then add: a load with `driver_directory="drivers/a"` stores `source_path == "drivers/a"`; a second load with the same SHA and driver directory returns the same row id; a load with `driver_directory=None` at the same SHA creates a second row with `source_path is None`
- [X] T009 In `backend/tests/functional/graphql/test_application_driver_version_propagation.py` add a fixture that builds a local git repository in `tmp_path` with dulwich `porcelain` (`init`, `add`, `commit`, as in `backend/tests/unit/services/driver/test_provider_commit_sha.py`), holding the fixture driver `backend/tests/unit/services/driver/fixtures/local_driver_directory` both at the root and under `drivers/a/`. Add an operation file `backend/tests/functional/graphql/operations/load_remote_driver_directory.graphql` (`mutation LoadRemoteDriverDirectory($repositoryUrl: String!, $branch: String!, $driverDirectory: String) { loadRemoteApplicationDriverVersion(...) { id sourceType sourcePath sourceCommitSha } }`). Tests (FR-001, FR-005, Constitution §V): call it with the repository path, the branch and `driverDirectory: "./drivers/a/"`, read the row with `session.get` and assert `source_type == "git"` and `source_path == "drivers/a"`; query `applicationDriver { versions { sourcePath } }` and assert `"drivers/a"`. Use the existing `prefect_manager_mock` fixture

**Checkpoint**: a driver directory load stores `source_path`, and the GraphQL argument reaches the database.

---

## Phase 3: User Story 1 - Load, deploy and run a driver from a driver directory through the API, SDK or CLI (Priority: P1) 🎯

**Goal**: actions of a driver version loaded from a driver directory run from that directory, with only it on the import path (FR-004); two driver versions from one commit keep separate actions (FR-010); the SDK and the CLI take the driver directory (FR-001).

**Independent Test**: the `[api-chromium]` variant of `shard_general` (T052): every session loads `simple-app` from `drivers/simple-app` of `driver-collection`, deploys it and runs its setup actions; `test_driver_version_reselection` checks `sourcePath` and the pull steps.

### Action deployments

- [X] T010 [US1] In `backend/styrmin_backend/workflows/utils.py` change `set_directory_pull_step` to return `{"prefect.deployments.steps.set_working_directory": {"directory": f"{clone_directory_name}/{directory}"}}` (relative, no `/opt/prefect/`, research R-002), stripping a trailing `/` from `directory`; update the docstring to say the path resolves against the folder `git_clone` cloned into. In `backend/tests/unit/workflows/test_git_source_commit_pinning.py` update `test_set_directory_step_follows_the_clone_directory` to expect `lab-driver-a-555d155/backend` and `lab-driver-a-master/backend`
- [X] T011 [US1] In `backend/styrmin_backend/services/user.py` make `ActionsWorkflowBuilder.build_user_action_workflow_definition` set `set_directory=self.source.driver_directory` on the `GitSourceWorkflowDefinition`
- [X] T012 [P] [US1] In `backend/tests/unit/workflows/test_git_source_commit_pinning.py` add: the builder with `GitSource(..., driver_directory="drivers/infrahub")` sets `set_directory == "drivers/infrahub"`; its `to_deployment()` pull steps are exactly `git_clone` then `set_working_directory` with `directory == "lab-driver-a-555d155/drivers/infrahub"` ([contracts/action-deployments.md](contracts/action-deployments.md#pull-steps)); the builder without a driver directory keeps one `git_clone` step and `set_directory is None`
- [X] T013 [US1] In `backend/styrmin_backend/services/driver/driver_directory.py` add `driver_directory_digest(driver_directory: str) -> str` (first 7 hex characters of SHA-256 of the UTF-8 value, with a doctest). In `backend/styrmin_backend/workflows/manager.py`:
  - `register_user_action(..., driver_directory: str | None = None)`: when set, append the tag `directory/<driver_directory>` and set `deployment_name = f"{workflow.name} ({application}@{fingerprint} {driver_directory_digest(driver_directory)})"` (without a fingerprint: `f"{workflow.name} ({application} {digest})"`); unchanged otherwise.
  - `get_user_action_deployment_id(..., driver_directory: str | None = None)`: when set, add `directory/<driver_directory>` to `tags`; when `None`, drop every returned deployment that has a tag starting with `directory/` before taking the newest.
  - Update both docstrings (research R-003).
- [X] T014 [US1] In `backend/styrmin_backend/services/driver/labels.py` add `driver_directory_of(*, source_type: str, source_path: str | None) -> str | None` next to `short_fingerprint`: returns `source_path` when `source_type == "git"`, else `None` (a local row's `source_path` is a server path, not a driver directory)
- [X] T015 [US1] In `backend/styrmin_backend/services/applications.py`: pass `driver_directory=driver_object.source.driver_directory` to `prefect_manager.register_user_action`; in `instantiate_application`, pass `driver_directory=driver_directory_of(source_type=..., source_path=...)` of the same driver version row whose `content_hash` and `source_commit_sha` feed `instance_fingerprint` to both `get_user_action_deployment_id` calls
- [X] T016 [US1] In `backend/styrmin_backend/services/reconciliation/remediation.py` pass `driver_directory=driver_directory_of(source_type=driver_version.source_type, source_path=driver_version.source_path)` to all five `get_user_action_deployment_id` calls (create `pre`/`post`; upgrade `core`/`pre`/`post`)
- [X] T017 [P] [US1] In `backend/tests/unit/workflows/test_user_action_registration.py` add, following the existing tests' Prefect client mock: a registration with `driver_directory="drivers/a"` has the `directory/drivers/a` tag and a name ending in `@<fingerprint> <digest>)`; two registrations with the same driver name and fingerprint and directories `drivers/a` and `drivers/b` get distinct names (US1-6); a lookup with `driver_directory="drivers/a"` filters on the `directory/drivers/a` tag; a lookup without a driver directory skips a newer deployment tagged `directory/drivers/a` and returns the older untagged one, and returns `None` when only tagged deployments match
- [X] T018 [P] [US1] In `backend/tests/unit/services/reconciliation/test_remediation.py` add: for a git driver version with `source_path="drivers/a"`, every user-action lookup receives `driver_directory="drivers/a"`; for a git row with `source_path=None` and for a local row with a server path, it receives `None`
- [X] T019 [P] [US1] Create `backend/tests/unit/workflows/test_action_driver_directory.py` (US1-3, US1-4, research R-001): build `tmp_path/clone/drivers/a/{actions.py,helpers.py}` and `tmp_path/clone/shared.py`; `actions.py` defines a Prefect `@flow` that imports `helpers`, and a second file `actions_shared.py` whose flow module imports `shared` at import time. Start from `monkeypatch.chdir(tmp_path)`, run Prefect's `run_steps([set_directory_pull_step(directory="drivers/a", clone_directory_name="clone")])`, then `load_flow_from_entrypoint("actions.py:<flow>")` succeeds and `load_flow_from_entrypoint("actions_shared.py:<flow>")` raises (`ModuleNotFoundError`, possibly wrapped in Prefect's `ScriptError`). Remove the modules the test loaded from `sys.modules` in a fixture finaliser
- [X] T020 [US1] SDK: in `python_sdk/src/styrmin_sdk/graphql/load_version.graphql` add `$driverDirectory: String = null`, pass `driverDirectory: $driverDirectory`, and select `sourceRepository`, `sourceBranch` and `sourcePath`; in `python_sdk/src/styrmin_sdk/resources/drivers.py` add `driver_directory: str | None = None` to `load_version` and include `"driverDirectory"` in the variables only when it is not `None`. Run `uv run invoke validate-graphql` and `uv run invoke generate`, and stage `python_sdk/src/styrmin_sdk/graphql/_generated/` and `frontend/src/generated/`
- [X] T021 [P] [US1] In `python_sdk/tests/test_drivers.py` add: `load_version(url, "main", driver_directory="drivers/a")` sends `driverDirectory: "drivers/a"`; `load_version(url, "main")` sends no `driverDirectory` key; the parsed result exposes `source_path`
- [X] T022 [US1] CLI: in `cli/src/styrminctl/commands/drivers.py` add to `load_version` a keyword option `driver_directory: Annotated[str | None, Parameter(name="--driver-directory", help="Folder of the repository that holds driver.styrmin.yml, relative to the repository root. Default: the repository root.")] = None` and pass it to `sdk.drivers.load_version`; in `_print_version_details` print `  Driver directory: <path>` after the commit line when `getattr(version, "source_path", None)` is set and the version is git-sourced ([contracts/sdk-cli-frontend.md](contracts/sdk-cli-frontend.md#cli--styrminctl-drivers-load-version))
- [X] T023 [P] [US1] In `cli/tests/test_drivers.py` add: `drivers load-version <url> main --driver-directory drivers/a` calls `load_version(repository_url=..., branch="main", driver_directory="drivers/a")` and prints `Driver directory: drivers/a`; the existing `test_drivers_load_version` expects `driver_directory=None`; `drivers load-version --help` lists `--driver-directory`

### E2E

- [X] T024 [US1] In `backend/tests/e2e/conftest.py` (`git_server`): move the per-driver preparation (copy, chart location rewrite for drivers with `chart_name`, simple-app `spec.info`) into a helper `_prepare_driver(dest: Path, name: str, info: dict, chart_server: str) -> None`, use it for the existing per-driver repositories unchanged, and add a `driver-collection` repository whose `drivers/simple-app/` and `drivers/db-test/` are prepared with the same helper. Commit and push it with the others, and yield its URL as `git_urls["driver-collection"]`. Keep every existing repository, including `simple-app`, which `test_driver_version_reselection.py` and `helpers/drivers.py` push branches to
- [X] T025 [US1] Add `driver_directory: str | None = None` to `load_driver_version` in `backend/tests/e2e/drivers/protocol.py`, `backend/tests/e2e/drivers/api_driver.py` (pass it to `client.drivers.load_version`) and `backend/tests/e2e/drivers/ui_driver.py` (pass it to `DriversListPage.load_remote_version`); in `backend/tests/e2e/pages/drivers_list.py` add `driver_directory: str | None = None` to `load_remote_version` and fill `#driverDirectory` when it is set (the field is added in T029; the `[ui-chromium]` variant needs T029 first)
- [X] T026 [US1] In `backend/tests/e2e/conftest.py` (`styrmin_resources`): load with `driver.load_driver_version(git_url=git_server["driver-collection"], ref="master", driver_directory="drivers/simple-app")` and add `"driver_version_id": driver_version.id` to the yielded dict. Before the change, search `backend/tests/e2e/` for `source_repository`, `sourceRepository` and `git_server["simple-app"]` and check that no test assumes the session driver version comes from the `simple-app` repository (plan "Risks")
- [X] T027 [US1] In `backend/tests/e2e/test_driver_version_reselection.py` (`test_driver_version_reselection`), before publishing the next version: read the session driver's versions with `load_query("get_application_driver_versions")` through the client transport, as `test_driver_reload_identity.py` does, and assert that the version with id `styrmin_resources["driver_version_id"]` has `sourcePath == "drivers/simple-app"`; then, through the Prefect port-forward already used by `_assert_actions_pinned`, read the deployments tagged `fingerprint/<its sourceCommitSha[:7]>` and `directory/drivers/simple-app` and assert there is at least one, and that each has two pull steps, `git_clone` then `set_working_directory` with a `directory` ending in `/drivers/simple-app`

**Checkpoint**: US1 is testable through the API variant (T052).

---

## Phase 4: User Story 2 - Load from the drawer and view the driver directory on the Overview tab (Priority: P1)

**Goal**: the drawer takes the driver directory; the Overview tab and the drivers list show it (FR-001, FR-005).

**Independent Test**: frontend tests (T032 to T034) and the `[ui-chromium]` variant of `shard_general` (T053), whose session fixture loads through the drawer.

- [X] T028 [US2] In `frontend/src/graphql/load_remote_driver.graphql` add `$driverDirectory: String = null` and pass `driverDirectory: $driverDirectory`; run `npm_config_ignore_workspace=true uv run invoke generate` and stage `frontend/src/generated/graphql.ts`
- [X] T029 [US2] In `frontend/src/pages/drivers/LoadDriverDrawer.tsx`: add `driverDirectory: z.string()` to `remoteSchema` (empty allowed) and `driverDirectory: ""` to the remote form's `defaultValues`; add a third Git-tab field after Branch with `Label htmlFor="driverDirectory"` "Driver directory", `Input id="driverDirectory"`, placeholder `drivers/my-driver`, the same `font-mono text-xs` class, and the help text "Folder that holds driver.styrmin.yml, relative to the repository root. Leave empty for the root."; in `onSubmit`, send `{ repositoryUrl, branch, ...(trimmed ? { driverDirectory: trimmed } : {}) }`. Keep the existing error alert and the entered values on failure ([contracts/sdk-cli-frontend.md](contracts/sdk-cli-frontend.md#frontend--load-a-driver-drawer))
- [X] T030 [US2] In `frontend/src/pages/drivers/DriverDetailPage.tsx` (`OverviewPanel`): for a git version with `version.sourcePath`, insert after the Source row a row `{ label: "Driver directory", value: mono(version.sourcePath), copy: version.sourcePath }` rendered with `data-testid="driver-overview-driver-directory"` on its `<tr>` (extend the `rows` item type with an optional `testId`). No new row for local versions or git versions without `sourcePath`
- [X] T031 [US2] In `frontend/src/pages/drivers/lib/driverList.ts` change `versionSource` so a git version with `sourcePath` returns `` `${repo} @ ${branch} · ${sourcePath}` `` (or `` `${repo} · ${sourcePath}` `` without a branch); local versions and git versions without `sourcePath` are unchanged. Check that the drivers list query selects `sourcePath` for versions (it does for local versions today)
- [X] T032 [P] [US2] In `frontend/src/__tests__/drivers/LoadDriverDrawer.test.tsx` add: filling `drivers/a` sends `driverDirectory: "drivers/a"`; leaving it empty (or spaces only) sends no `driverDirectory`; a rejected mutation shows the error message and keeps the three values
- [X] T033 [P] [US2] In `frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx` add: a git version with `sourcePath: "drivers/a"` shows the `driver-overview-driver-directory` row with `drivers/a`; a git version with `sourcePath: null` and a local version show no such row
- [X] T034 [P] [US2] In `frontend/src/__tests__/drivers/driverList.test.ts` add `versionSource` cases for a git version with `sourcePath` (with and without a branch); keep the existing local and git cases unchanged (US2-6)
- [X] T035 [US2] In `backend/tests/e2e/test_ui_smoke.py` (`test_driver_detail_inspects_versions_via_tabs`): open `/drivers/{driver_id}?version={styrmin_resources["driver_version_id"]}` instead of `/drivers/{driver_id}`, and after the Overview check assert `expect(page.locator("[data-testid=driver-overview-driver-directory]")).to_contain_text("drivers/simple-app")`

**Checkpoint**: US2 is testable through the frontend tests and the UI variant (T053).

---

## Phase 5: User Story 3 - Refuse unsafe driver directories and explain failed loads (Priority: P1)

**Goal**: no file outside the clone is read (FR-008); failed loads name the driver directory, repository, branch and commit (FR-009); messages carry no user info (critique E3).

**Independent Test**: `uv run pytest backend/tests/unit/services/driver/test_provider.py backend/tests/unit/services/driver/test_driver_directory.py -v` and the refusal case of the propagation test.

- [X] T036 [US3] In `backend/styrmin_backend/services/driver/provider.py` (`GitDriverProvider.provide()`), after the commit SHA and before yielding, in this order:
  1. `resolve_inside(tempdir_path, driver_directory or ".")`; `None` → `DriverLoadingError` "Driver directory '<dir>' of repository '<url>' (branch '<branch>', commit <sha>) leads outside the repository: '<dir>' is a symlink to a path outside it."
  2. Not a folder or missing → `DriverLoadingError` "Driver directory '<dir>' does not exist in repository '<url>' (branch '<branch>', commit <sha>)."
  3. For each of `config.SETTINGS.driver.spec_file`, `.values_template` and `.actions_code_file`: `resolve_inside(tempdir_path, <driver dir relative>/<file>)`; `None` → the "leads outside the repository" message naming that file's path relative to the clone. This runs for root loads too (FR-008).
  4. `driver.styrmin.yml` not a file → `MissingDriverSpecificationError` "No driver.styrmin.yml in driver directory '<dir>' of repository '<url>' (branch '<branch>', commit <sha>)." (root: "No driver.styrmin.yml at the root of repository '<url>' (branch '<branch>', commit <sha>).")
  5. Yield the resolved driver directory.

  Use the exact shapes in [contracts/graphql-schema.md](contracts/graphql-schema.md#errors): `<dir>` reads `the repository root` for a root load, `<url>` is `redact_repository_url(repository)`, `<sha>` is the full SHA; never include the temporary path or a symlink target. Also pass the clone error's repository through `redact_repository_url` and add `driver directory '<dir>'` to it when one is set. After a successful check, `logger.info` (loguru, as in `services/applications.py`) the redacted repository, branch, commit and driver directory
- [X] T037 [P] [US3] In `backend/tests/unit/services/driver/test_provider.py` add tests against a local dulwich repository in `tmp_path` (fixture pattern from `test_provider_commit_sha.py`), each asserting the message parts listed in T036: driver directory `drivers/evil` symlinked to `/etc` is refused and no file is read; a root `driver.styrmin.yml` symlinked to a file outside the repository is refused on a root load; `drivers/a/values.j2.yml` symlinked outside is refused; `drivers/inner` symlinked to `../drivers/a` inside the repository is accepted; `drivers/missing` and a driver directory that is a file give the "does not exist" message with the full commit SHA; a folder without `driver.styrmin.yml` gives `MissingDriverSpecificationError`; a refused value (`../x`) raises before `porcelain.clone` is called (monkeypatch it to fail the test); a clone failure of `https://user:token@invalid.example/x.git` gives a message without `token`
- [X] T038 [P] [US3] In `backend/tests/functional/graphql/test_application_driver_version_propagation.py` add: `driverDirectory: "../x"` returns a GraphQL error with `extensions.code == "VALIDATION_ERROR"` and no `ApplicationDriverVersion` row is stored; `driverDirectory: "drivers/missing"` returns an error whose message names `drivers/missing` and the commit SHA

**Checkpoint**: US3 refusals and messages are covered.

---

## Phase 6: User Story 4 - Loads from the repository root keep working (Priority: P1)

**Goal**: root loads keep their stored values, deployment names, tags and pull steps (FR-002, SC-002).

**Independent Test**: the tests below plus the unchanged root-loading E2E fixtures (`semaphore`, `generic-app`, `infrahub`, the test drivers) in CI.

- [ ] T039 [P] [US4] In `backend/tests/functional/graphql/test_application_driver_version_propagation.py` add: a root load of the T009 repository without `driverDirectory` stores `source_path IS NULL`; reloads at the same commit with no argument, `driverDirectory: ""` and `driverDirectory: "."` return the same `id` (US4-1, US4-2)
- [ ] T040 [P] [US4] In `backend/tests/unit/workflows/test_user_action_registration.py` add: a registration without a driver directory keeps the name `User Action: <action> (<driver>@<fingerprint>)` and the five existing tags, with no `directory/` tag (US4-3)

**Checkpoint**: root loads verified unchanged.

---

## Phase 7: Documentation (Constitution §VII)

- [ ] T041 [P] In `docs/docs/drivers/loading-drivers.md`, section "From a git repository": replace "The repository must contain a `driver.styrmin.yml` at its root" with the driver directory rule; show `styrminctl drivers load-version <url> main --driver-directory drivers/infrahub`, the SDK call `client.drivers.load_version(url, "main", driver_directory="drivers/infrahub")` and the drawer's "Driver directory" field; say that actions run from the driver directory and import only modules inside it; say that a reload after any commit to the repository creates a new driver version, even when the driver directory did not change; list the refused values; replace `loadApplicationDriverVersionFromGithub` with `loadRemoteApplicationDriverVersion` and name the `driverDirectory` argument
- [ ] T042 [P] In `docs/docs/drivers/creating-a-driver.md`, "The shape of a driver": add that a driver can sit in a folder of a repository that holds other drivers, that its actions run from that folder and import only modules inside it, and that code several drivers share goes into each driver directory or into the action's image; link to `loading-drivers.md`
- [ ] T043 [P] In `docs/docs/reference/styrminctl.md` add a section "`drivers load-version` — load a driver version from git" before "Related": the two arguments, `--driver-directory`, the `Driver directory:` output line, the refused values, and that errors name the driver directory, repository, branch and commit
- [ ] T044 [P] In `driver/DRIVERS.md`, "Driver Loading": step 1 clones the repository and step 2 reads the files from the driver directory (the repository root when none is given); add the import rule for `actions.py`
- [ ] T045 [P] In `dev/knowledge/backend/api.md`, mutation table row of `loadRemoteApplicationDriverVersion`: arguments `repositoryUrl, branch, driverDirectory`; note that `sourcePath` holds the driver directory for git driver versions loaded from one
- [ ] T046 [P] In `dev/knowledge/backend/hooks-and-actions.md`, "Registration Pipeline" and "Lookup": the `set_working_directory` pull step for driver directory versions, the `directory/<path>` tag, the deployment name digest, and the lookup rule that drops `directory/` deployments for root driver versions; replace the root-only "Driver Repository" tree caption with "Driver directory"
- [ ] T047 Check `CONTEXT.md`: the **Driver directory** entry and the edits to **Application driver version**, **Driver specification file** and **Provenance fingerprint** (committed with the spec) match the implementation; fix any drift
- [ ] T048 Scan every local and remote branch for used ADR numbers (`for b in $(git for-each-ref --format='%(refname)' refs/heads refs/remotes); do git ls-tree -r --name-only "$b" dev/adr/; done | sort -u`), take the next free number (`0076` was free on 2026-10-17), and write `dev/adr/<NNNN>-driver-actions-import-only-from-their-driver-directory.md` (MADR, in the style of `dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md`): decision 1, actions run from their driver directory and import only from it (FR-004); decision 2, a git load refuses a driver directory or driver file whose real path leaves the clone, also for root loads (FR-008); rejected alternatives from research R-001 and R-004; consequences for driver authors. Link it from `docs/docs/drivers/loading-drivers.md` if that page links ADRs elsewhere, and from the spec's Documentation section
- [ ] T049 Run `uv run towncrier create -c "Admins can load an application driver from a driver directory of a git repository: \`styrminctl drivers load-version --driver-directory\`, the SDK's \`driver_directory\`, the \`driverDirectory\` argument of \`loadRemoteApplicationDriverVersion\` and the \"Load a driver\" drawer. The driver version's Overview tab and the drivers list show the driver directory, and actions run from it." 517.added.md` and check the fragment against `dev/guidelines/changelog.md`

---

## Phase 8: Polish and Verification

- [ ] T050 Stage all changes, then run `uv run invoke format lint` and `uv run invoke validate-graphql`; fix every finding
- [ ] T051 Run `uv run pytest backend/tests/unit backend/tests/functional python_sdk/tests cli/tests -q` and, in a Node 22 container, `cd frontend && pnpm --ignore-workspace exec vitest run && pnpm --ignore-workspace lint && pnpm --ignore-workspace exec tsc -b --noEmit`; record the totals from the logs, not from memory
- [ ] T052 E2E `[api-chromium]`: `docker compose build server`, then `sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_general" -k api-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-028-api.log`. Expect `styrmin_resources` to load from `drivers/simple-app` and every test to pass, including `test_driver_version_reselection`. Record the evidence in `specs/028-git-driver-directory/e2e-evidence.md`
- [ ] T053 E2E `[ui-chromium]`: in a new session, `sleep infinity | uv run pytest backend/tests/e2e -m "ci and shard_general" -k ui-chromium -v -s --pdb 2>&1 | tee /tmp/e2e-028-ui.log`. Expect the session fixture to load through the drawer's "Driver directory" field and `test_driver_detail_inspects_versions_via_tabs` and `test_driver_version_reselection` to pass. Record the evidence in `specs/028-git-driver-directory/e2e-evidence.md`
- [ ] T054 Run the quickstart sections 1 to 4 ([quickstart.md](quickstart.md)) once more on the final tree and tick the spec checklist; note in `e2e-evidence.md` that CI runs the other shards, which all now load the session driver from a driver directory

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 → Phase 2 → Phases 3 to 6 → Phase 7 → Phase 8.
- Phase 7 can start once the behaviour it documents is merged into the branch (T041 to T046 after T022, T029 to T031 and T036).

### User Story Dependencies

- US1 (Phase 3) depends on Phase 2.
- US2 (Phase 4) depends on Phase 2. T025's drawer fill needs T029; the UI variant run (T053) needs US1's T024 to T026 and US2's T029 and T035.
- US3 (Phase 5) depends on T005; T038 depends on T009.
- US4 (Phase 6) depends on T009 (T039) and T013 (T040).

### Within Each Story

- T010 → T011 → T012; T013 → T014 → T015, T016 → T017, T018.
- T020 → T021; T022 → T023; T024 → T026 → T027; T025 before T026's UI variant run.
- T028 → T029, T030, T031 → T032, T033, T034.

### Parallel Opportunities

- Phase 2: T003 with T004; T008 after T006.
- Phase 3: T012, T017, T018, T019, T021, T023 are separate test files.
- Phase 4: T032, T033, T034 in parallel; T030 and T031 touch different files.
- Phase 5 and Phase 6 tests (T037 to T040) in parallel.
- Phase 7: T041 to T046 in parallel.

---

## Parallel Example: User Story 1 tests

```text
After T016 and T022:
  T012 backend/tests/unit/workflows/test_git_source_commit_pinning.py
  T017 backend/tests/unit/workflows/test_user_action_registration.py
  T018 backend/tests/unit/services/reconciliation/test_remediation.py
  T019 backend/tests/unit/workflows/test_action_driver_directory.py
  T021 python_sdk/tests/test_drivers.py
  T023 cli/tests/test_drivers.py
```

---

## Implementation Strategy

1. Phases 1 and 2: the path rule, the stored value and the GraphQL argument, with the propagation test green.
2. Phase 3 (US1): action deployments, SDK, CLI and the E2E fixture; run the unit tests, then T052 as soon as the API variant can run.
3. Phases 4 to 6: the drawer and the Overview and list display, the symlink checks and messages, and the root regression tests.
4. Phase 7: documentation, the ADR and the changelog fragment in the same change (Constitution §VII).
5. Phase 8: lint, the full unit and frontend suites, and both E2E variants with recorded evidence. The feature is not done until T052 and T053 have recorded `PASSED` lines.
