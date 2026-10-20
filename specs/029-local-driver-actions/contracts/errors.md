# Contract: Typed Errors

**Module**: `backend/styrmin_backend/services/driver/exceptions.py`. All three subclass `DriverError` (Constitution §IV). None reaches a GraphQL response: each is recorded on a step and, for the request check, as a task message. The `error_code` values reuse existing codes.

The message texts are part of the contract: SC-003 requires that a user can fix the problem from the message alone, and tests assert the parts listed under "Must contain".

## Words that name the agent pod

The two errors of the check name the pod where the action runs: the agent's Prefect process worker runs every action as a process in the agent pod, and an action's `image:` has no effect, so the errors name no image (research R-006, corrected after the review of #372; [ADR-081](../../../dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md)). The pull step passes its host name, which is the pod name in Kubernetes, as `agent_pod`; `get_function` passes none. `describe_agent_pod(agent_pod)` in the same module builds the words `{agent pod words}`:

| `agent_pod` | `{agent pod words}` |
|-------------|---------------------|
| A name | `the Styrmin agent pod {agent_pod}`, for example `the Styrmin agent pod styrmin-agent-7c9d8-x2k4q` |
| `None` | `the Styrmin agent pod` |

## DriverFilesNotFoundError (FR-004)

```python
class DriverFilesNotFoundError(DriverError):
    error_code = "NOT_FOUND"
    default_message = "The driver files are not in the agent pod, where the action runs"

    def __init__(
        self,
        *,
        path: str,
        missing: list[str],
        agent_pod: str | None = None,
    ) -> None: ...
```

- Raised by `check_local_driver` when `path` is not a directory, or when the driver specification file or the actions file is missing in it. A missing values template is not an error: the fingerprint uses empty bytes for it, as the loader does.
- `missing` holds the missing file names, or the path itself when the directory is missing.
- `error_metadata`: `{"path": path, "agent_pod": agent_pod, "missing": missing}`.

Message:

```text
The driver files are not at {path} in {agent pod words}: {missing, joined with ", "} not found. The agent pod runs every driver action, so it must hold the driver at the same path as the Styrmin server. Mount or copy the driver into the agent pod at {path}, or load the driver from a path that both the server and the agent pod hold.
```

Must contain: the path, the agent pod, each missing name, the two fixes.

## DriverFingerprintMismatchError (FR-003)

```python
class DriverFingerprintMismatchError(DriverError):
    error_code = "VALIDATION_ERROR"
    default_message = (
        "The driver files in the agent pod, where the action runs, differ from the "
        "driver version"
    )

    def __init__(
        self,
        *,
        path: str,
        expected: str,
        actual: str,
        agent_pod: str | None = None,
    ) -> None: ...
```

- Raised by `check_local_driver` when `compute_driver_directory_fingerprint` of the files at `path` differs from `expected`.
- `expected` and `actual` are full SHA-256 hex digests; the message shows their first 7 characters, as driver version labels do.
- `error_metadata`: `{"path": path, "agent_pod": agent_pod, "expected": expected, "actual": actual}`.

Message:

```text
The driver files at {path} in {agent pod words} are not the files of this driver version: their provenance fingerprint is {actual[:7]}, and the driver version was loaded with {expected[:7]}. If the files changed after the driver was loaded, load the driver again and use the new driver version: styrminctl drivers load-local-version {path, shell-quoted}. If the agent pod holds other files at {path} than the Styrmin server, give both the same files first.
```

Must contain: the path, the agent pod, both short fingerprints, the `styrminctl drivers load-local-version` command.

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
