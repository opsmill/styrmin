# Implementation Plan: Load an Application Driver from a Driver Directory of a Git Repository

**Branch**: `fac/check-driver-from-git-repo-works-0d15v` | **Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/028-git-driver-directory/spec.md`

## Summary

An admin who loads a driver version from git can give the driver directory, a path relative to the repository root, on the GraphQL mutation, the SDK, `styrminctl` and the "Load a driver" drawer. Styrmin normalises and checks the value before the clone, clones the whole repository as today, checks that the driver directory and the three driver files have real paths inside the clone, and reads the driver from the driver directory. The driver version stores the driver directory in the existing `source_path` column, and the Overview tab shows it. Each action's Prefect deployment adds Prefect's built-in `set_working_directory` step after `git_clone`, so the action runs from the driver directory and only that folder is on its import path. Deployments of driver versions loaded from a driver directory get a `directory/<path>` tag and a digest in their name, so two driver versions from one commit keep separate actions. Loads from the repository root keep their stored values, deployment names, tags and pull steps.

## Technical Context

**Language/Version**: Python 3.14+ (backend, SDK, CLI); TypeScript 5.9.3 with React 19 (frontend, Node 22)

**Primary Dependencies**: Strawberry GraphQL, SQLModel and SQLAlchemy (async), Pydantic v2, dulwich 1.1.0 (driver clone), Prefect 3.8.6 (action deployments, `set_working_directory` pull step), Cyclopts (CLI), httpx (SDK); TanStack Form and TanStack Query (frontend). No new dependency.

**Storage**: PostgreSQL. No schema change: `applicationdriverversion.source_path` exists and is part of the unique identity index ([data-model.md](data-model.md)).

**Testing**: pytest (unit, functional GraphQL propagation, E2E on a disposable vCluster with `[api-chromium]` and `[ui-chromium]` variants); Vitest and React Testing Library (frontend).

**Target Platform**: Styrmin server (Linux container), Prefect action Jobs on the agent's cluster, browser UI.

**Project Type**: Web service with a React frontend, a Python SDK and a CLI.

**Performance Goals**: No change. A load still clones the repository once.

**Constraints**:

- No file outside the clone is read during a git load (FR-008).
- Existing driver versions, Prefect deployments and deployments keep working without migration (SC-002).
- Prefect deployment names cannot contain `/` (research R-003).

**Scale/Scope**: Seven backend modules, the GraphQL schema (one optional argument), the SDK and CLI (one optional parameter each), two frontend components, the E2E fixtures and documentation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How the plan meets it |
| --- | --- | --- |
| I. Declarative state reconciliation | Pass | No change to reconciliation. The remediation service passes the driver directory to the action lookup, so it resolves the same deployment for the same driver version on every run. |
| II. Driver-based deployment | Pass | A driver stays self-contained: its actions import only from its own driver directory (FR-004). The driver directory is part of the driver version's identity. |
| III. Layered architecture | Pass | The resolver passes the argument to `load_application_driver_from_git_repository`; the path rule and the checks live in the driver service; storage goes through `uow.application_driver_versions`. |
| IV. Type safety and typed errors | Pass | Refusals and failed loads raise the existing `DriverLoadingError` and `MissingDriverSpecificationError` (`VALIDATION_ERROR`). No union error types. Type hints on every new function. |
| V. Test-first development | Pass | Unit tests for the path rule, provider, storage, pull steps, registration and lookup; a Prefect-run unit test for the import path; a GraphQL propagation test for `driverDirectory` and `sourcePath`; E2E coverage by moving the root session fixture's load to a driver directory, with two assertions added to existing tests (research R-009). No new heavy test node. |
| VI. Format and lint before commit | Pass | `uv run invoke format lint` and the frontend lint run before each commit. |
| VII. Documentation accuracy | Pass | `loading-drivers.md`, `driver/DRIVERS.md`, `dev/knowledge/backend/api.md`, `dev/knowledge/backend/hooks-and-actions.md`, `CONTEXT.md` (already drafted), a new ADR and a towncrier fragment ship in the same change (see "Documentation" below). |

**Governance gates** ([`dev/constitution.md`](../../dev/constitution.md#governance-gates)):

- Database schema or migration change: not crossed.
- GraphQL schema modification: crossed. One optional argument on `loadRemoteApplicationDriverVersion`; `sourcePath` now has a value for git driver versions loaded from a driver directory. The PRD ([#517 comment](https://github.com/opsmill/styrmin/issues/517#issuecomment-6236268970)) records this gate as discussed.
- New dependency: not crossed.
- CI/CD workflow change: not crossed.
- Authentication or authorization change: not crossed; the mutation keeps the `ADMIN` role.

**Post-design re-check**: Pass. Phase 1 adds no layer, no dependency and no schema column. The change to `set_directory_pull_step` (research R-002) affects only git-sourced workflows, and none sets `set_directory` today.

## Project Structure

### Documentation (this feature)

```text
specs/028-git-driver-directory/
├── spec.md
├── plan.md                 # this file
├── research.md             # Phase 0
├── data-model.md           # Phase 1
├── quickstart.md           # Phase 1
├── contracts/
│   ├── graphql-schema.md
│   ├── sdk-cli-frontend.md
│   └── action-deployments.md
├── checklists/requirements.md
└── tasks.md                # Phase 2 (speckit-tasks)
```

### Source code (files this feature changes)

```text
backend/styrmin_backend/
├── services/driver/
│   ├── driver_directory.py               # new: normalise_driver_directory(), resolve_inside()
│   ├── models/structure/source.py        # GitSource.driver_directory
│   ├── provider.py                       # GitDriverProvider: normalise before clone, check and yield driver directory
│   └── loaders.py                        # get_git_driver_loader(driver_directory=)
├── services/applications.py              # load_application_driver_from_git_repository(driver_directory=); source_path for git rows; lookup arg
├── services/user.py                      # ActionsWorkflowBuilder: set_directory from GitSource.driver_directory
├── services/reconciliation/remediation.py # pass driver directory to action lookups
├── workflows/utils.py                    # set_directory_pull_step: relative path
├── workflows/manager.py                  # register_user_action / get_user_action_deployment_id: driver_directory
└── api/schema/mutation.py                # driverDirectory argument
schema.graphql                            # regenerated

