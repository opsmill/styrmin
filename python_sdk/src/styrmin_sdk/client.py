"""Main entry point for the Styrmin SDK."""

from __future__ import annotations

from typing import Self

from styrmin_sdk._transport import Transport
from styrmin_sdk.resources.backup_storage_locations import BackupStorageLocationResource
from styrmin_sdk.resources.backups import BackupResource
from styrmin_sdk.resources.clusters import ClusterResource
from styrmin_sdk.resources.deployments import DeploymentResource
from styrmin_sdk.resources.drivers import DriverResource
from styrmin_sdk.resources.environment_backups import (
    EnvironmentBackupResource,
    EnvironmentRestoreResource,
)
from styrmin_sdk.resources.environments import EnvironmentResource
from styrmin_sdk.resources.schedules import ScheduleResource
from styrmin_sdk.resources.tasks import TaskResource


class StyrminClient:
    """Async client for the Styrmin API.

    Usage::

        async with StyrminClient(server_address="http://localhost:8000") as client:
            cluster = await client.clusters.create(name="prod")
    """

    def __init__(
        self,
        server_address: str = "http://localhost:8000",
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._transport = Transport(
            server_address=server_address,
            timeout=timeout,
            headers=headers,
        )
        self.backup_storage_locations = BackupStorageLocationResource(self._transport)
        self.clusters = ClusterResource(self._transport)
        self.environments = EnvironmentResource(self._transport)
        self.drivers = DriverResource(self._transport)
        self.deployments = DeploymentResource(self._transport)
        self.tasks = TaskResource(self._transport)
        self.backups = BackupResource(self._transport)
        self.environment_backups = EnvironmentBackupResource(self._transport)
        self.environment_restores = EnvironmentRestoreResource(self._transport)
        self.schedules = ScheduleResource(self._transport)

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
