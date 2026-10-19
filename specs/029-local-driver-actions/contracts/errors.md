# Contract: Typed Errors

**Module**: `backend/styrmin_backend/services/driver/exceptions.py`. All three subclass `DriverError` (Constitution §IV). None reaches a GraphQL response: each is recorded on a step and, for the request check, as a task message. The `error_code` values reuse existing codes.

The message texts are part of the contract: SC-003 requires that a user can fix the problem from the message alone, and tests assert the parts listed under "Must contain".

## Words that name the image of the action's Job

The two errors of the check name the image that runs the action's Job ([local-driver-check.md](local-driver-check.md#the-pull-step), research R-006). The check passes the image name and the work pool that it read from the Prefect API; either is `None` when the API does not give it. `describe_action_image(image, work_pool)` in the same module builds the words `{image words}` that follow "in" in both messages:

| What the check read | `{image words}` |
|---------------------|-----------------|
| The image name | `the image {image}`, for example `the image registry.opsmill.io/opsmill/styrmin:latest` |
| Only the work pool | `the default image of the work pool {work_pool}`, for example `the default image of the work pool user-work-pool` |
| Neither | `the image of this action's Job` |

## DriverFilesNotFoundError (FR-004)

```python
class DriverFilesNotFoundError(DriverError):
    error_code = "NOT_FOUND"
    default_message = "The driver files are not in the action's image"

    def __init__(
        self,
        *,
        path: str,
        image: str | None,
        missing: list[str],
        work_pool: str | None = None,
    ) -> None: ...
```

- Raised by `check_local_driver` when `path` is not a directory, or when the driver specification file or the actions file is missing in it. A missing values template is not an error: the fingerprint uses empty bytes for it, as the loader does.
- `missing` holds the missing file names, or the path itself when the directory is missing.
- `error_metadata`: `{"path": path, "image": image, "work_pool": work_pool, "missing": missing}`.

Message:

```text
The driver files are not at {path} in {image words}: {missing, joined with ", "} not found. An action's image must hold the driver at the same path as the Styrmin server. Add the driver to the image at {path}, or load the driver from a path that the image holds.
```

Must contain: the path, the image when the check read it (otherwise the work pool when it read that), each missing name.

## DriverFingerprintMismatchError (FR-003)

```python
class DriverFingerprintMismatchError(DriverError):
    error_code = "VALIDATION_ERROR"
    default_message = "The driver files in the action's image differ from the driver version"

    def __init__(
        self,
        *,
        path: str,
        image: str | None,
        expected: str,
        actual: str,
        work_pool: str | None = None,
    ) -> None: ...
```

- Raised by `check_local_driver` when `compute_driver_directory_fingerprint` of the files at `path` differs from `expected`.
- `expected` and `actual` are full SHA-256 hex digests; the message shows their first 7 characters, as driver version labels do.
- `error_metadata`: `{"path": path, "image": image, "work_pool": work_pool, "expected": expected, "actual": actual}`.

Message:

```text
The driver files at {path} in {image words} are not the files of this driver version: their provenance fingerprint is {actual[:7]}, and the driver version was loaded with {expected[:7]}. The files changed after the driver was loaded. Rebuild the image with the files you loaded and load the driver again, or load the driver again from {path} and use the new driver version.
```

Must contain: the path, the image when the check read it (otherwise the work pool when it read that), both short fingerprints, "Rebuild the image", "load the driver again".

## ActionNotRegisteredError (FR-005)

```python
class ActionNotRegisteredError(DriverError):
    error_code = "NOT_FOUND"
    default_message = "A declared action has no registered flow"

    def __init__(
        self,
        *,
        driver_name: str,
        driver_version_label: str,      # format_driver_version_label(...), e.g. "1@0123abc"
        actions: list[str],             # declared action names for this hook and mode
        hook: HookKind,
        mode: Literal["pre", "core", "post"],
        load_command: str,
    ) -> None: ...
```

- Raised by `resolve_hook_flow` when the driver version declares at least one action for the hook and mode and the lookup finds no deployment.
- `load_command`:
  - local: `styrminctl drivers load-local-version {source_path}`;
  - git from the repository root: `styrminctl drivers load-version {source_repository} {source_branch}`;
  - git from a driver directory: the same, followed by `--driver-directory {source_path}`.
- `error_metadata`: `{"driver": driver_name, "driver_version": driver_version_label, "actions": actions, "hook": hook.value, "mode": mode}`.

Message:

```text
Driver version {driver_name} {driver_version_label} declares the action {actions, joined with ", "} for the {hook} hook, mode {mode}, but no flow is registered for it, so the hook cannot run. Load the driver again to register its actions: {load_command}. Then request the change again; a deployment whose creation failed must be deleted and created again. If the driver's files or commit changed since it was loaded, the load creates a new driver version; use that version instead.
```

Must contain: the driver name, the version label, each action name, the hook, the mode, "Load the driver again", the load command, "request the change again".

## How the errors appear to users

| Error | Recorded by | Step error text |
|-------|-------------|-----------------|
| `DriverFilesNotFoundError`, `DriverFingerprintMismatchError` | `run_driver_action_or_fail` through `StepReporter.step` | `RuntimeError: Deployment flow run <id> crashed: <message> (<Prefect state message>)` ([local-driver-check.md](local-driver-check.md#how-the-error-reaches-the-hook-step)) |
| `ActionNotRegisteredError` (flow) | `apply_state` | `ActionNotRegisteredError: <message>` |
| `ActionNotRegisteredError` (request check) | `update_deployment_version` | `ActionNotRegisteredError: <message>`, and the same text without the class name as `Task.message` |
