"""Pin what ``run_deployment_or_fail`` and its driver-action variant hand to Prefect."""

import io
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from loguru import logger
from prefect.client.schemas.filters import LogFilter
from prefect.client.schemas.objects import FlowRun, Log
from prefect.client.schemas.sorting import LogSort
from prefect.states import Crashed, Failed
from prefect.workers.base import BaseJobConfiguration
from pydantic import SecretStr

from styrmin_backend import config
from styrmin_backend.agent.tasks.utils import (
    BACKUP_ID_ENV,
    FIRST_ERROR_LOG_MAX_LENGTH,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
    action_job_variables,
    run_deployment_or_fail,
    run_driver_action_or_fail,
)
from styrmin_backend.config import API_TOKEN_ENV
from styrmin_backend.services.reconciliation.remediation import (
    Remediation,
    RemediationType,
)

MODULE = "styrmin_backend.agent.tasks.utils"
REMEDIATION_MODULE = "styrmin_backend.services.reconciliation.remediation"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        API_TOKEN_ENV,
        TASK_ID_ENV,
        BACKUP_ID_ENV,
        RESTORE_ID_ENV,
        STEP_ID_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _completed_flow_run() -> MagicMock:
    flow_run = MagicMock()
    flow_run.state.is_failed.return_value = False
    flow_run.state.is_crashed.return_value = False
    return flow_run


@pytest.mark.asyncio
async def test_defaults_poll_interval_to_one_second() -> None:
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_deployment_or_fail(name="flow/deployment", parameters={})

    assert run.await_args is not None
    assert run.await_args.kwargs["poll_interval"] == 1


@pytest.mark.asyncio
async def test_explicit_poll_interval_is_kept() -> None:
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_deployment_or_fail(name="flow/deployment", poll_interval=10)

    assert run.await_args is not None
    assert run.await_args.kwargs["poll_interval"] == 10


# The error of a crashed flow run holds its first ERROR log (spec 029, research R-002).

CRASH_MESSAGE = "Process exited with status code: 1"
CHECK_ERROR = (
    "The driver files at /styrmin/drivers/my-app in the image "
    "registry.opsmill.io/opsmill/styrmin:latest are not the files of this driver "
    "version: their provenance fingerprint is 9b1e2c4, and the driver version was "
    "loaded with 0a7d3f1."
)
_START = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


class FakePrefectClient:
    """A Prefect client whose ``read_logs`` serves ``logs`` as the Prefect API does.

    It keeps the logs that match the filter's flow runs and lowest level, sorts
    them by timestamp and returns at most ``limit``. With ``error`` set, every
    read raises it.
    """

    def __init__(self, logs: list[Log], error: Exception | None = None) -> None:
        self.logs = logs
        self.error = error
        self.reads = 0

    async def __aenter__(self) -> "FakePrefectClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def read_logs(
        self,
        log_filter: LogFilter | None = None,
        limit: int | None = None,
        offset: int | None = None,
        sort: LogSort | None = None,
    ) -> list[Log]:
        self.reads += 1
        if self.error is not None:
            raise self.error
        logs = list(self.logs)
        if log_filter is not None and log_filter.flow_run_id is not None:
            flow_run_ids = log_filter.flow_run_id.any_ or []
            logs = [log for log in logs if log.flow_run_id in flow_run_ids]
        if log_filter is not None and log_filter.level is not None:
            lowest = log_filter.level.ge_ or 0
            logs = [log for log in logs if log.level >= lowest]
        logs.sort(key=lambda log: log.timestamp, reverse=sort == LogSort.TIMESTAMP_DESC)
        return logs[offset or 0 :][:limit]


def _log(flow_run_id: UUID, level: int, message: str, second: int) -> Log:
    return Log(
        name="prefect.flow_runs",
        level=level,
        message=message,
        timestamp=_START + timedelta(seconds=second),
        flow_run_id=flow_run_id,
    )


