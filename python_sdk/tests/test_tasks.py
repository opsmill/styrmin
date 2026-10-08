"""Tests for task resource operations."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from styrmin_sdk import FailedStep, ResourceNotFoundError, StyrminClient
from styrmin_sdk.models import StepKind, StepOutput, StepStatus, TaskResult

TASK_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
STARTED_TASK_ID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
NESTED_TASK_ID = "cccccccc-dddd-eeee-ffff-000000000000"
DEPLOYMENT_ID = "11111111-2222-3333-4444-555555555555"
HELMRELEASE_ERROR = "UpgradeFailed: Helm upgrade failed. Pods not ready: my-app-6d9 (app: ImagePullBackOff)"


def _step(
    key: str,
    name: str,
    status: str,
    *,
    error: str | None = None,
    has_output: bool = False,
    started_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors = [] if error is None else [{"attempt": 1, "message": error, "occurredAt": "2026-10-06T10:01:05+00:00"}]
    return {
        "id": str(uuid5(NAMESPACE_URL, key)),
        "key": key,
        "name": name,
        "kind": "OPERATOR_PHASE" if key.startswith("operator:") else "HOOK",
        "status": status,
        "startedAt": "2026-10-06T10:00:00+00:00",
        "endedAt": None if status == "RUNNING" else "2026-10-06T10:01:05+00:00",
        "durationSeconds": None if status == "RUNNING" else 65.0,
        "attemptCount": 1,
        "errors": errors,
        "error": error,
        "detail": None,
        "rolledBackAt": None,
        "rollbackMessage": None,
        "hasOutput": has_output,
        "supersededBy": None,
        "startedTasks": started_tasks or [],
        "noReportSince": None,
    }


def _task_response(
    task_id: str,
    steps: list[dict[str, Any]],
    *,
    result: str = "FAILED",
    started_tasks: list[dict[str, Any]] | None = None,
    started_by: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "task": {
                "id": task_id,
                "type": "update_instance",
                "status": "completed",
                "message": None,
                "deploymentId": DEPLOYMENT_ID,
                "createdOn": "2026-10-06T10:00:00+00:00",
                "result": result,
                "startedByStepId": None if started_by is None else "99999999-8888-7777-6666-555555555555",
                "startedBy": started_by,
                "startedTasks": started_tasks or [],
                "steps": steps,
            }
        }
    }


def _started_task(task_id: str, result: str = "FAILED") -> dict[str, Any]:
    return {"id": task_id, "type": "deploy", "status": "completed", "result": result}


async def test_get_task_returns_steps_result_and_started_tasks(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = _task_response(
        TASK_ID,
        [
            _step("plan", "Plan the changes", "SUCCEEDED"),
            _step("hook:upgrade:core", "Run the upgrade hook", "FAILED", error="boom", has_output=True),
            _step("operator:helmrelease", "Install or upgrade the HelmRelease", "RUNNING"),
        ],
        started_tasks=[_started_task(STARTED_TASK_ID, "SUCCEEDED")],
    )

    task = await client.tasks.get(TASK_ID)

    assert task.result == TaskResult.FAILED
    assert [step.key for step in task.steps] == ["plan", "hook:upgrade:core", "operator:helmrelease"]
    hook = task.steps[1]
    assert hook.kind == StepKind.HOOK
    assert hook.status == StepStatus.FAILED
    assert hook.error == "boom"
    assert hook.errors[0].message == "boom"
    assert hook.has_output is True
    assert task.steps[2].duration_seconds is None
    assert task.started_tasks[0].id == UUID(STARTED_TASK_ID)
    assert task.started_tasks[0].result == TaskResult.SUCCEEDED
    query, variables = mock_transport.execute.call_args.args
    # Step.output is read one step at a time, with step_output().
    assert re.search(r"\boutput(Truncated)?\b", query) is None
    assert variables == {"taskId": TASK_ID}


async def test_get_task_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"task": None},
        "errors": [{"message": "Task not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError):
        await client.tasks.get(TASK_ID)


async def test_step_output_reads_one_step(client: StyrminClient, mock_transport: AsyncMock) -> None:
    step_id = str(uuid5(NAMESPACE_URL, "hook:upgrade:core"))
    mock_transport.execute.return_value = {
        "data": {"step": {"id": step_id, "output": "line 1\nline 2", "outputTruncated": True}}
    }

    output = await client.tasks.step_output(step_id)

    assert output == StepOutput.model_validate({"id": step_id, "output": "line 1\nline 2", "outputTruncated": True})
    query, variables = mock_transport.execute.call_args.args
    assert "query GetStepOutput" in query
    assert variables == {"stepId": step_id}


async def test_step_output_not_found(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.return_value = {
        "data": {"step": None},
        "errors": [{"message": "Step not found", "extensions": {"code": "NOT_FOUND"}}],
    }

    with pytest.raises(ResourceNotFoundError):
        await client.tasks.step_output(str(uuid5(NAMESPACE_URL, "missing")))


async def test_failed_step_finds_the_first_failed_step_of_the_task(
    client: StyrminClient, mock_transport: AsyncMock
) -> None:
    mock_transport.execute.return_value = _task_response(
        TASK_ID,
        [
            _step("operator:prerequisites", "Create network policies and secrets", "SUCCEEDED"),
            _step("operator:helmrelease", "Install or upgrade the HelmRelease", "FAILED", error=HELMRELEASE_ERROR),
            _step("operator:ready", "Wait for the pods to be ready", "FAILED", error="later failure"),
        ],
        started_tasks=[_started_task(STARTED_TASK_ID)],
    )

    step = await client.tasks.failed_step(TASK_ID)

    assert step == FailedStep(name="Install or upgrade the HelmRelease", task_id=UUID(TASK_ID), error=HELMRELEASE_ERROR)
    # The task's own failed step wins: its started tasks are not read.
    assert mock_transport.execute.await_count == 1


async def test_failed_step_searches_the_started_tasks(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _task_response(
            TASK_ID,
            [_step("hook:upgrade:core", "Run the upgrade hook", "SUCCEEDED")],
            started_tasks=[_started_task(STARTED_TASK_ID, "SUCCEEDED"), _started_task(NESTED_TASK_ID)],
        ),
        _task_response(STARTED_TASK_ID, [_step("plan", "Plan the changes", "SUCCEEDED")], result="SUCCEEDED"),
        _task_response(
            NESTED_TASK_ID,
            [_step("operator:helmrelease", "Install or upgrade the HelmRelease", "FAILED", error=HELMRELEASE_ERROR)],
        ),
    ]

    step = await client.tasks.failed_step(TASK_ID)

    assert step is not None
    assert step.name == "Install or upgrade the HelmRelease"
    assert step.task_id == UUID(NESTED_TASK_ID)
    assert step.error == HELMRELEASE_ERROR
    read = [call.args[1]["taskId"] for call in mock_transport.execute.call_args_list]
    assert read == [TASK_ID, STARTED_TASK_ID, NESTED_TASK_ID]


async def test_failed_step_returns_none_without_a_failed_step(client: StyrminClient, mock_transport: AsyncMock) -> None:
    mock_transport.execute.side_effect = [
        _task_response(
            TASK_ID,
            [
                _step("plan", "Plan the changes", "SUCCEEDED"),
                _step("operator:helmrelease", "Install or upgrade the HelmRelease", "SUPERSEDED"),
            ],
            started_tasks=[_started_task(STARTED_TASK_ID, "SUCCEEDED")],
        ),
        _task_response(STARTED_TASK_ID, [], result="SUCCEEDED"),
    ]

    assert await client.tasks.failed_step(TASK_ID) is None
