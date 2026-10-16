"""Unit tests for the cluster-side tasks of the backup storage location sync flows (#488, #497).

The task bodies run through ``Task.fn`` with the Kubernetes config, the API
client, ``VeleroClient`` and the credentials block patched.
"""

from __future__ import annotations

import inspect
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.agent.service.kubernetes.velero.client import BslDeletion
from styrmin_backend.workflows.bsl_credentials import BslCredentials
from styrmin_backend.workflows.templates.bsl_sync import (
    create_velero_bsl_task,
    delete_velero_bsl_task,
    sync_bsl_create_flow,
    sync_bsl_update_credentials_flow,
    update_velero_bsl_credentials_task,
)

MODULE = "styrmin_backend.workflows.templates.bsl_sync"
VELERO_CLIENT = "styrmin_backend.agent.service.kubernetes.velero.client.VeleroClient"
BSL_ID = "550e8400-e29b-41d4-a716-446655440000"
CREDENTIALS = BslCredentials(access_key_id="key", secret_access_key="secret")


@contextmanager
def _cluster(velero_client: MagicMock, logger: MagicMock) -> Generator[AsyncMock]:
    api_client = MagicMock()
    api_client.close = AsyncMock()
    with (
        patch("kubernetes_asyncio.config.load_incluster_config", MagicMock()),
        patch("kubernetes_asyncio.client.ApiClient", return_value=api_client),
        patch(VELERO_CLIENT, return_value=velero_client),
        patch(f"{MODULE}.get_run_logger", return_value=logger),
        patch(
            f"{MODULE}.load_bsl_credentials", AsyncMock(return_value=CREDENTIALS)
        ) as load_credentials,
    ):
        yield load_credentials


async def _create(velero_client: MagicMock, logger: MagicMock) -> None:
    with _cluster(velero_client, logger):
        await create_velero_bsl_task.fn(
            bsl_id=BSL_ID,
            namespace="styrmin",
            bucket="backups",
            region="us-east-1",
            endpoint="https://s3.example.com",
        )


async def test_create_makes_the_objects_when_the_location_has_none() -> None:
    velero_client = MagicMock()
    velero_client.list_bsl_names = AsyncMock(return_value=[])
    velero_client.create_bsl = AsyncMock()

    await _create(velero_client, MagicMock())

    velero_client.list_bsl_names.assert_awaited_once_with(BSL_ID, "styrmin")
    created = velero_client.create_bsl.await_args.kwargs["bsl"]
    assert created.name == f"styrmin-bsl-{BSL_ID}"


async def test_create_writes_the_keys_of_the_location_credentials_block() -> None:
    velero_client = MagicMock()
    velero_client.list_bsl_names = AsyncMock(return_value=[])
    velero_client.create_bsl = AsyncMock()

    with _cluster(velero_client, MagicMock()) as load_credentials:
        await create_velero_bsl_task.fn(
            bsl_id=BSL_ID,
            namespace="styrmin",
            bucket="backups",
            region="us-east-1",
            endpoint="https://s3.example.com",
        )

    load_credentials.assert_awaited_once_with(BSL_ID)
    kwargs = velero_client.create_bsl.await_args.kwargs
    assert (kwargs["access_key_id"], kwargs["secret_access_key"]) == ("key", "secret")


async def test_update_writes_the_keys_of_the_location_credentials_block() -> None:
    velero_client = MagicMock()
    velero_client.update_bsl_secret = AsyncMock()

    with _cluster(velero_client, MagicMock()) as load_credentials:
        await update_velero_bsl_credentials_task.fn(bsl_id=BSL_ID, namespace="styrmin")

    load_credentials.assert_awaited_once_with(BSL_ID)
    velero_client.update_bsl_secret.assert_awaited_once_with(
        bsl_id=BSL_ID,
        namespace="styrmin",
        access_key_id="key",
        secret_access_key="secret",
    )


@pytest.mark.parametrize(
    "flow", [sync_bsl_create_flow, sync_bsl_update_credentials_flow]
)
def test_flows_take_no_s3_keys_as_parameters(flow) -> None:
    """#497: Prefect stores flow-run parameters, so the keys must not be one."""
    parameters = inspect.signature(flow.fn).parameters
    assert not {"access_key_id", "secret_access_key"} & parameters.keys()


async def test_create_adds_nothing_beside_an_existing_object_of_the_location() -> None:
    """Assigning the location again must not add a second Velero location for the bucket."""
    velero_client = MagicMock()
    velero_client.list_bsl_names = AsyncMock(return_value=["styrmin-bsl-old-name"])
    velero_client.create_bsl = AsyncMock()
    logger = MagicMock()

    await _create(velero_client, logger)

    velero_client.create_bsl.assert_not_awaited()
    assert "styrmin-bsl-old-name" in logger.info.call_args.args[0]


async def test_delete_logs_how_many_objects_it_deleted() -> None:
    velero_client = MagicMock()
    velero_client.delete_bsl = AsyncMock(
        return_value=BslDeletion(locations=0, secrets=0)
    )
    logger = MagicMock()

    with _cluster(velero_client, logger):
        await delete_velero_bsl_task.fn(bsl_id=BSL_ID, namespace="styrmin")

    message = logger.info.call_args.args[0]
    assert "Deleted 0 Velero BSL(s) and 0 credential Secret(s)" in message