@pytest.fixture
def warnings_log() -> Iterator[io.StringIO]:
    sink = io.StringIO()
    handler_id = logger.add(sink, level="WARNING", format="{level}|{message}")
    yield sink
    logger.remove(handler_id)


async def _run_and_fail(flow_run: FlowRun, client: FakePrefectClient) -> str:
    """Run a deployment whose flow run ends as ``flow_run``; return the error's text."""
    with (
        patch(f"{MODULE}.arun_deployment", AsyncMock(return_value=flow_run)),
        patch(f"{MODULE}.get_client", return_value=client),
        pytest.raises(RuntimeError) as raised,
    ):
        await run_deployment_or_fail(name="flow/deployment", parameters={})
    return str(raised.value)


@pytest.mark.asyncio
async def test_crashed_run_error_holds_its_first_error_log_and_the_state_message() -> (
    None
):
    flow_run = FlowRun(flow_id=uuid4(), state=Crashed(message=CRASH_MESSAGE))
    other_run_id = uuid4()
    client = FakePrefectClient(
        [
            _log(other_run_id, logging.ERROR, "An error of another flow run", 0),
            _log(flow_run.id, logging.INFO, "Running 1 deployment pull step(s)", 1),
            _log(flow_run.id, logging.ERROR, CHECK_ERROR, 2),
            _log(
                flow_run.id,
                logging.ERROR,
                "Unexpected exception encountered when trying to load flow",
                3,
            ),
        ]
    )

    message = await _run_and_fail(flow_run, client)

    assert message == (
        f"Deployment flow run {flow_run.id} crashed: {CHECK_ERROR} ({CRASH_MESSAGE})"
    )


@pytest.mark.asyncio
async def test_crashed_run_without_an_error_log_keeps_the_state_message(
    warnings_log: io.StringIO,
) -> None:
    flow_run = FlowRun(flow_id=uuid4(), state=Crashed(message=CRASH_MESSAGE))
    client = FakePrefectClient(
        [_log(flow_run.id, logging.INFO, "Running 1 deployment pull step(s)", 0)]
    )

    message = await _run_and_fail(flow_run, client)

    assert message == f"Deployment flow run {flow_run.id} crashed: {CRASH_MESSAGE}"
    assert f"WARNING|Crashed flow run {flow_run.id} has no ERROR log" in (
        warnings_log.getvalue()
    )


@pytest.mark.asyncio
async def test_crashed_run_whose_logs_cannot_be_read_keeps_the_state_message(
    warnings_log: io.StringIO,
) -> None:
    flow_run = FlowRun(flow_id=uuid4(), state=Crashed(message=CRASH_MESSAGE))
    client = FakePrefectClient([], error=RuntimeError("Prefect API is unreachable"))

    message = await _run_and_fail(flow_run, client)

    assert message == f"Deployment flow run {flow_run.id} crashed: {CRASH_MESSAGE}"
    assert client.reads == 1
    warnings = warnings_log.getvalue()
    assert f"WARNING|Could not read the logs of crashed flow run {flow_run.id}" in (
        warnings
    )
    assert "Prefect API is unreachable" in warnings


@pytest.mark.asyncio
async def test_crashed_run_error_cuts_a_long_error_log_to_4000_characters() -> None:
    flow_run = FlowRun(flow_id=uuid4(), state=Crashed(message=CRASH_MESSAGE))
    long_log = "x" * 10_000
    client = FakePrefectClient([_log(flow_run.id, logging.ERROR, long_log, 0)])

    message = await _run_and_fail(flow_run, client)

    assert FIRST_ERROR_LOG_MAX_LENGTH == 4000
    assert message == (
        f"Deployment flow run {flow_run.id} crashed: {'x' * 4000} ({CRASH_MESSAGE})"
    )


