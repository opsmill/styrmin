"""Unit tests for the StyrminDeployment CR apply (017-post-render-env-vars,
FR-011).

The operator builds the HelmRelease from the CR's ``spec.context``. A
merge-patch update keeps context keys the new body omits, so a cleared env var
would still reach the HelmRelease. The agent therefore replaces each spec key
it writes (``replace_spec_keys_on_update``) and leaves server-owned keys such
as ``spec.deletionRequested`` alone.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import upsert_custom_resource
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
from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION
from styrmin_backend.operator.crd.builder import build_styrmin_deployment_body

_upsert = upsert_custom_resource.__wrapped__
_API = "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CustomObjectsApi"


def _mock_api() -> MagicMock:
    api = MagicMock()
    api.create_namespaced_custom_object = AsyncMock(
        side_effect=ApiException(status=409)
    )
    api.patch_namespaced_custom_object = AsyncMock()
    return api


async def _run(api: MagicMock, body: dict[str, Any]) -> list[dict[str, Any]]:
    with patch(_API, return_value=api):
        await _upsert(
            plurals=CRD_PLURAL,
            body=body,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace="ns",
            replace_spec_keys_on_update=True,
            client=MagicMock(),
        )
    kwargs = api.patch_namespaced_custom_object.call_args.kwargs
    assert kwargs["_content_type"] == "application/json-patch+json"
    return kwargs["body"]


def _apply_add_ops(live: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply RFC 6902 ``add`` ops on object members; a missing parent fails."""
    result = copy.deepcopy(live)
    for op in ops:
        assert op["op"] == "add"
        tokens = [
            t.replace("~1", "/").replace("~0", "~") for t in op["path"].split("/")[1:]
        ]
        *parents, leaf = tokens
        node = result
        for token in parents:
            node = node[token]
        node[leaf] = op["value"]
    return result


def _context(env_vars: dict[str, str] | None) -> GlobalContext:
    deployment_id = uuid4()
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig(env_vars=env_vars)),
        instance=InstanceContext(
            id=uuid4(),
            config=ResolvedConfig(env_vars=env_vars),
            deployment_id=deployment_id,
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


def _crd_body(env_vars: dict[str, str] | None) -> dict[str, Any]:
    return build_styrmin_deployment_body(
        context=_context(env_vars), release_reference="rel", namespace="ns"
    )


@pytest.mark.asyncio
async def test_conflict_replaces_each_spec_key_the_body_sets() -> None:
    body = {
        "metadata": {"name": "rel", "labels": {"app.kubernetes.io/managed-by": "x"}},
        "spec": {"deploymentId": "d", "instanceId": None, "context": {"a": 1}},
    }

    ops = await _run(_mock_api(), body)

    assert ops == [
        {"op": "add", "path": "/spec/deploymentId", "value": "d"},
        {"op": "add", "path": "/spec/instanceId", "value": {}},
        {"op": "remove", "path": "/spec/instanceId"},
        {"op": "add", "path": "/spec/context", "value": {"a": 1}},
        {
            "op": "add",
            "path": "/metadata/labels/app.kubernetes.io~1managed-by",
            "value": "x",
        },
    ]


@pytest.mark.asyncio
async def test_cleared_context_key_is_gone_and_deletion_request_survives() -> None:
    live = _crd_body({"LOG_LEVEL": "debug"})
    live["spec"]["deletionRequested"] = True
    assert live["spec"]["context"]["instance"]["config"]["env_vars"]
    desired = _crd_body(None)

    result = _apply_add_ops(live, await _run(_mock_api(), desired))

    assert "env_vars" not in result["spec"]["context"]["instance"]["config"]
    assert "env_vars" not in result["spec"]["context"]["deployment"]["config"]
    assert result["spec"]["context"] == desired["spec"]["context"]
    assert result["spec"]["deletionRequested"] is True


@pytest.mark.asyncio
async def test_agent_crd_apply_opts_into_per_key_replace() -> None:
    from styrmin_backend.agent.tasks import orchestration

    upsert = AsyncMock()
    body = _crd_body(None)
    with patch.object(orchestration, "upsert_custom_resource", upsert):
        await orchestration._apply_styrmin_deployment_crd(body=body, namespace="ns")

    upsert.assert_awaited_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["plurals"] == CRD_PLURAL
    assert kwargs["body"] is body
    assert kwargs["replace_spec_keys_on_update"] is True
