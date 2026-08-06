"""Environment-level backup and restore resource operations.

The environment-level surface is the coordinated counterpart to
:mod:`styrmin_sdk.resources.backups`: one parent record groups one constituent
backup per eligible deployment in an environment. The parent's ``status`` is
*derived* from its constituents on every read (never stored), so polling for
completion means polling for a terminal derived status rather than a stored
column flipping.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from uuid import UUID

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.create_environment_backup import (
    CreateEnvironmentBackup,
    CreateEnvironmentBackupCreateEnvironmentBackup,
)
from styrmin_sdk.graphql._generated.enums import EnvironmentBackupStatus
from styrmin_sdk.graphql._generated.get_environment_backup import (
    GetEnvironmentBackup,
    GetEnvironmentBackupEnvironmentBackup,
)
from styrmin_sdk.graphql._generated.list_environment_backups import (
    ListEnvironmentBackups,
    ListEnvironmentBackupsEnvironmentBackups,
)
from styrmin_sdk.resources._base import BaseResource

#: Derived statuses that will never change again. ``PARTIAL`` is terminal: it
#: means some constituents failed and the rest completed, which is a final
#: outcome, not a transitional one.
TERMINAL_ENVIRONMENT_BACKUP_STATUSES: Final[frozenset[EnvironmentBackupStatus]] = frozenset(
    {
        EnvironmentBackupStatus.COMPLETED,
        EnvironmentBackupStatus.PARTIAL,
        EnvironmentBackupStatus.FAILED,
    }
)


class EnvironmentBackupResource(BaseResource):
    """``client.environment_backups`` — coordinated environment snapshots."""

    async def create(
        self,
        environment_id: str | UUID,
        name: str | None = None,
    ) -> CreateEnvironmentBackupCreateEnvironmentBackup:
        """Create an environment backup and dispatch one constituent per eligible deployment.

        Returns as soon as every constituent has been created and dispatched, so
        the returned ``status`` is typically ``PENDING`` or ``IN_PROGRESS``. An
        environment with no eligible deployments yields a config-only snapshot
        that is ``COMPLETED`` immediately.
        """
        variables: dict[str, Any] = {"environmentId": str(environment_id)}
        if name is not None:
            variables["name"] = name

        result = await self._transport.execute(load_query("create_environment_backup"), variables)
        self._check_graphql_errors(result)
        return self._parse(
            CreateEnvironmentBackup,
            result["data"],
            "create_environment_backup",
            CreateEnvironmentBackupCreateEnvironmentBackup,
        )

    async def get(self, environment_backup_id: str | UUID) -> GetEnvironmentBackupEnvironmentBackup:
        result = await self._transport.execute(
            load_query("get_environment_backup"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            GetEnvironmentBackup,
            result["data"],
            "environment_backup",
            GetEnvironmentBackupEnvironmentBackup,
        )

    async def list(self, environment_id: str | UUID) -> list[ListEnvironmentBackupsEnvironmentBackups]:
        """List an environment's environment backups, newest first."""
        result = await self._transport.execute(
            load_query("list_environment_backups"),
            {"environmentId": str(environment_id)},
        )
        self._check_graphql_errors(result)
        data = ListEnvironmentBackups.model_validate(result["data"])
        return data.environment_backups or []

    async def wait_for_backup(
        self,
        environment_backup_id: str | UUID,
        max_wait: float = 600,
        interval: float = 5,
    ) -> GetEnvironmentBackupEnvironmentBackup:
        """Poll :meth:`get` until the derived parent status is terminal.

        Returns the last observed snapshot when ``max_wait`` elapses first, so
        callers always get a value and can inspect the non-terminal status
        themselves rather than catching a timeout.
        """
        elapsed = 0.0
        while elapsed < max_wait:
            environment_backup = await self.get(environment_backup_id)
            if environment_backup.status in TERMINAL_ENVIRONMENT_BACKUP_STATUSES:
                return environment_backup
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get(environment_backup_id)
