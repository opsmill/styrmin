"""Unit tests for ``upsert_custom_resource(replace_spec_on_update=True)``
(017-post-render-env-vars, T009, FR-011, research D-003, critique E3).

On a 409 the HelmRelease apply sends one JSON Patch that replaces ``spec``
wholesale (``None`` pruned) and adds each owned ``metadata.labels`` /
``metadata.annotations`` key individually, so stale ``spec.values`` entries
disappear while kopf annotations and Flux's finalizer survive.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import upsert_custom_resource

_upsert = upsert_custom_resource.__wrapped__
_API = "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CustomObjectsApi"

_BODY: dict[str, Any] = {
    "apiVersion": "helm.toolkit.fluxcd.io/v2",
    "kind": "HelmRelease",
    "metadata": {
        "name": "rel",
        "labels": {"app.kubernetes.io/managed-by": "styrmin", "plain": "x"},
        "annotations": {"styrmin.io/deployment-id": "abc"},
    },
    "spec": {
        "interval": "1h",
        "values": {
            "infrahubServer": {"infrahubServer": {"args": None, "env": {"A": "1"}}}
        },
    },
}


def _mock_api(*, conflict: bool = True) -> MagicMock:
    api = MagicMock()
    api.create_namespaced_custom_object = AsyncMock(
        side_effect=ApiException(status=409) if conflict else None
    )
    api.patch_namespaced_custom_object = AsyncMock()
    return api


async def _run(api: MagicMock, body: dict[str, Any], **kwargs: Any) -> None:
    with patch(_API, return_value=api):
        await _upsert(
            plurals="helmreleases",
            body=body,
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace="ns",
            client=MagicMock(),
            **kwargs,
        )


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _apply_add_ops(live: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply RFC 6902 ``add`` ops on object members; a missing parent fails."""
    result = copy.deepcopy(live)
    for op in ops:
        assert op["op"] == "add"
        *parents, leaf = [_unescape(t) for t in op["path"].split("/")[1:]]
        node = result
        for token in parents:
            node = node[token]
        node[leaf] = op["value"]
    return result


@pytest.mark.asyncio
async def test_conflict_sends_single_json_patch() -> None:
    api = _mock_api()

    await _run(api, _BODY, prune_none_on_create=True, replace_spec_on_update=True)

    api.patch_namespaced_custom_object.assert_awaited_once()
    kwargs = api.patch_namespaced_custom_object.call_args.kwargs
    assert kwargs["_content_type"] == "application/json-patch+json"
    assert kwargs["name"] == "rel"
    assert kwargs["body"] == [
        {
            "op": "add",
            "path": "/spec",
            "value": {
                "interval": "1h",
                "values": {"infrahubServer": {"infrahubServer": {"env": {"A": "1"}}}},
            },
        },
        {
            "op": "add",
            "path": "/metadata/labels/app.kubernetes.io~1managed-by",
            "value": "styrmin",
        },
        {"op": "add", "path": "/metadata/labels/plain", "value": "x"},
        {
            "op": "add",
            "path": "/metadata/annotations/styrmin.io~1deployment-id",
            "value": "abc",
        },
    ]


@pytest.mark.asyncio
async def test_ops_only_touch_spec_and_keys_the_body_sets() -> None:
    api = _mock_api()

    await _run(api, _BODY, replace_spec_on_update=True)

    paths = [
        op["path"] for op in api.patch_namespaced_custom_object.call_args.kwargs["body"]
    ]
    assert not any(p.startswith("/metadata/finalizers") for p in paths)
    assert "/metadata/labels" not in paths
    assert "/metadata/annotations" not in paths
    assert not any(p.startswith("/status") for p in paths)


@pytest.mark.asyncio
async def test_applied_patch_drops_stale_spec_and_keeps_foreign_metadata() -> None:
    live = {
        "metadata": {
            "name": "rel",
            "finalizers": ["finalizers.fluxcd.io"],
            "labels": {"plain": "old", "someone/else": "keep"},
            "annotations": {
                "kopf.zalando.org/last-handled-configuration": "{}",
                "styrmin.io/deployment-id": "abc",
            },
        },
        "spec": {
            "interval": "1h",
            "values": {"extraEnv": [{"name": "STALE_VALUES_ENV", "value": "x"}]},
        },
        "status": {"observedGeneration": 3},
    }
    api = _mock_api()

    await _run(api, _BODY, replace_spec_on_update=True)
    result = _apply_add_ops(
        live, api.patch_namespaced_custom_object.call_args.kwargs["body"]
    )

    assert "extraEnv" not in result["spec"]["values"]
    assert result["spec"]["values"]["infrahubServer"]["infrahubServer"] == {
        "env": {"A": "1"}
    }
    assert result["metadata"]["finalizers"] == ["finalizers.fluxcd.io"]
    assert result["metadata"]["labels"] == {
        "plain": "x",
        "someone/else": "keep",
        "app.kubernetes.io/managed-by": "styrmin",
    }
    assert (
        result["metadata"]["annotations"]["kopf.zalando.org/last-handled-configuration"]
        == "{}"
    )
    assert result["status"] == {"observedGeneration": 3}


