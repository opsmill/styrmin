"""Unit tests for the cluster-side tasks of the backup storage location sync flows (#488).

The task bodies run through ``Task.fn`` with the Kubernetes config, the API
client and ``VeleroClient`` patched.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from styrmin_backend.agent.service.kubernetes.velero.client import BslDeletion
from styrmin_backend.workflows.templates.bsl_sync import (
    create_velero_bsl_task,
    delete_velero_bsl_task,
)

MODULE = "styrmin_backend.workflows.templates.bsl_sync"
VELERO_CLIENT = "styrmin_backend.agent.service.kubernetes.velero.client.VeleroClient"
BSL_ID = "550e8400-e29b-41d4-a716-446655440000"


@contextmanager
def _cluster(velero_client: MagicMock, logger: MagicMock) -> Generator[None]:
    api_client = MagicMock()
    api_client.close = AsyncMock()
    with (
        patch("kubernetes_asyncio.config.load_incluster_config", MagicMock()),
        patch("kubernetes_asyncio.client.ApiClient", return_value=api_client),
        patch(VELERO_CLIENT, return_value=velero_client),
        patch(f"{MODULE}.get_run_logger", return_value=logger),
    ):
        yield


async def _create(velero_client: MagicMock, logger: MagicMock) -> None:
    with _cluster(velero_client, logger):
        await create_velero_bsl_task.fn(
            bsl_id=BSL_ID,
            namespace="styrmin",
            bucket="backups",
            region="us-east-1",
            endpoint="https://s3.example.com",
            access_key_id="key",
            secret_access_key="secret",
        )


async def test_create_makes_the_objects_when_the_location_has_none() -> None:
    velero_client = MagicMock()
    velero_client.list_bsl_names = AsyncMock(return_value=[])
    velero_client.create_bsl = AsyncMock()

    await _create(velero_client, MagicMock())

    velero_client.list_bsl_names.assert_awaited_once_with(BSL_ID, "styrmin")
    created = velero_client.create_bsl.await_args.kwargs["bsl"]
    assert created.name == f"styrmin-bsl-{BSL_ID}"


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
