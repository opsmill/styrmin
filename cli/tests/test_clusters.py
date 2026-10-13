"""Tests for the clusters command group."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk.exceptions import ResourceNotFoundError, StyrminError, StyrminTransportError
from styrmin_sdk.models import ClusterUpdateResult
from styrminctl.cli import app
from styrminctl.output import console

if TYPE_CHECKING:
    from pathlib import Path

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
    assert "update" in output


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


STORED_CONFIG: dict[str, Any] = {
    "dedicated_ingress": {"service": {"type": "LoadBalancer"}},
    "fqdn_suffix": "apps.example.com",
    "ingress_class": "traefik",
    "runtime_class": "default",
    "scheduling": {"tolerations": [{"key": "dedicated", "operator": "Exists"}]},
}

SNAKE_CASE_CONFIG: dict[str, Any] = {
    "ingress_class": "nginx",
    "fqdn_suffix": "apps.example.com",
    "external_url_port": 8443,
    "dedicated_ingress": {"implementation": "traefik", "service": {"type": "LoadBalancer"}},
    "standard_storage": {"storage_class": "standard"},
    "scheduling": {"tolerations": [{"key": "dedicated", "operator": "EXISTS"}]},
}

CAMEL_CASE_CONFIG: dict[str, Any] = {
    "ingressClass": "nginx",
    "fqdnSuffix": "apps.example.com",
    "externalUrlPort": 8443,
    "dedicatedIngress": {"implementation": "traefik", "service": {"type": "LoadBalancer"}},
    "standardStorage": {"storageClass": "standard"},
    "scheduling": {"tolerations": [{"key": "dedicated", "operator": "EXISTS"}]},
}


def _write_config(tmp_path: Path, config: dict[str, Any]) -> str:
    path = tmp_path / "cluster.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return f"@{path}"


def _deployment(name: str, environment: str = "staging", task_id: str | None = None) -> dict[str, Any]:
    return {
        "deploymentId": "11111111-2222-3333-4444-555555555555",
        "deploymentName": name,
        "environmentId": "66666666-7777-8888-9999-000000000000",
        "environmentName": environment,
        "taskId": task_id,
    }


def _update_result(**overrides: Any) -> ClusterUpdateResult:  # noqa: ANN401
    data: dict[str, Any] = {
        "cluster": {
            "id": CLUSTER_UUID,
            "name": "my-cluster",
            "config": STORED_CONFIG,
            "capabilities": {},
            "createdOn": "2026-10-12T10:00:00+00:00",
            "updatedOn": None,
        },
        "dryRun": False,
        "redeployed": [],
        "waitingForIngress": [],
        "skippedRestoring": [],
        "failedToStart": [],
        "unchangedCount": 0,
        "ingressControllers": [],
        "failedEnvironments": [],
        **overrides,
    }
    return ClusterUpdateResult.model_validate(data)


def _mock_update(mock_client: MagicMock, result: ClusterUpdateResult | None = None) -> AsyncMock:
    mock_client.clusters.update = AsyncMock(return_value=result or _update_result())
    return mock_client.clusters.update


@pytest.mark.parametrize("config", [SNAKE_CASE_CONFIG, CAMEL_CASE_CONFIG], ids=["snake_case", "camel_case"])
def test_clusters_update_file_reaches_sdk_as_parsed(
    mock_client: MagicMock, tmp_path: Path, config: dict[str, Any]
) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", _write_config(tmp_path, config)])
    assert exc.value.code == 0

    update.assert_called_once_with(config, cluster_id=None, cluster_name="my-cluster", dry_run=False)


def test_clusters_update_by_id_dry_run(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    update = _mock_update(mock_client, _update_result(dryRun=True, redeployed=[_deployment("web")]))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "--id", CLUSTER_UUID, "--config", '{"ingress_class": "nginx"}', "--dry-run"])
    assert exc.value.code == 0

    update.assert_called_once_with({"ingress_class": "nginx"}, cluster_id=CLUSTER_UUID, cluster_name=None, dry_run=True)
    output = capsys.readouterr().out
    assert "nothing was saved" in output
    assert "1 deployment(s) would be redeployed" in output
    assert "web" in output
    assert "Success" not in output


def test_clusters_update_prints_what_it_redeploys(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    task_id = "99999999-8888-7777-6666-555555555555"
    _mock_update(
        mock_client,
        _update_result(
            redeployed=[_deployment("web", task_id=task_id)],
            waitingForIngress=[_deployment("api")],
            unchangedCount=3,
            ingressControllers=[
                {
                    "environmentId": "66666666-7777-8888-9999-000000000000",
                    "environmentName": "staging",
                    "action": "CREATE",
                    "failed": False,
                }
            ],
        ),
    )

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", '{"dedicated_ingress": {}}'])
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert "1 deployment(s) are being redeployed" in output
    assert task_id in output
    assert "wait for their environment's dedicated ingress" in output
    assert "api" in output
    assert "create" in output
    assert "3 deployment(s) already run with this config" in output
    assert "styrminctl tasks get TASK_ID" in output
    assert "Run this command again" not in output


def test_clusters_update_says_to_run_again_when_a_redeploy_could_not_start(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_update(
        mock_client,
        _update_result(
            failedToStart=[_deployment("broken")],
            failedEnvironments=[{"environmentId": "66666666-7777-8888-9999-000000000000", "environmentName": "prod"}],
        ),
    )

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", '{"ingress_class": "nginx"}'])
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert "1 deployment(s) could not be redeployed" in output
    assert "broken" in output
    assert "could not be evaluated: prod" in output
    assert "Run this command again to retry them" in output


def test_clusters_update_says_when_nothing_is_redeployed(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _mock_update(mock_client, _update_result(unchangedCount=4))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", '{"ingress_class": "traefik"}'])
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert "No deployment takes a changed value, so none is redeployed." in output
    assert "4 deployment(s) already run with this config" in output


def test_clusters_update_timeout_says_the_server_may_still_work(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_client.clusters.update = AsyncMock(side_effect=StyrminTransportError("ReadTimeout: timed out"))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", '{"ingress_class": "nginx"}'])
    assert exc.value.code == 1

    output = " ".join(capsys.readouterr().out.split())
    assert "may still be saving the config" in output


@pytest.mark.parametrize(
    ("config", "key_path"),
    [
        ({"ingress_class": "nginx", "fqdn_sufix": "apps.example.com"}, "fqdn_sufix"),
        ({"dedicated_ingress": {"servce": {"type": "LoadBalancer"}}}, "dedicated_ingress.servce"),
        ({"scheduling": {"tolerations": [{"key": "x", "operatr": "Exists"}]}}, "scheduling.tolerations[0].operatr"),
    ],
    ids=["top_level", "nested", "inside_list"],
)
def test_clusters_update_refuses_unknown_keys_before_connecting(
    mock_client: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    config: dict[str, Any],
    key_path: str,
) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", _write_config(tmp_path, config)])
    assert exc.value.code == 1

    update.assert_not_called()
    mock_client.__aenter__.assert_not_called()
    assert key_path in capsys.readouterr().out


def test_clusters_update_refuses_a_config_that_is_not_an_object(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", "[]"])
    assert exc.value.code == 1

    update.assert_not_called()
    assert "JSON object" in capsys.readouterr().out


def test_clusters_get_json_prints_only_the_config(mock_client: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    long_value = "a-very-long-annotation-value-" * 10
    config = {**STORED_CONFIG, "dedicated_ingress": {"service": {"annotations": {"example.com/key": long_value}}}}
    mock_client.clusters.get = AsyncMock(return_value=MagicMock(id=CLUSTER_UUID, name="cluster-1", config=config))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "get", "cluster-1", "--json"])
    assert exc.value.code == 0

    assert json.loads(capsys.readouterr().out) == config


@pytest.mark.parametrize(
    "args",
    [
        ["clusters", "update", "my-cluster", "--id", CLUSTER_UUID, "--config", "{}"],
        ["clusters", "update", "--config", "{}"],
    ],
    ids=["name_and_id", "neither"],
)
def test_clusters_update_requires_exactly_one_identifier(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(args)
    assert exc.value.code == 1

    update.assert_not_called()
    assert "--id" in capsys.readouterr().out


def test_clusters_update_requires_config(mock_client: MagicMock) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster"])
    assert exc.value.code != 0

    update.assert_not_called()


def test_clusters_update_server_error_exits_non_zero(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_client.clusters.update = AsyncMock(side_effect=ResourceNotFoundError("Cluster not found", "NOT_FOUND"))

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "missing", "--config", "{}"])
    assert exc.value.code == 1
    assert "Cluster not found" in capsys.readouterr().out


def _config_cell(output: str) -> str:
    line = next(line for line in output.splitlines() if "{" in line)
    return line[line.index("{") : line.rindex("}") + 1]


def test_clusters_get_prints_config_as_json(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console, "_width", 1000)
    mock_client.clusters.get = AsyncMock(
        return_value=MagicMock(id=CLUSTER_UUID, name="cluster-1", config=STORED_CONFIG)
    )

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "get", "cluster-1"])
    assert exc.value.code == 0

    assert json.loads(_config_cell(capsys.readouterr().out)) == STORED_CONFIG


def test_clusters_list_prints_config_as_json(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console, "_width", 1000)
    mock_client.clusters.list = AsyncMock(
        return_value=[MagicMock(id=CLUSTER_UUID, name="cluster-1", config=STORED_CONFIG)]
    )

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "list"])
    assert exc.value.code == 0

    assert json.loads(_config_cell(capsys.readouterr().out)) == STORED_CONFIG
