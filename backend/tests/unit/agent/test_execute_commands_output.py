"""``execute_commands`` records a failed command's output on its hook step (spec 019, research D10)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from styrmin_backend import config
from styrmin_backend.actions import primitives as action_primitives
from styrmin_backend.actions.primitives import execute_commands
from styrmin_backend.agent.service.kubernetes import primitives as k8s_primitives
from styrmin_backend.agent.service.kubernetes.exceptions import JobFailedError
from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from tests.helpers.fake_kubernetes import FakeKubernetes, FakePod, serve
from tests.helpers.step_api import FakeStepApi

NAMESPACE = "styrmin-app"
#: ``execute_commands`` names its Job after the release reference.
JOB = "app-release-job"
HOOK_STEP = "hook:upgrade:core"

Event = tuple[Any, ...]


@pytest.fixture
def events() -> list[Event]:
    return []


@pytest.fixture
def step_api(monkeypatch: pytest.MonkeyPatch, events: list[Event]) -> FakeStepApi:
    """The action Job's environment: an action token, the task and the hook step."""
    for name in (BACKUP_ID_ENV, RESTORE_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    api = FakeStepApi(events)
    api.ids[HOOK_STEP] = uuid4()
    monkeypatch.setenv(API_TOKEN_ENV, "action-token")
    monkeypatch.setenv(TASK_ID_ENV, str(uuid4()))
    monkeypatch.setenv(STEP_ID_ENV, str(api.ids[HOOK_STEP]))
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    api.install(monkeypatch)
    return api


@pytest.fixture
def cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[FakeKubernetes], Any]:
    """Run ``execute_commands``' Job against a fake Kubernetes API."""

    @asynccontextmanager
    async def _serve(fake: FakeKubernetes) -> AsyncIterator[FakeKubernetes]:
        async with serve(fake) as client:
            monkeypatch.setattr(
                action_primitives,
                "run_job",
                partial(k8s_primitives.run_job, client=client),
            )
            yield fake

    return _serve


def _context() -> MagicMock:
    context = MagicMock()
    context.instance.namespace = NAMESPACE
    context.instance.release_reference = "app-release"
    return context


def _job_pod(log: bytes) -> FakePod:
    return FakePod(
        name=f"{JOB}-abcde",
        labels={"batch.kubernetes.io/job-name": JOB},
        created=datetime(2026, 10, 6, 10, 0, tzinfo=UTC),
        logs={"user-job": log},
    )


async def _execute() -> None:
    await execute_commands.fn(
        commands=["sh", "-c", "echo step-output-1; echo step-output-2; exit 3"],
        image="busybox:1.36",
        context=_context(),
    )


def _outputs(api: FakeStepApi) -> list[dict]:
    return [record for record in api.records if record["event"] == "OUTPUT"]


async def test_failed_job_records_its_output_on_the_hook_step_then_raises(
    step_api: FakeStepApi, cluster: Callable[[FakeKubernetes], Any]
) -> None:
    fake = FakeKubernetes(pods=[_job_pod(b"step-output-1\nstep-output-2\n")])

    async with cluster(fake):
        with pytest.raises(JobFailedError) as raised:
            await _execute()

    assert str(raised.value) == f"Job {JOB} failed in namespace {NAMESPACE}"
    output = _outputs(step_api)
    assert len(output) == 1
    assert output[0]["stepId"] == str(step_api.ids[HOOK_STEP])
    assert (output[0]["output"], output[0]["outputTruncated"]) == (
        "step-output-1\nstep-output-2\n",
        False,
    )
    assert fake.log_reads[0]["container"] == "user-job"


async def test_cut_output_is_recorded_as_truncated(
    step_api: FakeStepApi, cluster: Callable[[FakeKubernetes], Any]
) -> None:
    log = b"".join(f"line {n}\n".encode() for n in range(250))

    async with cluster(FakeKubernetes(pods=[_job_pod(log)])):
        with pytest.raises(JobFailedError):
            await _execute()

    (output,) = _outputs(step_api)
    assert output["outputTruncated"] is True
    assert output["output"].splitlines()[0] == "line 50"


async def test_output_that_cannot_be_read_is_named_in_the_error(
    step_api: FakeStepApi, cluster: Callable[[FakeKubernetes], Any]
) -> None:
    async with cluster(FakeKubernetes()):
        with pytest.raises(JobFailedError) as raised:
            await _execute()

    assert str(raised.value) == (
        f"Job {JOB} failed in namespace {NAMESPACE}. The output could not be read: "
        f"no pod of Job {JOB} was found in namespace {NAMESPACE}"
    )
    assert raised.value.output is None
    assert _outputs(step_api) == []


async def test_without_a_hook_step_the_failure_is_still_raised(
    step_api: FakeStepApi,
    cluster: Callable[[FakeKubernetes], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(STEP_ID_ENV)

    async with cluster(FakeKubernetes(pods=[_job_pod(b"boom\n")])):
        with pytest.raises(JobFailedError):
            await _execute()

    assert step_api.records == []


async def test_succeeded_job_records_nothing(
    step_api: FakeStepApi, cluster: Callable[[FakeKubernetes], Any]
) -> None:
    async with cluster(FakeKubernetes(job_succeeds=True)) as fake:
        await _execute()

    assert step_api.records == []
    assert fake.log_reads == []
