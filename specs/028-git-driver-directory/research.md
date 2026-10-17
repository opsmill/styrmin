# Research: Load an Application Driver from a Driver Directory of a Git Repository

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-17

Versions checked: Prefect 3.8.6 and dulwich 1.1.0, from the project's `uv.lock` (`.venv`). Code references are to commit `ce8cb7d8`.

## R-001: How Prefect sets the working directory of a driver action, and what it puts on the import path

**Question**: The spec requires each action to run with the driver directory as its working directory, and no other folder of the repository on the import path (FR-004). Does Prefect support this, or does Styrmin need to extend it?

**Findings** (Prefect 3.8.6 source):

- An action's Prefect deployment has one pull step today, `prefect.deployments.steps.git_clone` ([`workflows/models.py`](../../backend/styrmin_backend/workflows/models.py), `GitSourceWorkflowDefinition.to_deployment`). The step clones into `<current working directory>/<clone_directory_name>` and does not change the working directory (`prefect/deployments/steps/pull.py`, `git_clone`).
- Prefect runs the pull steps, then changes the working directory to the `directory` output of the last step that returned one (`prefect/flows.py`, `load_flow_from_flow_run`; `prefect/runner/_workspace_resolver.py`). After `git_clone` alone, that is the root of the clone, which is why actions run from the repository root today.
- Prefect's built-in `prefect.deployments.steps.set_working_directory` step changes the working directory and returns it as `directory`. A relative path resolves against the working directory at that point, which is still the folder `git_clone` cloned into.
- An action's entrypoint is `<file>:<function>`, for example `actions.py:post_setup`, because the driver specification file's `location` is `actions.py::post_setup` and its pattern forbids `/` ([`actions.py`](../../backend/styrmin_backend/services/driver/models/resources/actions.py)). Prefect loads such a file with `load_script_as_module` (`prefect/utilities/importtools.py`). It puts two folders on `sys.path` while the file runs: the file's folder and the working directory. With the working directory set to the driver directory, both are the driver directory.
- The job runs `python -m prefect.engine`, so `sys.path[0]` is the container's start folder, not the clone root.

**Decision**: Use Prefect's built-in `set_working_directory` step. For a driver version loaded from a driver directory, the action's deployment gets two pull steps: `git_clone`, then `set_working_directory` with the relative path `<clone_directory_name>/<driver directory>`. A driver version loaded from the repository root keeps one pull step, unchanged.

**Rationale**: The step exists for this purpose, so neither an extension nor an upstream change is needed. With the working directory set, Prefect's own loader puts only the driver directory on the import path, which is FR-004.

**Alternatives considered**:

- An entrypoint that names the file in the driver directory, such as `drivers/infrahub/actions.py:setup`, run from the clone root. Rejected: Prefect would put the clone root on `sys.path` as the working directory, which FR-004 forbids, and the action would run from the root.
- Prefect's step-output templating (an `id` on `git_clone` and `{{ clone.directory }}/drivers/infrahub`). Rejected: it gives the same path, because Styrmin already names the clone folder (`clone_directory_name`), and it adds a template that a unit test can only check as a string.
- An upstream change to Prefect. Not needed.

## R-002: The existing `set_directory_pull_step` helper writes a path that does not exist in the action's container

**Question**: `GitSourceWorkflowDefinition` already has a `set_directory` field, rendered by `set_directory_pull_step` ([`workflows/utils.py`](../../backend/styrmin_backend/workflows/utils.py)). Can driver actions use it as it is, as the PRD assumes?

**Findings**:

- The helper writes the absolute path `/opt/prefect/<clone_directory_name>/<directory>`.
- Driver actions run as Kubernetes Jobs of `user-work-pool` ([`job_configuration.yaml`](../../backend/styrmin_backend/workflows/templates/job_configuration.yaml)). Their image defaults to `styrmin` ([`variables.json`](../../backend/styrmin_backend/workflows/templates/variables.json)), whose working directory is `/source` ([`docker/Dockerfile`](../../docker/Dockerfile), `WORKDIR /source`). An action can also set its own `image`. `git_clone` clones into the image's working directory, so the clone of a default action is `/source/<clone_directory_name>`, not `/opt/prefect/...`.
- No git-sourced workflow sets `set_directory` today. Styrmin's own flows set it on `LocalSourceWorkflowDefinition`, which renders `set_working_directory` directly with `/source/backend/` ([`catalogue.py`](../../backend/styrmin_backend/workflows/catalogue.py)). Only the unit test `test_set_directory_step_follows_the_clone_directory` exercises the helper ([`test_git_source_commit_pinning.py`](../../backend/tests/unit/workflows/test_git_source_commit_pinning.py)).

