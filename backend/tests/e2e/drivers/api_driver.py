"""ApiScenarioDriver — wraps StyrminClient to satisfy the ScenarioDriver protocol.

Each method is a thin passthrough that normalises SDK errors into the
driver-neutral ``ScenarioActionError`` hierarchy and adapts SDK payloads
into the driver-neutral ref types.
"""

from __future__ import annotations

from typing import Any

from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import ResourceNotFoundError, StyrminError

from tests.e2e.drivers.errors import (
    ResourceNotFound,
    ScenarioActionError,
    ScenarioTimeout,
)
from tests.e2e.drivers.refs import (
    BackupRef,
    BSLRef,
    ClusterRef,
    DeploymentRef,
    DriverVersionRef,
    EnvironmentRef,
    RestoreRef,
    TimelineEntry,
)


def _normalise(exc: Exception) -> Exception:
    """Map an SDK exception onto the driver-neutral hierarchy."""
    if isinstance(exc, ResourceNotFoundError):
        return ResourceNotFound(str(exc))
    if isinstance(exc, StyrminError):
        return ScenarioActionError(str(exc))
    return exc


class ApiScenarioDriver:
    def __init__(self, client: StyrminClient) -> None:
        self._client = client

    # --- Platform setup ---------------------------------------------------

    async def create_cluster(self, *, name: str, config: dict[str, Any]) -> ClusterRef:
        try:
            cluster = await self._client.clusters.create(name=name, config=config)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return ClusterRef(id=str(cluster.id), name=cluster.name)

    async def create_environment(
        self, *, name: str, cluster_id: str, config: dict[str, Any]
    ) -> EnvironmentRef:
        try:
            env = await self._client.environments.create(
                name=name, cluster_id=cluster_id, config=config
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return EnvironmentRef(
            id=str(env.id),
            name=env.name,
            cluster_id=cluster_id,
        )

    async def delete_environment(self, *, environment_id: str) -> None:
        try:
            await self._client.environments.delete(environment_id=environment_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def create_backup_storage_location(
        self,
        *,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> BSLRef:
        try:
            bsl = await self._client.backup_storage_locations.create(
                name=name,
                endpoint=endpoint,
                bucket=bucket,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BSLRef(id=str(bsl.id), name=bsl.name)

    async def assign_bsl_to_environment(
        self, *, environment_id: str, bsl_id: str
    ) -> None:
        try:
            await self._client.backup_storage_locations.assign(
                environment_id=environment_id, bsl_id=bsl_id
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def load_driver_version(self, *, git_url: str, ref: str) -> DriverVersionRef:
        try:
            version = await self._client.drivers.load_version(git_url, ref)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return DriverVersionRef(
            id=str(version.id),
            application_driver_id=str(version.application_driver_id),
            driver_name=getattr(version, "driver_name", "") or "",
            version=getattr(version, "version", "") or "",
        )

    # --- Deployments ------------------------------------------------------

    async def create_deployment(
        self,
        *,
        driver: str,
        version: str,
        environment_id: str,
        name: str | None = None,
        service_name_overrides: list[dict[str, str]] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> DeploymentRef:
        try:
            task = await self._client.deployments.create(
                driver=driver,
                version=version,
                environment_id=environment_id,
                name=name,
                parameters=parameters,
                service_name_overrides=service_name_overrides,
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        deployment_id = task.deployment_id
        if deployment_id is None:
            raise ScenarioActionError(
                "deploy mutation returned a task without a deployment_id"
            )
        return DeploymentRef(
            id=str(deployment_id),
            status="pending",
            application_version=None,
            instance_id=None,
        )

    async def wait_for_deployment_running(
        self, *, deployment_id: str, timeout: float = 300.0
    ) -> DeploymentRef:
        import asyncio
        import time

        deadline = time.time() + timeout
        deployment = None
        while time.time() < deadline:
            try:
                deployment = await self._client.deployments.get(deployment_id)
            except ResourceNotFoundError:
                # Deployment hasn't materialised yet — keep polling. Other
                # SDK errors (auth, 5xx, schema mismatch) propagate so a
                # broken server doesn't hide as a generic timeout.
                deployment = None
            else:
                if deployment.status == "running":
                    instance_id = None
                    if deployment.application_instance:
                        instance_id = str(deployment.application_instance.id)
                    return DeploymentRef(
                        id=str(deployment.id),
                        status=deployment.status,
                        application_version=deployment.application_version,
                        instance_id=instance_id,
                    )
            await asyncio.sleep(10)
        status = deployment.status if deployment else "unknown"
        raise ScenarioTimeout(
            f"Deployment {deployment_id} did not reach 'running' after {timeout}s "
            f"(status: {status})"
        )

    async def upgrade_deployment(self, *, deployment_id: str, version: str) -> None:
        try:
            await self._client.deployments.update_version(deployment_id, version)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def get_deployment_timeline(
        self, *, deployment_id: str
    ) -> list[TimelineEntry]:
        try:
            entries = await self._client.deployments.get_timeline(deployment_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return [
            TimelineEntry(
                task_id=str(entry.task.id),
                # SDK's generated Pydantic model renames ``type`` → ``type_``
                # to avoid shadowing the Python builtin.
                task_type=entry.task.type_,
                task_status=entry.task.status,
                application_version=entry.application_version,
                created_on=(
                    entry.task.created_on.isoformat()
                    if entry.task.created_on is not None
                    else None
                ),
            )
            for entry in entries
        ]

    # --- Backup / Restore -------------------------------------------------

    async def create_backup(self, *, instance_id: str) -> BackupRef:
        try:
            backup = await self._client.backups.create_backup(instance_id=instance_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BackupRef(id=str(backup.id), name=backup.name, status=backup.status)

    async def wait_for_backup(
        self, *, backup_id: str, max_wait: float = 300.0
    ) -> BackupRef:
        try:
            backup = await self._client.backups.wait_for_backup(
                backup_id, max_wait=max_wait
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BackupRef(id=str(backup.id), name=backup.name, status=backup.status)

    async def create_restore(
        self, *, backup_id: str, target_namespace: str
    ) -> RestoreRef:
        try:
            restore = await self._client.backups.create_restore(
                backup_id=backup_id, target_namespace=target_namespace
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return RestoreRef(id=str(restore.id), status=restore.status)

    async def wait_for_restore(
        self, *, restore_id: str, max_wait: float = 600.0
    ) -> RestoreRef:
        try:
            restore = await self._client.backups.wait_for_restore(
                restore_id, max_wait=max_wait
            )
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return RestoreRef(id=str(restore.id), status=restore.status)

    async def delete_backup(self, *, backup_id: str) -> None:
        try:
            await self._client.backups.delete_backup(backup_id)
        except StyrminError as exc:
            raise _normalise(exc) from exc

    async def get_backup(self, *, backup_id: str) -> BackupRef:
        try:
            backup = await self._client.backups.get_backup(backup_id)
        except ResourceNotFoundError as exc:
            raise ResourceNotFound(str(exc)) from exc
        except StyrminError as exc:
            raise _normalise(exc) from exc
        return BackupRef(id=str(backup.id), name=backup.name, status=backup.status)
