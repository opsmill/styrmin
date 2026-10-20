"""The check that runs before an action of a driver version loaded from a local directory.

Spec 029 (research R-001, R-004, R-006). The Prefect deployment of such an
action has one pull step, :func:`check_local_driver`. Before Prefect imports
``actions.py``, the step checks that the driver files at the driver version's
path, where the action runs (in the agent pod, through the agent's Prefect
process worker), have the provenance fingerprint that the driver version was
loaded with. It then returns the path, so that Prefect
changes into it and imports the action from it, as it does from the driver
directory of a git driver version (ADR-079).

The agent pod has no server settings and no database. This module must
import without them: it imports only Prefect and the driver modules ``hash``
and ``exceptions``.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from uuid import UUID

from prefect.logging.loggers import PrefectLogAdapter, flow_run_logger, get_logger

from styrmin_backend.services.driver.exceptions import (
    DriverFilesNotFoundError,
    DriverFingerprintMismatchError,
)
from styrmin_backend.services.driver.hash import compute_driver_directory_fingerprint

# Set by the Prefect worker in the environment of the flow run's process.
FLOW_RUN_ID_ENV = "PREFECT__FLOW_RUN_ID"

_logger_outside_flow_run = get_logger(__name__)


def check_local_driver_files(
    directory: str,
    content_hash: str,
    spec_file: str,
    values_template: str,
    actions_file: str,
    agent_pod: str | None = None,
) -> str:
    """Check that the driver files at ``directory`` have the provenance fingerprint ``content_hash``.

    The pull step :func:`check_local_driver` and
    ``LocalDriverActionWorkflowDefinition.get_function`` run this check before
    they import the action.

    Args:
        directory: The path that the driver version was loaded from.
        content_hash: The full provenance fingerprint of the driver version.
        spec_file: The name of the driver specification file.
        values_template: The name of the values template; a missing one hashes as empty.
        actions_file: The name of the actions file.
        agent_pod: The agent pod that the errors name, when the check runs in it.

    Returns:
        The provenance fingerprint of the files at ``directory``.

    Raises:
        DriverFilesNotFoundError: ``directory`` is not a directory, or the driver
            specification file or the actions file is missing in it, also when
            the file is removed between the check and the read.
        DriverFingerprintMismatchError: the files at ``directory`` have another
            provenance fingerprint.
        OSError: a driver file cannot be read for another reason, for example
            a ``PermissionError``, or a values template path that is a directory.
    """
    path = Path(directory)
    if not path.is_dir():
        raise DriverFilesNotFoundError(
            path=directory, missing=[directory], agent_pod=agent_pod
        )
    missing = [
        name for name in (spec_file, actions_file) if not (path / name).is_file()
    ]
    if missing:
        raise DriverFilesNotFoundError(
            path=directory, missing=missing, agent_pod=agent_pod
        )

    try:
        actual = compute_driver_directory_fingerprint(
            path,
            spec_file=spec_file,
            values_template=values_template,
            actions_file=actions_file,
            include_actions=True,
        )
    except FileNotFoundError as exc:
        # The file was removed after the check above.
        name = Path(str(exc.filename)).name if exc.filename else spec_file
        raise DriverFilesNotFoundError(
            path=directory, missing=[name], agent_pod=agent_pod
        ) from exc
    if actual != content_hash:
        raise DriverFingerprintMismatchError(
            path=directory,
            expected=content_hash,
            actual=actual,
            agent_pod=agent_pod,
        )
    return actual


def check_local_driver(
    directory: str,
    content_hash: str,
    spec_file: str,
    values_template: str,
    actions_file: str,
) -> dict[str, str]:
    """Prefect pull step of an action of a driver version loaded from a local directory.

    Runs :func:`check_local_driver_files`, whose errors name this pod (the
    agent pod, where the agent's process worker runs the action), logs the
    path and the short provenance fingerprint in the flow run, and returns
    ``{"directory": directory}``.
    Prefect then changes into ``directory`` and imports the deployment's
    entrypoint from it. The step never imports the actions file.

    When the check fails, the step logs the error at ``ERROR`` in the flow run
    before it raises. Prefect runs pull steps before the flow run's engine
    starts: when a step raises, Prefect prints the traceback to the process
    output, logs nothing in the flow run, and the flow run crashes with only
    an exit status. The hook step shows the first ``ERROR`` log of a crashed
    flow run (``run_deployment_or_fail``, research R-002), so this log is how
    the error reaches the hook step. Any other exception, such as an
    ``OSError`` from reading a driver file, is logged at ``ERROR`` with the
    path for the same reason.

    Raises:
        DriverFilesNotFoundError: see :func:`check_local_driver_files`.
        DriverFingerprintMismatchError: see :func:`check_local_driver_files`.
        OSError: see :func:`check_local_driver_files`.
    """
    try:
        fingerprint = check_local_driver_files(
            directory=directory,
            content_hash=content_hash,
            spec_file=spec_file,
            values_template=values_template,
            actions_file=actions_file,
            agent_pod=socket.gethostname(),
        )
    except (DriverFilesNotFoundError, DriverFingerprintMismatchError) as exc:
        _logger().error("%s", exc)
        raise
    except Exception as exc:
        _logger().error(
            "Could not check the driver files at %s: %s: %s",
            directory,
            type(exc).__name__,
            exc,
        )
        raise
    _logger().info(
        "The driver files at %s have the provenance fingerprint %s of the driver version. "
        "The action runs from %s.",
        directory,
        fingerprint[:7],
        directory,
    )
    return {"directory": directory}


# The fully qualified name of the pull step, which Prefect imports in the action's process.
CHECK_LOCAL_DRIVER_STEP = f"{__name__}.{check_local_driver.__name__}"


def _flow_run_id() -> UUID | None:
    """The id of the flow run that this process runs, or None outside a flow run."""
    value = os.environ.get(FLOW_RUN_ID_ENV)
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _logger() -> PrefectLogAdapter | logging.Logger:
    """A logger whose lines appear in the logs of the flow run, when there is one."""
    flow_run_id = _flow_run_id()
    if flow_run_id is None:
        return _logger_outside_flow_run
    return flow_run_logger(flow_run_id=flow_run_id)