**Decision**: Change `set_directory_pull_step` to write the relative path `<clone_directory_name>/<directory>`, and update its unit test. The PRD's assumption "the existing `set_directory` pull step can set the working directory for driver actions" holds for the Prefect step, but not for this helper's path.

**Rationale**: A relative path resolves against the folder `git_clone` cloned into, whatever the action's image is. The helper has no other caller, so the change affects only driver actions.

**Alternatives considered**: Keep `/opt/prefect/` and set the Job's working directory to `/opt/prefect`. Rejected: it changes every action's container, and an action's own image could still differ.

## R-003: Two driver versions from one commit replace each other's actions

**Question**: FR-010 requires that two driver versions loaded from different driver directories at the same commit keep their own actions, also when their drivers have the same name. Does the current action registration allow this?

**Findings** ([`manager.py`](../../backend/styrmin_backend/workflows/manager.py)):

- `register_user_action` names each Prefect deployment `<workflow name> (<driver name>@<short commit>)` and tags it `application/<driver name>`, `version/<supported versions>`, `hook/<hook>`, `mode/<mode>`, `fingerprint/<short commit>`.
- Prefect replaces a deployment with the same flow and deployment name. Two driver directories that hold drivers with the same name, loaded at the same commit, produce the same deployment name, so the second load replaces the first driver version's actions.
- `get_user_action_deployment_id` looks a deployment up with `DeploymentFilterTags(all_=...)`, which matches every deployment that has at least these tags, newest first. Prefect's tag filter has `all_`, `any_` and `is_null_`, and no filter that excludes a tag (checked in `prefect.client.schemas.filters.DeploymentFilterTags`).
- Prefect refuses `/`, `%`, `&`, `>` and `<` in deployment names (`prefect/types/names.py`, `BANNED_CHARACTERS`). A driver directory cannot go into the deployment name as it is.
- The lookup has three callers, each with the driver version row at hand: `instantiate_application` ([`applications.py`](../../backend/styrmin_backend/services/applications.py)) and the create and upgrade paths of the remediation service ([`remediation.py`](../../backend/styrmin_backend/services/reconciliation/remediation.py)).

**Decision**:

- When an action belongs to a driver version loaded from a driver directory, `register_user_action` adds the tag `directory/<driver directory>` and appends the first 7 hex characters of the SHA-256 of the driver directory to the deployment name: `<workflow name> (<driver name>@<short commit> <directory digest>)`.
- `get_user_action_deployment_id` takes the driver directory. With one, it adds the same tag to the filter. Without one, it drops every result that carries a `directory/` tag before it picks the newest, so a root driver version never runs another driver directory's action.
- The three callers pass the driver version's `source_path` when its `source_type` is `git`, and nothing otherwise.

**Rationale**: Driver versions loaded from the repository root keep the deployment names and tags they have today, so existing deployments are found as before (SC-002). The digest keeps the name within Prefect's rules and unique per driver directory; the tag carries the readable path.

**Alternatives considered**:

- Tag and name each deployment with the driver version's id. Rejected: the registration runs before the row exists in the same load, and existing deployments carry no such tag, so every lookup would need a second path for them.
- Replace `/` with another character in the deployment name. Rejected: `drivers/a-b` and `drivers-a/b` would give the same name.
- Refuse a second driver with the same name and commit. Rejected: PRD user story 5 expects two such driver versions to exist side by side.

## R-004: Symlinks in a cloned repository

**Question**: FR-008 requires Styrmin to refuse a driver directory, or a driver file, whose real path is outside the clone. Does dulwich check out symlinks?

**Findings**: Yes. A test repository with `drivers/evil -> /etc`, `driver.styrmin.yml -> /etc/hostname` and `drivers/inner -> ../a`, cloned with `porcelain.clone`, gave three symlinks. The first two resolve outside the clone; the third resolves inside. dulwich creates symlinks with `os.symlink` on Linux (`dulwich/index.py`, `build_file_from_blob`), and `porcelain.clone` exposes no option to turn this off. Today a repository whose root `driver.styrmin.yml` is a symlink to a server file makes Styrmin read that file.

**Decision**: After the clone, Styrmin resolves the driver directory and each of `driver.styrmin.yml`, `values.j2.yml` and `actions.py` with `Path.resolve()`, and refuses the load when a resolved path is not inside the resolved clone root. The check runs for every git load, from a driver directory or from the root, before any file is read. Symlinks whose target is inside the clone are accepted.

**Rationale**: Resolving the real path catches every symlink depth and dangling links (a dangling link resolves to its target path). The three driver files are the only files a load reads, so checking them is enough.

**Alternatives considered**:

