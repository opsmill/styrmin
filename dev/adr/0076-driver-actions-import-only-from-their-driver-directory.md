# ADR-076: Driver Actions Import Only from Their Driver Directory, and Git Loads Stay Inside the Clone

**Status**: Accepted
**Date**: 2026-10-17
**Decision-makers**: Fatih Acar
**Source**: [issue #517](https://github.com/opsmill/styrmin/issues/517);
[PRD](https://github.com/opsmill/styrmin/issues/517#issuecomment-6236268970);
[spec 028](../../specs/028-git-driver-directory/spec.md) (FR-004, FR-008);
[research R-001 and R-004](../../specs/028-git-driver-directory/research.md)
**Related**: [ADR-053](0053-driver-version-provenance-fingerprint.md) (a git driver version is identified by the commit of the whole repository)

## Context

Until spec 028, a load from git read `driver.styrmin.yml`, `values.j2.yml` and `actions.py` from the
root of the cloned repository, and each driver action's Prefect deployment cloned the repository
and ran from the root of the clone. A repository that held several drivers in folders could not
be loaded.

Spec 028 lets an admin give the driver directory, a folder of the repository relative to its root,
when loading from git. Two questions follow, and both limit what a driver author can do:

1. From which folder does an action run, and which folders of the repository can `actions.py`
   import modules from?
2. A load reads files on the Styrmin server. The repository is written by the driver author, and
   dulwich checks out symlinks as symlinks: a test repository with `driver.styrmin.yml ->
   /etc/hostname` made Styrmin read `/etc/hostname` on a load from the repository root (research
   R-004). Which paths may a git load read?

How Prefect 3.8.6 runs an action (research R-001): it runs the deployment's pull steps, then
changes the working directory to the `directory` output of the last step that returned one. After
`git_clone` alone, that is the root of the clone. An action's entrypoint is `actions.py:<function>`,
and Prefect's script loader puts two folders on `sys.path` while the file runs: the file's folder
and the working directory.

## Decision drivers

- A driver stays self-contained (Constitution §II): what an action runs comes from its own driver
  directory, not from another driver's folder.
- A git load must not read a file outside the cloned repository.
- Loads from the repository root and their existing deployments keep working.
- Use what Prefect and dulwich provide before extending them.

## Considered options

For the folder an action runs from (decision 1):

1. Keep running from the clone root, with an entrypoint that names the file in the driver
   directory, such as `drivers/infrahub/actions.py:setup`.
2. Run from the driver directory, by adding Prefect's built-in `set_working_directory` pull step
   after `git_clone`.
3. As option 2, but build the path with Prefect's step-output templating
   (`{{ clone.directory }}/drivers/infrahub`).

For the paths a git load may read (decision 2):

1. Turn off symlink checkout in dulwich.
2. After the clone, resolve the real path of the driver directory and of the three driver files,
   and refuse the load when the driver directory is outside the clone or a driver file is outside
   the driver directory. Run the check for every git load.
3. As option 2, and apply the same check to loads from a local directory.

## Decision

Decision 1: we chose option 2. Each action of a driver version loaded from a driver directory has
two pull steps: `git_clone`, then `set_working_directory` with the relative path
`<clone folder>/<driver directory>`. The action runs with the driver directory as its working
directory, and Prefect's script loader puts only the driver directory on `sys.path`. `actions.py`
can import modules from the driver directory, and packages installed in the action's image, but
not modules from other folders of the repository. Styrmin adds no other folder to the import path.
A driver version loaded from the repository root keeps its single `git_clone` step.

Option 1 puts the clone root on `sys.path` as the working directory, so an action could import
from any folder of the repository, and the action would run from the root. Option 3 gives the same
path as option 2, because Styrmin already names the clone folder, and adds a template that a unit
test can check only as a string.

Decision 2: we chose option 2. After the clone and before reading any file, the git driver
provider resolves the driver directory and `driver.styrmin.yml`, `values.j2.yml` and `actions.py`
with `Path.resolve()`. It refuses the load when the resolved driver directory is not inside the
resolved clone root, or when a resolved driver file is not inside the resolved driver directory:
Prefect's script loader puts the folder of the resolved `actions.py` on `sys.path`, so an
`actions.py` that is a symlink to `../../shared/actions.py` would let the action import from
`shared/`. It also refuses the load when the driver directory or a driver file cannot be followed,
such as a symlink loop: Python 3.14 `Path.resolve()` does not raise on a loop. The check runs for
loads from the repository root too, where the driver directory is the clone root. A symlink whose
target is inside the driver directory is accepted. Before the clone, Styrmin also refuses a driver
directory that is an absolute path, that contains a `..` segment, a backslash, `{`, `}` or a
control character, or that is longer than 255 characters once stored. Prefect fills in
`{{ ... }}` templates (blocks, variables, environment variables) in the `set_working_directory`
step before it runs it, so a driver directory with a template could move the action to another
folder or write a secret into a log.

Option 1 is not available through `porcelain.clone`: only the lower-level `build_index_from_tree`
takes a `symlink_fn`, so Styrmin would have to replace `porcelain.clone` with dulwich internals.
It would also turn symlinks inside the repository into plain files, which authors may rely on.
Option 3 would refuse valid local loads: the admin gives a local path on the server, and a
Kubernetes ConfigMap or Secret volume exposes every file as a symlink.

## Consequences

- Good, because a driver directory holds everything its actions import from the repository, so
  two drivers in one repository cannot change each other's actions through a shared module.
- Good, because a repository cannot make a git load read a file outside the clone, through a
  driver directory value or a symlink, for loads from a driver directory and from the root.
- Good, because both decisions use Prefect's and dulwich's existing behaviour: one built-in pull
  step and one real-path check, with no extension or upstream change.
- Bad, because a driver author who wants code shared by several drivers must copy it into each
  driver directory or install it in the image the actions run in (the action's `image`).
- Bad, because a load from the repository root whose `driver.styrmin.yml`, `values.j2.yml` or
  `actions.py` is a symlink to a path outside the repository, which loaded before spec 028, now
  fails.
- Neutral, because each action's Job still clones the whole repository: the load needs the whole
  commit for the fingerprint, and a sparse checkout would add a second clone mode to test
  (research R-010).

## Confirmation

- `backend/tests/unit/workflows/test_action_driver_directory.py` runs Prefect's pull steps with a
  `set_working_directory` step and loads the action: a module in the driver directory imports, and
  a module at the root of the tree does not.
- `backend/tests/unit/workflows/test_git_source_commit_pinning.py` checks the two pull steps of a
  driver directory version and the single step of a root version.
- `backend/tests/unit/services/driver/test_provider.py` loads from local repositories with
  symlinks: a driver directory that leads outside the clone, a driver file that leads outside the
  driver directory (also to another folder of the repository) and a symlink loop are refused, and
  a driver directory or a driver file that is a symlink inside the driver directory is accepted.
- `backend/tests/unit/services/driver/test_driver_directory.py` covers the values refused before
  the clone.
- Every E2E session loads its `simple-app` driver from the driver directory `drivers/simple-app`
  and runs its setup actions, whose `actions.py` imports a module next to it;
  `test_driver_version_reselection.py` checks that those setup actions completed.

## More information

- The load surfaces, the stored form of a driver directory and the error messages are in
  [Loading a Driver](../../docs/docs/drivers/loading-drivers.md#from-a-git-repository).
- Sharing code between driver directories is out of scope of spec 028.