@pytest.mark.asyncio
async def test_tilde_and_slash_are_escaped_per_rfc_6901() -> None:
    body = {"metadata": {"name": "rel", "labels": {"a~b/c": "v"}}, "spec": {}}
    api = _mock_api()

    await _run(api, body, replace_spec_on_update=True)

    paths = [
        op["path"] for op in api.patch_namespaced_custom_object.call_args.kwargs["body"]
    ]
    assert paths == ["/spec", "/metadata/labels/a~0b~1c"]


@pytest.mark.asyncio
async def test_body_without_metadata_maps_only_replaces_spec() -> None:
    body = {"metadata": {"name": "rel"}, "spec": {"interval": "1h"}}
    api = _mock_api()

    await _run(api, body, replace_spec_on_update=True)

    assert api.patch_namespaced_custom_object.call_args.kwargs["body"] == [
        {"op": "add", "path": "/spec", "value": {"interval": "1h"}}
    ]


@pytest.mark.asyncio
async def test_caller_body_is_not_mutated() -> None:
    body = copy.deepcopy(_BODY)
    api = _mock_api()

    await _run(api, body, prune_none_on_create=True, replace_spec_on_update=True)

    assert body == _BODY


@pytest.mark.asyncio
async def test_create_path_still_prunes_and_skips_patch() -> None:
    api = _mock_api(conflict=False)

    await _run(api, _BODY, prune_none_on_create=True, replace_spec_on_update=True)

    sent = api.create_namespaced_custom_object.call_args.kwargs["body"]
    assert "args" not in sent["spec"]["values"]["infrahubServer"]["infrahubServer"]
    api.patch_namespaced_custom_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_conflict_error_is_raised() -> None:
    api = _mock_api()
    api.create_namespaced_custom_object.side_effect = ApiException(status=500)

    with pytest.raises(ApiException):
        await _run(api, _BODY, replace_spec_on_update=True)
    api.patch_namespaced_custom_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_flag_off_keeps_merge_patch() -> None:
    api = _mock_api()

    await _run(api, _BODY, prune_none_on_create=True)

    kwargs = api.patch_namespaced_custom_object.call_args.kwargs
    assert kwargs["_content_type"] == "application/merge-patch+json"
    assert kwargs["body"] is _BODY


@pytest.mark.asyncio
async def test_operator_helmrelease_apply_opts_into_replace_spec() -> None:
    from uuid import uuid4

    from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
        ApplicationHelmReleaseBuilder,
    )
    from styrmin_backend.context.models.config import (
        ClusterConfig,
        DeploymentConfig,
        EnvironmentConfig,
        ResolvedConfig,
    )
    from styrmin_backend.context.models.contexts import (
        ApplicationContext,
        ClusterContext,
        DeploymentContext,
        EnvironmentContext,
        GlobalContext,
        InstanceContext,
    )
    from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
    from styrmin_backend.operator.pipeline import execute_phase_helmrelease

    context = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=uuid4(),
            namespace="ns",
            release_reference="rel",
        ),
        app=ApplicationContext(
            name="app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="c", version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )
    upsert = AsyncMock()
    built = MagicMock()
    built.render.return_value = _BODY
    with (
        patch(
            "styrmin_backend.agent.service.kubernetes.primitives.upsert_custom_resource",
            upsert,
        ),
        patch.object(ApplicationHelmReleaseBuilder, "build", return_value=built),
    ):
        result = await execute_phase_helmrelease(
            crd_spec={"context": context.model_dump(mode="json")}, namespace="ns"
        )

    assert result.success, result.errors
    calls = {c.kwargs["plurals"]: c.kwargs for c in upsert.await_args_list}
    assert calls["helmreleases"]["replace_spec_on_update"] is True
    assert calls["helmreleases"]["prune_none_on_create"] is True
    assert "replace_spec_on_update" not in calls["helmrepositories"]
    assert "replace_spec_on_update" not in calls["helmcharts"]