- Turn off symlink checkout in dulwich. Rejected: `porcelain.clone` exposes no such option; the lower-level `build_index_from_tree` takes a `symlink_fn`, but using it means replacing `porcelain.clone` with dulwich internals. It would also change in-repository symlinks into plain files, which authors may rely on.
- Apply the same check to loads from a local directory. Rejected: the admin gives that path on the server, and a Kubernetes ConfigMap or Secret volume exposes every file as a symlink. The spec scopes FR-008 to the cloned repository.

## R-005: One stored form of a driver directory, and the values refused before the clone

**Question**: FR-006 and FR-007 define the stored form and the refused values. Which rules, and where do they run?

**Decision**: A pure function in the driver service, used by the git driver provider's constructor, so it runs before the clone:

1. Remove surrounding whitespace.
2. Refuse a value that contains a backslash or a NUL character, or that starts with `/` (FR-007).
3. Split on `/`, drop empty segments and `.` segments.
4. Refuse a value with a `..` segment (FR-007).
5. Return `None` when no segment is left, which means the repository root; otherwise join the segments with `/`.

Examples: `./drivers/infrahub/` → `drivers/infrahub`; `drivers//./infrahub` → `drivers/infrahub`; `""`, `.`, `./` → `None`; `/etc`, `../x`, `a/../b`, `drivers\infrahub` → refused.

**Rationale**: Splitting on `/` gives the same result for every way of writing a path, so a reload at the same commit finds the existing driver version (identity includes `source_path`). `a/../b` is refused rather than reduced, as FR-007 says, because a `..` segment in a driver directory is more likely an error than a shortcut. A NUL character is refused because the operating system cannot open such a path.

**Alternatives considered**: `PurePosixPath` normalisation. Rejected: it keeps `..` segments and treats a leading `//` as a separate root, so the rules would need code around it anyway.

## R-006: Error messages for a missing driver directory or driver specification file

**Question**: FR-009 requires the error to name the driver directory, the repository, the branch and the commit. What does a load return today?

**Findings**: A missing `driver.styrmin.yml` raises `MissingDriverSpecificationError("The driver specification file could not be found: [Errno 2] No such file or directory: '/tmp/tmpab12/driver.styrmin.yml'")` from `ResourceFileLoader` ([`loaders.py`](../../backend/styrmin_backend/services/driver/loaders.py)). It names a temporary path, and not the repository, branch or commit. Both errors are `DriverError` subclasses with the code `VALIDATION_ERROR` ([`exceptions.py`](../../backend/styrmin_backend/services/driver/exceptions.py)).

**Decision**: The git driver provider checks, after the clone and the symlink check, that the driver directory is a folder and that it holds `driver.styrmin.yml`:

- Not a folder, or missing: `DriverLoadingError("Driver directory 'drivers/missing' does not exist in repository 'git://…/x.git' (branch 'main', commit 0123456789ab…)")`.
- No driver specification file: `MissingDriverSpecificationError("No driver.styrmin.yml in driver directory 'drivers/infrahub' of repository '…' (branch 'main', commit …)")`.
- For a root load the messages name "the repository root" instead of a driver directory.

No new error code (spec Clarifications).

**Rationale**: The provider is the one place that knows the four values. Raising before the loader reads files keeps the temporary path out of the message.

## R-007: Where the driver directory travels through the code

**Decision**:

- `GitSource` ([`source.py`](../../backend/styrmin_backend/services/driver/models/structure/source.py)) gets `driver_directory: str | None = None`, the normalised value. It is the one carrier from the provider to storage and to the action builder.
- `load_application_driver_from_object` stores `source.driver_directory` in `source_path` for git rows and uses it in `get_by_identity`. A root load passes `None`, which matches every existing git row (SC-002).
- `ActionsWorkflowBuilder` sets `set_directory` from `source.driver_directory` and passes the driver directory to `register_user_action`.
- `GitSourceWorkflowDefinition.get_function`, which only the local test executor uses, is not changed.

**Rationale**: The source model already carries the repository, branch and token, and the loader returns it on `ApplicationDriver.source`. Adding the field there needs no new parameter on the loader or the storage function.

## R-008: GraphQL, SDK and CLI names

**Decision**:

- GraphQL: `loadRemoteApplicationDriverVersion(repositoryUrl: String!, branch: String!, driverDirectory: String = null)`. No change to the output type; `sourcePath` already exists.
- SDK: `drivers.load_version(repository_url, branch, driver_directory=None)`. The `load_version.graphql` operation passes `$driverDirectory` and selects `sourceRepository`, `sourceBranch` and `sourcePath`, so the CLI can print them.
- CLI: `styrminctl drivers load-version <repository_url> <branch> [--driver-directory <path>]`. When the loaded version has a `sourcePath`, the output prints `Driver directory: <path>`.
- Frontend: `load_remote_driver.graphql` passes `$driverDirectory`; the drawer sends the field only when it is not empty.

