"""The check that runs before an action of a driver version loaded from a local directory.

Spec 029 (research R-001, R-004, R-006). The Prefect deployment of such an
action has one pull step, :func:`check_local_driver`. Before Prefect imports
``actions.py``, the step checks that the driver files at the driver version's
path, in the image of the action's Job, have the provenance fingerprint that
the driver version was loaded with. It then returns the path, so that Prefect
changes into it and imports the action from it, as it does from the driver
directory of a git driver version (ADR-079).

The action's Job has no server settings and no database. This module must
import without them: it imports only Prefect and the driver modules ``hash``
and ``exceptions``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from prefect.client.orchestration import get_client
from prefect.logging.loggers import PrefectLogAdapter, flow_run_logger, get_logger

from styrmin_backend.services.driver.exceptions import (
    DriverFilesNotFoundError,
    DriverFingerprintMismatchError,
    describe_action_image,
)
from styrmin_backend.services.driver.hash import compute_driver_directory_fingerprint

# Set by the Prefect worker in the environment of the flow run's Job.
FLOW_RUN_ID_ENV = "PREFECT__FLOW_RUN_ID"

_logger_outside_flow_run = get_logger(__name__)


def check_local_driver_files(
    directory: str,
    content_hash: str,
    spec_file: str,
    values_template: str,
    actions_file: str,
) -> str:
    """Check that the driver files at ``directory`` have the provenance fingerprint ``content_hash``.

    The pull step :func:`check_local_driver` and
    ``LocalDriverActionWorkflowDefinition.get_function`` run this check before
    they import the action. The image named in the errors is read from the
    Prefect API only when the check fails.

    Args:
        directory: The path that the driver version was loaded from.
        content_hash: The full provenance fingerprint of the driver version.
        spec_file: The name of the driver specification file.
        values_template: The name of the values template; a missing one hashes as empty.
        actions_file: The name of the actions file.

    Returns:
        The provenance fingerprint of the files at ``directory``.

    Raises:
        DriverFilesNotFoundError: ``directory`` is not a directory, or the driver
            specification file or the actions file is missing in it.
        DriverFingerprintMismatchError: the files at ``directory`` have another
            provenance fingerprint.
    """
    path = Path(directory)
    if not path.is_dir():
        image, work_pool = _action_image()
        raise DriverFilesNotFoundError(
            path=directory, image=image, work_pool=work_pool, missing=[directory]
        )
    missing = [
        name for name in (spec_file, actions_file) if not (path / name).is_file()
    ]
    if missing:
        image, work_pool = _action_image()
        raise DriverFilesNotFoundError(
            path=directory, image=image, work_pool=work_pool, missing=missing
        )

    actual = compute_driver_directory_fingerprint(
        path,
        spec_file=spec_file,
        values_template=values_template,
        actions_file=actions_file,
        include_actions=True,
    )
    if actual != content_hash:
        image, work_pool = _action_image()
        raise DriverFingerprintMismatchError(
            path=directory,
            image=image,
            work_pool=work_pool,
            expected=content_hash,
            actual=actual,
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

    Runs :func:`check_local_driver_files`, logs the path and the short
    provenance fingerprint in the flow run, and returns ``{"directory": directory}``.
    Prefect then changes into ``directory`` and imports the deployment's
    entrypoint from it. The step never imports the actions file.

    Raises:
        DriverFilesNotFoundError: see :func:`check_local_driver_files`.
        DriverFingerprintMismatchError: see :func:`check_local_driver_files`.
    """
    fingerprint = check_local_driver_files(
        directory=directory,
        content_hash=content_hash,
        spec_file=spec_file,
        values_template=values_template,
        actions_file=actions_file,
    )
    _logger().info(
        "The driver files at %s have the provenance fingerprint %s of the driver version. "
        "The action runs from %s.",
        directory,
        fingerprint[:7],
        directory,
    )
    return {"directory": directory}


# The fully qualified name of the pull step, which Prefect imports in the action's Job.
CHECK_LOCAL_DRIVER_STEP = f"{__name__}.{check_local_driver.__name__}"


def _flow_run_id() -> UUID | None:
    """The id of the flow run whose Job runs this process, or None outside such a Job."""
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


def _work_pool_default_image(base_job_template: dict[str, Any]) -> str | None:
    """The default of the ``image`` variable in a work pool's base job template."""
    image = (
        base_job_template.get("variables", {})
        .get("properties", {})
        .get("image", {})
        .get("default")
    )
    return str(image) if image else None


def _action_image() -> tuple[str | None, str | None]:
    """The image of this action's Job and its work pool, named in the errors of the check (research R-006).

    Reads the flow run in ``PREFECT__FLOW_RUN_ID``, then the ``image`` job
    variable of its deployment, otherwise the default image of its work pool.
    Returns ``(image, work_pool)``; either is ``None`` when the Prefect API
    does not give it, and the error then names the image as
    ``describe_action_image`` does. A failure to read the API is logged and
    returns what was read before it, so it never replaces the error of the check.
    """
    flow_run_id = _flow_run_id()
    if flow_run_id is None:
        return None, None

    image: str | None = None
    work_pool_name: str | None = None
    try:
        with get_client(sync_client=True) as client:
            flow_run = client.read_flow_run(flow_run_id)
            work_pool_name = flow_run.work_pool_name
            if flow_run.deployment_id is not None:
                deployment = client.read_deployment(flow_run.deployment_id)
                work_pool_name = work_pool_name or deployment.work_pool_name
                image = deployment.job_variables.get("image") or None
            if image is None and work_pool_name:
                image = _work_pool_default_image(
                    client.read_work_pool(work_pool_name).base_job_template
                )
    except Exception:  # noqa: BLE001 - the error of the check must reach the hook step
        _logger().warning(
            "Could not read the image of this action's Job from the Prefect API; the error names %s instead.",
            describe_action_image(None, work_pool_name),
            exc_info=True,
        )
        return None, work_pool_name

    return (str(image) if image else None), work_pool_name