python_sdk/src/styrmin_sdk/
├── graphql/load_version.graphql          # $driverDirectory, source fields
├── graphql/_generated/                   # regenerated
└── resources/drivers.py                  # load_version(driver_directory=)

cli/src/styrminctl/commands/drivers.py    # --driver-directory, "Driver directory:" line

frontend/src/
├── graphql/load_remote_driver.graphql    # $driverDirectory
├── generated/graphql.ts                  # regenerated
├── pages/drivers/LoadDriverDrawer.tsx    # Driver directory field
├── pages/drivers/DriverDetailPage.tsx    # Overview "Driver directory" row
└── pages/drivers/lib/driverList.ts       # Source cell shows the driver directory

backend/tests/
├── unit/services/driver/test_driver_directory.py           # new
├── unit/services/driver/test_provider.py                   # git provider cases (local repository)
├── unit/services/driver/test_loaders_git_commit_sha.py     # storage of source_path, identity
├── unit/workflows/test_git_source_commit_pinning.py        # pull steps
├── unit/workflows/test_action_driver_directory.py          # new: Prefect run_steps + import
├── unit/workflows/test_user_action_registration.py         # names, tags, lookup
├── unit/services/reconciliation/test_remediation.py        # lookup receives the driver directory
├── functional/graphql/test_application_driver_version_propagation.py  # driverDirectory → source_path → sourcePath
└── e2e/
    ├── conftest.py                       # driver-collection repository; styrmin_resources loads from it
    ├── drivers/{protocol,api_driver,ui_driver}.py  # load_driver_version(driver_directory=)
    ├── pages/drivers_list.py             # fill #driverDirectory
    ├── test_driver_version_reselection.py # sourcePath and pull-step assertions
    └── test_ui_smoke.py                  # Overview row assertion

python_sdk/tests/test_drivers.py, cli/tests/test_drivers.py
frontend/src/__tests__/drivers/LoadDriverDrawer.test.tsx, frontend/src/__tests__/drivers/driverList.test.ts,
frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx

