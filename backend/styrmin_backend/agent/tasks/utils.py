import logging
import os
import re
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from loguru import logger
from prefect import get_run_logger
from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import (
    LogFilter,
    LogFilterFlowRunId,
    LogFilterLevel,
)
from prefect.client.schemas.objects import FlowRun
from prefect.client.schemas.sorting import LogSort
from prefect.deployments.flow_runs import arun_deployment
from prefect.exceptions import MissingContextError

from styrmin_backend import config
from styrmin_backend.config import API_TOKEN_ENV
from styrmin_backend.services.driver.driver_directory import redact_user_info

#: The parent of the steps a USER flow run records; exactly one is set (019 research D3).
TASK_ID_ENV = "STYRMIN_TASK_ID"
BACKUP_ID_ENV = "STYRMIN_BACKUP_ID"
RESTORE_ID_ENV = "STYRMIN_RESTORE_ID"
#: The hook step that runs a driver action.
STEP_ID_ENV = "STYRMIN_STEP_ID"
#: The most characters of a crashed flow run's first error log that its error holds.
FIRST_ERROR_LOG_MAX_LENGTH = 4000
#: What replaces a secret in the first error log of a crashed driver action.
REDACTED = "<redacted>"
# ``Bearer <credential>`` or ``Basic <credential>``, as in an Authorization header.
_AUTHORIZATION = re.compile(r"(?i)\b(bearer|basic)(\s+)[^\s\"',;]+")
# A key whose name says it holds a secret, then ``=`` or ``:``, then its value.
_SECRET_FIELD = re.compile(
    r"(?i)\b([\w.-]*(?:password|passwd|secret|token|api[_-]?key|private[_-]?key"
    r"|credential)[\w.-]*)([\"']?\s*[:=]\s*[\"']?)([^\s\"',;}]+)"
)


def action_job_variables(
    token: str | None,
    *,
    task_id: UUID | str | None = None,
    backup_id: UUID | str | None = None,
    restore_id: UUID | str | None = None,
    step_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Prefect job variables that set the action token and the step parent in the flow run's environment."""
    env = {
        name: str(value)
        for name, value in (
            (API_TOKEN_ENV, token),
            (TASK_ID_ENV, task_id),
            (BACKUP_ID_ENV, backup_id),
            (RESTORE_ID_ENV, restore_id),
            (STEP_ID_ENV, step_id),
        )
        if value
    }
    return {"env": env} if env else {}


def log_in_run(level: int, message: str) -> None:
    """Log ``message`` in the current flow or task run, so it shows in that run's logs.

    Outside a flow or task run, ``message`` goes to the process log (loguru).
    """
    try:
        get_run_logger().log(level, "%s", message)
    except MissingContextError:
        logger.log(logging.getLevelName(level), message)


def redact_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    """Return ``text`` with the secrets that it may hold replaced by ``REDACTED``.

    Replaces each value of ``secrets``, such as the action token; the user
    info of every ``scheme://`` URL; the credential after ``Bearer`` or
    ``Basic``; and the value after ``=`` or ``:`` of a key whose name contains
    ``password``, ``passwd``, ``secret``, ``token``, ``api_key``,
    ``private_key`` or ``credential``. A secret written in any other form is
    kept.

    >>> redact_secrets("login failed: password=hunter2 for https://u:p@db/x", ["t0k"])
    'login failed: password=<redacted> for https://db/x'
    >>> redact_secrets("STYRMIN_TOKEN is t0k", ["t0k"])
    'STYRMIN_TOKEN is <redacted>'
    >>> redact_secrets('{"api_key": "abc"} Authorization: Bearer xyz')
    '{"api_key": "<redacted>"} Authorization: Bearer <redacted>'
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = redact_user_info(text)
    text = _AUTHORIZATION.sub(rf"\1\2{REDACTED}", text)
    return _SECRET_FIELD.sub(rf"\1\2{REDACTED}", text)


async def _first_error_log(flow_run_id: UUID) -> str | None:
    """The first ``ERROR`` log of a flow run, cut to ``FIRST_ERROR_LOG_MAX_LENGTH`` characters.

    A flow run crashes when its process exits before the flow starts, for example
    when the check of a local driver version's files raises (spec 029,
    research R-002). Prefect's state message then holds only the exit status,
    and the error that explains the crash is in the flow run's logs. Returns
    ``None``, and logs a warning in the calling flow run, when the flow run has
    no such log or the logs cannot be read; the caller then keeps the state
    message alone.
    """
    try:
        async with get_client() as client:
            logs = await client.read_logs(
                LogFilter(
                    flow_run_id=LogFilterFlowRunId(any_=[flow_run_id]),
                    level=LogFilterLevel(ge_=logging.ERROR),
                ),
                limit=1,
                sort=LogSort.TIMESTAMP_ASC,
            )
    except Exception as exc:  # noqa: BLE001 - the crash must still raise its error
        log_in_run(
            logging.WARNING,
            f"Could not read the logs of crashed flow run {flow_run_id}; its error "
            f"holds only the state message: {exc}",
        )
        return None
    if not logs:
        log_in_run(
            logging.WARNING,
            f"Crashed flow run {flow_run_id} has no ERROR log; its error holds only "
            "the state message",
        )
        return None
    return logs[0].message[:FIRST_ERROR_LOG_MAX_LENGTH]


async def _run_deployment_or_fail(
    kwargs: dict[str, Any], *, crash_log_secrets: list[str] | None
) -> FlowRun:
    """Run a Prefect deployment and raise if the flow run fails or crashes.

    With ``crash_log_secrets`` set, the error of a crashed flow run holds its
    first ``ERROR`` log, redacted with :func:`redact_secrets` and these
    secrets, followed by the state message in parentheses.
    """
    # Prefect's 5s default rounds every hook/remediation wait up to 5s.
    kwargs.setdefault("poll_interval", 1)
    flow_run: FlowRun = await arun_deployment(**kwargs)
    if flow_run.state and flow_run.state.is_failed():
        raise RuntimeError(
            f"Deployment flow run {flow_run.id} failed: {flow_run.state.message}"
        )
    if flow_run.state and flow_run.state.is_crashed():
        detail = flow_run.state.message
        if crash_log_secrets is not None:
            first_error = await _first_error_log(flow_run.id)
            if first_error:
                detail = f"{redact_secrets(first_error, crash_log_secrets)} ({detail})"
        raise RuntimeError(f"Deployment flow run {flow_run.id} crashed: {detail}")
    return flow_run


async def run_deployment_or_fail(**kwargs: Any) -> FlowRun:
    """Run a Prefect deployment and raise if the flow run fails or crashes.

    The error holds the flow run's state message. Only a driver action's error
    holds its logs (:func:`run_driver_action_or_fail`).
    """
    return await _run_deployment_or_fail(kwargs, crash_log_secrets=None)


async def run_driver_action_or_fail(
    *, step_id: UUID | None = None, **kwargs: Any
) -> FlowRun:
    """``run_deployment_or_fail`` for a driver action run by the hook step ``step_id``.

    Forwards this flow run's API token and task id, and adds the hook step.
    The error of a crashed action holds its first ``ERROR`` log, with the
    action token and the other secrets that :func:`redact_secrets` finds
    replaced (spec 029, research R-002), followed by the state message.
    """
    token = config.SETTINGS.agent.api_token
    secret = token.get_secret_value() if token else None
    return await _run_deployment_or_fail(
        {
            "job_variables": action_job_variables(
                secret,
                task_id=os.environ.get(TASK_ID_ENV),
                step_id=step_id,
            ),
            **kwargs,
        },
        crash_log_secrets=[secret] if secret else [],
    )
