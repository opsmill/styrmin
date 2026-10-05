from __future__ import annotations

import logging

from kubernetes_asyncio.client import CoreV1Api
from prefect import flow

from styrmin_backend.agent.service.kubernetes.dependency import get_api_client
from styrmin_backend.workflows.models import KubernetesConnectivityResult

logger = logging.getLogger(__name__)


@flow(name="validate_kubernetes_connectivity")
async def validate_kubernetes_connectivity() -> KubernetesConnectivityResult:
    """Validate connectivity to the configured Kubernetes cluster."""

    gen = get_api_client()
    client = await gen.__anext__()

    try:
        v1 = CoreV1Api(client)
        await v1.list_namespace(limit=1)
        return KubernetesConnectivityResult(
            connected=True,
            cluster_info=client.configuration.host,
        )
    except Exception as exc:
        logger.error("Kubernetes connectivity check failed: %s", exc)
        return KubernetesConnectivityResult(
            connected=False,
            error=str(exc),
        )