docs/docs/drivers/loading-drivers.md, docs/docs/drivers/creating-a-driver.md,
docs/docs/reference/styrminctl.md, driver/DRIVERS.md,
dev/knowledge/backend/api.md, dev/knowledge/backend/hooks-and-actions.md,
dev/adr/00NN-driver-actions-import-only-from-their-driver-directory.md,
CONTEXT.md, changelog/517.added.md
```

**Structure decision**: The existing web-service layout (backend, SDK, CLI, frontend). The path rule is a new module in the driver service, next to the provider that uses it, because both the provider (before and after the clone) and its tests need it without the loader.

## Design

### 1. Driver directory path rule (new, `services/driver/driver_directory.py`)

- `normalise_driver_directory(value: str | None) -> str | None` applies [research R-005](research.md#r-005-one-stored-form-of-a-driver-directory-and-the-values-refused-before-the-clone) and raises `DriverLoadingError` with the messages in [contracts/graphql-schema.md](contracts/graphql-schema.md#errors).
- `resolve_inside(root: Path, relative: Path) -> Path` returns `(root / relative).resolve()` and raises when the result is not `root.resolve()` or below it. The caller adds the repository, branch, commit and driver directory to the message.

### 2. Git driver provider (`provider.py`, extends)

- `GitDriverProvider.__init__(repository, branch, token, driver_directory=None)` normalises the value (refusal before any clone, FR-007) and stores it on `GitSource.driver_directory`.
- `provide()`, after the clone and the commit SHA:
  1. Resolve the driver directory (the clone root when `None`) with `resolve_inside`.
  2. Fail with the FR-009 message when it is not a folder.
  3. Resolve `driver.styrmin.yml`, `values.j2.yml` and `actions.py` (names from `config.SETTINGS.driver`) with `resolve_inside`, for root loads too (FR-008).
  4. Fail with the FR-009 message when `driver.styrmin.yml` is not a file.
  5. Yield the resolved driver directory.
- Clone errors keep their current message and add the driver directory when one is set.
- Every driver loading message shows the repository URL without user info (`https://user:token@host/x.git` becomes `https://host/x.git`), the clone error included (critique E3).
- A successful git load logs the repository (without user info), branch, commit and driver directory at info level (critique E8).

### 3. Loader and storage (`loaders.py`, `applications.py`, extend)

- `get_git_driver_loader(repository, branch, token, driver_directory=None)` passes the value to the provider.
- `load_application_driver_from_git_repository(repository_url, branch, uow, driver_directory=None)` passes it to the loader.
- `load_application_driver_from_object`: for a `GitSource`, `source_path = source.driver_directory`. The identity lookup and the row use it. A root load passes `None`, the value every existing git row has.

### 4. Action deployments (`user.py`, `workflows/utils.py`, `workflows/manager.py`, extend)

- `ActionsWorkflowBuilder` sets `set_directory=source.driver_directory` on each `GitSourceWorkflowDefinition`.
- `set_directory_pull_step` writes `<clone_directory_name>/<directory>` (relative, research R-002).
- `register_user_action(..., driver_directory=None)` and `get_user_action_deployment_id(..., driver_directory=None)` follow [contracts/action-deployments.md](contracts/action-deployments.md).
- A small helper, `driver_directory_of(row) -> str | None` (in `services/driver/labels.py`, next to `short_fingerprint`), returns `row.source_path` for git rows and `None` otherwise. `instantiate_application` and the two remediation paths call it.

### 5. GraphQL (`api/schema/mutation.py`, extends)

`load_remote_application_driver_version(self, repository_url: str, branch: str, info, driver_directory: str | None = None)`. Regenerate `schema.graphql`.

### 6. SDK and CLI (extend)

As in [contracts/sdk-cli-frontend.md](contracts/sdk-cli-frontend.md). Regenerate the SDK types with `uv run invoke generate` (`npm_config_ignore_workspace=true` in this worktree).

### 7. Frontend (extends)

- Drawer: a third Git-tab field `driverDirectory`, optional; trimmed value sent only when not empty.
- Overview tab: a "Driver directory" row with `data-testid="driver-overview-driver-directory"` for git versions with `sourcePath`.
- Drivers list: `versionSource` (`frontend/src/pages/drivers/lib/driverList.ts`) appends the driver directory for git versions with `sourcePath`, so the Source cell and its search show it (critique P2).
- Regenerate `frontend/src/generated/graphql.ts`.

### 8. E2E (extends; research R-009)

- `git_server` adds the `driver-collection` repository (`drivers/simple-app/`, `drivers/db-test/`), with the same per-driver preparation as the other repositories. The preparation moves into a helper so the per-driver repositories and the collection share it.
- `load_driver_version(..., driver_directory=None)` on the protocol, API driver and UI driver; `DriversListPage.load_remote_version(..., driver_directory=None)`.
- `styrmin_resources` loads from `git_server["driver-collection"]` with `driver_directory="drivers/simple-app"` and yields `driver_version_id`.
- `test_driver_version_reselection` asserts `sourcePath == "drivers/simple-app"` for `driver_version_id` (through `get_application_driver_versions`) and that the action deployments tagged with that version's commit and `directory/drivers/simple-app` have `git_clone` then `set_working_directory`.
- `test_driver_detail_inspects_versions_via_tabs` opens `?version=<driver_version_id>` and asserts the Overview row.

### 9. ADR

A new ADR (next free number on every branch at writing time; `0076` is free on 2026-10-17): "Driver actions import only from their driver directory, and a git load refuses paths that leave the clone". It records FR-004 and FR-008, the rejected alternatives in research R-001 and R-004, and the consequence for driver authors (shared code goes in each driver directory or in the action image).

