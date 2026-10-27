"""Pods read from a kind cluster with ``kubectl get pod -o json`` (#574).

Each file in ``pods/`` keeps the pod's name, namespace, labels, node, the names
and images of its containers and init containers, and its whole ``status``.
The pods come from failed deployments of Styrmin 0.1.54 on kind (Kubernetes
v1.37.0) on 2026-10-27:

- ``pod_not_scheduled``: a volume claim on a storage class that does not exist;
- ``pod_init_container_failing``: the Semaphore driver's ``admin`` init container
  fails its DNS lookups and runs again after 7 restarts;
- ``pod_image_pull_failing``: an image tag that does not exist.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kubernetes_asyncio.client import V1Pod
from kubernetes_asyncio.client.api_client import ApiClient

_PODS = Path(__file__).parent / "pods"


async def load_pod(name: str) -> V1Pod:
    """The pod of ``pods/<name>.json`` as the Kubernetes client returns it.

    The client needs a running event loop, so the function is async.
    """
    data = (_PODS / f"{name}.json").read_text()
    async with ApiClient() as api:
        return api.deserialize(SimpleNamespace(data=data), "V1Pod")
