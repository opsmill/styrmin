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
from styrmin_sdk.graphql._generated.enums import EnvironmentBackupStatus, EnvironmentRestoreStatus
from styrmin_sdk.graphql._generated.get_environment_backup import (
    GetEnvironmentBackup,
    GetEnvironmentBackupEnvironmentBackup,
)
from styrmin_sdk.graphql._generated.get_environment_restore import (
    GetEnvironmentRestore,
    GetEnvironmentRestoreEnvironmentRestore,
)
from styrmin_sdk.graphql._generated.list_environment_backups import (
    ListEnvironmentBackups,
    ListEnvironmentBackupsEnvironmentBackups,
)
from styrmin_sdk.graphql._generated.list_environment_restores import (
    ListEnvironmentRestores,
    ListEnvironmentRestoresEnvironmentRestores,
)
from styrmin_sdk.graphql._generated.restore_environment_backup import (
    RestoreEnvironmentBackup,
    RestoreEnvironmentBackupRestoreEnvironmentBackup,
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

#: The restore-side sibling of :data:`TERMINAL_ENVIRONMENT_BACKUP_STATUSES`.
#: The two enums are distinct Python types even though they share member names,
#: so a single shared frozenset would never match a restore's status.
TERMINAL_ENVIRONMENT_RESTORE_STATUSES: Final[frozenset[EnvironmentRestoreStatus]] = frozenset(
    {
        EnvironmentRestoreStatus.COMPLETED,
        EnvironmentRestoreStatus.PARTIAL,
        EnvironmentRestoreStatus.FAILED,
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

    async def delete(self, environment_backup_id: str | UUID) -> None:
        """Delete an environment backup and everything that hangs off it.

        Cascades through the constituent backups (and any restores of them) and
        the snapshot's own environment restores.

        Succeeds regardless of the snapshot's derived status: deleting one whose
        constituents are still in flight is the documented escape hatch for an
        environment pinned in progress by a constituent whose work was never
        picked up, which otherwise blocks every new environment-level operation.
        """
        result = await self._transport.execute(
            load_query("delete_environment_backup"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)

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

    async def restore(
        self,
        environment_backup_id: str | UUID,
    ) -> RestoreEnvironmentBackupRestoreEnvironmentBackup:
        """Restore an environment backup in place: revert config, restore every usable constituent.

        Requires the ``ADMIN`` role — the operation reverts the environment's
        config, so it carries the same privilege as editing it directly.

        Constituent classification happens synchronously, so
        ``skipped_constituents`` on the returned record is already complete:
        every constituent that will not be restored is listed with its
        deployment name and a free-text ``reason`` (spec FR-007, zero silent
        skips). Render the reason as text — it is not a closed vocabulary.
        """
        result = await self._transport.execute(
            load_query("restore_environment_backup"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            RestoreEnvironmentBackup,
            result["data"],
            "restore_environment_backup",
            RestoreEnvironmentBackupRestoreEnvironmentBackup,
        )

    async def get_restore(
        self,
        environment_restore_id: str | UUID,
    ) -> GetEnvironmentRestoreEnvironmentRestore:
        result = await self._transport.execute(
            load_query("get_environment_restore"),
            {"environmentRestoreId": str(environment_restore_id)},
        )
        self._check_graphql_errors(result)
        return self._parse(
            GetEnvironmentRestore,
            result["data"],
            "environment_restore",
            GetEnvironmentRestoreEnvironmentRestore,
        )

    async def list_restores(
        self,
        environment_backup_id: str | UUID,
    ) -> list[ListEnvironmentRestoresEnvironmentRestores]:
        """List the coordinated restores performed from an environment backup, newest first."""
        result = await self._transport.execute(
            load_query("list_environment_restores"),
            {"environmentBackupId": str(environment_backup_id)},
        )
        self._check_graphql_errors(result)
        data = ListEnvironmentRestores.model_validate(result["data"])
        return data.environment_restores or []

    async def wait_for_restore(
        self,
        environment_restore_id: str | UUID,
        max_wait: float = 900,
        interval: float = 5,
    ) -> GetEnvironmentRestoreEnvironmentRestore:
        """Poll :meth:`get_restore` until the derived parent status is terminal.

        The default ``max_wait`` is longer than :meth:`wait_for_backup`'s:
        restoring an environment reverts its config and redeploys, so the
        constituent restores start behind a reconciliation the backup path does
        not have to wait for.

        Returns the last observed record when ``max_wait`` elapses first, so
        callers always get a value and can inspect the non-terminal status
        themselves rather than catching a timeout.
        """
        elapsed = 0.0
        while elapsed < max_wait:
            environment_restore = await self.get_restore(environment_restore_id)
            if environment_restore.status in TERMINAL_ENVIRONMENT_RESTORE_STATUSES:
                return environment_restore
            await asyncio.sleep(interval)
            elapsed += interval
        return await self.get_restore(environment_restore_id)