## Documentation

| Page | Change |
| --- | --- |
| [`docs/docs/drivers/loading-drivers.md`](../../docs/docs/drivers/loading-drivers.md) | "From a git repository": the driver directory on the CLI, the SDK, the GraphQL mutation and the drawer; the files it must hold; actions run from it and import only from it; a reload after any commit to the repository creates a new driver version; the refused values; the mutation name `loadRemoteApplicationDriverVersion` (the page says `loadApplicationDriverVersionFromGithub`). |
| [`docs/docs/reference/styrminctl.md`](../../docs/docs/reference/styrminctl.md) | New section `drivers load-version`: the two arguments, `--driver-directory`, the `Driver directory:` output line, the refused values and the errors (critique E9). |
| [`docs/docs/drivers/creating-a-driver.md`](../../docs/docs/drivers/creating-a-driver.md) | "The shape of a driver": a driver can sit in a folder of a repository that holds other drivers; its actions run from that folder and import only modules inside it (critique E9). |
| [`driver/DRIVERS.md`](../../driver/DRIVERS.md) | "Driver Loading": the driver directory, and the import rule for `actions.py`. |
| [`dev/knowledge/backend/api.md`](../../dev/knowledge/backend/api.md) | Mutation table: the `driverDirectory` argument; `sourcePath` for git driver versions. |
| [`dev/knowledge/backend/hooks-and-actions.md`](../../dev/knowledge/backend/hooks-and-actions.md) | Registration pipeline: `set_working_directory`, the `directory/` tag, the deployment name, the lookup rule. |
| [`CONTEXT.md`](../../CONTEXT.md) | **Driver directory** entry and the edits to **Application driver version**, **Driver specification file** and **Provenance fingerprint** (committed with the spec). |
| `dev/adr/00NN-…md` | New ADR (Design §9). |
| `changelog/517.added.md` | Towncrier fragment: admins can load a driver from a driver directory of a git repository. |

## Risks

| Risk | Mitigation |
| --- | --- |
| The `styrmin_resources` change reaches every E2E shard; a test that assumes the session driver comes from the `simple-app` repository root fails. | `git_server` keeps the `simple-app` repository; tests that push branches use it unchanged. Search for `git_server["simple-app"]` and `source_repository` in `backend/tests/e2e/` before the change, and run `shard_general` in both variants locally. CI runs all shards. |
| A root lookup drops a deployment it should keep. | Only deployments with a `directory/` tag are dropped, and only this change adds that tag. Unit test covers both lookups. |
| The server is rolled back after driver versions were loaded from a driver directory. The older lookup does not drop `directory/` deployments, so a root driver version with the same driver name, `version` and commit could pick one (critique E2). | Accepted: it needs a root driver and a driver directory with the same name and `version` at one commit. Those deployments keep their `set_working_directory` step, so actions still run from their own folder. |
| The relative `set_working_directory` path resolves against a different folder in the Prefect runner path than in the engine path. | Both paths resolve it against the working directory after `git_clone`, which does not change it (research R-001). The E2E session runs setup actions of the driver directory version in a real Job. |

## Coverage of acceptance scenarios

| Scenario | Test |
| --- | --- |
| US1-1, US1-2 | E2E: `styrmin_resources` (both variants), `test_driver_version_reselection`; CLI: `cli/tests/test_drivers.py` |
| US1-3, US1-4 (imports) | Unit: `test_action_driver_directory.py` (Prefect `run_steps` and `load_flow_from_entrypoint`) |
| US1-5 (reload in another form) | Unit: `test_loaders_git_commit_sha.py`; propagation test |
| US1-6 (two same-name drivers at one commit) | Unit: `test_user_action_registration.py` (names, tags, lookup) |
| US2-1, US2-2, US2-5 | Frontend: `LoadDriverDrawer.test.tsx`; E2E UI variant of `styrmin_resources` |
| US2-3, US2-4 | Frontend: `DriverDetailPage.test.tsx`; E2E: `test_driver_detail_inspects_versions_via_tabs` |
| US2-6 | Frontend: `driverList.test.ts` |
| US3-1 to US3-5 | Unit: `test_driver_directory.py`, `test_provider.py` (local repository with symlinks); propagation test for one refused value |
| US4-1, US4-2 | Unit: `test_loaders_git_commit_sha.py`; propagation test (root load stores `NULL`) |
| US4-3 | Unit: `test_git_source_commit_pinning.py` (root keeps one pull step); E2E: every root driver fixture (`semaphore`, `generic-app`, `infrahub`, test drivers) |

## Complexity Tracking

No constitution violations to justify.
