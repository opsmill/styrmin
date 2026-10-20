# Python Coding Guidelines

## Tooling

- **Linter & Formatter:** ruff (all rules enabled via `select = ["ALL"]`, with selective ignores)
- **Type Checker:** ty (Astral's type checker, configured in `[tool.ty]` in `pyproject.toml`)
- **Line Length:** 120 characters (hard limit), 150 for pycodestyle
- **Quote Style:** Double quotes
- **Complexity:** Max cyclomatic complexity of 10

Run before committing:

```bash
uv run invoke format lint
```

## Type Hints

All public functions must have complete type annotations (enforced by ty).

- Use `X | Y` syntax instead of `Union[X, Y]`
- Use `X | None` instead of `Optional[X]`
- Prefer `Sequence[T]` over `list[T]` for read-only return types
- Use `TYPE_CHECKING` blocks to avoid circular imports:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from styrmin_backend.db.models import Cluster
```

Tests are exempt from strict typing enforcement.

## Import Ordering

Managed by ruff isort. Standard order:

1. `from __future__ import annotations`
2. Standard library imports
3. Third-party imports
4. Local application imports
5. `TYPE_CHECKING` block (at the end of imports)

## Logging

Use **loguru**, not the standard `logging` module:

```python
from loguru import logger

logger.info("Processing deployment_id={}", deployment_id)
logger.debug("Context resolved: cluster={} env={}", cluster.name, env.name)
```

Use brace-style placeholders `{}` (not f-strings or `%`-formatting) in log messages for structured logging.

<!-- Extracted from specs/022-post-render-container-overrides on 2026-10-15 -->

Log whether a user-supplied override is set, not its value. Container `args` often carry flags
such as `--password=...`, so the patch builder logs `command_set` and `args_set` as booleans.

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

### Remove the user info from repository URLs in messages and logs

A repository URL can carry credentials, such as `https://user:token@host/x.git`. Pass every
repository URL through `redact_user_info` (`services/driver/driver_directory.py`) before it goes
into an error message or a log line. Pass the text of an exception that a clone raised through it
too, because some clone errors repeat the URL with its user info.

```python
repository = redact_user_info(self.source.repository)
...
raise DriverLoadingError(
    f"Failed to clone git repository {quoted(repository)}: {redact_user_info(str(exc))}"
) from exc
```

`redact_user_info` removes the user info of every `scheme://` URL in the text. An scp-style address
such as `git@github.com:o/r.git` has no scheme and is kept as it is. Reference:
`GitDriverProvider.provide` in `services/driver/provider.py`.

### Redact the text of a flow run's logs before it goes into a step or a task

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

Every signed-in user who can read a task can read the errors of its steps and its message,
Read-only users included: on the deployment page, with `styrminctl tasks get` and through the
GraphQL API. A flow run's logs can hold secrets, such as the action token or a password that an
action printed. Before text from a flow run's logs goes into a step error or a task message, pass
it through `redact_secrets` (`agent/tasks/utils.py`) with the secrets that the code knows, such as
the action token:

```python
first_error = await _first_error_log(flow_run.id)
if first_error:
    detail = f"{redact_secrets(first_error, crash_log_secrets)} ({detail})"
```

`redact_secrets` replaces the given values, the user info of every `scheme://` URL, the credential
after `Bearer` or `Basic`, and the value after `=` or `:` of a key whose name contains `password`,
`passwd`, `secret`, `token`, `api_key`, `private_key` or `credential`. It keeps a secret written in
any other form, so copy only the text that users need, such as the first `ERROR` log, cut to a
fixed length. Reference: `_run_deployment_or_fail` and `run_driver_action_or_fail` in
`agent/tasks/utils.py`
([ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md), R-002).

## Service Layer

Services are **module-level async functions**, not classes:

```python
async def create_cluster(name: str, config: dict | None, uow: UnitOfWork) -> Cluster:
    async with uow:
        cluster = Cluster(name=name, config=config)
        await uow.clusters.add(cluster)
        await uow.commit()
        return cluster
```

Conventions:

- Every service function takes `uow: UnitOfWork` as a parameter
- Use `async with uow:` context manager for transaction scope
- Call `await uow.commit()` explicitly to persist changes
- Naming: action verbs (`get_`, `create_`, `update_`, `delete_`, `deploy_`, `refresh_`)

### Validate before any step that starts a flow run

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

Run every validation of the request before calling anything that starts a Prefect flow run:
`apply_state`, or `_ensure_ingress_controller`, which creates and reconciles the internal ingress
deployment when an environment declares `dedicated_ingress`. `PrefectManager.run_action` creates
the flow run immediately. If a later check raises, the unit of work rolls back the database rows,
but the flow run already exists and runs against rows that were never committed.

Order a service function as: load, validate everything, then the steps with side effects outside
the database. Reference: `services/deployment.py::update_deployment_version`, which resolves the
target driver version and re-checks image overrides before `_ensure_ingress_controller`.

Save the deployment with its new instance before `apply_state`. `uow.deployments.save` flushes the
rows, so the database rejects a conflict, such as an instance name already in use, before the flow
run starts. Save the task that `apply_state` returns after it ([#499](https://github.com/opsmill/styrmin/issues/499)).

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

The same order applies to a service that commits in phases. Run every check that can refuse the
request before the first commit, including the checks that a later phase runs again. Otherwise a
refused request leaves the first phase's writes saved. `update_deployment` in
`services/deployment.py` commits the new config in phase 1 and builds the instance in phase 2. It
replaces the names in the request's affinity terms with ids, and resolves the terms of the
environment's config and of each component's config (`check_deployment_scheduling`), before the
phase 1 commit, so a term that names a missing or deleted deployment saves nothing
([ADR-075](../../adr/0075-deployment-references-stored-by-id.md)).

### Calculate a status that several writers change; do not store it

<!-- Extracted from specs/019-task-steps on 2026-10-08 -->
<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->
<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->
<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

When a status or result depends on rows that different processes write at different times,
calculate it on every read from those rows instead of storing it. A stored value forces every
writer to recalculate it, and a writer that forgets leaves it wrong. These features follow this
rule:

- The status of an environment backup or restore comes from its constituent backups or restores
  ([ADR-055](../../adr/0055-environment-backup-parent-records.md)).
- The status of an environment clone comes from its capture, its created environment, its
  cross-target restores and its recorded clone errors
  ([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md)).
- The task result comes from the steps and `Task.status` of the task and of the tasks its hook
  steps started. Flows, driver actions and status reports write these
  ([ADR-060](../../adr/0060-steps-and-derived-task-result.md)).
- The applications that wait for a dedicated ingress controller are recalculated from the
  database each time the cluster config fan-out runs or the status reporter continues it. No list
  of them is stored, which also makes the continuation safe to run twice
  ([ADR-066](../../adr/0066-cluster-config-fanout.md) decision 2).

Write the calculation as a pure function over rows that are already loaded
(`services/steps/results.py::compute_task_result`), so a list read can load the rows in bulk and
apply it in memory (see [Load list fields in a fixed number of queries](#load-list-fields-in-a-fixed-number-of-queries)).

Commit a parent row in the same transaction as every child row its status is calculated from.
Until its children are committed, a parent calculates a wrong status: an environment backup with
no constituent backups reads `COMPLETED`. Guards that look for unfinished child rows do not see it
either, so a second environment backup of the same environment is not refused.
`register_environment_backup` writes the parent, the constituents and their errors into the
caller's transaction, and `create_environment_backup` commits once, before it dispatches any flow
(`services/backup/environment.py`).

When rows that the calculation reads can be deleted, for example by retention cleanup or by a
cascade, record each deletion on the record whose status depends on them:

- Write an explicit event on the record in the same transaction as the deletion. An environment
  clone gets a `clone_errors` entry whose step names the deletion, such as
  `environment_backup_deleted` or `created_environment_deleted`.
- Never infer an outcome from a null foreign key. A null `created_environment_id` cannot tell
  "the environment was deleted" from "the environment was not created yet".
- Mark the event as fatal only when the record had not finished. Cleanup then never changes the
  outcome of a finished record.
- When an input is missing and no event explains it, keep the recorded outcome instead of
  calculating a new one.
- Decide whether each record had finished before the cascade deletes the rows the calculation
  reads, and pass that answer to the code that writes the event. Calculated after the cascade, a
  clone that was still restoring would read as finished.

Reference: the module docstring of `services/backup/clone.py`, and
`delete_environment_backup` in `services/backup/environment.py`, which takes the
`{clone_id: was_terminal}` result of `guard_no_clone_capturing_environment_backup` before the
cascade and passes it to `detach_clones_from_environment_backup`.

### Join the caller's transaction when you reuse a service that commits

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->

A service that creates many rows by calling a service that ends with `uow.commit()`, such as
`create_backup`, must not let each call commit on its own. The parent row and every child row
would no longer commit together (see the previous section), and the reused service's rollback on
an error would also discard the rows written before it.

Pass the reused service a `_SharedTransaction(uow)` view, which forwards every repository to the
caller's unit of work and turns `commit()` and `rollback()` into no-ops:

- Construct the view inside the caller's `async with uow` block, because the real unit of work
  binds its repositories in `__aenter__`.
- Collect the flow runs to start while the transaction is open, commit once, then start them.
- Use the view only with services that raise before their first write. Its `rollback()` does
  nothing, so rows the reused service already flushed stay in the transaction.
  `create_backup` raises `BackupAlreadyInProgressError` before it creates its row.

Reference: `_SharedTransaction` and `register_environment_backup` in
`services/backup/environment.py`.

### Set the row id before the INSERT when a unique name is built from it

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->

When a default name contains the row id, such as `styrmin-<backup id>`, generate the id with
`uuid4()` and pass it to the model, so the name is final when the row is inserted. Do not insert a
placeholder name and rename the row afterwards: the name column is unique, so two rows created in
one transaction, or two concurrent requests, collide on the placeholder.

```python
backup_id = uuid4()
backup = Backup(
    id=backup_id,
    name=name or f"styrmin-{backup_id}",
    ...
)
```

`create_backup` and `create_restore` in `services/backup/service.py`, and
`register_environment_backup` in `services/backup/environment.py`, follow this rule.

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

Choose the ids first, too, when one operation creates several records whose configs name each
other, or a record whose config names records created after it. Generate one id per record before
you create any of them, rewrite the references in every config with those ids, and pass each id
to the function that creates its record. Each config is then written once, in its final form, and
the order in which the records are created does not decide whether a reference resolves. Pass the
records that are not created yet to the checks that look references up, so the checks accept their
ids.

The environment clone flow (`_run_environment_clone` in `workflows/templates/clone.py`) builds
`counterpart_ids = {source deployment id: uuid4()}` before it creates the new environment,
rewrites the copied configs with `remap_deployment_references`, and calls
`deploy_application(..., deployment_id=<chosen id>, upcoming_deployments=...)` for each
counterpart. Do not create the rows first and update their configs afterwards: rows without an
instance are a state the rest of the code does not handle, and a crash between the two writes
leaves configs that name the wrong records
([ADR-075](../../adr/0075-deployment-references-stored-by-id.md)).

### Store a reference to another record by its id; look up a name only during the write

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

A user can rename a deployment and other records. A config that names another record by its name
stops matching it after a rename ([#492](https://github.com/opsmill/styrmin/issues/492)), and
rewriting the name in every config on each rename does not survive a restore that brings back an
older config (PR [#504](https://github.com/opsmill/styrmin/pull/504)). When a config that Styrmin
stores refers to another record:

- Accept a name in the request when users write configs by hand, because ids differ in each
  environment. Replace the name with the record's id before anything is saved or dispatched, and
  store the id only, in one canonical form (a lowercase UUID string).
- Look the name up after the request's own changes. Pass the records that the same write creates
  or renames, with their names after the write, so that a reference can name the record being
  created or its new name. A record found under a name that the same write changes is not a match.
- Refuse a reference that names no live record in the same scope, by name or by id, and save
  nothing. Give the full path of the reference in the config that was written, with the level as
  the prefix (`environment.config.…`, `deployment.config.…`, `component[<name>].config.…`), and the
  name or id it gives.
- When the config is used later, at reconcile, look up ids only. Refuse an id of a deleted
  (tombstoned) record and give its last name, because the stored config shows only the id.

Reference: `bind_deployment_references` and `resolve_deployment_reference` in
`services/scheduling/`. This is the rule of
[Name a Kubernetes object after its record's id, and find it by the id](#name-a-kubernetes-object-after-its-records-id-and-find-it-by-the-id)
applied to the configs that Styrmin stores. See
[ADR-075](../../adr/0075-deployment-references-stored-by-id.md).

### Check for an operation in progress against its unfinished rows

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

To refuse an operation because another one is running, look for an operation row that has not
finished, `PENDING` rows included. Do not use a state field of the target entity such as
`Deployment.status`. A state can outlive the operation that set it: a deployment left in
`RESTORING` by a restore whose flow died would otherwise refuse every later restore, and a clone's
counterpart deployment starts in `RESTORING` before its first restore
([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) decision 4).

Counting `PENDING` rows comes with a duty. A caller that commits a `PENDING` row and then fails to
start its flow run must settle that row itself, because no process picks up a `PENDING` row that
has no flow run, and it would refuse every later operation on the same target. Mark the row
`FAILED` with the reason, and move the target out of the state the operation set, the same way the
flow does when it fails. Reference: `settle_undispatched_restore` in `services/backup/service.py`,
called by the `createRestore` mutation and by the environment restore. The clone flow uses its own
copy, `_settle_undispatched_restore` in `workflows/templates/clone.py`.

### Expire an in-flight guard when the flow it protects stops waiting

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

A guard that refuses an action because a flow is still waiting on a row must stop refusing when
that flow stops waiting. Otherwise a row that never finishes, such as a constituent backup whose
flow run was never started and stays `PENDING`, blocks the action forever and leaves no way out.

- Bound the guard in time as well as in state, and let both the guard and the flow read one
  constant, so the two limits cannot drift apart. `CAPTURE_POLL_TIMEOUT_SECONDS` in
  `workflows/templates/clone.py` is defined as `CAPTURE_IN_FLIGHT_GUARD_SECONDS` from
  `services/backup/clone.py`.
- Log a line when the guard stops refusing because of the time limit
  (`clone_capture_guard_expired`).
- Make sure every guard of this kind leaves a way out that the operator can always reach, such as
  deleting the record ([ADR-055](../../adr/0055-environment-backup-parent-records.md) decision 6,
  [ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) decision 5).

### Never let work added to a status report fail the report

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

`report_deployment_statuses` in `services/deployment_status.py` writes the observed state of
every deployment in one transaction. Work added to it must not be able to roll that back:

- Run the work inside a savepoint (`async with uow.session.begin_nested():`), catch every
  exception, and log it with the deployment id.
- Run it only when the report changes something the work depends on. The cluster config fan-out
  hook runs only when a deployment's state changes.

Reference: `_record_operator_steps` and `_run_cluster_config_fanout_hook` in
`services/deployment_status.py`.

### Look up the flows of a hook only through `services/driver/hooks.py`

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

To find the registered flows that a hook runs, call `resolve_setup_hooks` or
`resolve_upgrade_hooks` in `services/driver/hooks.py`. Do not call
`PrefectManager.get_user_action_deployment_id` for a hook. That lookup returns `None` both when the
driver version declares no action and when the declared action has no registered flow, so code
that calls it directly skips the hook with no error, which is the defect of
[#372](https://github.com/opsmill/styrmin/issues/372).

The helpers read the declared actions (`uow.actions.list_by_driver_version`), look up only the
declared hook and mode pairs, and raise `ActionNotRegisteredError` when a declared pair has no
registered flow. The error names the driver version, the hook, the mode and the actions, and gives
the command that loads the driver again.

```python
upgrade = await resolve_upgrade_hooks(
    driver_version, application_name, uow=uow, prefect_manager=prefect_manager
)
if upgrade is None:
    ...  # no upgrade/core action declared: a plain update
```

The only other caller of `get_user_action_deployment_id` is `ensure_action_registrations` in
`services/applications.py`, which uses the same key to decide which actions a load registers
([ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)).

### Record a failure that a request check finds on a failed task with no flow run

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

When a request check finds that a change cannot run, and users must view why in the deployment's
task history, do not raise a GraphQL error and do not write the change:

1. Leave the record unchanged, so that the next identical request is not a no-op once the cause is
   fixed.
2. Save a task of the change's type with status `failed`, no flow run, and the error text as its
   message.
3. Record the step that could not run as failed, with `open_step` and `fail_step` from the step
   recorder.
4. Commit and return the task. Clients then report it as they report any failed task.

Run the check with the other validations, before any step that starts a flow run (see
[Validate before any step that starts a flow run](#validate-before-any-step-that-starts-a-flow-run)).
Reference: `_fail_upgrade_of_unregistered_action` in `services/deployment.py`, called from
`update_deployment_version` when the target driver version's upgrade action has no registered flow
([ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md), R-009).

## Repository Pattern

Repositories use abstract base classes with concrete SQLModel implementations:

```python
class ClusterRepository(BaseRepository[Cluster], ABC):
    @abstractmethod
    async def get_by_name(self, name: str) -> Cluster | None:
        raise NotImplementedError()

class SQLModelClusterRepository(BaseSQLModelRepository[Cluster], ClusterRepository):
    model_class = Cluster

    async def get_by_name(self, name: str) -> Cluster | None:
        statement = select(self.model_class).where(self.model_class.name == name)
        result = await self.session.exec(statement)
        return result.first()
```

Use `_eager_load_options()` for relationships to prevent N+1 queries.

<!-- Extracted from specs/011-deployment-backup-history on 2026-10-10 -->

### Break timestamp ties by id when a client picks "the latest"

When a list ordered by a timestamp is used to pick one row, such as "the newest completed backup"
for `styrminctl backups restore --last`, add `id` as a second sort key. Two rows can share a
timestamp, and without the second key the database can return them in any order, so the same
call can pick a different row each time.

```python
statement = statement.order_by(
    self.model_class.created_on.desc(),  # type: ignore[union-attr]
    self.model_class.id.desc(),  # type: ignore[union-attr]
)
```

`BackupRepository.get_by_instance_id` and `get_by_deployment_id` in
`backend/styrmin_backend/repository/backup.py` follow this rule.

## Error Handling

Custom exceptions inherit from `ServiceError` with `error_code` and `default_message`:

```python
class DeploymentNotFoundError(ServiceError):
    error_code = "NOT_FOUND"
    default_message = "Deployment not found"
```

Raise with exception chaining:

```python
raise InvalidContextError() from e
```

### Check the real path of each file you read from a repository a user controls

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

dulwich checks out symlinks as symlinks, so a cloned repository can hold a file that points at a
file of the Styrmin server, such as `driver.styrmin.yml -> /etc/hostname`. Before you read a file
from a clone, resolve its real path and refuse it when it is outside the folder it must stay in:
the clone root for a folder, the driver directory for a driver file. Run the check after the clone
and before the first read.

```python
resolved = resolve_inside(clone, driver_directory or ".")
if resolved is None:
    raise DriverLoadingError("... leads outside the repository ...")
for name in (spec_file, values_template, actions_code_file):
    if resolve_inside(resolved, name) is None:
        raise DriverLoadingError("... is a symlink to a path outside ...")
    if error := _follow_error(resolved / name):
        raise unreadable(name, error)
```

- Use `resolve_inside` (`services/driver/driver_directory.py`). It follows symlinks at every
  depth, and a dangling symlink resolves to its target path.
- Also check that each path can be followed. In Python 3.14, `Path.resolve()` does not raise on a
  symlink loop, so call `stat()` and report the `OSError` (`_follow_error` in
  `services/driver/provider.py`).
- Accept a symlink whose target is inside the allowed folder: authors may rely on such links.
- Name the path relative to the repository in the message, never the temporary clone path or the
  target of the symlink.
- Do not apply this check to a local path that the admin gives on the server. A Kubernetes
  ConfigMap or Secret volume exposes every file as a symlink.

Reference: `GitDriverProvider._check_driver_directory` in `services/driver/provider.py`
([ADR-079](../../adr/0079-driver-actions-import-only-from-their-driver-directory.md)).

### Retiring a driver-facing template surface

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

When a template filter or function that drivers call is removed, keep it registered in
`get_jinja_environment()` as a stub that raises a typed `ServiceError`. Do not unregister it:
Jinja's generic "no filter named …" error tells the user nothing about the fix.

```python
def component_env_vars(*args: object, **kwargs: object) -> NoReturn:  # noqa: ARG001
    raise RetiredTemplateFilterError
```

The error carries an `error_code`, the retired name and a `migration_guide` URL in its
metadata, and a `default_message` that tells **both** audiences what to do (users: upgrade the
deployment's driver version; driver authors: what replaces the call) and includes the URL. The
typed code does not survive the StyrminDeployment CR → operator hop, so the message string must
be enough on its own.

<!-- Extracted from specs/022-post-render-container-overrides on 2026-10-15 -->

- Also reject the retired filter when a driver version is loaded, so that a new driver version
  that calls it fails at the API instead of at the next render. `JinjaTemplateValidator` walks the
  `Filter` nodes of the parsed template and raises the same typed error with the line of the call.
  Keep the render-time stub for driver versions loaded before the load check existed.
- When you remove a key from a driver format model that forbids unknown keys
  (`extra="forbid"`), add a `before` model validator that raises a `PydanticCustomError` naming
  the removed key and linking the migration guide. The generic `extra_forbidden` error names
  neither. Reference: `Specification.reject_removed_container_overrides` in
  `services/driver/models/resources/driver.py`.

### Validate config writes by delta when a driver change can strand stored values

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

When a driver upgrade can make stored deployment config invalid (for example component env vars
on a component that loses its component container), reject only what the write **adds or
changes**. Accept unchanged re-submissions and removals:

| Submitted vs stored | Result |
|---|---|
| identical | accepted |
| subset (keys removed) | accepted |
| new key or changed value | typed `ServiceError` |

The frontend and `styrminctl apply` submit full configs, so an absolute check blocks every
unrelated edit on that deployment and blocks removing the stranded values. Validate against the
driver version the deployment is pinned to **after** the write, not the pre-switch version. Keep
the stranded values and expose them through a read flag (e.g. `ComponentEnvVars.isApplicable`)
rather than deleting them. Reference: `services/deployment.py::_validate_component_container_targets`.

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

The same rule applies to checks that depend on the deployment's current state, such as an image
reference that must stay valid once `{{ app.version }}` is replaced by the application version.
On write, check only new or changed entries: an unchanged stored entry was checked when it was
written. On a version change, re-check the stored entries that apply under the target driver
version before any task starts, so the change is rejected instead of failing at render. Checks for
an unknown target (a component the driver does not declare) still cover every submitted entry, as
for env vars and container overrides. References:
`services/image_overrides/validator.py::prevalidate_image_overrides` (`stored_config`) and
`services/deployment.py::_validate_image_overrides_for_version`.

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

Two kinds of check do not follow the delta rule in the same way:

- **A rule that the bound driver version sets on the component checks unchanged stored values
  too.** `SINGLETON_REPLICA_OVERRIDE` rejects a stored override above 1 on a component that the
  driver version bound after the write marks `singleton: true`, also when the write sends it
  again unchanged. The stored value breaks the rule of the driver version that the deployment will
  be bound to, so accepting it would render a count that the driver forbids. A version change to
  such a driver version is rejected until the same request lowers or clears the override.
- **A limit from a server setting checks only added or changed values.** `REPLICA_COUNT_ABOVE_MAXIMUM`
  (`STYRMIN_MAX_REPLICA_COUNT`) accepts a stored count sent again unchanged, so an operator who
  lowers the setting does not block every other edit of the deployments above it. Put such a check
  in the service layer, not in a context model validator, because the agent parses stored contexts
  without the server's settings. The context model checks only limits that hold everywhere, such as
  the Kubernetes `int32` range.

Reference: `services/replicas/validator.py::validate_replica_overrides`.

<!-- Extracted from specs/016-backup-retention-ttl on 2026-08-04 -->

### Never add new logic inside a swallow-and-proceed block

When an existing block catches broadly and continues with a fallback —

```python
try:
    bsl = await resolve_storage_location(...)
except Exception as exc:                    # noqa: BLE001
    logger.warning("BSL resolution failed: {}", exc)
    bsl = None                              # proceed with the default
```

— **do not put a new resolution step inside it**, however convenient the already-loaded
rows are. Its failure would be absorbed by a warning written about something else, and
the new step's fallback would be applied invisibly. That is how a configured policy
silently becomes a hard-coded default.

Give the new work its own step with its own handling, so its fallback is logged as its
own event, naming the value used and where it came from:

```python
ttl, ttl_source = resolve_backup_ttl(deployment.config, env.config, cluster.config)
logger.info("Resolved backup TTL {ttl} from {scope} scope for backup {id}", ...)
```

The rule generalises: **a fallback is only acceptable when it is observable.** If code
substitutes a default, the log line must say so and say why — otherwise the silent path
is indistinguishable from the configured one during an incident.

<!-- Extracted from specs/011-env-config-input-hardening on 2026-05-10 -->

### Validator entry-point type guards

Public validators MUST type-check their inputs at the **entry point**,
before any encoding, size computation, or other downstream work. Non-string
(or otherwise wrong-typed) inputs surface as a typed `ServiceError` with
`error_code` + `error_metadata` — never as a generic `AttributeError` /
`TypeError` raised by a downstream `.encode("utf-8")` or similar:

```python
def validate_env_var_value(name: str, value: str, scope: str | None = None) -> None:
    if not isinstance(value, str):
        raise InvalidEnvVarValueError(
            name=name,
            value_type=type(value).__name__,
            scope=scope,
        )
    # ... existing 64 KiB cap check, encoding, etc. ...
```

The same guard belongs in any dict-level helper that callers can hit
without passing through the per-value validator (defence in depth — see
spec 011/US3 for the regression that motivated the rule).

`bool` is a subclass of `int`, not `str` — `isinstance(value, str)`
correctly rejects `True`/`False`. Coercing wrong-typed values via `str(value)`
is **forbidden**: an operator who passes `1` may have meant `"1"` or may
have intended an integer; a typed error tells them which.

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

**Integers.** `bool` *is* a subclass of `int`, and Pydantic's lax mode turns `"3"` and `3.0`
into `3`. To reject them with a typed error, check the value in a `mode="before"` validator,
before Pydantic converts it:

```python
def _check_replica_count(value: Any, component_name: str | None) -> Any:
    if value is None or (
        isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_REPLICA_COUNT
    ):
        return value
    raise InvalidReplicaCountError(component_name=component_name, requested_replicas=value)
```

- In a model that gives a load error with the field path instead of a typed `ServiceError` (the
  driver specification models), use `StrictInt` and `StrictBool` with `Field(ge=..., le=...)`.
- A client that builds a Pydantic input from user JSON (the SDK and `styrminctl`) runs the same
  check before `model_validate`, because the generated input model would convert `true` to `1`
  before the server sees it. Reference: `styrmin_sdk.resources.deployments.check_replica_counts`.
- Bound an integer that ends in a Kubernetes field by the field's type (`int32` for
  `spec.replicas`: `MAX_REPLICA_COUNT = 2_147_483_647`), so a value that Kubernetes would reject
  fails at write time, not when helm-controller applies the release.
- To compare a stored value with a default, compare the type as well:
  `type(value) is type(default) and value == default`. `1 == True` and `1 == 1.0` are true in
  Python. Reference: `services/parameters/retired.py::drop_retired_parameters`.

### Validate URLs that a browser loads or opens

<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

When a value from a user or a driver file becomes a URL that the browser loads or opens, such as
the driver logo or a driver link, validate it before you store it:

- Parse it with Pydantic's `HttpUrl`, then check the scheme against an explicit list. An image
  must be `https`, because browsers block an `http` image on a page served over `https` as mixed
  content. A link may be `http` or `https`. The parse and the scheme check keep `javascript:` and
  `data:` values away from the browser.
- Reject a URL that contains a username or a password.
- Never repeat such a value in an error or a warning message: the message names the field and
  says that it must not contain a username or a password.

Reference: `_url_problem` in `services/driver/models/resources/driver.py`. It is private to that
module; move it to a shared module when a second caller needs it.

### Schema-walking propagation tests

Every Strawberry input that mirrors a Pydantic config model MUST have a
runtime test that introspects both sides and asserts every Pydantic field
has a corresponding Strawberry input field. The test fails fast with the
missing field name when schema drift introduces a Pydantic field without
its input mirror. See [ADR-014](../../adr/0014-schema-walking-input-propagation-tests.md)
for the full pattern and the `EnvironmentConfig` ↔ `UpdateEnvironmentInput`
exemplar at `backend/tests/functional/graphql/test_environment_update_propagation.py`.

The schema walk is fail-on-drift; the existing per-field round-trip tests
are fail-on-regression. Both stay; neither subsumes the other.

### Per-target failure isolation in fanout writes

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

When a write fans out to many targets, for example a config update that redeploys every
deployment it changes, one target that fails must not stop the others or undo their writes:

- Wrap each per-target write in a savepoint inside the `try`, catch every exception, count and log
  the failure with the target's id, and continue with the next target. The redeploy path opens
  nested `async with uow` blocks of its own. When one of them fails while a savepoint is open,
  `SqlModelUnitOfWork.__aexit__` rolls back only that savepoint; without a savepoint it rolls back
  the whole transaction, including the targets already written.
- Never call `uow.commit()` inside a savepoint. In SQLAlchemy 2.0 it commits the outer
  transaction, so `SqlModelUnitOfWork.commit()` raises there.
- Commit after a limited set of targets, not once for the whole fan-out. `apply_state` starts the
  flow run before the caller commits, and the flow waits only `TASK_ROW_WAIT_SECONDS` (10 seconds,
  `services/steps/internal_flows.py`) for its task row. The cluster config fan-out commits once per
  environment.
- Copy the values you need after a failure before you roll back. A rollback expires the ORM rows
  that were loaded in the transaction (`_EnvironmentRef` in `services/cluster_config_fanout.py`).
- Return the failures to the caller when the mutation has a result type for them, as
  `updateCluster` does with `failedToStart` and `failedEnvironments`. A redeploy that could not
  start creates no task, so it does not appear in the deployment timeline.

```python
try:
    async with uow.session.begin_nested():
        task = await redeploy_for_environment_update(deployment, uow)
except Exception:  # noqa: BLE001 — one deployment must not stop the others
    result.dispatch_failed += 1
    logger.exception("cluster_config_fanout_dispatch_error deployment_id={}", deployment.id)
    return
```

When a change reaches deployments through more than one config level, decide which deployments
to redeploy by comparing each deployment's resolved config with the one its active instance was
rendered with, not by comparing one level's stored config
([ADR-066](../../adr/0066-cluster-config-fanout.md) decision 1).

Reference: `services/cluster_config_fanout.py` and
[ADR-066](../../adr/0066-cluster-config-fanout.md) decision 6. `update_environment` in
`services/environments.py` predates the savepoint rule: its loop catches the error of each
redeploy without a savepoint.

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

The redeploy loop of `restore_environment_backup` in `services/backup/environment.py` follows the
rule. A restore puts back the captured environment config without checking it, so a redeploy
refused because an affinity term names a deployment deleted since the backup does not drop the
other redeploys ([ADR-075](../../adr/0075-deployment-references-stored-by-id.md)).

<!-- Extracted from specs/011-admin-user-group-mgmt on 2026-05-13 -->

### Admin & authorization mutations

Rules for any mutation that touches user/group state, admin-conferring rows, or session lifecycle. See [`knowledge/backend/services.md`](../../knowledge/backend/services.md) → "Authorization helpers" for the helper modules and [`knowledge/backend/api.md`](../../knowledge/backend/api.md) → "Admin user/group surface" for the wire contract.

- New mutations that change admin-conferring state (role assignment, group membership, active flag, hard-delete) MUST attach `PermissionExtension([RequiresRole(Role.ADMIN)])`. Do not invent ad-hoc role checks in the resolver body.
- Any operation that could violate the last-admin invariant MUST call through `auth/admin_guards` inside its own transaction, with the admin-conferring rows locked via `SELECT ... FOR UPDATE`. Inline rule re-implementations are forbidden — the four-action matrix (`DEACTIVATE` / `DELETE` / `DEMOTE` / `REMOVE_FROM_ADMIN_GROUP`) lives in one place.
- Membership replacements MUST go through `auth/membership.replace_user_groups` / `replace_group_members`. Do not issue a full `DELETE all → INSERT all` pattern; diff-and-mutate is the only acceptable shape (zero statements on no-change is required).
- Mutations that invalidate sessions (`resetUserPassword`, `updateUser(active=False)`, role downgrade where the new role removes admin) MUST share a single transaction with the originating change. The write order is: mutate the user row → flush (no commit) → delete affected sessions → commit. A failure in the session delete MUST roll back the user-row change.
- Admin mutations MUST emit one Loguru audit line on success, after the transaction commits, in the shape:

  ```python
  logger.info(
      "admin_mutation actor={} action={} target={} changed_fields={}",
      actor_id, action_name, target_id, comma_separated_field_names,
  )
  ```

  Field **names only** — never values. Emit from the service function so it only fires on commit, never from the resolver.
- Password-bearing GraphQL variables MUST be added to the `MASKED_VARIABLE_NAMES` frozenset in `api/logging/mask.py`. Per-mutation ad-hoc masking is forbidden — every password field on the schema goes through that one allow-list. Adding a new password field is a one-line PR change that triggers code review on the import site.

<!-- Extracted from specs/019-task-steps on 2026-10-08 -->

- A mutation that only Styrmin's own flows and driver actions may call, such as `recordStep`, MUST attach `PermissionExtension([RequiresRole(Role.READ_WRITE), IsActionsServiceAccount()])` and MUST NOT be on the unauthenticated allow-list (`api/auth/allowlist.py`). The flows call it with the action token of the built-in `styrmin-actions` user ([ADR-059](../../adr/0059-driver-action-api-tokens.md)); every other user, admins included, gets `FORBIDDEN`, so no person can change what the flows recorded. `IsActionsServiceAccount`'s error message names step recording, so give it a general message when a second mutation uses it.

## Database Models (SQLModel)

- Inherit from `StyrminModel` (provides `id`, `created_on`, `updated_on`)
- Use `table=True` for database-backed models
- JSON columns: `Field(sa_column=Column(JSON))`
- Relationships: `Relationship(back_populates="...")`

### Soft-delete and partial unique indexes

<!-- Extracted from specs/008-deployment-deletion on 2026-05-02 -->

When a column makes a row "tombstoned" (e.g., `deleted_at: datetime | None` set after soft-delete), unique constraints involving that table MUST be expressed as **partial unique indexes** predicated on `deleted_at IS NULL` — not as plain `Field(unique=True)` or `UniqueConstraint(...)`. Otherwise tombstoned rows continue to occupy the name slot and prevent operators from reusing names after deletion.

The pattern uses SQLAlchemy's `Index` in `__table_args__` so the constraint is dialect-portable (Postgres in production, SQLite in unit tests):

```python
from sqlalchemy import Index, text

class Deployment(StyrminModel, table=True):
    __table_args__ = (
        Index(
            "uq_deployment_env_name_active",
            "environment_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    name: str  # do NOT pass unique=True — the partial index above is the gate
    environment_id: UUID = Field(foreign_key="environment.id")
    deleted_at: datetime | None = Field(default=None, index=True)
```

Companion conventions for the surrounding code:

- The DB-level partial index is the **authoritative race-free guard**. Service-layer name-conflict checks are best-effort pre-flights that produce a friendly typed error; they do not replace the index. Wrap the eventual commit and map `sqlalchemy.exc.IntegrityError` to a typed `*ConflictError` so concurrent callers see consistent semantics.
- Repository helpers that resolve names (`get_by_name`, `find_names_with_prefix`) MUST take the relevant scope key (e.g., `environment_id`) as a required parameter and accept an optional `include_deleted: bool = False`. Default behaviour is "active rows in this scope only".
- The migration that introduces the partial index SHOULD include a defensive pre-flight: refuse to apply if any pair of currently-active rows already collide on the index columns. This catches corrupt input before the index is created. See migration `c9d0e1f2a3b4_deployment_name_scoped_uniqueness` for the worked pattern.

Worked example: `Deployment.name` (ADR-011). Rationale: ADR-008 (soft-delete tombstoning).

<!-- Extracted from specs/016-backup-retention-ttl on 2026-08-04 -->

### Plain `JSON` columns are not change-tracked — reassign, never mutate

A `Field(sa_column=Column(JSON))` has **no `MutableDict` wrapper**, so SQLAlchemy
does not observe in-place mutation of the dict or list it holds. `obj.col[k] = v`
and `obj.col.update(...)` leave the attribute clean, and the change is **silently
dropped at commit** — no error, no warning, no write.

Always **reassign the attribute**, which is what marks it dirty:

```python
# Wrong — silently does not persist
backup.metadata_["ttl"] = ttl

# Right — reassignment marks the attribute dirty
backup.metadata_ = {**(backup.metadata_ or {}), **metadata_updates}
```

Two details the worked example (`services/backup/service.py::update_backup_status`)
gets right and that are easy to miss:

- **Merge, do not replace.** The column is shared by more than one writer
  (`Backup.metadata_` carries `timeout` from one path and `ttl` / `ttl_source` /
  `expires_at` from another). Spreading the existing dict preserves keys you do not
  own.
- **Handle `None`.** Pre-existing rows have a null column, so `or {}` is required —
  not defensive noise.

Prefer a **typed** payload over a bare `dict` for the update keys (a `TypedDict` such
as `BackupMetadata`) so a key no reader looks up — a differently-spelled variant of a
field, say — fails type checking rather than persisting into a blob nothing reads.

**Test through a DB round-trip, not the in-memory object.** A propagation test that
asserts against the same instance it just mutated passes even when the write was
dropped. Read back through a fresh session or `UnitOfWork` so a change-tracking
regression actually fails:

```python
async with UnitOfWork() as uow:            # fresh session, not the writer's
    reloaded = await uow.backups.get(backup_id)
    assert reloaded.metadata_["ttl"] == "2160h"
```

### Merge by key when you update entries of a JSON list that another writer created

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

When code updates entries of a JSON list column that another writer created, write its entries
back into the stored list, matched by a key. Do not replace the list with the entries the code
could read. An entry it could not read, or that a newer writer added, would otherwise disappear,
and a status calculated from the list would lose it.

- Match by the entry's identifier, such as `deployment_id`.
- Keep every stored entry that the code did not update exactly as it was.
- Append the code's entries that have no stored counterpart.

Reference: `_read_results` and `_merge_results` in `workflows/templates/clone.py`, which update
`EnvironmentClone.deployment_results`.

### Normalize a stored JSON config by walking the dict, not by a model round-trip

<!-- Extracted from specs/027-deployment-reference-by-id on 2026-10-17 -->

When a write rewrites some values of a JSON config before it stores it, such as names replaced
with ids, change those keys in a copy of the dict and keep every other key as the user wrote it.
Do not validate the dict into its Pydantic model, change the model and dump it back. The dump also
changes keys the write did not touch (defaults, aliases, value forms), so a config written back
exactly as it was read would differ from the stored dict. The no-op checks compare the stored
dicts and the instance contexts built from them
([ADR-054](../../adr/0054-backend-authoritative-noop-detection.md)), so the write would start a
reconcile that changes nothing, and an older stored dict would change its form at its next write.

- Copy the dict (`copy.deepcopy`) and change only the keys you normalize.
- Give each normalized value exactly one stored form for one target, so that a request with the
  name and a request with the id store the same dict.
- Apply the same function on every write path that stores the config, so every stored config is
  in that form when the no-op checks compare it.

Reference: `bind_deployment_references` in `services/scheduling/references.py`.

## Domain Models (Pydantic)

- Use `BaseModel` for domain objects
- Use `PrivateAttr` for internal state
- Provide `@classmethod create()` factory methods
- Use `@property` for computed fields

### Add a typed field to a stored model without changing its dump at the default

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

When a Pydantic model is stored as JSON, written into a custom resource, or compared with a stored
copy, a new field must not appear in `model_dump()` while it holds its default. Leave the key out
with a `model_serializer(mode="wrap")`:

```python
@model_serializer(mode="wrap")
def _omit_replica_defaults(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
    data = handler(self)
    if data.get("replicas", 0) is None:
        del data["replicas"]
    if data.get("singleton") is False:
        del data["singleton"]
    return data
```

Without it, every dump gains `replicas: null, singleton: false` after the upgrade. The context
written into the `StyrminDeployment` resource then differs from the stored instance only by these
keys, so the first update of every deployment starts a HelmRelease upgrade that changes nothing.
Add a unit test that a model without the new keys dumps to the same dict as before the change.

Reference: `ReplicaDeclaration` in `context/models/components.py`;
`backend/tests/unit/services/driver/test_component_replicas.py::test_dump_without_the_keys_equals_the_dump_before_the_change`.

### Check driver data strictly at load, and drop only the invalid key on read

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

A typed field on the driver specification model rejects a bad value when the driver version is
loaded: the load fails with a `DriverLoadingError` that names the field path, and nothing is
stored. Rows stored before the field was typed may hold a value that the new type rejects. A read
of such a row must not fail the deployment:

- Parse a stored declaration so that an invalid key reads as unset. Drop only that key, and log a
  warning that names the key, its value, the component and the driver version.
- When two keys conflict, decide in a fixed order which one is dropped, and choose the order that
  gives the safer result. `singleton: true` with `replicas: 3` drops `replicas`, so the component
  runs one pod.
- A check or a read field that needs only some keys parses only those keys, so a problem in
  another key does not fail it.
- Never use the tolerant parser on the load path. New driver versions are always checked
  strictly.

References: `split_replica_keys`, `parse_stored_replica_declaration` and
`validate_ignoring_invalid_replica_keys` in `context/models/components.py`. For JSON entries that a
GraphQL type projects, see
[Show one unreadable JSON entry as degraded](#show-one-unreadable-json-entry-as-degraded-instead-of-failing-the-query).

## Rendering Kubernetes manifests

### No runtime defaults for optional emitted annotations

For optional operator-config fields that drive an emitted Kubernetes annotation, label, or similar wire artifact, the rendering site MUST emit the key only when the resolved value is not `None`:

```python
if context.instance.config.<field> is not None:
    annotations["<annotation-key>"] = context.instance.config.<field>
```

No defaulting at render time, no defaulting at Pydantic-model time, no defaulting in the builder. `None` propagates from the Pydantic field through `ResolvedConfig` to the renderer, and the renderer treats `None` as "skip this annotation". The downstream controller (external-dns, Traefik, …) applies its own default for absent annotations — the platform does not claim authority over defaults it has no business setting.

**Why:** always-emit-with-a-default rewrites the rendered manifest for every existing deployment on upgrade — even ones that never touched the knob. Code review should flag any `annotations["..."] = ... or "default"` shape. Chart-values templates honour the same rule with `{% if … %}` guards.

### Per-component pod overrides go through post-render into the component container

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

A new per-component override of the pod spec (env var, image, command and args overrides today) is a
Kustomize post-render patch, not a Helm values key. Helm replaces lists, so writing a chart's
list-shaped key from the values template drops every entry the chart ships.

- Target the component's declared **component container** (`components.<name>.container`) by
  `name` in a strategic-merge patch. kyaml merges containers and `env` entries by `name`, so
  chart entries the patch does not name survive.
- Target only `Deployment` and `StatefulSet`, narrowed by the component's identifier
  `labelSelector`. Chart Jobs often share the component label.
- Skip components without a component container. Never fall back to `containers[0]`.
- Append the patches after every patch that addresses a container by index (e.g. the
  scheduling `ResourcesPatch` on `containers/0`): a strategic merge moves the named container
  to index 0.
- Follow the strategic merge with the JSON6902 guard (`ComponentContainerPatch`). A merge that
  names a missing container adds it; the guard's `remove …/image` fails the render instead, and
  its key names the component and the container. Never add a container.
- Regenerate the patches from the resolved context on every render, so removing an override
  removes its entry without a marker.
- Test the outcome (entries present, chart entries kept, values replaced), not the exact
  order: kyaml's ordering is implementation behaviour.

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

- Build JSON6902 patches as Python lists and render them with `yaml.dump`, never with string
  formatting. A user-controlled value (an image reference, a component name) then cannot change
  the patch structure.
- JSON-pointer-escape every user-controlled name used in a patch path: `~` to `~0` first, then
  `/` to `~1` (RFC 6901). Component names are free-form strings; unescaped, a `/` splits the path.

<!-- Extracted from specs/022-post-render-container-overrides on 2026-10-15 -->

- The `yaml.dump` rule also applies to strategic-merge patches. `ContainerMergePatch` carries
  user strings in `env`, `command` and `args`; a value that contains a newline and
  `- op: remove` must stay one string.
- A strategic merge replaces the whole of a list that has no `patchMergeKey` in the Kubernetes
  schema (`command`, `args`). Write such a field into the patch only when an override is set, so
  a field without an override keeps the value the chart renders. Do not write an empty list or
  `null` as a "use the chart's value" marker.

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

- A per-component override of the workload spec, such as the replica count, is also a
  post-render patch. It targets the `Deployment` or `StatefulSet` by kind and label selector, not
  a container, so it needs no component container.
- Write each workload field from exactly one patch per kind per component. Two patches that write
  the same scalar path (`/spec/replicas`) give a result that depends on the order of the kustomize
  list, which is kyaml behaviour and not a documented contract. When two features set the same
  field, merge them into one builder: `build_component_replica_patches` writes 0 for a stopped
  component and the resolved count for a running one.
- Use a JSON6902 `add` for a scalar that the chart may or may not render. RFC 6902 `add` replaces
  an existing member and creates a missing one.
- Emit no patch when no source sets the value, so the chart's value applies. Never patch a
  fallback value such as `1`: it would change every chart that renders another value.

See [ADR-057](../../adr/0057-post-render-component-overrides.md),
[ADR-058](../../adr/0058-image-overrides-and-component-container-guard.md),
[ADR-069](../../adr/0069-container-command-args-by-post-render.md),
[ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md),
`services/component_container/patch_builder.py` and `services/replicas/patch_builder.py`.

### Remove a field that the chart may not render with a strategic merge `null`

<!-- Extracted from specs/024-ingress-class-post-render on 2026-10-16 -->

To remove a field from a rendered resource in a post-render patch, write a strategic merge patch
that sets the field to `null`, not a JSON6902 `remove` operation.

- A JSON6902 `remove` fails the whole render when the field is absent. Kustomize v5.7.1 exits with
  `error in remove for path: '/spec/ingressClassName': Unable to remove nonexistent key:
  ingressClassName: missing value`. Use `remove` only when the render should fail on an absent
  field, as the `ComponentContainerPatch` guard does.
- A strategic merge patch that sets the field to `null` deletes the field when it is present and
  leaves the resource unchanged when it is absent. Example: `IngressClassNameRemovalPatch` in
  `agent/service/kubernetes/resources/blocks/patches.py`.
- With a `target`, Kustomize applies the strategic merge patch to every matching resource and uses
  each resource's own group and version: a patch written for `networking.k8s.io/v1` also applies
  to a `networking.k8s.io/v1beta1` Ingress. The patch needs a `metadata.name`, but Kustomize does
  not match on it when a `target` is set.
- To set a value whatever the chart rendered, use a JSON6902 `add`. It replaces an existing value
  (RFC 6902, section 4.1), and Kustomize creates `metadata.annotations` when the resource has none.
- Leave the patch list of a case that the change does not affect as it is. A change to
  `spec.postRenderers` makes helm-controller upgrade every release that gets it
  ([`operator.md`](../../knowledge/agent/operator.md#fluxcd-controllers), "Post-renderers
  digest").

See [ADR-071](../../adr/0071-ingress-class-set-by-post-render.md) §1.

### Add keys to a map that the resource may not have with a strategic merge

<!-- Extracted from specs/025-helm-v4-defaults on 2026-10-16 -->

When a post-render patch adds keys to a map, such as `metadata.labels`, and its target can match a
resource that does not have that map, write a strategic merge patch, not a JSON6902 `add` per key.

- A JSON6902 `add` needs the parent of its path to exist. On a resource without
  `metadata.labels`, `add /metadata/labels/<key>` fails the whole render. Kustomize v5.7.1 exits
  with `add operation does not apply: doc is missing path:
  "/metadata/labels/styrmin~1deployment-id": missing value`.
- A strategic merge patch creates the map when it is missing and keeps the keys the resource
  has. Example: `MetadataLabelsMergePatch` in `agent/service/kubernetes/resources/blocks/patches.py`,
  which `build_target_for_label_patches` uses for every resource (`Target(name=".*")`).
- Keep a JSON6902 `add` only where every resource the target matches has the parent map, for
  example `TemplateLabelPatch` on the pod templates of `Deployment` and `StatefulSet` resources.
- `metadata.annotations` behaves differently: in a check with kustomize v5.7.1, a JSON6902 `add`
  under `/metadata/annotations/` succeeded on an `Ingress` without annotations. Why kustomize
  treats annotations and labels differently was not checked, so do not rely on it for other maps.

See [ADR-072](../../adr/0072-helm-v4-defaults-releases-keep-apply-method.md) §5.

### Post-render patches also reach Helm hooks

<!-- Extracted from specs/025-helm-v4-defaults on 2026-10-16 -->

helm-controller runs with `postRenderStrategy: combined`, so every patch in `spec.postRenderers`
applies to each Helm hook that its target matches, as it does to the chart's templates.

- Write each patch so that it works on any resource its target can match, including a Helm hook
  that lacks the labels, annotations or containers that the chart's templates have. A patch that
  fails on one resource fails the install or upgrade of the whole release.
- A Helm hook `Job` that carries a component's identifier label receives that component's
  scheduling patches. Keep that in mind when you widen or narrow a target.
- When you add a post-render patch, add it to the table in
  [Post-render patches and the Helm hooks they reach](../../knowledge/agent/overview.md#post-render-patches-and-the-helm-hooks-they-reach).

See [ADR-072](../../adr/0072-helm-v4-defaults-releases-keep-apply-method.md) §3.

### Custom-resource updates: replace the spec keys you write, merge the rest

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-03 -->

For a custom resource whose `spec` Styrmin rebuilds from context on every reconcile, apply it
with `upsert_custom_resource(..., replace_spec_keys_on_update=True)`. Styrmin owns each
top-level spec key it writes; everything else merges.

- Do not rely on JSON merge-patch alone: it keeps nested keys the new body omits, so a cleared
  value stays live (a stale env var under `spec.values` or `spec.context`).
- Do not replace the whole `spec`: that drops keys Styrmin never writes, such as `spec.suspend`
  from `flux suspend hr` or the server-owned `spec.deletionRequested` on the
  StyrminDeployment CR.
- Never touch metadata wholesale: labels and annotations are added key by key so Flux's
  finalizer and kopf's annotations survive.

See [ADR-057](../../adr/0057-post-render-component-overrides.md) §6 and
[`dev/knowledge/agent/operator.md`](../../knowledge/agent/operator.md#apply-semantics).

### Read the Helm release name from the active instance; never compute it from the deployment id

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

A deployment's Helm release name is chosen once and never changes, because renaming it would make
Flux install a second release over objects that Helm already owns. Code that needs the release name
reads the `release_reference` that the active instance's context carries. Code that creates a
context gets it from `_resolve_release_reference` in `services/context.py`, which returns, in
order:

1. an explicit release name, which the environment clone passes so that a counterpart deployment
   keeps the source deployment's release;
2. the release name the active instance already carries;
3. `styrmin-<deployment id>`, for the first instance of an ordinary deployment.

Do not build `styrmin-<deployment id>` and use it as the release name. That string is the
deployment's namespace and the name of its StyrminDeployment CR. It equals the release name for
most deployments but not for a counterpart deployment
([ADR-056](../../adr/0056-environment-clone-record-and-cross-target-restore.md) decision 3,
`operator/crd/builder.py`).

### Name a Kubernetes object after its record's id, and find it by the id

A user can rename a backup storage location, a deployment, a group and other records. A cluster
object named after such a name stays under the old name after a rename, so code that rebuilds the
name from the record misses it ([#488](https://github.com/opsmill/styrmin/issues/488)). For every
object that Styrmin creates for a record:

- Build its name from the record's id, as `get_kubernetes_reference` does for a deployment
  (`styrmin-<deployment id>`) and `velero_bsl_name` does for a backup storage location
  (`styrmin-bsl-<location id>`).
- Put the id on the object as a label, such as `styrmin.io/bsl-id`.
- To update or delete the object, find it by that label or by a name built only from the id, never
  by a name built from a field a user can change. Select by the label when objects that an earlier
  version named differently can still exist, because a label selector also finds them.
- When the name is what the user asked for, such as a service-name override, which names the
  Service, keep the name and select by the id label to update or delete the object.

Do not pass a record's name to a flow that acts on cluster objects. Pass the id.

See [ADR-073](../../adr/0073-kubernetes-objects-named-and-found-by-record-id.md).

### Delete the earlier Job of a name built from an id only when it has ended and Styrmin created it

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

A Job named only from a record's id has the same name on every run, so the second run's create
fails while the first run's Job exists. Before you create such a Job, read the Job that holds the
name and:

- Delete it only when Styrmin created it for this purpose. Check a label that Styrmin sets on it,
  such as `styrmin.io/action-job=true`. Otherwise raise a typed error that gives the
  `kubectl delete job` command.
- Delete it only when it has ended: it has the `Complete` or the `Failed` condition with status
  `True`. A Job with a failed pod and no `Failed` condition can still start a pod. While the Job
  runs, raise a typed error that tells the user to wait for the Job to end and request the change
  again. Another change of the same record may be running it.
- Delete it with the `Foreground` propagation policy and a `uid` precondition, then wait until a
  read answers 404 or finds another `uid`. Kubernetes then removes the Job only after its pods,
  and the delete never removes a Job that another writer created after the read.
- Record a line that names the deleted Job and how it ended, because the wait can take time.

Reference: `_delete_earlier_job` in `agent/service/kubernetes/primitives.py`, which `run_job` calls
before it creates the Job of `execute_commands`
([ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md),
"The Job of `execute_commands`").

### Delete an object that another writer can replace with a `resourceVersion` precondition

<!-- Extracted from specs/026-delete-service-aliases on 2026-10-17 -->

When code deletes an object by name, and another flow or the operator can write an object with the
same name in between, pass the `resourceVersion` that the code read or wrote to the delete:

- Take it from the listing that selected the object, or from the object that your create or
  replace returned.
- Treat the 409 that a changed object returns as "not deleted, and not an error". Log it and go on.
- Treat a 404 the same way: the object is already gone.

Without the precondition, the delete removes whatever holds the name now, such as another
deployment's `ClusterIP` Service that replaced a service alias, or an alias that another flow wrote
again. Three deletes use this rule today: the alias flow's deletion of stale aliases (#506) and of
the aliases it wrote for a deleted deployment, and the operator's teardown of a deployment's aliases
(`delete_service(name, namespace, resource_version)` in `agent/service/kubernetes/primitives.py`).

### Never create another deployment's namespace

<!-- Extracted from specs/026-delete-service-aliases on 2026-10-17 -->

A flow creates only its own deployment's namespace, in `_write_styrmin_deployment`, before it
writes the StyrminDeployment. Code that writes into the namespace of another deployment:

- Writes into the namespace only when it exists. Do not call `apply_namespace` or
  `apply_kubernetes_namespace` on it: a namespace that is missing may belong to a deleted
  deployment, and creating it again brings that deployment's namespace back.
- Skips the object, and logs why, when the write returns 404 (the namespace is gone) or 403
  because the namespace is terminating. `is_namespace_gone_error` in
  `agent/service/kubernetes/primitives.py` tells these apart from other errors: a 403 counts only
  with the `NamespaceTerminating` cause or the `NamespaceLifecycle` message.
- Lets every other error fail the step. An RBAC 403 must stay visible.

See [ADR-077](../../adr/0077-alias-flow-reads-deletion-state-at-write-time.md).

### Delete objects outside a deployment's namespace only for a requested deletion

<!-- Extracted from specs/026-delete-service-aliases on 2026-10-17 -->

The operator's delete handler also runs when a deployment keeps running:

- A restore deletes the deployment's namespace, which deletes its StyrminDeployment, and Velero
  restores only that namespace.
- A cross-target restore deletes a copy of the source's StyrminDeployment that carries the
  source's `spec.deploymentId`, in the counterpart's namespace.

So a teardown step that deletes objects outside the deployment's own namespace, such as its
service aliases in the other deployments' namespaces, acts only when:

- the StyrminDeployment's namespace is `styrmin-<spec.deploymentId>` (`get_kubernetes_reference`);
- and `spec.deletionRequested` is true, or the Namespace exists and is not `Terminating`
  (`teardown_deletes_aliases` in `agent/service/kubernetes/service_alias_rules.py`). When the
  Namespace cannot be read, the step deletes nothing and logs why.

Objects inside the deployment's own namespace need no such check, because Velero restores them with
the namespace. A step that deletes too little leaves objects that the next write of that name
replaces. A step that deletes too much breaks a running deployment until a flow writes the objects
again. See [ADR-076](../../adr/0076-teardown-deletes-service-aliases-in-all-namespaces.md).

## GraphQL (Strawberry)

- Types use `@strawberry.type` decorator
- Convert from DB models via `@classmethod from_instance()`
- Hide internal fields with `strawberry.Private[T]`
- Inject context via `info: strawberry.Info` parameter
- All GraphQL operations must be in `.graphql` files (see CLAUDE.md)

### Nested Resolvers

<!-- Extracted from specs/001-graphql-nested-resolvers on 2026-04-01 -->

When adding a nested object field to a GraphQL type, choose the resolver pattern based on whether the relationship is already eager-loaded:

- **Async UoW resolver** (preferred for new fields): Fetch via `info.context["uow"]`. Only executes when the field is requested. Use when the repository does not eager-load the relationship.
- **Sync resolver**: Access `self.instance.relationship` directly. Use only when the repository already eager-loads the relationship via `selectinload`.

**Nullability**: Match the resolver return type to the FK nullability in the database model. Non-nullable FK → non-nullable return. Nullable FK → nullable return.

**Error handling**: Non-nullable resolvers must raise an exception (e.g., `ValueError`) if the entity is not found — this surfaces as a GraphQL field error. Nullable resolvers return `None` when the FK is null (skip the DB query).

```python
# Async UoW resolver (non-nullable)
@strawberry.field
async def environment(self, info: strawberry.Info) -> Environment:
    uow = info.context["uow"]
    entity = await uow.environments.get(self.instance.environment_id)
    if entity is None:
        msg = f"Environment {self.instance.environment_id} not found"
        raise ValueError(msg)
    return Environment.from_instance(entity)

# Async UoW resolver (nullable)
@strawberry.field
async def deployment(self, info: strawberry.Info) -> Deployment | None:
    if self.instance.deployment_id is None:
        return None
    uow = info.context["uow"]
    entity = await uow.deployments.get(self.instance.deployment_id)
    return Deployment.from_instance(entity) if entity else None

# Sync resolver (relationship already eager-loaded)
@strawberry.field
def application_driver(self) -> ApplicationDriver:
    return ApplicationDriver.from_instance(self.instance.application_driver)
```

**Circular imports**: Use `strawberry.lazy()` with `Annotated` only when circular imports actually occur. Prefer standard imports when possible.

### Declare a mirror enum class for each GraphQL enum

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->

`strawberry.enum` binds one GraphQL name to one Python class. To expose a service-layer enum,
declare a `str, Enum` class in the API layer with `@strawberry.enum(name=...)` and the same
members, rather than registering the service-layer enum itself. Registering it claims its only
GraphQL name and makes an API concern of a service-layer type. `EnvironmentBackupStatus`
(`api/definitions/backup/environment_backup.py`) registers the service-layer
`EnvironmentOperationStatus` directly, which is why `EnvironmentRestoreStatus`, a second GraphQL
name for the same enum, had to be a mirror class.

Add a unit test that the mirror's members match the service-layer enum one for one, so the two
cannot drift apart. References: `EnvironmentRestoreStatus` in
`api/definitions/backup/environment_restore.py`, with
`test_environment_restore_status_mirrors_the_service_enum` in
`tests/unit/services/backup/test_environment_backup.py`; `EnvironmentCloneStatus` in
`api/definitions/backup/environment_clone.py`.

### Take a typed input that mirrors the config model in a mutation that writes a config

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

A mutation that writes a cluster, environment or deployment config takes a typed Strawberry input,
not a `config: JSON` argument:

- Declare one Strawberry input per Pydantic class and one enum mirror per Pydantic enum.
- Reuse the shared leaf inputs in `api/definitions/config/inputs.py`.
- Put the top-level input and its `*_input_to_dict` converter next to the entity, for example
  `UpdateClusterInput` and `update_cluster_input_to_dict` in `api/definitions/cluster/inputs.py`.
- When the input replaces the whole config, say so in its description.
- Cover it with a schema-walking propagation test (see
  [Schema-walking propagation tests](#schema-walking-propagation-tests)).

`createCluster` and `createEnvironment` still take `config: JSON`. Do not add another. Sources:
[ADR-012](../../adr/0012-environment-config-fanout.md) ("Convention to replicate"),
[ADR-018](../../adr/0018-typed-update-deployment-input.md) and
[ADR-066](../../adr/0066-cluster-config-fanout.md) decision 4.

### Show one unreadable JSON entry as degraded instead of failing the query

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

When a GraphQL type projects entries of a JSON column, and its wire type is stricter than the
column (for example a closed enum where the column holds free text), project each entry on its own.
For an entry that does not validate, log a warning and return a degraded entry instead of raising:
keep the fields that could be read and say in a text field which entry could not be read and why.
A single bad entry would otherwise fail the whole query with `INTERNAL_ERROR`, and the record could
no longer be read on any surface. Give the degraded entry the outcome that the status calculation
gives it, so the two agree.

Reference: `EnvironmentCloneDeploymentResult.from_stored` in
`api/definitions/backup/environment_clone.py`.

### Load list fields in a fixed number of queries

<!-- Extracted from specs/019-task-steps on 2026-10-08 -->

A nested resolver runs one query per parent object. That is acceptable for a single read, but a
list that a page reloads every 10 seconds multiplies it: per-field resolvers for the steps,
results and links of a 50-task timeline would run about a thousand queries on every refresh. When a
new nested field appears in such a list, load it in a number of queries that does not grow with
the number of items. Two patterns exist:

- **A read model built by the service.** The service loads the child rows of all items in bulk,
  calculates derived values in memory, and passes each GraphQL object its part through
  `strawberry.Private` fields. The resolver uses the private field when it is set and queries only
  for single reads. Use a sentinel (`NOT_LOADED` in `api/definitions/step/model.py`) rather than
  `None`, because `None` and `[]` are valid loaded values. Reference:
  `services/deployment_timeline.py::load_timeline_read_model` and `Task.steps` in
  `api/definitions/task/model.py`.
- **A per-request data loader** (`api/loaders.py`). Use it when the same type appears in several
  queries and places, such as `Backup.steps` in backup lists and in environment backups. One query
  reads the keys of the whole response, and a field that is not requested reads nothing.

```python
@strawberry.field
async def steps(self, info: strawberry.Info) -> list[Step]:
    if self.steps_view is not NOT_LOADED:  # set by the timeline read model
        return self.steps_view
    steps = await list_steps(StepParent.of_task(self.id), uow=info.context["uow"])
    return [Step.from_instance(step) for step in steps]
```

Add a unit test that counts the `SELECT` statements of the list query for one item and for many
items, and fails when the two counts differ or pass a fixed limit. Reference:
`tests/unit/services/test_deployment_timeline_steps.py::test_timeline_query_count_does_not_grow_with_tasks`.

Leave large text fields, such as `Step.output`, out of list queries. Expose a boolean
(`hasOutput`) and a single-item query (`Query.step`) that the client calls on request.

## Prefect Flows & Tasks

- `@task` for individual async operations
- `@flow` for multi-step orchestration
- Use `flow_run_name` / `task_run_name` for readable Prefect UI entries
- Only top-level wrapper flows register callbacks; inner flows do not

### Record units of work as steps

<!-- Extracted from specs/019-task-steps on 2026-10-08 -->

When a flow or a driver action primitive does work that users need to follow or diagnose, record
each unit of work as a step of its task, backup or restore, so users can view it without Prefect
or `kubectl` ([ADR-060](../../adr/0060-steps-and-derived-task-result.md)). Define the key, name
and kind of each step as a `StepDefinition` constant in `domain/steps.py`. How a step is written
depends on where the code runs:

- **Server code and INTERNAL flows** (database access) call the step recorder through
  `services/steps/internal_flows.py`: `open_task_step`, `end_step` and `fail_open_steps`. Never
  insert or update `step` rows any other way; the recorder enforces the state rules.
- **USER flows and driver actions** (no database access) use `StepReporter.from_env()` from
  `agent/steps/reporter.py`, which calls the `recordStep` mutation with the action token. Wrap
  the work in `async with reporter.step(*steps.MY_STEP):`, which records the start, the success,
  or the failure with the exception text before it raises the exception again.
- **To give a USER flow its step parent**, add it to the flow run's environment with
  `agent/tasks/utils.py::action_job_variables(token, task_id=..., backup_id=..., restore_id=...,
  step_id=...)`. Do not add flow parameters for it: they would change the parameters of every
  registered Prefect deployment for values that only the reporter reads.
- **A failed step write never fails the work.** The reporter and the INTERNAL-flow helpers log a
  warning and continue. Without a token or a parent, the reporter records nothing.
- **A USER flow cannot end its own steps when it crashes.** The INTERNAL flow that started it
  must catch the error of the USER flow run, call `fail_open_steps` with it, and raise it again,
  as the `apply_state`, `run_job`, backup and restore flows do.

See [Steps recorded by the flows](../../knowledge/backend/orchestration-flows.md#steps-recorded-by-the-flows)
for the steps that each flow records today.

### Decide whether a cron flow acts when its run starts late

<!-- Extracted from specs/020-backend-telemetry on 2026-10-10 -->

[CLAUDE RECOMMENDED – based on research D14 of spec 020 and the daily telemetry flow] When you
add a catalogue entry with a cron schedule, decide whether a run that starts late should still
do its work. Prefect keeps a run that was due while no worker was available in the `Late`
state, which is a `SCHEDULED` state type, and a worker starts it as soon as it comes back.
Prefect has no deployment or work-pool setting that drops runs that are too late.

- An idempotent cleanup, such as `cleanup_expired_sessions`, can run late without harm.
- A flow that must not act late compares `prefect.runtime.flow_run.scheduled_start_time` with
  the current time, logs one line and returns without doing the work. A run started on demand
  has its start time as its scheduled time, so it is not affected.

```python
from prefect.runtime import flow_run as flow_run_ctx

LATE_RUN_LIMIT = timedelta(hours=1)

scheduled = flow_run_ctx.scheduled_start_time
if scheduled is not None and datetime.now(UTC) - scheduled > LATE_RUN_LIMIT:
    log.info("No report sent: the run scheduled at %s started late", scheduled.isoformat())
    return False
```

`workflows/templates/telemetry.py` does this, so a report missed while the task worker was down
is not sent later.

### In a polling loop, reuse one unit of work and roll it back before each sleep

<!-- Extracted from specs/010-environment-clone on 2026-10-13 -->

When a flow polls the database until a row reaches a state, open one unit of work for the whole
loop and call `await uow.rollback()` before each sleep:

- Opening a new unit of work on each turn opens one session per turn, up to hundreds for one long
  wait, and holds connections from the pool.
- Without the rollback, the session's identity map keeps returning its first read of the row, so
  the loop never sees the row change. The rollback also returns the connection to the pool while
  the loop sleeps.
- Do not roll back after the last read: the rollback expires the loaded rows, and the caller must
  not receive expired rows.

```python
async with get_unit_of_work() as uow:
    while True:
        clone = await _load_clone(clone_id, uow)
        ...
        if capture_status in TERMINAL_ENVIRONMENT_OPERATION_STATUSES:
            return capture_status, clone
        await uow.rollback()
        await asyncio.sleep(poll_delay)
```

Reference: `_await_capture_terminal` in `workflows/templates/clone.py`.

### Read state that another deployment changes when you write, not from the flow's context

<!-- Extracted from specs/026-delete-service-aliases on 2026-10-17 -->

The server builds a flow's context when the change is requested, and passes it to the flow as a
parameter. A flow can run seconds or minutes later, and by then another deployment of the
environment may have been requested, deleted or restored. When a flow writes into another
deployment's namespace, or writes objects about another deployment:

- Read whether that deployment is being deleted from the cluster when you write: its Namespace
  (missing or `Terminating`) and its StyrminDeployment (`spec.deletionRequested` or
  `metadata.deletionTimestamp`). The server sets `spec.deletionRequested` before the deployment's
  status becomes `DELETING`, so the status in the context lags the request.
- Read the list of the other deployments from the server when you need it, with the flow's action
  token ([ADR-059](../../adr/0059-driver-action-api-tokens.md)), because the context lists no
  deployment requested after it. When the read fails, log a warning and use the context.
- When a write must not outlive a deletion that can start between your read and your write, read
  again after the write and delete what you wrote, with the `resourceVersion` that the write
  returned.
- Keep the deployment's own data from the context: it describes what this flow deploys.
- Do not change the context that driver templates render with to get these values.

Reference: `apply_service_aliases` and `with_current_peer_services` in
`agent/tasks/service_aliases.py`
([ADR-077](../../adr/0077-alias-flow-reads-deletion-state-at-write-time.md),
[ADR-078](../../adr/0078-alias-step-reads-current-services-from-server.md)).

### Refuse `{` and `}` in a user value that goes into a Prefect pull step

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

Before Prefect runs a deployment's pull steps, it fills in every `{{ ... }}` template in their
inputs: blocks such as `prefect.blocks.secret.x`, variables and environment variables. A user
value that Styrmin writes into a pull step can therefore change the step or write a secret into a
log. Refuse `{` and `}` in such a value when you validate it, before anything is cloned or
registered.

```python
if "{" in stripped or "}" in stripped:
    raise _refuse(value, "it contains '{' or '}'")
```

Reference: `normalise_driver_directory` in `services/driver/driver_directory.py`, which checks the
driver directory that goes into the `set_working_directory` step
([ADR-079](../../adr/0079-driver-actions-import-only-from-their-driver-directory.md)). Spec 028
did not check whether the repository URL that goes into the `git_clone` step needs the same
check.

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

Spec 029 applies the same check to the path of a local driver version that declares actions,
which goes into the `check_local_driver` pull step (`ensure_action_registrations` in
`services/applications.py`).

### Log the error of a pull step in the flow run before it raises

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

Prefect runs a deployment's pull steps before the flow run's engine starts. When a step raises,
Prefect prints the traceback to the process output, logs nothing in the flow run, and the flow run
crashes with only an exit status in its state message. The only text that reaches the hook step is
the first `ERROR` log of the crashed flow run, which `run_driver_action_or_fail` reads. A pull
step that Styrmin writes must therefore log its error at `ERROR` in the flow run, then raise:

```python
try:
    fingerprint = check_local_driver_files(...)
except (DriverFilesNotFoundError, DriverFingerprintMismatchError) as exc:
    _logger().error("%s", exc)  # flow_run_logger(flow_run_id=...) inside a flow run
    raise
```

Log any other exception at `ERROR` with its type before it is raised again, so an unexpected
failure also reaches the hook step. Write the error so that a user can fix the problem from its
text alone. Reference: `check_local_driver` in `workflows/local_driver.py`
([ADR-081](../../adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md), R-002).

## Outbound HTTP requests

<!-- Extracted from specs/020-backend-telemetry on 2026-10-10 -->

[CLAUDE RECOMMENDED – based on research D8 of spec 020 and ADR-047] When a request to an
external endpoint must stop after a fixed total time, wrap it in `asyncio.timeout`. An `httpx`
timeout applies to DNS, connect, write and read separately, so an endpoint that answers one
byte at a time can keep a request open far longer than the timeout value.

```python
async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
        response = await client.post(endpoint, json=envelope)
```

`services/telemetry/sender.py` does this for the daily telemetry report. `styrminctl`, which
is synchronous, gets the same limit by running the request on a daemon thread and joining it
with a budget ([ADR-047](../../adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md)).

## Python SDK

### Send a new optional GraphQL argument in its own operation

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

A GraphQL server refuses an operation that passes a field an argument the server does not know,
even when the variable is `null`. When an SDK method gets a new optional argument, keep the old operation for
calls without it, and add a second operation that declares the argument. Send the second operation
only when the caller gives a value. Calls without the value then keep working against servers that
predate the argument.

When a server answers the second operation with `Unknown argument '<name>' on field '<field>'`,
raise `IncompatibleServerError` with a message that says which change added the argument and what
to do: upgrade the server, or call without the argument.

```python
if driver_directory is None:
    result = await self._transport.execute(load_query("load_version"), variables)
    ...
variables["driverDirectory"] = driver_directory
result = await self._transport.execute(
    load_query("load_version_with_driver_directory"), variables
)
_raise_if_server_lacks_driver_directory(result)
self._check_graphql_errors(result)
```

Use `@overload` so the return type follows the argument, because the two operations generate two
result types. References: `DriverResource.load_version` in
`python_sdk/src/styrmin_sdk/resources/drivers.py` (#517), and `update_version()` with
`update_deployment_version_with_input.graphql` in `resources/deployments.py` (#388).

## Invoke Tasks

When a task does not use `context`, suppress with `# noqa: ARG001`:

```python
@task
def my_task(context: Context) -> None:  # noqa: ARG001
    ...
```

## Testing

- pytest with pytest-asyncio (`asyncio_mode = "auto"`)
- Fake repositories for unit tests (see `tests/unit/services/fakes.py`)
- `fast_depends.dependency_provider` for dependency overrides in tests
- Test naming: `test_<function>_<scenario>`
- `assert` statements allowed in tests (S101 ignored)
- Type hints optional in test files
- **GraphQL schema changes require a propagation test** — see
  [`dev/guides/graphql-propagation-tests.md`](../../guides/graphql-propagation-tests.md).

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

- **Validators implemented in both the backend and the frontend share one test-vector file.**
  Both test suites read the same JSON list of inputs and expected results, so the two
  implementations cannot drift without a test failing. Example:
  `frontend/src/lib/image-reference.vectors.json`, read by
  `backend/tests/unit/services/image_overrides/test_reference.py` and
  `frontend/src/lib/image-reference.test.ts`.

<!-- Extracted from specs/001-env-backup-restore on 2026-10-13 -->

- **Put a test that needs no cluster under `backend/tests/unit/`, even when it imports modules
  from `tests.e2e`.** Collecting any module under `tests/e2e/` starts a vCluster, because
  `tests/e2e/conftest.py` has an `autouse` fixture that depends on the session `vcluster` fixture.
  The unit job ignores `tests/e2e/`, and the CI E2E jobs select tests by the `ci` and shard
  markers, so a test placed there without those markers runs in no CI job. Example:
  `backend/tests/unit/test_e2e_driver_conformance.py`.

<!-- Extracted from specs/023-per-component-replicas on 2026-10-16 -->

- **To prove that a task waits for a rollout, read the workload once after the task completes.**
  Do not poll for the counts. A test that waits for the counts passes when the task returned
  before the pods were ready, so it does not test the wait. Assert `spec.replicas`,
  `status.replicas` and the updated, ready and available counts in one read; after a scale-down,
  `status.replicas` shows whether the extra pods are gone. Example:
  `backend/tests/e2e/test_deployment_image_override.py::test_scale_server_and_singleton_guard` with
  `read_workload_replicas` from `backend/tests/e2e/helpers/workloads.py`.

<!-- Extracted from specs/024-ingress-class-post-render on 2026-10-16 -->

- **A change to a post-render patch ships an integration test that applies the patch with
  `kubectl kustomize` and checks the resulting resources, not the patch objects.** Where the
  change depends on what a chart renders, render a real chart with `helm template` first. Skip
  the module with `pytest.mark.skipif` when `helm` or `kubectl` is not on `PATH`. Examples, all
  under `backend/tests/integration/`:
  - `test_ingress_class_post_render.py` and `test_container_override_migration_parity.py` run
    `helm template` and then `kubectl kustomize`;
  - `test_component_container_kustomize.py` runs `kubectl kustomize` on fixed manifests.

<!-- Extracted from specs/025-helm-v4-defaults on 2026-10-16 -->

- **Put chart behaviour that only an E2E test needs behind a chart value that is off by default,
  and turn it on from a test driver under `backend/tests/e2e/fixtures/drivers/`.** Do not add a
  parameter to an example driver for it: the parameter would appear in the deploy form of a
  driver that users read as a reference. Do not turn it on by patching the HelmRelease's
  `spec.values` from the test either: the next Styrmin update of the deployment rewrites
  `spec.values`. Example: `preUpgradeHookJob.enabled` in the `simple-app` chart, turned on by the
  `hook-job` test driver that `test_pod_scheduling.py` uses.

<!-- Extracted from specs/029-local-driver-actions on 2026-10-20 -->

- **In an E2E test that loads more than one variant of a driver, give each variant its own driver
  name, and pin `driver_version_id` on every create and version change.** Without a pin, a create
  or a version change binds the deployment to the latest version of its driver that supports the
  application version (latest-wins, see `CONTEXT.md`), which can be a variant that a test loaded
  later in the same session. A name of its own keeps the variants away from the deployments of
  other tests that use the original driver. The pin keeps each deployment on its own variant when
  several variants share a name. Example: `backend/tests/e2e/test_local_driver_actions.py`, whose
  variants share the name `local-actions-check` and whose `_create_pinned_deployment` pins every
  create.
