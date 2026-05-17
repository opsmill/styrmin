"""Tests for the clusters command group."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import StyrminError
from styrminctl.cli import app

CLUSTER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def test_clusters_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        app(["clusters", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "create" in output
    assert "list" in output
    assert "get" in output
    assert "delete" in output


def test_clusters_create(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.clusters.create = AsyncMock(return_value=MagicMock(id=CLUSTER_UUID, name="my-cluster"))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "create", "my-cluster"])
    assert exc.value.code == 0
    mock_client.clusters.create.assert_called_once_with(name="my-cluster", config=None)
    output = capsys.readouterr().out
    assert "my-cluster" in output
    assert "Success" in output


def test_clusters_create_with_config(mock_client: MagicMock) -> None:
    mock_client.clusters.create = AsyncMock(return_value=MagicMock(id=CLUSTER_UUID, name="my-cluster"))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "create", "my-cluster", "--config", '{"key": "value"}'])
    assert exc.value.code == 0
    mock_client.clusters.create.assert_called_once_with(name="my-cluster", config={"key": "value"})


def test_clusters_list(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_cluster = MagicMock(id=CLUSTER_UUID, name="cluster-1", config=None)
    mock_client.clusters.list = AsyncMock(return_value=[mock_cluster])

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "cluster-1" in output


def test_clusters_list_empty(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.clusters.list = AsyncMock(return_value=[])

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "list"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "No clusters found" in output


def test_clusters_get(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.clusters.get = AsyncMock(return_value=MagicMock(id=CLUSTER_UUID, name="cluster-1", config=None))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "get", CLUSTER_UUID])
    assert exc.value.code == 0
    mock_client.clusters.get.assert_called_once_with(cluster_id=None, cluster_name=CLUSTER_UUID)
    output = capsys.readouterr().out
    assert "cluster-1" in output


def test_clusters_delete(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    mock_client.clusters.delete = AsyncMock(return_value=None)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "delete", CLUSTER_UUID])
    assert exc.value.code == 0
    mock_client.clusters.delete.assert_called_once_with(cluster_id=None, cluster_name=CLUSTER_UUID)
    output = capsys.readouterr().out
    assert "deleted" in output.lower()


def test_clusters_create_error(mock_client: MagicMock) -> None:
    mock_client.clusters.create = AsyncMock(side_effect=StyrminError("API error"))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "create", "bad-cluster"])
    assert exc.value.code == 1
