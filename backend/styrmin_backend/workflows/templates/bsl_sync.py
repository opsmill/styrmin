"""Prefect workflow templates for BSL sync operations.

Manages the lifecycle of Velero BackupStorageLocation CRDs and their
credential Secrets on Kubernetes clusters.

INTERNAL flows (styrmin-work-pool): DB lookups, dispatching USER flows.
USER flows (user-work-pool / K8s Job): K8s operations only.
"""

from __future__ import annotations

from typing import Any

from prefect import flow, task
from prefect.logging import get_run_logger

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupStorageLocation,
)


def _build_velero_bsl(
    bsl_name: str,
    bsl_id: str,
    namespace: str,
    bucket: str,
    region: str,
    endpoint: str,
) -> VeleroBackupStorageLocation:
    """Build a VeleroBackupStorageLocation dataclass."""
    velero_name = f"styrmin-bsl-{bsl_name}"
    return VeleroBackupStorageLocation(
        name=velero_name,
        namespace=namespace,
        bucket=bucket,
        region=region,
        endpoint=endpoint,
        credential_secret_name=f"{velero_name}-credentials",
        bsl_id=bsl_id,
    )


@task(task_run_name="Create Velero BSL: {bsl_name}")
async def create_velero_bsl_task(
    bsl_name: str,
    bsl_id: str,
    namespace: str,
    bucket: str,
    region: str,
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
) -> dict[str, Any]:
    """Create the Velero BSL CRD and credential Secret on the cluster."""
    from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClient
    from kubernetes_asyncio import client as k8s_client
    from kubernetes_asyncio.config import load_incluster_config

    logger = get_run_logger()

    load_incluster_config()
    api_client = k8s_client.ApiClient()

    try:
        velero_client = VeleroClient(api_client)
        bsl = _build_velero_bsl(
            bsl_name=bsl_name,
            bsl_id=bsl_id,
            namespace=namespace,
            bucket=bucket,
            region=region,
            endpoint=endpoint,
        )
        result = await velero_client.create_bsl(
            bsl=bsl,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        logger.info(f"Created Velero BSL '{bsl.name}' on cluster")
        return result
    finally:
        await api_client.close()


@task(task_run_name="Delete Velero BSL: {bsl_name}")
async def delete_velero_bsl_task(
    bsl_name: str,
    namespace: str,
) -> None:
    """Delete the Velero BSL CRD and credential Secret from the cluster."""
    from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClient
    from kubernetes_asyncio import client as k8s_client
    from kubernetes_asyncio.config import load_incluster_config

    logger = get_run_logger()

    load_incluster_config()
    api_client = k8s_client.ApiClient()

    try:
        velero_client = VeleroClient(api_client)
        velero_name = f"styrmin-bsl-{bsl_name}"
        secret_name = f"{velero_name}-credentials"
        await velero_client.delete_bsl(
            name=velero_name, secret_name=secret_name, namespace=namespace
        )
        logger.info(f"Deleted Velero BSL '{velero_name}' from cluster")
    finally:
        await api_client.close()


@task(task_run_name="Update Velero BSL credentials: {bsl_name}")
async def update_velero_bsl_credentials_task(
    bsl_name: str,
    namespace: str,
    access_key_id: str,
    secret_access_key: str,
) -> None:
    """Update the credential Secret for a Velero BSL on the cluster."""
    from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClient
    from kubernetes_asyncio import client as k8s_client
    from kubernetes_asyncio.config import load_incluster_config

    logger = get_run_logger()

    load_incluster_config()
    api_client = k8s_client.ApiClient()

    try:
        velero_client = VeleroClient(api_client)
        velero_name = f"styrmin-bsl-{bsl_name}"
        secret_name = f"{velero_name}-credentials"
        await velero_client.update_bsl_secret(
            secret_name=secret_name,
            namespace=namespace,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        logger.info(f"Updated credentials for Velero BSL '{velero_name}'")
    finally:
        await api_client.close()


@flow(name="sync-bsl-create")
async def sync_bsl_create_flow(
    bsl_id: str,
    bsl_name: str,
    namespace: str,
    bucket: str,
    region: str,
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
) -> dict[str, Any]:
    """Create a Velero BSL and credentials on the cluster."""
    return await create_velero_bsl_task(
        bsl_name=bsl_name,
        bsl_id=bsl_id,
        namespace=namespace,
        bucket=bucket,
        region=region,
        endpoint=endpoint,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )


@flow(name="sync-bsl-delete")
async def sync_bsl_delete_flow(
    bsl_name: str,
    namespace: str,
) -> None:
    """Delete a Velero BSL and credentials from the cluster."""
    await delete_velero_bsl_task(bsl_name=bsl_name, namespace=namespace)


@flow(name="sync-bsl-update-credentials")
async def sync_bsl_update_credentials_flow(
    bsl_name: str,
    namespace: str,
    access_key_id: str,
    secret_access_key: str,
) -> None:
    """Update credentials for a Velero BSL on the cluster."""
    await update_velero_bsl_credentials_task(
        bsl_name=bsl_name,
        namespace=namespace,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )
