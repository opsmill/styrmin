"""``styrmin agent apply-crds``: the agent chart's hook applies the chart's CRDs (#432, #433).

Helm never updates ``crds/``. A new CRD that drops a version the cluster stored objects in is
recreated when it has no objects (the OCIRepository CRD of source-controller v1.4.0 stored
``v1beta2``), and refused otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from kubernetes_asyncio.client.exceptions import ApiException

from styrmin_backend.cli.agent import agent_app
from styrmin_backend.operator.crd import install as install_module
from styrmin_backend.operator.crd.install import (
    CrdApplyAction,
    CrdApplyError,
    apply_crd,
    load_crd_files,
    removed_stored_versions,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
NAME = "ocirepositories.source.toolkit.fluxcd.io"


def _crd(*versions: str, storage: str | None = None) -> dict[str, Any]:
    storage = storage or versions[0]
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {"name": NAME},
        "spec": {
            "group": "source.toolkit.fluxcd.io",
            "names": {"plural": "ocirepositories", "kind": "OCIRepository"},
            "versions": [
                {"name": v, "served": True, "storage": v == storage} for v in versions
            ],
        },
    }


def _existing(*versions: str, stored: list[str]) -> dict[str, Any]:
    return {**_crd(*versions), "status": {"storedVersions": stored}}


@pytest.fixture
def api(mocker) -> Any:
    """The ApiextensionsV1Api and CustomObjectsApi that ``apply_crd`` builds."""
    extensions = mocker.MagicMock()
    extensions.patch_custom_resource_definition = mocker.AsyncMock()
    extensions.delete_custom_resource_definition = mocker.AsyncMock()
    mocker.patch.object(
        install_module.kubeclient, "ApiextensionsV1Api", return_value=extensions
    )
    custom = mocker.MagicMock()
    custom.list_cluster_custom_object = mocker.AsyncMock(return_value={"items": []})
    mocker.patch.object(
        install_module.kubeclient, "CustomObjectsApi", return_value=custom
    )
    mocker.patch.object(install_module, "_DELETE_POLL_SECONDS", 0)
    return extensions, custom


def _serve(mocker, *crds: dict[str, Any] | None) -> Any:
    """Answer one ``_read_crd`` call per value."""
    return mocker.patch.object(
        install_module, "_read_crd", new=mocker.AsyncMock(side_effect=list(crds))
    )


def test_chart_crds_load() -> None:
    crds = load_crd_files(REPO_ROOT / "helm" / "agent" / "crds")

    names = {crd["metadata"]["name"] for crd in crds}
    assert {
        "helmreleases.helm.toolkit.fluxcd.io",
        "helmcharts.source.toolkit.fluxcd.io",
        "helmrepositories.source.toolkit.fluxcd.io",
        NAME,
        "styrmindeployments.styrmin.io",
        "clusterkopfpeerings.kopf.dev",
    } <= names


def test_load_rejects_a_file_that_is_not_a_crd(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("apiVersion: v1\nkind: ConfigMap\n")

    with pytest.raises(CrdApplyError, match="config.yaml holds a ConfigMap"):
        load_crd_files(tmp_path)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(["v1beta2"], ["v1beta2"]), (["v1"], []), (["v1beta2", "v1"], ["v1beta2"])],
)
def test_removed_stored_versions(stored: list[str], expected: list[str]) -> None:
    assert (
        removed_stored_versions(_existing("v1beta2", stored=stored), _crd("v1"))
        == expected
    )


@pytest.mark.anyio
async def test_a_missing_crd_is_applied(mocker, api) -> None:
    extensions, _ = api
    _serve(mocker, None)

    result = await apply_crd(mocker.Mock(), _crd("v1"))

    assert result.action is CrdApplyAction.APPLIED
    extensions.patch_custom_resource_definition.assert_awaited_once_with(
        name=NAME,
        body=_crd("v1"),
        field_manager="styrmin-agent",
        force=True,
        _content_type="application/apply-patch+yaml",
    )
    extensions.delete_custom_resource_definition.assert_not_awaited()


@pytest.mark.anyio
async def test_a_crd_that_keeps_its_stored_versions_is_applied(mocker, api) -> None:
    extensions, custom = api
    _serve(mocker, _existing("v1", "v1beta2", stored=["v1"]))

    result = await apply_crd(mocker.Mock(), _crd("v1"))

    assert result.action is CrdApplyAction.APPLIED
    extensions.patch_custom_resource_definition.assert_awaited_once()
    custom.list_cluster_custom_object.assert_not_awaited()
    extensions.delete_custom_resource_definition.assert_not_awaited()


@pytest.mark.anyio
async def test_a_crd_without_objects_is_recreated_to_drop_a_stored_version(
    mocker, api
) -> None:
    extensions, custom = api
    # Read before the update, then twice while waiting for the delete.
    existing = _existing("v1beta2", stored=["v1beta2"])
    _serve(mocker, existing, existing, None)

    result = await apply_crd(mocker.Mock(), _crd("v1"))

    assert result.action is CrdApplyAction.RECREATED
    custom.list_cluster_custom_object.assert_awaited_once_with(
        group="source.toolkit.fluxcd.io",
        version="v1beta2",
        plural="ocirepositories",
        limit=1,
    )
    extensions.delete_custom_resource_definition.assert_awaited_once_with(name=NAME)
    extensions.patch_custom_resource_definition.assert_awaited_once()


@pytest.mark.anyio
async def test_a_crd_with_objects_in_a_dropped_version_is_refused(mocker, api) -> None:
    extensions, custom = api
    custom.list_cluster_custom_object.return_value = {"items": [{"metadata": {}}]}
    _serve(mocker, _existing("v1beta2", stored=["v1beta2"]))

    with pytest.raises(CrdApplyError, match=r"objects stored in version\(s\) v1beta2"):
        await apply_crd(mocker.Mock(), _crd("v1"))

    extensions.delete_custom_resource_definition.assert_not_awaited()
    extensions.patch_custom_resource_definition.assert_not_awaited()


@pytest.mark.anyio
async def test_a_crd_that_is_not_deleted_in_time_fails(mocker, api) -> None:
    existing = _existing("v1beta2", stored=["v1beta2"])
    mocker.patch.object(
        install_module, "_read_crd", new=mocker.AsyncMock(return_value=existing)
    )
    mocker.patch.object(install_module, "_DELETE_TIMEOUT_SECONDS", 0)

    with pytest.raises(CrdApplyError, match="was not deleted"):
        await apply_crd(mocker.Mock(), _crd("v1"))


@pytest.mark.anyio
async def test_read_crd_returns_none_when_missing(mocker) -> None:
    extensions = mocker.MagicMock()
    extensions.read_custom_resource_definition = mocker.AsyncMock(
        side_effect=ApiException(status=404)
    )

    assert await install_module._read_crd(extensions, NAME) is None


def test_cli_prints_each_crd(mocker, tmp_path: Path, capsys) -> None:
    (tmp_path / "crd.yaml").write_text("---\n" + _yaml(_crd("v1")))
    mocker.patch(
        "styrmin_backend.operator.kubernetes.get_kubernetes_client",
        return_value=_FakeClient(),
    )
    mocker.patch.object(
        install_module,
        "apply_crd",
        new=mocker.AsyncMock(
            return_value=install_module.CrdApplyResult(
                name=NAME, action=CrdApplyAction.RECREATED
            )
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        agent_app(["apply-crds", str(tmp_path)])

    assert exc_info.value.code == 0
    assert f"{NAME}: recreated" in capsys.readouterr().out


def test_cli_exits_non_zero_on_a_refused_crd(mocker, tmp_path: Path, capsys) -> None:
    (tmp_path / "crd.yaml").write_text(_yaml(_crd("v1")))
    mocker.patch(
        "styrmin_backend.operator.kubernetes.get_kubernetes_client",
        return_value=_FakeClient(),
    )
    mocker.patch.object(
        install_module,
        "apply_crd",
        new=mocker.AsyncMock(side_effect=CrdApplyError("objects stored in v1beta2")),
    )

    with pytest.raises(SystemExit) as exc_info:
        agent_app(["apply-crds", str(tmp_path)])

    assert exc_info.value.code == 1
    assert "objects stored in v1beta2" in capsys.readouterr().out


def _yaml(document: dict[str, Any]) -> str:
    return yaml.safe_dump(document)


class _FakeClient:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None
