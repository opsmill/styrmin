"""Tests for the environments command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app

ENV_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
CLUSTER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def test_environments_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["environments", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "list" in output
    assert "get" in output
    assert "delete" in output


def test_environments_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_env = MagicMock(id=ENV_UUID, name="staging", cluster=MagicMock(name="cluster-1"))
    mock_client.environments.create = AsyncMock(return_value=mock_env)

    with pytest.raises(SystemExit) as exc:
        app(["environments", "create", "staging", "--cluster-id", CLUSTER_UUID])
    assert exc.value.code == 0
    mock_client.environments.create.assert_called_once_with(
        name="staging", cluster_id=CLUSTER_UUID, cluster_name=None, config=None
    )
    output = capsys.readouterr().out
    assert "staging" in output


def test_environments_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_env = MagicMock(id=ENV_UUID, name="staging", cluster=MagicMock(name="cluster-1"), config=None)
    mock_client.environments.list = AsyncMock(return_value=[mock_env])

    with pytest.raises(SystemExit) as exc:
        app(["environments", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "staging" in output


def test_environments_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environments.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["environments", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No environments found" in output


def test_environments_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_env = MagicMock(id=ENV_UUID, name="staging", cluster=MagicMock(name="cluster-1"), config=None)
    mock_client.environments.get = AsyncMock(return_value=mock_env)

    with pytest.raises(SystemExit) as exc:
        app(["environments", "get", ENV_UUID])
    assert exc.value.code == 0
    mock_client.environments.get.assert_called_once_with(
        environment_name=ENV_UUID, cluster_id=None, cluster_name="default"
    )


def test_environments_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.environments.delete = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["environments", "delete", ENV_UUID])
    assert exc.value.code == 0
    mock_client.environments.delete.assert_called_once_with(
        environment_name=ENV_UUID, cluster_id=None, cluster_name="default"
    )
    output = capsys.readouterr().out
    assert "deleted" in output.lower()


def test_environments_create_error(mock_client: MagicMock) -> None:
    mock_client.environments.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["environments", "create", "bad-env", "--cluster-id", CLUSTER_UUID])
    assert exc.value.code == 1