@pytest.mark.asyncio
async def test_failed_run_error_is_unchanged() -> None:
    flow_run = FlowRun(
        flow_id=uuid4(),
        state=Failed(message="Flow run encountered an exception: ValueError: boom"),
    )
    client = FakePrefectClient([_log(flow_run.id, logging.ERROR, CHECK_ERROR, 0)])

    message = await _run_and_fail(flow_run, client)

    assert message == (
        f"Deployment flow run {flow_run.id} failed: "
        "Flow run encountered an exception: ValueError: boom"
    )
    assert client.reads == 0


# Driver action token forwarding (issue #381, ADR-059).


@pytest.mark.asyncio
async def test_driver_action_receives_this_jobs_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", SecretStr("action-token"))
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_driver_action_or_fail(name="flow/deployment", parameters={})

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token"}
    }


@pytest.mark.asyncio
async def test_driver_action_without_token_gets_no_job_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", None)
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_driver_action_or_fail(name="flow/deployment", parameters={})

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {}


@pytest.mark.asyncio
async def test_driver_action_forwards_token_and_task_and_adds_hook_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, step_id = uuid4(), uuid4()
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", SecretStr("action-token"))
    monkeypatch.setenv(TASK_ID_ENV, str(task_id))
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_driver_action_or_fail(
            name="flow/deployment", parameters={}, step_id=step_id
        )

    assert run.await_args is not None
    assert "step_id" not in run.await_args.kwargs
    assert run.await_args.kwargs["job_variables"] == {
        "env": {
            API_TOKEN_ENV: "action-token",
            TASK_ID_ENV: str(task_id),
            STEP_ID_ENV: str(step_id),
        }
    }


def test_action_job_variables_sets_each_given_variable() -> None:
    ids = {name: uuid4() for name in ("task", "backup", "restore", "step")}

    variables = action_job_variables(
        "action-token",
        task_id=ids["task"],
        backup_id=ids["backup"],
        restore_id=ids["restore"],
        step_id=ids["step"],
    )

    assert variables == {
        "env": {
            API_TOKEN_ENV: "action-token",
            TASK_ID_ENV: str(ids["task"]),
            BACKUP_ID_ENV: str(ids["backup"]),
            RESTORE_ID_ENV: str(ids["restore"]),
            STEP_ID_ENV: str(ids["step"]),
        }
    }
    assert action_job_variables(None) == {}


@pytest.mark.asyncio
async def test_remediation_passes_token_to_its_flow_run() -> None:
    remediation = Remediation.model_construct(
        instance=MagicMock(id=uuid4()),
        flow_id=uuid4(),
        parameters={},
        type=RemediationType.UPGRADE_INSTANCE,
    )
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{REMEDIATION_MODULE}.run_deployment_or_fail", run):
        await remediation.apply(api_token="action-token")

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token"}
    }


@pytest.mark.asyncio
async def test_remediation_passes_task_id_to_its_flow_run() -> None:
    remediation = Remediation.model_construct(
        instance=MagicMock(id=uuid4()),
        flow_id=uuid4(),
        parameters={},
        type=RemediationType.CREATE_INSTANCE,
    )
    task_id = uuid4()
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{REMEDIATION_MODULE}.run_deployment_or_fail", run):
        await remediation.apply(api_token="action-token", task_id=task_id)

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(task_id)}
    }


@pytest.mark.asyncio
async def test_token_env_merges_with_work_pool_env_defaults() -> None:
    """Prefect adds a flow run's ``env`` to the pool's default env instead of replacing it."""
    base_job_template = {
        "job_configuration": {"env": "{{ env }}", "command": "{{ command }}"},
        "variables": {
            "properties": {
                "env": {
                    "type": "object",
                    "default": {"STYRMIN_URL_API": "http://styrmin:8000"},
                },
                "command": {"type": "string"},
            }
        },
    }
    configuration = await BaseJobConfiguration.from_template_and_values(
        base_job_template=base_job_template,
        values=action_job_variables("action-token", task_id="task-1"),
    )

    assert configuration.env["STYRMIN_URL_API"] == "http://styrmin:8000"
    assert configuration.env[API_TOKEN_ENV] == "action-token"
    assert configuration.env[TASK_ID_ENV] == "task-1"
