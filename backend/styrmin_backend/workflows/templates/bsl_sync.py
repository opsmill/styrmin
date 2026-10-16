"""Prefect workflow templates for BSL sync operations.

Manages the lifecycle of Velero BackupStorageLocation CRDs and their
credential Secrets on Kubernetes clusters. The flows identify a location by its
id, never by its name, which an administrator can change.

INTERNAL flows (styrmin-work-pool): DB lookups, dispatching USER flows.
USER flows (user-work-pool / K8s Job): K8s operations only.
"""

from __future__ import annotations

from prefect import flow, task
from prefect.logging import get_run_logger

from styrmin_backend.agent.service.kubernetes.velero.resources import (
    VeleroBackupStorageLocation,
)


@task(task_run_name="Create Velero BSL: {bsl_id}")
async def create_velero_bsl_task(
    bsl_id: str,
    namespace: str,
    bucket: str,
    region: str,
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
) -> None:
    """Create the Velero BSL CRD and credential Secret on the cluster.

    Creates nothing when a Velero BSL with the location's id label already
    exists, whatever its name, so the cluster never has two Velero locations
    for one location.
    """
    from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClient
    from kubernetes_asyncio import client as k8s_client
    from kubernetes_asyncio.config import load_incluster_config

    logger = get_run_logger()

    load_incluster_config()
    api_client = k8s_client.ApiClient()

    try:
        velero_client = VeleroClient(api_client)
        if existing := await velero_client.list_bsl_names(bsl_id, namespace):
            logger.info(
                f"Velero BSL of location {bsl_id} already exists "
                f"({', '.join(existing)}), nothing to create"
            )
            return
        bsl = VeleroBackupStorageLocation(
            bsl_id=bsl_id,
            namespace=namespace,
            bucket=bucket,
            region=region,
            endpoint=endpoint,
        )
        await velero_client.create_bsl(
            bsl=bsl,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        logger.info(f"Created Velero BSL '{bsl.name}' on cluster")
    finally:
        await api_client.close()


@task(task_run_name="Delete Velero BSL: {bsl_id}")
async def delete_velero_bsl_task(
    bsl_id: str,
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
        deleted = await velero_client.delete_bsl(bsl_id=bsl_id, namespace=namespace)
        logger.info(
            f"Deleted {deleted.locations} Velero BSL(s) and {deleted.secrets} "
            f"credential Secret(s) of location {bsl_id} from cluster"
        )
    finally:
        await api_client.close()


@task(task_run_name="Update Velero BSL credentials: {bsl_id}")
async def update_velero_bsl_credentials_task(
    bsl_id: str,
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
        await velero_client.update_bsl_secret(
            bsl_id=bsl_id,
            namespace=namespace,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        logger.info(f"Updated credentials for the Velero BSL of location {bsl_id}")
    finally:
        await api_client.close()


@flow(name="sync-bsl-create")
async def sync_bsl_create_flow(
    bsl_id: str,
    namespace: str,
    bucket: str,
    region: str,
    endpoint: str,
    access_key_id: str,
    secret_access_key: str,
) -> None:
    """Create a Velero BSL and credentials on the cluster."""
    await create_velero_bsl_task(
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
    bsl_id: str,
    namespace: str,
) -> None:
    """Delete a Velero BSL and credentials from the cluster."""
    await delete_velero_bsl_task(bsl_id=bsl_id, namespace=namespace)


@flow(name="sync-bsl-update-credentials")
async def sync_bsl_update_credentials_flow(
    bsl_id: str,
    namespace: str,
    access_key_id: str,
    secret_access_key: str,
) -> None:
    """Update credentials for a Velero BSL on the cluster."""
    await update_velero_bsl_credentials_task(
        bsl_id=bsl_id,
        namespace=namespace,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )
