"""Unit tests for the backup storage location methods of ``VeleroClient`` (#488).

The client finds a location's Velero object and credentials Secret by the
``styrmin.io/bsl-id`` label, so a renamed location, and objects that an earlier
Styrmin version named after the location's name, are still found.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client import ApiException

from styrmin_backend.agent.service.kubernetes.velero.client import (
    BslDeletion,
    VeleroClient,
    VeleroClientError,
)

BSL_ID = "550e8400-e29b-41d4-a716-446655440000"
SELECTOR = f"styrmin.io/bsl-id={BSL_ID}"
CORE_V1_API = "kubernetes_asyncio.client.CoreV1Api"


def _bsl_items(*names: str) -> dict[str, Any]:
    return {"items": [{"metadata": {"name": name}} for name in names]}


def _secret_list(*names: str) -> SimpleNamespace:
    return SimpleNamespace(
        items=[SimpleNamespace(metadata=SimpleNamespace(name=name)) for name in names]
    )


def _client(bsl_names: tuple[str, ...] = ()) -> VeleroClient:
    client = VeleroClient(api_client=MagicMock())
    client.custom_api = MagicMock()
    client.custom_api.list_namespaced_custom_object = AsyncMock(
        return_value=_bsl_items(*bsl_names)
    )
    client.custom_api.delete_namespaced_custom_object = AsyncMock()
    return client


def _core_api(secret_names: tuple[str, ...] = ()) -> MagicMock:
    core_api = MagicMock()
    core_api.list_namespaced_secret = AsyncMock(
        return_value=_secret_list(*secret_names)
    )
    core_api.delete_namespaced_secret = AsyncMock()
    core_api.patch_namespaced_secret = AsyncMock()
    return core_api


# get_bsl_name ----------------------------------------------------------------


async def test_get_bsl_name_selects_by_location_id_label() -> None:
    client = _client((f"styrmin-bsl-{BSL_ID}",))

    assert await client.get_bsl_name(BSL_ID, "styrmin") == f"styrmin-bsl-{BSL_ID}"
    assert (
        client.custom_api.list_namespaced_custom_object.await_args.kwargs[
            "label_selector"
        ]
        == SELECTOR
    )


async def test_get_bsl_name_finds_an_object_named_after_the_location_name() -> None:
    client = _client(("styrmin-bsl-old-name",))

    assert await client.get_bsl_name(BSL_ID, "styrmin") == "styrmin-bsl-old-name"


async def test_get_bsl_name_prefers_the_object_named_after_the_id() -> None:
    client = _client(("styrmin-bsl-old-name", f"styrmin-bsl-{BSL_ID}"))

    assert await client.get_bsl_name(BSL_ID, "styrmin") == f"styrmin-bsl-{BSL_ID}"


async def test_get_bsl_name_raises_when_the_location_has_no_object() -> None:
    client = _client()

    with pytest.raises(VeleroClientError, match=BSL_ID):
        await client.get_bsl_name(BSL_ID, "styrmin")


# delete_bsl ------------------------------------------------------------------


async def test_delete_bsl_removes_every_labelled_object_whatever_its_name() -> None:
    client = _client((f"styrmin-bsl-{BSL_ID}", "styrmin-bsl-old-name"))
    core_api = _core_api(("styrmin-bsl-old-name-credentials",))

    with patch(CORE_V1_API, return_value=core_api):
        deleted = await client.delete_bsl(bsl_id=BSL_ID, namespace="styrmin")

    assert deleted == BslDeletion(locations=2, secrets=1)
    deleted_bsls = [
        call.kwargs["name"]
        for call in client.custom_api.delete_namespaced_custom_object.await_args_list
    ]
    assert deleted_bsls == [f"styrmin-bsl-{BSL_ID}", "styrmin-bsl-old-name"]
    core_api.list_namespaced_secret.assert_awaited_once_with(
        namespace="styrmin", label_selector=SELECTOR
    )
    core_api.delete_namespaced_secret.assert_awaited_once_with(
        name="styrmin-bsl-old-name-credentials", namespace="styrmin"
    )


async def test_delete_bsl_with_nothing_left_in_the_cluster_succeeds() -> None:
    client = _client()
    core_api = _core_api()

    with patch(CORE_V1_API, return_value=core_api):
        deleted = await client.delete_bsl(bsl_id=BSL_ID, namespace="styrmin")

    assert deleted == BslDeletion(locations=0, secrets=0)
    client.custom_api.delete_namespaced_custom_object.assert_not_awaited()
    core_api.delete_namespaced_secret.assert_not_awaited()


async def test_delete_bsl_treats_an_object_deleted_meanwhile_as_removed() -> None:
    client = _client((f"styrmin-bsl-{BSL_ID}",))
    client.custom_api.delete_namespaced_custom_object.side_effect = ApiException(
        status=404
    )
    core_api = _core_api((f"styrmin-bsl-{BSL_ID}-credentials",))
    core_api.delete_namespaced_secret.side_effect = ApiException(status=404)

    with patch(CORE_V1_API, return_value=core_api):
        deleted = await client.delete_bsl(bsl_id=BSL_ID, namespace="styrmin")

    # Removed, but not by this call.
    assert deleted == BslDeletion(locations=0, secrets=0)


async def test_delete_bsl_removes_the_secret_when_the_velero_object_fails() -> None:
    client = _client((f"styrmin-bsl-{BSL_ID}",))
    client.custom_api.delete_namespaced_custom_object.side_effect = ApiException(
        status=500
    )
    core_api = _core_api((f"styrmin-bsl-{BSL_ID}-credentials",))

    with (
        patch(CORE_V1_API, return_value=core_api),
        pytest.raises(VeleroClientError, match="Velero BSL"),
    ):
        await client.delete_bsl(bsl_id=BSL_ID, namespace="styrmin")

    core_api.delete_namespaced_secret.assert_awaited_once_with(
        name=f"styrmin-bsl-{BSL_ID}-credentials", namespace="styrmin"
    )


# update_bsl_secret -----------------------------------------------------------


async def test_update_bsl_secret_patches_the_labelled_secret() -> None:
    client = _client()
    core_api = _core_api(("styrmin-bsl-old-name-credentials",))

    with patch(CORE_V1_API, return_value=core_api):
        await client.update_bsl_secret(
            bsl_id=BSL_ID,
            namespace="styrmin",
            access_key_id="new-key",
            secret_access_key="new-secret",
        )

    core_api.list_namespaced_secret.assert_awaited_once_with(
        namespace="styrmin", label_selector=SELECTOR
    )
    patched = core_api.patch_namespaced_secret.await_args.kwargs
    assert patched["name"] == "styrmin-bsl-old-name-credentials"
    assert "aws_access_key_id = new-key" in patched["body"]["stringData"]["cloud"]


async def test_update_bsl_secret_raises_when_the_location_has_no_secret() -> None:
    client = _client()
    core_api = _core_api()

    with (
        patch(CORE_V1_API, return_value=core_api),
        pytest.raises(VeleroClientError, match=BSL_ID),
    ):
        await client.update_bsl_secret(
            bsl_id=BSL_ID,
            namespace="styrmin",
            access_key_id="new-key",
            secret_access_key="new-secret",
        )

    core_api.patch_namespaced_secret.assert_not_awaited()


async def test_update_bsl_secret_patches_the_other_secrets_after_a_failure() -> None:
    client = _client()
    core_api = _core_api(
        (f"styrmin-bsl-{BSL_ID}-credentials", "styrmin-bsl-old-name-credentials")
    )
    core_api.patch_namespaced_secret.side_effect = [ApiException(status=500), None]

    with (
        patch(CORE_V1_API, return_value=core_api),
        pytest.raises(VeleroClientError, match=f"styrmin-bsl-{BSL_ID}-credentials"),
    ):
        await client.update_bsl_secret(
            bsl_id=BSL_ID,
            namespace="styrmin",
            access_key_id="new-key",
            secret_access_key="new-secret",
        )

    patched = [
        call.kwargs["name"] for call in core_api.patch_namespaced_secret.await_args_list
    ]
    assert patched == [
        f"styrmin-bsl-{BSL_ID}-credentials",
        "styrmin-bsl-old-name-credentials",
    ]
