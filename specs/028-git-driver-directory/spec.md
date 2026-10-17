# Feature Specification: Load an Application Driver from a Driver Directory of a Git Repository

**Feature Branch**: `fac/check-driver-from-git-repo-works-0d15v`

**Created**: 2026-10-17

**Status**: Draft

**Input**: PRD "Load an application driver from a driver directory of a git repository" — [opsmill/styrmin#517 (comment)](https://github.com/opsmill/styrmin/issues/517#issuecomment-6236268970). Seed issue: [#517](https://github.com/opsmill/styrmin/issues/517).

## Context

A load from git takes a repository URL and a branch. Styrmin clones the repository and reads the **driver specification file** (`driver.styrmin.yml`), `values.j2.yml` and `actions.py` from the root of the clone ([`provider.py`](../../backend/styrmin_backend/services/driver/provider.py), [`directory.py`](../../backend/styrmin_backend/services/driver/models/structure/directory.py)). Each driver action becomes a Prefect deployment that clones the same repository and runs from the root of the clone, because it sets no working directory ([`user.py`](../../backend/styrmin_backend/services/user.py), [`workflows/models.py`](../../backend/styrmin_backend/workflows/models.py)). The user documentation states: "The repository must contain a `driver.styrmin.yml` at its root" ([`loading-drivers.md`](../../docs/docs/drivers/loading-drivers.md)).

A driver author who keeps several drivers in one repository therefore cannot load any of them. This repository has the same problem: the example drivers are in `driver/examples/<name>/`, and the E2E fixtures copy each one to the root of its own repository on a test git server before they load it ([`conftest.py`](../../backend/tests/e2e/conftest.py)). No user request has been recorded; the gap was found while checking the E2E coverage of git driver loading.

The application driver version already has a `source_path` column, part of its unique identity index. Only loads from a local directory fill it today ([`applications.py`](../../backend/styrmin_backend/services/applications.py)).

This feature lets an admin give the **driver directory**, relative to the repository root, when loading from git. Styrmin reads the driver from that directory, runs its actions from it, stores it in `source_path`, and shows it on the driver version's Overview tab. A load without a driver directory reads from the repository root, as it does today.

## Clarifications

### Session 2026-10-17 (autonomous, from the PRD)

The PRD leaves some points open or names surfaces that differ from the code. These answers were taken without the user so that later phases do not reopen them.

- Q: What is the new argument called? → A: `driverDirectory` on `loadRemoteApplicationDriverVersion`, `driver_directory` on the SDK's `drivers.load_version`, and `--driver-directory` on `styrminctl drivers load-version`. The name is the glossary term ([`CONTEXT.md`](../../CONTEXT.md), **Driver directory**), which AGENTS.md asks code and schema to use verbatim. The output field stays `sourcePath`, because it already exists and also carries the local path.
- Q: Does a refused or failed load need a new error code? → A: No. Refusals and load failures raise the existing driver loading error, whose code is `VALIDATION_ERROR`. The message carries what the admin needs (FR-009). No client branches on a finer code today.
- Q: Do FR-004 (actions import only from their driver directory) and FR-008 (symlink refusal, also for loads from the repository root) need an ADR? → A: Yes, one short new ADR, as the PRD recommends, because both decisions limit what a driver author can do. It takes the next free ADR number when it is written.
- Q: The PRD names a "Source tab". The driver detail page has no Source tab: its Overview tab holds the "Source" row (repository and branch) and the "Commit" row. → A: The Overview tab gets a "Driver directory" row for git driver versions loaded from a driver directory. Spec 012's FR-012 described this display as a "subpath"; this feature implements it with the glossary term.
- Q: What happens when two driver directories of one repository hold drivers with the same name, loaded at the same commit? → A: Each load creates its own driver version, because `source_path` differs, and each driver version MUST keep its own actions (FR-010). Today Styrmin names each action's Prefect deployment after the driver name and the short commit SHA ([`manager.py`](../../backend/styrmin_backend/workflows/manager.py)), so the second load would replace the first driver version's actions. PRD user story 5 ("tell apart two driver versions loaded from the same repository and commit") assumes this case exists.
- Q: Are `drivers//infrahub` and `drivers/./infrahub` the same driver directory as `drivers/infrahub`? → A: Yes. FR-006 asks for one stored form, so empty segments and `.` segments are removed as well as a leading `./` and a trailing `/`. Surrounding whitespace is removed before the empty check.
- Q: Does the "Load a driver" drawer check the value before sending it? → A: No. The server applies FR-006 to FR-009 and the drawer shows the server's error message, so the three load surfaces share one rule.
- Q: Is a driver directory, or a driver file, that is a symlink to a target inside the clone accepted? → A: Yes. FR-008 refuses only real paths outside the clone.

## User Scenarios & Testing *(mandatory)*

The PRD identifies one P1 journey: load, deploy and run the actions of a driver from a driver directory. The stories below split that journey by surface and outcome so each part can be tested on its own. All four ship in one change.

### User Story 1 - Load, deploy and run a driver from a driver directory through the API, SDK or CLI (Priority: P1)

A driver author keeps several drivers in one repository, for example `your-org/styrmin-drivers` with `drivers/infrahub/` and `drivers/semaphore/`. An admin loads `drivers/infrahub` on branch `main` with `styrminctl drivers load-version`, the SDK or the GraphQL API. The admin then deploys it, and its setup and upgrade actions run from `drivers/infrahub/`.

**Why this priority**: Without it, a driver kept in a folder of a repository cannot be loaded at all. Admins script loads, so the API, SDK and CLI are the main surfaces.

**Independent Test**: Load a driver from a driver directory of a test repository with the SDK, deploy it, and check that the driver version stores the driver directory and that its setup actions succeed.

**Acceptance Scenarios**:

1. **Given** a repository whose `drivers/infrahub/` folder holds a `driver.styrmin.yml`, a `values.j2.yml` and an `actions.py`, **When** an admin loads it with the repository URL, branch `main` and driver directory `drivers/infrahub`, and then deploys it, **Then** the driver version is created with `sourcePath` = `drivers/infrahub`, and its setup actions run and succeed.
2. **Given** the same repository, **When** the admin runs `styrminctl drivers load-version <url> main --driver-directory drivers/infrahub`, **Then** the result is the same as a load through the API.
3. **Given** a driver directory whose `actions.py` imports a helper module kept in the same driver directory, **When** an action runs, **Then** the import succeeds.
4. **Given** a driver directory whose `actions.py` imports a module kept in another folder of the repository, **When** an action runs, **Then** the import fails, because Styrmin adds no other folder of the repository to the import path.
5. **Given** a driver version already loaded from `drivers/infrahub` at commit C, **When** the admin loads `./drivers/infrahub/` at the same commit, **Then** Styrmin returns the existing driver version and creates no new one.
6. **Given** two driver directories of one repository that hold drivers with the same name, **When** the admin loads both at the same commit and deploys each, **Then** each deployment runs the actions of its own driver directory.

---

### User Story 2 - Load from the drawer and view the driver directory on the Overview tab (Priority: P1)

An admin opens the "Load a driver" drawer on the drivers page, chooses a load from git, and fills in the repository URL, the branch and the driver directory. After the load, the admin opens the driver version and views the driver directory on its Overview tab, next to the repository, the branch and the commit.

**Why this priority**: The drawer is the load surface for admins who do not script. The Overview tab is where an admin tells apart two driver versions loaded from the same repository and commit.

**Independent Test**: Load a driver from a driver directory through the drawer, open the driver version, and check the "Driver directory" row.

**Acceptance Scenarios**:

1. **Given** the drawer in git mode, **When** the admin fills in the repository URL, the branch and `drivers/infrahub`, and submits, **Then** the driver version is created from that driver directory.
2. **Given** the drawer in git mode, **When** the admin leaves the driver directory empty and submits, **Then** the driver is loaded from the repository root, as today.
3. **Given** a git driver version loaded from `drivers/infrahub`, **When** the admin opens its Overview tab, **Then** a "Driver directory" row shows `drivers/infrahub`.
4. **Given** a git driver version loaded from the repository root, **When** the admin opens its Overview tab, **Then** no "Driver directory" row is shown.
5. **Given** the drawer, **When** the server refuses the driver directory, **Then** the drawer shows the server's error message and keeps the values the admin entered.
6. **Given** two driver versions of one driver, loaded from `drivers/infrahub` and `drivers/infrahub-next` of the same repository, **When** the admin opens the drivers list, **Then** each version's Source cell shows its driver directory.

---

### User Story 3 - Refuse unsafe driver directories and explain failed loads (Priority: P1)

An admin who types a wrong driver directory gets an error that says what to correct. A driver repository cannot make the Styrmin server read files outside the clone, through a `..` segment, an absolute path or a symlink.

**Why this priority**: A load reads files on the server. A driver directory value, or a symlink in a repository, must not lead outside the clone. An error that names the directory, repository, branch and commit lets the admin correct the load without reading the server logs.

**Independent Test**: Send loads with each refused form and with a missing driver directory, and check the refusals and the error messages.

**Acceptance Scenarios**:

1. **Given** a driver directory `/etc`, `../other`, `drivers/../../etc`, `drivers\infrahub` or a value with a NUL character, **When** an admin loads it, **Then** Styrmin refuses the load before it clones the repository, and creates no driver version.
2. **Given** a repository in which `drivers/infrahub` is a symlink to a folder outside the repository, **When** an admin loads that driver directory, **Then** Styrmin refuses the load and reads no file outside the clone.
3. **Given** a repository whose root `driver.styrmin.yml`, `values.j2.yml` or `actions.py` is a symlink to a file outside the repository, **When** an admin loads it from the repository root, **Then** Styrmin refuses the load.
4. **Given** a driver directory `drivers/missing` that does not exist in the repository, **When** an admin loads it, **Then** the error names `drivers/missing`, the repository, the branch and the commit.
5. **Given** a driver directory that exists but holds no `driver.styrmin.yml`, **When** an admin loads it, **Then** the error names the driver directory, the repository, the branch and the commit, and says that the driver specification file is missing.

---

### User Story 4 - Loads from the repository root keep working (Priority: P1)

An admin who loads drivers from the root of their own repository keeps doing so without change. Existing driver versions and deployments are not changed.

**Why this priority**: Every git driver version loaded so far comes from a repository root. A change that broke those loads, or that made a reload create duplicate driver versions, would affect every installation.

**Independent Test**: Reload an existing root driver at the commit it was loaded from, and check that Styrmin returns the existing driver version.

**Acceptance Scenarios**:

1. **Given** a git driver version loaded from a repository root before this change, **When** an admin reloads it at the same commit without a driver directory, **Then** Styrmin returns the existing driver version.
2. **Given** the same driver version, **When** an admin reloads it with a driver directory of `""` or `.`, **Then** Styrmin returns the existing driver version.
3. **Given** a deployment of a driver version loaded from a repository root before this change, **When** an action of that deployment runs after the change, **Then** it runs from the repository root, as before.

---

### Edge Cases

- A commit that changes only another driver directory still makes a reload create a new driver version, because a git driver version's fingerprint is the commit of the whole repository ([ADR-053](../../dev/adr/0053-driver-version-provenance-fingerprint.md)). With latest-wins resolution, the next upgrade of a deployment binds to that new driver version. This is accepted and documented (FR-011).
- A driver directory written as `./drivers/infrahub`, `drivers/infrahub/`, `drivers//infrahub` or `drivers/./infrahub` is stored as `drivers/infrahub`, so a reload at the same commit creates no duplicate driver version (FR-006).
- A driver directory with a `..` segment, an absolute path, a backslash, or a symlink that leads outside the clone is refused (FR-007, FR-008).
- A driver directory that is a file, not a folder, fails the load with the FR-009 error.
- An action that imports a module from outside its driver directory fails to import. Code that several drivers share goes into each driver directory or into the action's image.
- Two driver directories that hold drivers with the same name, loaded at the same commit, create two driver versions. The version picker labels both `<version>@<short commit>`; the Overview tab's "Driver directory" row tells them apart. Each keeps its own actions (FR-010).
- Helm charts are not affected, because a driver's chart comes from an OCI or HTTP chart repository, never from the git repository.
- A load from a local directory is not changed. The path given there already is the driver directory.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Admins MUST be able to give the path of a driver directory, relative to the repository root, when they load a driver version from git. This applies to the GraphQL mutation `loadRemoteApplicationDriverVersion`, the SDK's `drivers.load_version`, `styrminctl drivers load-version` and the "Load a driver" drawer. The value is optional on every surface.
- **FR-002**: When no driver directory is given, Styrmin MUST read the driver from the repository root, as it does today.
- **FR-003**: Styrmin MUST read `driver.styrmin.yml`, `values.j2.yml` and `actions.py` from the driver directory.
- **FR-004**: Styrmin MUST run each driver action with the driver directory as the working directory, and MUST add no other folder of the repository to the import path.
- **FR-005**: The driver version MUST record the driver directory in `source_path`, the GraphQL field `sourcePath` MUST return it, the driver version's Overview tab MUST show it in a "Driver directory" row, and the drivers list MUST show it in the version's Source cell. A git driver version loaded from the repository root records no value and shows no row and no directory in the Source cell.
- **FR-006**: Styrmin MUST store a driver directory in one form. It removes surrounding whitespace, a leading `./`, a trailing `/`, empty segments and `.` segments. It treats an empty value or `.` the same as a load without a driver directory.
- **FR-007**: Styrmin MUST refuse, before it clones, a driver directory that is an absolute path or that contains a `..` segment, a backslash or a NUL character.
- **FR-008**: Styrmin MUST refuse a load when the driver directory, or one of the three driver files, has a real path outside the cloned repository. This applies to loads from the repository root too.
- **FR-009**: When the driver directory does not exist, is not a folder, or holds no `driver.styrmin.yml`, the load error MUST name the driver directory, the repository, the branch and the commit.
- **FR-010**: Two driver versions loaded from different driver directories of one repository at the same commit MUST each run the actions of their own driver directory, also when their drivers have the same name. A load MUST NOT replace the actions of another driver version.
- **FR-011**: The user documentation MUST describe the driver directory on each load surface, state that a reload after any commit to the repository creates a new driver version even when the driver directory did not change, and give the correct mutation name `loadRemoteApplicationDriverVersion`.

### Key Entities

- **Driver directory** (existing concept, new glossary entry in [`CONTEXT.md`](../../CONTEXT.md)): the folder that holds an application driver's driver specification file, `values.j2.yml` and `actions.py`. For a load from git, it is the repository root or a folder of the repository, given as a path relative to the root. It is stored on the application driver version as `source_path`, which stays empty for the repository root. Terms to avoid: "subfolder", "subpath", "driver root".
- **Application driver version** (existing): a git driver version keeps its identity from the commit SHA of the whole repository ([ADR-053](../../dev/adr/0053-driver-version-provenance-fingerprint.md)). The driver directory is part of its identity through `source_path`. A reload after any commit to the repository creates a new driver version, even when the driver directory did not change.
- **Provenance fingerprint** (existing, unchanged): its glossary entry says that, for git, the commit covers the whole repository.

No new entity and no new database column are needed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An admin can load a driver from a driver directory of a repository that holds at least two drivers, deploy it and run its setup and upgrade actions to success, without moving any file. This works from each load surface: the GraphQL API and SDK, `styrminctl`, and the drawer.
- **SC-002**: Loads without a driver directory behave as they do today. A reload of an existing root driver at the commit it was loaded from returns the existing driver version, and no existing driver version or deployment changes.
- **SC-003**: Styrmin refuses every driver directory value covered by FR-007 or FR-008 (100% of the refused forms listed in User Story 3), and reads no file outside the cloned repository.
- **SC-004**: When a load fails because the driver directory does not exist or holds no driver specification file, the error message alone tells the admin which driver directory, repository, branch and commit to check, without reading the server logs.

## Documentation

Constitution §VII requires these updates in the same change:

- [`docs/docs/drivers/loading-drivers.md`](../../docs/docs/drivers/loading-drivers.md), section "From a git repository": the driver directory on each surface, the reload rule, the import rule for actions, and the correct mutation name.
- The CLI reference for `styrminctl drivers load-version`.
- [`CONTEXT.md`](../../CONTEXT.md): the new **Driver directory** entry, and edits to **Application driver version**, **Driver specification file** and **Provenance fingerprint**.
- A new ADR for the import rule (FR-004) and the symlink refusal (FR-008): [ADR-076](../../dev/adr/0076-driver-actions-import-only-from-their-driver-directory.md).
- A towncrier fragment for #517.

## Assumptions

- An existing git driver version with no `source_path` was loaded from the repository root.
- Only an admin starts a reload. Nothing reloads a driver automatically.
- The `set_working_directory` pull step that Styrmin already uses for its own Prefect flows can set the working directory for driver actions.
- The GraphQL mutation keeps the `ADMIN` role.

## Out of Scope

- Loading every driver of a repository in one call. Each load names one driver directory.
- A driver directory option for loads from a local directory.
- Loading from a git tag or a commit ([#528](https://github.com/opsmill/styrmin/issues/528)).
- Sharing code between driver directories.
- A fingerprint per driver directory.
- Automatic reloads, for example from a webhook.
- Moving existing driver versions to a driver directory.
- Removing the E2E copy step for every example driver. `conftest.py` still rewrites each driver's chart location.
