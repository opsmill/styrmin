"""Unit tests for the Prefect Secret block that holds a location's S3 keys (#497)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from prefect.blocks.system import Secret
from prefect.exceptions import ObjectNotFound

from styrmin_backend.workflows.bsl_credentials import (
    BslCredentials,
    credentials_block_name,
    delete_bsl_credentials,
    load_bsl_credentials,
    save_bsl_credentials,
)

MODULE = "styrmin_backend.workflows.bsl_credentials"
BSL_ID = "550e8400-e29b-41d4-a716-446655440000"
BLOCK_NAME = f"styrmin-bsl-{BSL_ID}-credentials"
CREDENTIALS = BslCredentials(access_key_id="AKIA", secret_access_key="s3cr3t")


def test_block_is_named_after_the_location_id() -> None:
    assert credentials_block_name(BSL_ID) == BLOCK_NAME


async def test_save_stores_the_keys_as_a_json_string() -> None:
    """Prefect API reads return a dict value of a Secret block in plain text."""
    with patch.object(Secret, "asave", autospec=True) as asave:
        await save_bsl_credentials(BSL_ID, CREDENTIALS)

    secret, name = asave.await_args.args
    assert name == BLOCK_NAME
    assert asave.await_args.kwargs == {"overwrite": True}
    value = secret.value.get_secret_value()
    assert isinstance(value, str)
    assert json.loads(value) == {"access_key_id": "AKIA", "secret_access_key": "s3cr3t"}


async def test_load_returns_the_saved_keys() -> None:
    saved = Secret(
        value=json.dumps({"access_key_id": "AKIA", "secret_access_key": "s3cr3t"})
    )
    with patch.object(Secret, "aload", AsyncMock(return_value=saved)) as aload:
        assert await load_bsl_credentials(BSL_ID) == CREDENTIALS

    aload.assert_awaited_once_with(BLOCK_NAME)


def _client(read: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.read_block_document_by_name = read
    client.delete_block_document = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


async def test_delete_removes_the_block() -> None:
    document_id = uuid4()
    read = AsyncMock(return_value=MagicMock(id=document_id))
    context = _client(read)

    with patch(f"{MODULE}.get_client", return_value=context):
        await delete_bsl_credentials(BSL_ID)

    read.assert_awaited_once_with(
        BLOCK_NAME, block_type_slug="secret", include_secrets=False
    )
    client = context.__aenter__.return_value
    client.delete_block_document.assert_awaited_once_with(document_id)


async def test_delete_does_nothing_when_there_is_no_block() -> None:
    """A location that was never assigned has no block."""
    response = httpx.Response(404, request=httpx.Request("GET", "http://prefect"))
    not_found = ObjectNotFound(
        http_exc=httpx.HTTPStatusError("", request=response.request, response=response)
    )
    context = _client(AsyncMock(side_effect=not_found))

    with patch(f"{MODULE}.get_client", return_value=context):
        await delete_bsl_credentials(BSL_ID)

    context.__aenter__.return_value.delete_block_document.assert_not_awaited()
