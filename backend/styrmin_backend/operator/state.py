"""Desired state resolution for the operator.

Queries the Styrmin backend API to build GlobalContext, then uses
the existing utility resource builders to compute desired resource specs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from styrmin_backend import config
from styrmin_backend.agent.service.kubernetes.resources.builders.utility import (
    UtilityResourceBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.factory import (
    build_utility,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.operator.config import (
    LABEL_OPERATOR_MANAGED,
    LABEL_OPERATOR_MANAGED_VALUE,
)

logger = logging.getLogger(__name__)


async def fetch_context(deployment_id: str) -> GlobalContext:
    """Fetch GlobalContext for a deployment from the Styrmin backend API.

    Args:
        deployment_id: UUID string of the deployment.

    Returns:
        Fully resolved GlobalContext.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        httpx.ConnectError: If the backend is unreachable.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{config.SETTINGS.url.api}/deployments/{deployment_id}/context",
        )
        response.raise_for_status()
        return GlobalContext.model_validate(response.json())


def build_desired_resources(
    context: GlobalContext,
    release_reference: str,
    namespace: str,
) -> list[dict[str, Any]]:
    """Build the full set of desired utility resources for a deployment.

    Uses the same UtilityResourceBuilder and utility implementations
    as the Prefect flows, ensuring identical resource specs.

    Args:
        context: The GlobalContext for the deployment.
        release_reference: Kubernetes release reference for the deployment.
        namespace: Target namespace.

    Returns:
        List of Kubernetes resource dicts with ownership labels applied.
    """
    builder = UtilityResourceBuilder(context=context)
    all_resources: list[dict[str, Any]] = []

    for utility_ctx in context.utilities:
        utility = build_utility(utility_kind=utility_ctx.kind.value)
        resources = builder.build(
            utility=utility,
            release_reference=release_reference,
            namespace=namespace,
        )
        all_resources.extend(resources)

    return all_resources


def filter_resources_by_kind(
    resources: list[dict[str, Any]], kind: str
) -> list[dict[str, Any]]:
    """Filter a resource list to only include resources of a specific kind."""
    return [r for r in resources if r.get("kind") == kind]


def add_operator_managed_label(resource: dict[str, Any]) -> dict[str, Any]:
    """Add the operator-managed label to a resource dict."""
    metadata = resource.setdefault("metadata", {})
    labels = metadata.setdefault("labels", {})
    labels[LABEL_OPERATOR_MANAGED] = LABEL_OPERATOR_MANAGED_VALUE
    return resource
