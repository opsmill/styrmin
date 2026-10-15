"""Unit tests for the create-path ``null`` pruning in ``upsert_custom_resource``.

A values template may render ``key: null``. The *create* ``POST`` would store it
verbatim, so the caller passes ``prune_none_on_create=True`` to strip it; the
merge-patch *update* path keeps the ``null``, which deletes the key (RFC 7386).
These tests pin both halves of that contract plus the recursive prune helper.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.primitives import (
    _prune_none,
    upsert_custom_resource,
)

# Call the undecorated function so we can inject a mock client directly without
# fast_depends' ``ApiClient`` type validation.
_upsert = upsert_custom_resource.__wrapped__


class TestPruneNone:
    def test_drops_none_keys_recursively(self) -> None:
        assert _prune_none({"a": None, "b": 1, "c": {"d": None, "e": 2}}) == {
            "b": 1,
            "c": {"e": 2},
        }

    def test_recurses_into_lists_but_keeps_elements(self) -> None:
        assert _prune_none({"l": [{"x": None, "y": 1}, "z"]}) == {"l": [{"y": 1}, "z"]}

    def test_empty_dict_after_prune_is_kept_not_dropped(self) -> None:
        # An emptied sub-map is not None, so it stays — we never over-prune
        # structural keys the chart may rely on.
        assert _prune_none({"outer": {"only": None}}) == {"outer": {}}

    def test_non_container_values_pass_through(self) -> None:
        assert _prune_none("x") == "x"
        assert _prune_none(0) == 0
        assert _prune_none([1, None, 2]) == [1, None, 2]


def _mock_api() -> tuple[MagicMock, MagicMock]:
    api = MagicMock()
    api.create_namespaced_custom_object = AsyncMock()
    api.patch_namespaced_custom_object = AsyncMock()
    return api, MagicMock()  # api, dummy client


_BODY = {
    "metadata": {"name": "rel"},
    "spec": {
        "values": {"infrahubServer": {"infrahubServer": {"args": None, "env": {}}}}
    },
}


@pytest.mark.asyncio
async def test_create_prunes_none_when_flag_set() -> None:
    api, client = _mock_api()
    with patch(
        "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CustomObjectsApi",
        return_value=api,
    ):
        await _upsert(
            plurals="helmreleases",
            body=_BODY,
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace="ns",
            prune_none_on_create=True,
            client=client,
        )
    sent = api.create_namespaced_custom_object.call_args.kwargs["body"]
    inner = sent["spec"]["values"]["infrahubServer"]["infrahubServer"]
    assert "args" not in inner, "null args must be pruned from the create body"
    assert inner == {"env": {}}, "non-null siblings must survive"
    # The caller's original body is untouched (prune works on a copy).
    assert _BODY["spec"]["values"]["infrahubServer"]["infrahubServer"]["args"] is None


@pytest.mark.asyncio
async def test_create_keeps_none_when_flag_unset() -> None:
    api, client = _mock_api()
    with patch(
        "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CustomObjectsApi",
        return_value=api,
    ):
        await _upsert(
            plurals="things",
            body=_BODY,
            group="g",
            version="v1",
            namespace="ns",
            client=client,
        )
    sent = api.create_namespaced_custom_object.call_args.kwargs["body"]
    assert sent["spec"]["values"]["infrahubServer"]["infrahubServer"]["args"] is None


@pytest.mark.asyncio
async def test_update_patch_retains_none_for_deletion() -> None:
    """On 409 the merge-patch body keeps ``null`` so it deletes the key."""
    api, client = _mock_api()
    api.create_namespaced_custom_object.side_effect = ApiException(status=409)
    with patch(
        "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CustomObjectsApi",
        return_value=api,
    ):
        await _upsert(
            plurals="helmreleases",
            body=_BODY,
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace="ns",
            prune_none_on_create=True,
            client=client,
        )
    api.patch_namespaced_custom_object.assert_awaited_once()
    kwargs = api.patch_namespaced_custom_object.call_args.kwargs
    assert kwargs["_content_type"] == "application/merge-patch+json"
    inner = kwargs["body"]["spec"]["values"]["infrahubServer"]["infrahubServer"]
    assert inner["args"] is None, "patch must keep null so merge-patch deletes the key"
