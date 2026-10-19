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
2. Compute the fingerprint. When it differs from `content_hash`, raise `DriverFingerprintMismatchError` ([errors.md](errors.md#driverfingerprintmismatcherror-fr-003)).
3. Return `{"directory": directory}`. Prefect changes into it and imports `<actions_file>:<function>` (the entrypoint).

The step never imports `actions.py`.

Image named in the errors (R-006), resolved only on the error path:

1. The deployment's `job_variables["image"]` of the flow run in `PREFECT__FLOW_RUN_ID`.
2. Otherwise the `default` of `variables.properties.image` in the base job template of the flow run's work pool.
3. Otherwise the text `the default image of the work pool <name>`, or `the image of this action's Job` when the work pool is unknown.

A failure to read Prefect's API in this resolution never hides the original error.

Import constraints: `workflows/local_driver.py` imports only the standard library, `prefect`, `services/driver/hash.py` and `services/driver/exceptions.py`. Importing it must not read server settings or open a database connection, because the Job has neither.

## How the error reaches the hook step

`run_deployment_or_fail` (`agent/tasks/utils.py`):

```python
if flow_run.state and flow_run.state.is_crashed():
    first_error = await _first_error_log(flow_run.id)   # None when absent or unreadable
    detail = f"{first_error} ({flow_run.state.message})" if first_error else flow_run.state.message
    raise RuntimeError(f"Deployment flow run {flow_run.id} crashed: {detail}")
```

- `_first_error_log` calls `client.read_logs(LogFilter(flow_run_id={"any_": [id]}, level={"ge_": 40}), limit=1, sort=LogSort.TIMESTAMP_ASC)` and returns the message cut to 4,000 characters.
- Any exception while reading logs returns `None` and is logged at warning level.
- The failed-state branch is unchanged.

Example of the hook step error for FR-003:

```text
RuntimeError: Deployment flow run 6f0c… crashed: The driver files at /styrmin/drivers/my-app in the image registry.opsmill.io/opsmill/styrmin:latest are not the files of this driver version: their provenance fingerprint is 9b1e2c4, and the driver version was loaded with 0a7d3f1. The files changed after the driver was loaded. Rebuild the image with the files you loaded and load the driver again, or load the driver again from /styrmin/drivers/my-app and use the new driver version. (Process exited with status code: 1. …)
```

## Observable results (tests)

- Unchanged files: the step returns the directory, and the action's marker is logged (E2E user story 1).
- Changed `actions.py`, values template or driver specification file: `DriverFingerprintMismatchError` with both short fingerprints (unit), and the hook step shows it (E2E user story 2).
- Missing directory, or missing `actions.py`: `DriverFilesNotFoundError` naming what is missing (unit), and the hook step shows it (E2E user story 2).
- A crashed flow run with an error log: the error contains the log text. Without one, or when the read fails: today's text (unit).
