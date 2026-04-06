"""Builder for StyrminDeployment CRD bodies.

Constructs a StyrminDeployment custom resource body from a GlobalContext
and rendered Helm specifications, suitable for use with
upsert_custom_resource().
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.operator.config import (
    CRD_GROUP,
    CRD_KIND,
    CRD_VERSION,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
)


def build_styrmin_deployment_body(
    context: GlobalContext,
    release_reference: str,
    namespace: str,
    helm_chart_spec: dict[str, Any] | None = None,
    helm_repo_spec: dict[str, Any] | None = None,
    internal: bool = False,
) -> dict[str, Any]:
    """Build a StyrminDeployment CRD body from deployment context.

    Args:
        context: The fully resolved GlobalContext for the deployment.
        release_reference: The Kubernetes release reference.
        namespace: Target namespace.
        helm_chart_spec: Rendered Helm chart spec (optional, derived from context if not provided).
        helm_repo_spec: Rendered Helm repository spec (optional).
        internal: Whether this is an internal deployment (e.g., ingress controller). Defaults to False.

    Returns:
        Dict suitable for upsert_custom_resource.
    """
    return {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": CRD_KIND,
        "metadata": {
            "name": release_reference,
            "namespace": namespace,
            "labels": {
                LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
            },
        },
        "spec": {
            "deploymentId": str(context.instance.deployment_id),
            "releaseReference": release_reference,
            "appName": context.app.name,
            "appVersion": context.app.version,
            "internal": internal,
            "context": context.model_dump(mode="json", exclude_none=True),
            "helm": {
                "chart": {
                    "id": str(context.app.helm.chart.id),
                    "name": context.app.helm.chart.name,
                    "version": context.app.helm.chart.version,
                    "values_template": context.app.helm.chart.values_template,
                },
                "repository": {
                    "id": str(context.app.helm.repository.id),
                    "url": context.app.helm.repository.url,
                },
            },
            "labels": context.labels,
            "parameters": context.parameters,
        },
    }
