"""Tests for the tasks command group."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import NAMESPACE_URL, uuid5

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrmin_sdk.models import StepOutput, Task
from styrminctl.cli import app

TASK_ID = "550e8400-e29b-41d4-a716-446655440000"
STARTED_TASK_ID = "660e8400-e29b-41d4-a716-446655440001"


def test_tasks_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["tasks", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "list" in output
    assert "get" in output


def test_tasks_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="abc-123", type="deploy", status="running", message="deploying", deployment_id="dep-1")
    mock_client.tasks.list = AsyncMock(return_value=[mock_task])

    with pytest.raises(SystemExit) as exc:
        app(["tasks", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "abc-123" in output
    assert "deploy" in output


def test_tasks_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.tasks.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["tasks", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No tasks found" in output


def _step(name: str, status: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    step: dict[str, Any] = {
        "id": str(uuid5(NAMESPACE_URL, name)),
        "key": name.lower().replace(" ", "-"),
        "name": name,
        "kind": "OPERATOR_PHASE",
        "status": status,
        "startedAt": "2026-10-06T10:00:00+00:00",
        "endedAt": None,
        "durationSeconds": None,
        "attemptCount": 1,
        "errors": [],
        "error": None,
        "detail": None,
        "rolledBackAt": None,
        "rollbackMessage": None,
        "hasOutput": False,
        "supersededBy": None,
        "startedTasks": [],
        "noReportSince": None,
    }
    step.update(fields)
    return step


def _task(steps: list[dict[str, Any]], started_tasks: list[dict[str, Any]] | None = None) -> Task:
    return Task.model_validate(
        {
            "id": TASK_ID,
            "type": "upgrade_instance",
            "status": "completed",
            "message": "done",
            "deploymentId": None,
            "createdOn": "2026-10-06T10:00:00+00:00",
            "result": "FAILED",
            "startedByStepId": None,
            "startedBy": None,
            "startedTasks": started_tasks or [],
            "steps": steps,
        }
    )


def _run_get(mock_client: MagicMock, task: Task, capsys: pytest.CaptureFixture[str]) -> str:
    mock_client.tasks.get = AsyncMock(return_value=task)
    with pytest.raises(SystemExit) as exc:
        app(["tasks", "get", TASK_ID])
    assert exc.value.code == 0
    mock_client.tasks.get.assert_called_once_with(TASK_ID)
    return capsys.readouterr().out


def test_tasks_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The task table gains a result column; the steps table lists each step (FR-012)."""
    monkeypatch.setenv("COLUMNS", "200")
    task = _task(
        [
            _step("Plan the changes", "SUCCEEDED", endedAt="2026-10-06T10:00:01+00:00", durationSeconds=0.4),
            _step(
                "Create network policies and secrets",
                "SUCCEEDED",
                endedAt="2026-10-06T10:01:05+00:00",
                durationSeconds=65.2,
                attemptCount=2,
            ),
            _step(
                "Install or upgrade the HelmRelease",
                "FAILED",
                endedAt="2026-10-06T10:05:00+00:00",
                durationSeconds=235.0,
                error="Pods not ready: my-app-6d9 (app: ImagePullBackOff)",
                detail="UpgradeFailed: Helm upgrade failed",
            ),
            _step("Wait for the pods to be ready", "PENDING", startedAt=None),
        ]
    )

    output = _run_get(mock_client, task, capsys)

    assert TASK_ID in output
    assert "result" in output
    assert "FAILED" in output
    assert "Steps" in output
    lines = output.splitlines()
    plan = next(line for line in lines if "Plan the changes" in line)
    assert "SUCCEEDED" in plan
    assert "<1s" in plan
    prerequisites = next(line for line in lines if "Create network policies and secrets" in line)
    assert "1m 05s" in prerequisites
    assert " 2 " in prerequisites
    helmrelease = next(line for line in lines if "Install or upgrade the HelmRelease" in line)
    assert "3m 55s" in helmrelease
    assert "Pods not ready: my-app-6d9 (app: ImagePullBackOff)" in helmrelease
    # FluxCD's detail follows the error on the next line of the same cell.
    assert "UpgradeFailed: Helm upgrade failed" in lines[lines.index(helmrelease) + 1]
    assert "PENDING" in next(line for line in lines if "Wait for the pods to be ready" in line)
    assert "No steps recorded" not in output
    assert "Started tasks" not in output
    mock_client.tasks.step_output.assert_not_called()


def test_tasks_get_running_step_and_command_output(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    task = _task(
        [
            _step(
                "Run the upgrade hook",
                "FAILED",
                kind="HOOK",
                durationSeconds=12.0,
                error="command exited with 3",
                hasOutput=True,
            ),
            _step("Install or upgrade the HelmRelease", "RUNNING"),
        ]
    )
    hook_id = task.steps[0].id
    mock_client.tasks.step_output = AsyncMock(
        return_value=StepOutput.model_validate(
            {"id": hook_id, "output": "step-output-1\n[step-output-2]\n\n", "outputTruncated": False}
        )
    )

    output = _run_get(mock_client, task, capsys)

    lines = output.splitlines()
    hook = next(line for line in lines if "Run the upgrade hook" in line)
    assert "12s" in hook
    assert "command exited with 3" in hook
    # Command output is printed as text, not read as Rich markup.
    assert "output: [step-output-2]" in lines[lines.index(hook) + 1]
    assert "step-output-1" not in output
    assert "running" in next(line for line in lines if "Install or upgrade the HelmRelease" in line)
    # Only the step with output has its output read.
    mock_client.tasks.step_output.assert_awaited_once_with(hook_id)


def test_tasks_get_without_steps(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    output = _run_get(mock_client, _task([]), capsys)

    assert "No steps recorded for this task." in output
    assert "Steps" not in output


def test_tasks_get_started_tasks(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    task = _task(
        [_step("Run the upgrade hook", "SUCCEEDED", kind="HOOK", durationSeconds=3725.0)],
        started_tasks=[{"id": STARTED_TASK_ID, "type": "deploy", "status": "completed", "result": "FAILED"}],
    )

    output = _run_get(mock_client, task, capsys)

    assert "1h 02m" in next(line for line in output.splitlines() if "Run the upgrade hook" in line)
    assert "Started tasks" in output
    started = next(line for line in output.splitlines() if STARTED_TASK_ID in line)
    assert "deploy" in started
    assert "FAILED" in started


def test_tasks_list_error(mock_client: MagicMock) -> None:
    mock_client.tasks.list = AsyncMock(side_effect=StyrminError("connection failed"))

    with pytest.raises(SystemExit) as exc:
        app(["tasks", "list"])
    assert exc.value.code == 1
