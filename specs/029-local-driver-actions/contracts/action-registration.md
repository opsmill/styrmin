# Contract: Action Registration on Load (FR-001, FR-002, FR-006)

**Modules**: `services/applications.py`, `services/user.py`, `services/driver/labels.py`, `workflows/models.py`, `workflows/manager.py` (unchanged signatures).

## Registration key

```python
def action_directory_of(*, source_type: str, source_path: str | None) -> str | None:
    """The ``driver_directory`` of a driver version's action registrations and lookups.

    ``source_path`` for ``git`` (the driver directory, or None for the repository root)
    and for ``local`` (the absolute path on the server); None for any other source type.
    """
```

`driver_directory_of` keeps its current behaviour; only the GraphQL field `driverDirectory` uses it after this change.

The key of a driver version (`ActionRegistrationKey`, [data-model.md](../data-model.md#value-objects-new-service-layer)):

| Part | Value |
|------|-------|
| `application` | `driver_spec.metadata.name` (load) or the application driver's `name` (hooks) |
| `version` | `application_supported_versions` |
| `fingerprint` | `short_fingerprint(content_hash=..., source_commit_sha=...)` |
| `directory` | `action_directory_of(source_type=..., source_path=...)` |

`PrefectManager.register_user_action(..., fingerprint=key.fingerprint, driver_directory=key.directory)` and `get_user_action_deployment_id(..., fingerprint=key.fingerprint, driver_directory=key.directory)` keep their signatures and their ADR-080 tag and name rules.

## Workflow definition of a local action

```python
class LocalDriverActionWorkflowDefinition(WorkflowDefinition):
    directory: str          # the version's source_path
    content_hash: str       # the version's full content_hash
    spec_file: str          # DriverSettings.spec_file at load time
    values_template: str    # DriverSettings.values_template at load time
    actions_file: str       # DriverSettings.actions_code_file at load time

    @property
    def entrypoint(self) -> str:        # "actions.py:<function>", as GitSourceWorkflowDefinition
        ...

    async def to_deployment(self) -> dict[str, Any]:
        # base payload (name, entrypoint, tags, job_variables image when set)
        # + pull_steps = [{"styrmin_backend.workflows.local_driver.check_local_driver": {
        #       "directory": ..., "content_hash": ..., "spec_file": ...,
        #       "values_template": ..., "actions_file": ...}}]
        ...

    def get_function(self) -> Callable[..., Awaitable[Any]]:
        # imports the function from <directory>/<module>, for validate_workflow
        ...
```

`ActionsWorkflowBuilder.__init__(self, source: GitSource | LocalSource, commit_sha: str | None = None, content_hash: str | None = None)`:

- `GitSource` → `GitSourceWorkflowDefinition`, as today.
- `LocalSource` → `LocalDriverActionWorkflowDefinition` with `directory=source.path`, `content_hash=content_hash` (required for a local source) and the three file names from `config.SETTINGS.driver`.
- Both use `name=f"User Action: {action.name}"`, `type=WorkflowType.USER`, `namespace="user"` and `image=action.image`.

## `ensure_action_registrations`

```python
async def ensure_action_registrations(
    driver_object: ApplicationDriver,
    prefect_manager: PrefectManager,
) -> int:
    """Register the declared actions whose hook and mode have no registered flow.

    Returns the number of actions registered.
    """
```

Behaviour:

1. Return 0 when `driver_object.driver_spec.spec.actions` is empty.
2. For a `LocalSource` whose `path` contains `{` or `}`, raise `DriverLoadingError` naming the path and the reason (Prefect templates in pull step inputs, R-005).
3. Build the key from `driver_object` (`source_path` is `source.path` for local and `source.driver_directory` for git).
4. Group the declared actions by `(hook, mode)`. For each group, call `get_user_action_deployment_id` with the key. Keep the groups whose lookup returns `None`.
5. When no group is kept, return 0. No Prefect write happens.
6. For a `GitSource`, call `register_token(namespace="user", token=source.token)`.
7. Register every action of every kept group with `register_user_action`.
8. Return the number of registered actions.

Callers in `load_application_driver_from_object`:

- When `get_by_identity` finds a version: call it before each `return`, including the branch that fills the info columns.
- When the load creates a version: call it where the git-only registration block is today, for git and local sources. The `isinstance(..., GitSource)` gate is removed.

A load that raises from `ensure_action_registrations` stores no new version: the call comes before the insert, as the registration does today.

## Lookup rule (unchanged, now also for local versions)

Tag filter `all_`: `application/`, `hook/`, `mode/`, `version/`, `fingerprint/` (when set), `directory/` (when set). Without a directory, deployments that carry a `directory/` tag are dropped. Newest first.

| Driver version | `directory/` tag | Name suffix |
|----------------|------------------|-------------|
| git, repository root | none | `(<driver>@<sha7>)` |
| git, driver directory `drivers/infrahub` | `directory/drivers/infrahub` | `(<driver>@<sha7> <digest>)` |
| local, `/styrmin/drivers/infrahub` (new) | `directory//styrmin/drivers/infrahub` | `(<driver>@<hash7> <digest>)` |

## Observable results (tests)

- Loading `/styrmin/drivers/semaphore` locally (functional test: `driver/examples/semaphore`) creates three deployments tagged `fingerprint/<hash7>` and `directory/<path>`, each with the check pull step.
- Each of the five bundled drivers loaded locally creates three deployments.
- Two local paths with the same files create two sets of deployments, each with its own `directory/` tag and pull step `directory`.
- Loading a version again when all its pairs resolve makes no `create_deployment` call.
- Deleting a version's deployments and loading it again creates them again.
- A local path with `{` is refused when the driver declares actions, and accepted when it declares none.
