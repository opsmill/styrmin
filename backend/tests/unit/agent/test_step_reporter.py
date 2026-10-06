"""The flow step reporter (spec 019, contracts/flow-step-reporter.md)."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from loguru import logger
from pydantic import SecretStr

from styrmin_backend import config
from styrmin_backend.agent.steps import reporter as reporter_module
from styrmin_backend.agent.steps.reporter import StepReporter
from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from styrmin_backend.domain.models import StepKind

_ENV_NAMES = (TASK_ID_ENV, BACKUP_ID_ENV, RESTORE_ID_ENV, STEP_ID_ENV)


class FakeApi:
    """Answers ``recordStep`` like the server and keeps every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.step_id = uuid4()
        self.respond: Callable[[httpx.Request], httpx.Response] = self._ok

    def _ok(self, request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": {"recordStep": {"id": str(self.step_id), "status": "RUNNING"}}
            },
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)

    def inputs(self) -> list[dict]:
        return [json.loads(r.content)["variables"]["input"] for r in self.requests]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", None)
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeApi:
    fake = FakeApi()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        reporter_module,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: real_client(
                transport=httpx.MockTransport(fake.handle), **kwargs
            )
        ),
    )
    return fake


@pytest.fixture
def warnings_log() -> Iterator[io.StringIO]:
    sink = io.StringIO()
    handler_id = logger.add(sink, level="WARNING", format="{level}|{message}")
    yield sink
    logger.remove(handler_id)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        if name == API_TOKEN_ENV:
            # Settings load STYRMIN_TOKEN once per process, so set the loaded value.
            monkeypatch.setattr(config.SETTINGS.agent, "api_token", SecretStr(value))
        else:
            monkeypatch.setenv(name, value)


# No-op mode.


@pytest.mark.asyncio
async def test_without_token_the_reporter_sends_nothing(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, **{TASK_ID_ENV: str(uuid4())})
    reporter = StepReporter.from_env()

    async with reporter.step("plan", "Plan the changes", StepKind.PLAN) as step:
        pass
    await reporter.record_output(uuid4(), "out", truncated=False)
    await reporter.fail_step("plan", "boom")

    assert not reporter.enabled
    assert step.id is None
    assert api.requests == []


@pytest.mark.asyncio
async def test_without_parent_the_reporter_sends_nothing(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token"})
    reporter = StepReporter.from_env()

    async with reporter.step("plan", "Plan the changes", StepKind.PLAN) as step:
        pass

    assert not reporter.enabled
    assert step.id is None
    assert api.requests == []


@pytest.mark.asyncio
async def test_two_parents_or_a_bad_id_turn_reporting_off(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(
        monkeypatch,
        **{
            API_TOKEN_ENV: "action-token",
            TASK_ID_ENV: str(uuid4()),
            BACKUP_ID_ENV: str(uuid4()),
        },
    )
    assert not StepReporter.from_env().enabled

    monkeypatch.delenv(BACKUP_ID_ENV)
    monkeypatch.setenv(TASK_ID_ENV, "not-a-uuid")
    assert not StepReporter.from_env().enabled
    assert api.requests == []


def test_from_env_reads_the_hook_step(monkeypatch: pytest.MonkeyPatch) -> None:
    hook_step = uuid4()
    _env(
        monkeypatch,
        **{
            API_TOKEN_ENV: "action-token",
            TASK_ID_ENV: str(uuid4()),
            STEP_ID_ENV: str(hook_step),
        },
    )

    reporter = StepReporter.from_env()

    assert reporter.enabled
    assert reporter.step_id == hook_step


# One call per event, with the right variables.


@pytest.mark.asyncio
async def test_step_records_started_then_succeeded(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = uuid4()
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(task_id)})
    reporter = StepReporter.from_env()
    before = datetime.now(UTC)

    async with reporter.step(
        "hook:setup:pre", "Run the setup pre-hook", StepKind.HOOK
    ) as step:
        assert step.id == api.step_id

    after = datetime.now(UTC)
    started, succeeded = api.inputs()
    assert {k: v for k, v in started.items() if k != "occurredAt"} == {
        "taskId": str(task_id),
        "key": "hook:setup:pre",
        "event": "STARTED",
        "name": "Run the setup pre-hook",
        "kind": "HOOK",
    }
    assert {k: v for k, v in succeeded.items() if k != "occurredAt"} == {
        "stepId": str(api.step_id),
        "event": "SUCCEEDED",
    }
    for record in (started, succeeded):
        assert before <= datetime.fromisoformat(record["occurredAt"]) <= after
    for request in api.requests:
        assert str(request.url) == "http://styrmin.test/graphql"
        assert request.headers["Authorization"] == "Bearer action-token"
        assert "recordStep" in json.loads(request.content)["query"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("env_name", "variable"),
    [(BACKUP_ID_ENV, "backupId"), (RESTORE_ID_ENV, "restoreId")],
)
async def test_step_addresses_a_backup_or_restore_parent(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch, env_name: str, variable: str
) -> None:
    parent_id = uuid4()
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", env_name: str(parent_id)})

    async with StepReporter.from_env().step(
        "restore:velero", "Run the Velero restore", StepKind.RESTORE
    ):
        pass

    started = api.inputs()[0]
    assert started[variable] == str(parent_id)
    assert "taskId" not in started


@pytest.mark.asyncio
async def test_failing_block_records_failed_and_re_raises(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(uuid4())})
    reporter = StepReporter.from_env()

    with pytest.raises(RuntimeError, match="hook exploded"):
        async with reporter.step("hook:upgrade:core", "Run the upgrade", StepKind.HOOK):
            raise RuntimeError("hook exploded")

    started, failed = api.inputs()
    assert started["event"] == "STARTED"
    assert failed["event"] == "FAILED"
    assert failed["stepId"] == str(api.step_id)
    assert failed["error"] == "RuntimeError: hook exploded"
    assert "occurredAt" in failed


