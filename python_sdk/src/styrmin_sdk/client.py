"""Main entry point for the Styrmin SDK."""

from __future__ import annotations

import os
from typing import Self

from styrmin_sdk._transport import Transport
from styrmin_sdk.resources.auth import AuthResource
from styrmin_sdk.resources.backup_storage_locations import BackupStorageLocationResource
from styrmin_sdk.resources.backups import BackupResource
from styrmin_sdk.resources.clusters import ClusterResource
from styrmin_sdk.resources.deployments import DeploymentResource
from styrmin_sdk.resources.drivers import DriverResource
from styrmin_sdk.resources.environment_backups import EnvironmentBackupResource
from styrmin_sdk.resources.environment_clones import EnvironmentCloneResource
from styrmin_sdk.resources.environments import EnvironmentResource
from styrmin_sdk.resources.groups import GroupResource
from styrmin_sdk.resources.schedules import ScheduleResource
from styrmin_sdk.resources.tasks import TaskResource
from styrmin_sdk.resources.users import UserResource


class StyrminClient:
    """Async client for the Styrmin API.

    Usage::

        async with StyrminClient(server_address="http://localhost:8000") as client:
            cluster = await client.clusters.create(name="prod")

    Authentication: pass ``token=...`` to authenticate, or set the
    ``STYRMIN_TOKEN`` env var. The explicit kwarg wins when both are present.
    """

    def __init__(
        self,
        server_address: str = "http://localhost:8000",
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        token: str | None = None,
    ) -> None:
        if token is None:
            token = os.environ.get("STYRMIN_TOKEN")
        merged_headers = dict(headers or {})
        if token:
            merged_headers["Authorization"] = f"Bearer {token}"
        self._transport = Transport(
            server_address=server_address,
            timeout=timeout,
            headers=merged_headers,
        )
        self.auth = AuthResource(self._transport)
        self.backup_storage_locations = BackupStorageLocationResource(self._transport)
        self.clusters = ClusterResource(self._transport)
        self.environments = EnvironmentResource(self._transport)
        self.drivers = DriverResource(self._transport)
        self.deployments = DeploymentResource(self._transport)
        self.tasks = TaskResource(self._transport)
        self.backups = BackupResource(self._transport)
        self.environment_backups = EnvironmentBackupResource(self._transport)
        self.environment_clones = EnvironmentCloneResource(self._transport)
        self.schedules = ScheduleResource(self._transport)
        self.users = UserResource(self._transport)
        self.groups = GroupResource(self._transport)

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
