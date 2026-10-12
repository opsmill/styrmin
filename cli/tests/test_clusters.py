"""Tests for the clusters command group."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from styrmin_sdk import UpdateClusterInput
from styrmin_sdk.exceptions import ResourceNotFoundError, StyrminError
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


def _mock_update(mock_client: MagicMock) -> AsyncMock:
    cluster = MagicMock(id=CLUSTER_UUID, config=STORED_CONFIG)
    cluster.name = "my-cluster"
    mock_client.clusters.update = AsyncMock(return_value=cluster)
    return mock_client.clusters.update


@pytest.mark.parametrize("config", [SNAKE_CASE_CONFIG, CAMEL_CASE_CONFIG], ids=["snake_case", "camel_case"])
def test_clusters_update_file_reaches_sdk_as_typed_input(
    mock_client: MagicMock, tmp_path: Path, config: dict[str, Any]
) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", _write_config(tmp_path, config)])
    assert exc.value.code == 0

    update.assert_called_once_with(
        input=UpdateClusterInput.model_validate(SNAKE_CASE_CONFIG), cluster_id=None, cluster_name="my-cluster"
    )
    sent = update.call_args.kwargs["input"]
    assert isinstance(sent, UpdateClusterInput)
    assert sent.model_dump(by_alias=True, exclude_none=True)["dedicatedIngress"] == {
        "implementation": "traefik",
        "service": {"type": "LoadBalancer"},
    }


def test_clusters_update_by_id(mock_client: MagicMock) -> None:
    update = _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "--id", CLUSTER_UUID, "--config", '{"ingress_class": "nginx"}'])
    assert exc.value.code == 0

    update.assert_called_once_with(
        input=UpdateClusterInput.model_validate({"ingress_class": "nginx"}), cluster_id=CLUSTER_UUID, cluster_name=None
    )


def test_clusters_update_accepts_stored_enum_values(mock_client: MagicMock, tmp_path: Path) -> None:
    """A file copied from `clusters get` carries the stored enum values, not the GraphQL names."""
    update = _mock_update(mock_client)
    stored = {
        "external_url_scheme": "http",
        "external_dns_endpoints_type": "NodeExternalIP",
        "scheduling": {
            "tolerations": [{"key": "dedicated", "operator": "Exists", "effect": "NoSchedule"}],
            "topology_spread_constraints": [
                {"max_skew": 1, "topology_key": "zone", "when_unsatisfiable": "DoNotSchedule"}
            ],
        },
    }

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", _write_config(tmp_path, stored)])
    assert exc.value.code == 0

    sent = update.call_args.kwargs["input"].model_dump(by_alias=True, exclude_none=True, mode="json")
    assert sent["externalUrlScheme"] == "HTTP"
    assert sent["externalDnsEndpointsType"] == "NODE_EXTERNAL_IP"
    assert sent["scheduling"]["tolerations"] == [{"key": "dedicated", "operator": "EXISTS", "effect": "NO_SCHEDULE"}]
    assert sent["scheduling"]["topologySpreadConstraints"][0]["whenUnsatisfiable"] == "DO_NOT_SCHEDULE"


@pytest.mark.parametrize(
    ("config", "key_path"),
    [
        ({"ingress_class": "nginx", "fqdn_sufix": "apps.example.com"}, "fqdn_sufix"),
        ({"dedicated_ingress": {"servce": {"type": "LoadBalancer"}}}, "dedicated_ingress.servce"),
        ({"scheduling": {"tolerations": [{"key": "x", "operatr": "Exists"}]}}, "scheduling.tolerations[0].operatr"),
    ],
    ids=["top_level", "nested", "inside_list"],
)
def test_clusters_update_refuses_unknown_keys_before_sdk_call(
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


def test_clusters_update_prints_json_config_and_redeploy_line(
    mock_client: MagicMock, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console, "_width", 1000)
    _mock_update(mock_client)

    with pytest.raises(SystemExit) as exc:
        app(["clusters", "update", "my-cluster", "--config", '{"ingress_class": "nginx"}'])
    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert f"Cluster 'my-cluster' updated (id: {CLUSTER_UUID})" in output
    assert json.loads(output[output.index("{") : output.rindex("}") + 1]) == STORED_CONFIG
    assert "Deployments that take a changed value are being redeployed." in output
    assert "styrminctl tasks list" in output


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
