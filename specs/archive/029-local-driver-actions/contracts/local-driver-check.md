# Contract: Check of a Local Driver in the Action's Job (FR-002, FR-003, FR-004)

**Modules**: `workflows/local_driver.py` (new), `services/driver/hash.py`, `agent/tasks/utils.py`.

## Fingerprint at a path

```python
def compute_driver_directory_fingerprint(
    directory: Path,
    *,
    spec_file: str,
    values_template: str,
    actions_file: str,
    include_actions: bool,
) -> str:
    """The provenance fingerprint of the driver files in ``directory``.

    Reads ``spec_file``, ``values_template`` (empty bytes when missing) and, when
    ``include_actions``, ``actions_file``, then returns ``compute_driver_content_hash``.
    Raises ``FileNotFoundError`` when ``spec_file``, or ``actions_file`` with
    ``include_actions``, is missing.
    """
```

The local loader (`services/driver/loaders.py`) computes `content_hash` with this function, with `include_actions = bool(spec.actions)`. The check step calls it with `include_actions=True`, because only a driver that declares actions registers the step. The two values are equal for the same files.

## The pull step

```python
def check_local_driver(
    directory: str,
    content_hash: str,
    spec_file: str,
    values_template: str,
    actions_file: str,
) -> dict[str, str]:
    """Prefect pull step of a local driver version's action.

    Returns {"directory": directory} when the files at ``directory`` have the
    provenance fingerprint ``content_hash``; raises otherwise.
    """
```

Order of operations:

1. When `directory` is not a directory, or `spec_file` or `actions_file` is missing in it, raise `DriverFilesNotFoundError` ([errors.md](errors.md#driverfilesnotfounderror-fr-004)).
2. Compute the fingerprint. A file removed between step 1 and its read raises `DriverFilesNotFoundError`; any other `OSError` of the read is raised as it is. When the fingerprint differs from `content_hash`, raise `DriverFingerprintMismatchError` ([errors.md](errors.md#driverfingerprintmismatcherror-fr-003)).
3. Return `{"directory": directory}`. Prefect changes into it and imports `<actions_file>:<function>` (the entrypoint).

The step never imports `actions.py`.

Pod named in the errors (R-006, corrected after the review of #372): the step passes `socket.gethostname()`, the agent pod's name in Kubernetes, as `agent_pod` ([errors.md](errors.md#words-that-name-the-agent-pod)). The errors name no image, and the check reads nothing from the Prefect API.

Import constraints: importing `workflows/local_driver.py` must succeed with an empty environment, read no server settings and open no database connection, because the Job has neither. It imports `services/driver/hash.py` and `services/driver/exceptions.py`, which load the driver package and its Pydantic models; that import was checked to succeed with an empty environment. A unit test imports the module in a subprocess with an empty environment (critique E1).

Logging: on success, the step logs one `INFO` line in the flow run, with the path and the short fingerprint (critique E9). On failure, the step logs the text of its error at `ERROR` in the flow run, then raises. Any other exception, such as a `PermissionError` on `actions.py`, is logged as `Could not check the driver files at <path>: <exception type>: <message>`. Prefect 3.8 runs pull steps in a workspace supervisor before the flow run's engine starts. When a step raises, the supervisor prints the traceback to the process output and logs nothing in the flow run, so without this log the flow run has no `ERROR` log and the hook step shows only the exit status. This was found by the user story 2 E2E run (T028).

## How the error reaches the hook step

`run_driver_action_or_fail` (`agent/tasks/utils.py`), for driver actions only:

```python
if flow_run.state and flow_run.state.is_crashed():
    detail = flow_run.state.message
    if crash_log_secrets is not None:  # set by run_driver_action_or_fail only
        first_error = await _first_error_log(flow_run.id)   # None when absent or unreadable
        if first_error:
            detail = f"{redact_secrets(first_error, crash_log_secrets)} ({detail})"
    raise RuntimeError(f"Deployment flow run {flow_run.id} crashed: {detail}")
```

- `run_deployment_or_fail`, which the orchestration flows and the remediations use, keeps the state message alone, so the logs of those flows never reach a task.
- `redact_secrets` replaces the action token, the user info of URLs, the credential after `Bearer` or `Basic`, and the value of a key whose name says it holds a secret, with `<redacted>`.

- The first `ERROR` log of a flow run whose check failed is the error that the check step logged before it raised (see "Logging" above).
- `_first_error_log` calls `client.read_logs(LogFilter(flow_run_id=LogFilterFlowRunId(any_=[id]), level=LogFilterLevel(ge_=40)), limit=1, sort=LogSort.TIMESTAMP_ASC)` and returns the message cut to 4,000 characters (`FIRST_ERROR_LOG_MAX_LENGTH`).
- When the flow run has no `ERROR` log, or any exception occurs while reading logs, it returns `None` and logs a warning in the calling flow run.
- The failed-state branch is unchanged.

Text of the hook step error: `Deployment flow run <id> crashed: <first ERROR log> (<state message>)`, or `Deployment flow run <id> crashed: <state message>` without a first `ERROR` log.

Example of the hook step error for FR-003:

```text
RuntimeError: Deployment flow run 6f0c… crashed: The driver files at /styrmin/drivers/my-app in the Styrmin agent pod styrmin-agent-7c9d8-x2k4q are not the files of this driver version: their provenance fingerprint is 9b1e2c4, and the driver version was loaded with 0a7d3f1. If the files changed after the driver was loaded, load the driver again and use the new driver version: styrminctl drivers load-local-version /styrmin/drivers/my-app. If the agent pod holds other files at /styrmin/drivers/my-app than the Styrmin server, give both the same files first. (Process exited with status code: 1. …)
```

Example of the hook step error for FR-004:

```text
RuntimeError: Deployment flow run 6f0c… crashed: The driver files are not at /styrmin/drivers/my-app in the Styrmin agent pod styrmin-agent-7c9d8-x2k4q: actions.py not found. The agent pod runs every driver action, so it must hold the driver at the same path as the Styrmin server. Mount or copy the driver into the agent pod at /styrmin/drivers/my-app, or load the driver from a path that both the server and the agent pod hold. (Process exited with status code: 1. …)
```

## Observable results (tests)

- Unchanged files: the step returns the directory, and the action's marker is logged (E2E user story 1).
- Changed `actions.py`, values template or driver specification file: `DriverFingerprintMismatchError` with both short fingerprints (unit), and the hook step shows it (E2E user story 2).
- Missing directory, or missing `actions.py`: `DriverFilesNotFoundError` naming what is missing (unit), and the hook step shows it (E2E user story 2).
- A crashed flow run with an error log: the error contains the log text. Without one, or when the read fails: today's text (unit).