@pytest.mark.asyncio
async def test_record_output_sends_output_on_the_step(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(uuid4())})
    hook_step = uuid4()

    await StepReporter.from_env().record_output(
        hook_step, "line 1\nline 2\n", truncated=True
    )

    (record,) = api.inputs()
    assert {k: v for k, v in record.items() if k != "occurredAt"} == {
        "stepId": str(hook_step),
        "event": "OUTPUT",
        "output": "line 1\nline 2\n",
        "outputTruncated": True,
    }


@pytest.mark.asyncio
async def test_record_output_without_a_step_sends_nothing(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(uuid4())})

    await StepReporter.from_env().record_output(None, "out", truncated=False)

    assert api.requests == []


@pytest.mark.asyncio
async def test_fail_step_addresses_the_step_by_key(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    restore_id = uuid4()
    _env(
        monkeypatch, **{API_TOKEN_ENV: "action-token", RESTORE_ID_ENV: str(restore_id)}
    )
    reporter = StepReporter.from_env()

    await reporter.fail_step("restore:velero", "PartiallyFailed")
    await reporter.fail_step(
        "restore:recovery", "exit 3", output="tail", output_truncated=True
    )

    without_output, with_output = api.inputs()
    assert {k: v for k, v in without_output.items() if k != "occurredAt"} == {
        "restoreId": str(restore_id),
        "key": "restore:velero",
        "event": "FAILED",
        "error": "PartiallyFailed",
    }
    assert with_output["output"] == "tail"
    assert with_output["outputTruncated"] is True


# Errors are logged, never raised.


def _connect_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _graphql_error(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(
        200,
        json={
            "data": None,
            "errors": [
                {"message": "Only the actions service account can record steps"}
            ],
        },
    )


def _server_error(request: httpx.Request) -> httpx.Response:
    del request
    return httpx.Response(502, text="Bad Gateway")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("respond", "logged"),
    [
        (_connect_error, "connection refused"),
        (_graphql_error, "Only the actions service account can record steps"),
        (_server_error, "Could not record STARTED"),
    ],
    ids=["network", "graphql", "not-json"],
)
async def test_failed_writes_are_logged_not_raised(
    api: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    warnings_log: io.StringIO,
    respond: Callable[[httpx.Request], httpx.Response],
    logged: str,
) -> None:
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(uuid4())})
    api.respond = respond
    reporter = StepReporter.from_env()

    async with reporter.step("plan", "Plan the changes", StepKind.PLAN) as step:
        ran = True
    await reporter.record_output(uuid4(), "out", truncated=False)
    await reporter.fail_step("plan", "boom")

    assert ran
    assert step.id is None
    assert len(api.requests) == 4
    assert logged in warnings_log.getvalue()
    assert warnings_log.getvalue().startswith("WARNING|")


@pytest.mark.asyncio
async def test_succeeded_falls_back_to_the_key_when_started_was_lost(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = uuid4()
    _env(monkeypatch, **{API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(task_id)})
    responses = iter([_connect_error, api.respond])
    api.respond = lambda request: next(responses)(request)

    async with StepReporter.from_env().step(
        "plan", "Plan the changes", StepKind.PLAN
    ) as step:
        assert step.id is None

    succeeded = api.inputs()[1]
    assert succeeded["event"] == "SUCCEEDED"
    assert succeeded["taskId"] == str(task_id)
    assert succeeded["key"] == "plan"
    assert "stepId" not in succeeded
