"""Kubernetes API client helpers for the operator.

Provides a properly managed ApiClient for use in operator handlers
and reconciler functions. Unlike the agent's get_api_client() which
is an async generator for fast_depends injection, this module provides
a simple async context manager suitable for long-lived operator code.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from kubernetes_asyncio.client.api_client import ApiClient

from styrmin_backend.agent.service.kubernetes.dependency import load_kubernetes_config


@asynccontextmanager
async def get_kubernetes_client() -> AsyncGenerator[ApiClient, None]:
    """Get a Kubernetes API client as an async context manager.

    Loads cluster config and yields a properly managed ApiClient
    that is closed when the context exits.

    Usage:
        async with get_kubernetes_client() as client:
            api = CoreV1Api(client)
            await api.list_namespaced_service(...)
    """
    await load_kubernetes_config()
    async with ApiClient() as client:
        yield client
