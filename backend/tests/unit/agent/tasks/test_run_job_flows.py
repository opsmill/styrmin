"""The ``run_job`` split (spec 019, research D11).

``run_job`` is the INTERNAL flow: it keeps the task callbacks, holds the
action token and runs the USER flow ``run_job_command``, which creates the
Kubernetes Job and records the ``command`` step.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from styrmin_backend import config
from styrmin_backend.agent.service.kubernetes.exceptions import JobFailedError
from styrmin_backend.agent.tasks import orchestration
from styrmin_backend.agent.tasks.orchestration import (
    RUN_JOB_COMMAND_DEPLOYMENT,
    orchestration_callback,
    run_job,
    run_job_command,
)
from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from styrmin_backend.domain.models import StepParent
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import PrefectAction
from tests.helpers.step_api import FakeStepApi

Event = tuple[Any, ...]


def _job(task_id: UUID) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "runtime_class": "kata",
        "env": [{"name": "GREETING", "value": "hello"}],
        "namespace": "styrmin-app",
        "commands": ["sh", "-c", "echo $GREETING"],
        "image": "busybox:1.36",
    }


def _expected_manifest(task_id: UUID) -> dict[str, Any]:
    """The Job manifest ``run_job`` built before the split."""
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "namespace": "styrmin-app",
            "generateName": f"job-run-{task_id}-",
        },
        "spec": {
            "template": {
                "spec": {
                    "parallelism": 1,
                    "completions": 1,
                    "restartPolicy": "Never",
                    "runtimeClassName": "kata",
                    "affinity": {
                        "podAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": [
                                {
                                    "labelSelector": {
                                        "matchLabels": {
                                            "helm.neo4j.com/pod_category": "neo4j-instance"
                                        }
                                    },
                                    "topologyKey": "kubernetes.io/hostname",
                                }
                            ]
                        }
                    },
                    "tolerations": [
                        {
                            "effect": "NoExecute",
                            "key": "node.kubernetes.io/not-ready",
                            "operator": "Exists",
                            "tolerationSeconds": 60,
                        },
                        {
                            "effect": "NoExecute",
                            "key": "node.kubernetes.io/unreachable",
                            "operator": "Exists",
                            "tolerationSeconds": 60,
                        },
                    ],
                    "containers": [
                        {
                            "name": "prefect-job",
                            "image": "busybox:1.36",
                            "env": [{"name": "GREETING", "value": "hello"}],
                            "command": ["sh", "-c", "echo $GREETING"],
                        }
                    ],
                }
            }
        },
    }


@pytest.fixture
def events() -> list[Event]:
    return []


# run_job (INTERNAL)


@pytest.fixture
def wrapper(monkeypatch: pytest.MonkeyPatch, events: list[Event]) -> SimpleNamespace:
    """Mocks of the token, the command flow, the step writes and the task callback."""

    @asynccontextmanager
    async def _action_api_token():
        events.append(("token created",))
        try:
            yield "action-token"
        finally:
            events.append(("token revoked",))

    async def _run_command(**kwargs: Any) -> None:
        events.append(("command flow", kwargs["name"]))

    async def _fail_open_steps(parent: StepParent, message: str) -> None:
        events.append(("open steps failed", parent, message))

    class _CallbackClient:
        def __init__(self, **_: Any) -> None:
            pass

        async def __aenter__(self) -> _CallbackClient:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def post(self, _url: str, *, json: dict) -> None:
            variables = json["variables"]
            events.append(("callback", variables["stateName"], variables["taskId"]))

    run_command = AsyncMock(side_effect=_run_command)
    fail_open = AsyncMock(side_effect=_fail_open_steps)
    monkeypatch.setattr(orchestration, "action_api_token", _action_api_token)
    monkeypatch.setattr(orchestration, "run_deployment_or_fail", run_command)
    monkeypatch.setattr(orchestration, "fail_open_steps", fail_open)
    monkeypatch.setattr(
        orchestration, "httpx", SimpleNamespace(AsyncClient=_CallbackClient)
    )
    return SimpleNamespace(run_command=run_command, fail_open=fail_open)


async def test_run_job_runs_the_command_flow_with_an_action_token(
    wrapper: SimpleNamespace, events: list[Event]
) -> None:
    task_id = uuid4()

    await run_job(**_job(task_id))

    wrapper.run_command.assert_awaited_once_with(
        name=RUN_JOB_COMMAND_DEPLOYMENT,
        parameters=_job(task_id),
        job_variables={
            "env": {API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(task_id)}
        },
    )
    wrapper.fail_open.assert_not_awaited()
    assert events == [
        ("callback", "Running", str(task_id)),
        ("token created",),
        ("command flow", RUN_JOB_COMMAND_DEPLOYMENT),
        ("token revoked",),
        ("callback", "Completed", str(task_id)),
    ]


async def test_run_job_fails_open_steps_before_raising(
    wrapper: SimpleNamespace, events: list[Event]
) -> None:
    task_id = uuid4()
    error = RuntimeError("Deployment flow run 42 crashed: pod evicted")
    wrapper.run_command.side_effect = error

    with pytest.raises(RuntimeError, match="pod evicted"):
        await run_job(**_job(task_id))

    wrapper.fail_open.assert_awaited_once_with(StepParent.of_task(task_id), str(error))
    assert events == [
        ("callback", "Running", str(task_id)),
        ("token created",),
        ("open steps failed", StepParent.of_task(task_id), str(error)),
        ("token revoked",),
        ("callback", "Failed", str(task_id)),
    ]


def test_only_run_job_reports_the_task_state() -> None:
    for hooks in (
        run_job.on_running_hooks,
        run_job.on_completion_hooks,
        run_job.on_failure_hooks,
        run_job.on_crashed_hooks,
        run_job.on_cancellation_hooks,
    ):
        assert hooks == [orchestration_callback]
    assert not any(
        (
            run_job_command.on_running_hooks,
            run_job_command.on_completion_hooks,
            run_job_command.on_failure_hooks,
            run_job_command.on_crashed_hooks,
            run_job_command.on_cancellation_hooks,
        )
    )


def test_catalogue_runs_run_job_internally_and_its_command_as_a_user_flow() -> None:
    catalogue = PrefectCatalogue()

    wrapper = catalogue.get_workflow_definition(PrefectAction.RUN_JOB)
    command = catalogue.get_workflow_definition(PrefectAction.RUN_JOB_COMMAND)

    assert (wrapper.type, wrapper.get_function()) == (WorkflowType.INTERNAL, run_job)
    assert (command.type, command.get_function()) == (
        WorkflowType.USER,
        run_job_command,
    )
    assert command.full_name == RUN_JOB_COMMAND_DEPLOYMENT
    assert "action/run_job_command" in command.tags


# run_job_command (USER)


@pytest.fixture
def step_api(
    monkeypatch: pytest.MonkeyPatch, events: list[Event]
) -> tuple[FakeStepApi, UUID]:
    for name in (BACKUP_ID_ENV, RESTORE_ID_ENV, STEP_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    task_id = uuid4()
    monkeypatch.setenv(API_TOKEN_ENV, "action-token")
    monkeypatch.setenv(TASK_ID_ENV, str(task_id))
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    api = FakeStepApi(events)
    api.install(monkeypatch)
    return api, task_id


@pytest.fixture
def kubernetes_job(monkeypatch: pytest.MonkeyPatch, events: list[Event]) -> AsyncMock:
    async def _run(*, manifest: dict, namespace: str) -> None:
        events.append(("kubernetes job", namespace))

    run = AsyncMock(side_effect=_run)
    monkeypatch.setattr(orchestration, "run_kubernetes_job", run)
    return run


async def test_run_job_command_runs_the_job_as_the_command_step(
    step_api: tuple[FakeStepApi, UUID],
    kubernetes_job: AsyncMock,
    events: list[Event],
) -> None:
    api, task_id = step_api

    await run_job_command(**_job(task_id))

    kubernetes_job.assert_awaited_once_with(
        manifest=_expected_manifest(task_id), namespace="styrmin-app"
    )
    assert events == [
        ("STARTED", "command"),
        ("kubernetes job", "styrmin-app"),
        ("SUCCEEDED", "command"),
    ]
    started = api.started("command")
    assert (started["taskId"], started["name"], started["kind"]) == (
        str(task_id),
        "Run the job's command",
        "COMMAND",
    )


async def test_run_job_command_records_a_failed_job_and_raises(
    step_api: tuple[FakeStepApi, UUID],
    kubernetes_job: AsyncMock,
    events: list[Event],
) -> None:
    api, task_id = step_api
    kubernetes_job.side_effect = JobFailedError("Job job-run-1 failed in namespace x")

    with pytest.raises(JobFailedError):
        await run_job_command(**_job(task_id))

    assert events == [("STARTED", "command"), ("FAILED", "command")]
    assert api.failed("command")["error"] == (
        "JobFailedError: Job job-run-1 failed in namespace x"
    )


async def test_run_job_command_records_the_job_output_on_the_command_step(
    step_api: tuple[FakeStepApi, UUID],
    kubernetes_job: AsyncMock,
    events: list[Event],
) -> None:
    api, task_id = step_api
    kubernetes_job.side_effect = JobFailedError(
        "Job job-run-1 failed in namespace x",
        output="Traceback: boom\n",
        truncated=True,
    )

    with pytest.raises(JobFailedError):
        await run_job_command(**_job(task_id))

    assert events == [
        ("STARTED", "command"),
        ("OUTPUT", "command"),
        ("FAILED", "command"),
    ]
    output = next(r for r in api.records if r["event"] == "OUTPUT")
    assert output["stepId"] == str(api.ids["command"])
    assert (output["output"], output["outputTruncated"]) == ("Traceback: boom\n", True)
    assert api.failed("command")["error"] == (
        "JobFailedError: Job job-run-1 failed in namespace x"
    )


async def test_run_job_command_without_runtime_class_keeps_the_default(
    step_api: tuple[FakeStepApi, UUID], kubernetes_job: AsyncMock
) -> None:
    _api, task_id = step_api

    await run_job_command(**{**_job(task_id), "runtime_class": ""})

    assert kubernetes_job.await_args is not None
    manifest = kubernetes_job.await_args.kwargs["manifest"]
    assert manifest["spec"]["template"]["spec"]["runtimeClassName"] is None
