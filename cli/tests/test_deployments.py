"""Tests for the deployments command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app

DEPLOYMENT_UUID = "a7b8c9d0-e1f2-3456-0123-456789abcdef"
ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"


def test_deployments_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["deployments", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "get" in output
    assert "update" in output
    assert "update-version" in output
    assert "start-components" in output
    assert "stop-components" in output
    assert "run-job" in output
    assert "context" in output


def test_deployments_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", deployment_id=DEPLOYMENT_UUID, status="pending")
    mock_client.deployments.create = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "create", "postgres", "14.0", ENV_UUID])
    assert exc.value.code == 0
    mock_client.deployments.create.assert_called_once_with(
        driver="postgres",
        version="14.0",
        environment_id=ENV_UUID,
        name=None,
        config=None,
    )
    output = capsys.readouterr().out
    assert DEPLOYMENT_UUID in output


def test_deployments_create_with_options(mock_client: MagicMock) -> None:
    mock_task = MagicMock(id="t-1", deployment_id=DEPLOYMENT_UUID, status="pending")
    mock_client.deployments.create = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "create", "postgres", "14.0", ENV_UUID, "--name", "my-db", "--config", '{"key": "val"}'])
    assert exc.value.code == 0
    mock_client.deployments.create.assert_called_once_with(
        driver="postgres",
        version="14.0",
        environment_id=ENV_UUID,
        name="my-db",
        config={"key": "val"},
    )


def test_deployments_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_deployment = MagicMock(
        id=DEPLOYMENT_UUID,
        name="my-db",
        status="running",
        application_version="14.0",
        application_driver_version_id="dv-1",
        environment_id=ENV_UUID,
        config=None,
        application_instance=None,
        components=[],
    )
    mock_client.deployments.get = AsyncMock(return_value=mock_deployment)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "get", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.deployments.get.assert_called_once_with(DEPLOYMENT_UUID)
    output = capsys.readouterr().out
    assert DEPLOYMENT_UUID in output


def test_deployments_update(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.update = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "update", DEPLOYMENT_UUID, "--config", '{"key": "val"}'])
    assert exc.value.code == 0
    mock_client.deployments.update.assert_called_once_with(DEPLOYMENT_UUID, config={"key": "val"})
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_update_version(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.update_version = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "update-version", DEPLOYMENT_UUID, "15.0"])
    assert exc.value.code == 0
    mock_client.deployments.update_version.assert_called_once_with(DEPLOYMENT_UUID, version="15.0")
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_start_components(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.start_components = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "start-components", DEPLOYMENT_UUID, "--component", "web", "--component", "worker"])
    assert exc.value.code == 0
    mock_client.deployments.start_components.assert_called_once_with(DEPLOYMENT_UUID, components=["web", "worker"])
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_stop_components(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.stop_components = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "stop-components", DEPLOYMENT_UUID, "--component", "worker"])
    assert exc.value.code == 0
    mock_client.deployments.stop_components.assert_called_once_with(DEPLOYMENT_UUID, components=["worker"])


def test_deployments_run_job(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_task = MagicMock(id="t-1", status="pending")
    mock_client.deployments.run_job = AsyncMock(return_value=mock_task)

    with pytest.raises(SystemExit) as exc:
        app(
            [
                "deployments",
                "run-job",
                DEPLOYMENT_UUID,
                "--image",
                "postgres:14",
                "--command",
                "pg_dump",
                "--command",
                "localhost",
                "--env",
                '{"PG_PASSWORD": "secret"}',
            ]
        )
    assert exc.value.code == 0
    mock_client.deployments.run_job.assert_called_once()
    output = capsys.readouterr().out
    assert "t-1" in output


def test_deployments_context(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_ctx = MagicMock(context={"namespace": "prod", "cluster": "main"})
    mock_client.deployments.get_context = AsyncMock(return_value=mock_ctx)

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "context", DEPLOYMENT_UUID])
    assert exc.value.code == 0
    mock_client.deployments.get_context.assert_called_once_with(DEPLOYMENT_UUID)


def test_deployments_create_error(mock_client: MagicMock) -> None:
    mock_client.deployments.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["deployments", "create", "postgres", "14.0", ENV_UUID])
    assert exc.value.code == 1
