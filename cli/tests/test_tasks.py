"""Tests for the tasks command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app


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


def test_tasks_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    task_uuid = "550e8400-e29b-41d4-a716-446655440000"
    mock_task = MagicMock(id=task_uuid, type="deploy", status="completed", message="done", deployment_id=None)
    mock_client.tasks.get = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["tasks", "get", task_uuid])
    assert exc.value.code == 0
    mock_client.tasks.get.assert_called_once_with(task_uuid)
    output = capsys.readouterr().out
    assert task_uuid[:12] in output


def test_tasks_list_error(mock_client: MagicMock) -> None:
    mock_client.tasks.list = AsyncMock(side_effect=StyrminError("connection failed"))

    with pytest.raises(SystemExit) as exc:
        app(["tasks", "list"])
    assert exc.value.code == 1