**Rationale**: The name is the glossary term (spec Clarifications). The argument is optional with a `null` default, so existing clients are not affected.

## R-009: E2E coverage that reuses the session fixtures

**Question**: Constitution §V requires E2E coverage of the user-visible flow, and the "reuse before you boot" rule prefers extending existing fixtures. Where does the coverage go?

**Findings**:

- `git_server` ([`conftest.py`](../../backend/tests/e2e/conftest.py)) copies each driver to the root of its own repository and pushes it to the test git server.
- `styrmin_resources`, the root session fixture of every E2E session, loads `simple-app` through the dual-entrypoint `load_driver_version` and yields the driver id. Every session deploys it, and `simple-app` declares setup (`pre`, `post`) and upgrade (`core`) actions, so every session runs actions of this driver version.
- `test_driver_version_reselection.py` and `helpers/drivers.py` clone the `simple-app` repository, change its root `driver.styrmin.yml` and push branches. They need the `simple-app` repository to stay a root repository.
- The UI variant of `load_driver_version` fills `#repositoryUrl` and `#branch` in the drawer and reads the ids from the driver detail page ([`pages/drivers_list.py`](../../backend/tests/e2e/pages/drivers_list.py)).
- `test_driver_detail_inspects_versions_via_tabs` (`test_ui_smoke.py`, `ui_only`, `shard_general`) opens the session driver's detail page and its Overview tab. `test_driver_reload_identity.py` reads driver versions through `get_application_driver_versions`, which selects `sourcePath`.

**Decision**:

- `git_server` builds one more repository, `driver-collection`, with `drivers/simple-app/` and `drivers/db-test/`, prepared the same way as their own repositories (chart location rewrite, simple-app `spec.info`). The other repositories are unchanged.
- `load_driver_version` on the protocol, the API driver and the UI driver gets an optional `driver_directory`. The UI driver fills a `#driverDirectory` field when it is given.
- `styrmin_resources` loads `simple-app` from `driver-collection` with `driver_directory="drivers/simple-app"` and yields `driver_version_id` next to `driver_id`. Every session in both variants then loads from a driver directory, deploys it and runs its setup actions; sessions that upgrade it also run its upgrade action.
- Assertions:
  - `test_driver_version_reselection` (both variants) reads the session driver's versions through `get_application_driver_versions` and asserts that `styrmin_resources["driver_version_id"]` has `sourcePath == "drivers/simple-app"`. It also asserts that the action deployments of that driver version carry the `set_working_directory` step after `git_clone`, next to the commit check it already makes.
  - `test_driver_detail_inspects_versions_via_tabs` (UI) opens `?version=<driver_version_id>` and asserts that the Overview tab's "Driver directory" row shows `drivers/simple-app`.
- No new test node is added.

**Rationale**: The session fixture already boots, deploys and runs the actions of this driver version in every session, so moving its load to a driver directory covers SC-001 at no extra boot cost. The `simple-app` root repository keeps covering root loads, together with `semaphore`, `generic-app`, `infrahub` and the three test drivers (SC-002).

**Alternatives considered**: A new E2E test that loads and deploys a second driver from a driver directory. Rejected by the "reuse before you boot" rule: it would deploy a second stack for the same assertions.

## R-010: Third-party dependency evaluation (planning directive)

| Need | Dependency | Built-in mechanism | Decision |
| --- | --- | --- | --- |
| Action runs from the driver directory | Prefect | `set_working_directory` pull step | Use it (R-001). No extension or upstream change. |
| Only the driver directory on the import path | Prefect | `load_script_as_module` adds the script's folder and the working directory | Follows from the working directory (R-001). |
| Clone only the driver directory | Prefect `git_clone` (`directories`, sparse checkout); dulwich `filter_spec` | Exists | Not used. The load needs the whole commit for the fingerprint, and actions need only their directory, which a full clone contains. A sparse checkout would change no requirement and adds a second clone mode to test. |
| Refuse symlinks that leave the clone | dulwich | `symlink_fn` on `build_index_from_tree`, not exposed by `porcelain.clone` | Check real paths after the clone (R-004). |
| Exclude a tag in a deployment lookup | Prefect | Tag filter has `all_`, `any_`, `is_null_` only | Filter the results in Styrmin (R-003). An upstream filter would not reach the pinned Prefect 3.8.6 in time, and the result set is small (one deployment per action and driver version). |
