"""Builder for StyrminDeployment CRD bodies.

Constructs a StyrminDeployment custom resource body from a GlobalContext
and rendered Helm specifications, suitable for use with
upsert_custom_resource().
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.operator.config import (
    ANNOTATION_INSTANCE_SEQUENCE,
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
    instance_sequence: int | None = None,
) -> dict[str, Any]:
    """Build a StyrminDeployment CRD body from deployment context.

    The CR is named after its **namespace**, not after the release reference:
    there is exactly one ``StyrminDeployment`` per deployment namespace, which is
    the invariant the status reporter, ``delete_deployment`` and the janitor all
    rely on (``styrmin-<deployment id>`` for both). The two strings are equal for
    every ordinary deployment; they diverge for an environment clone's
    counterpart, which keeps its own namespace and CR name while **adopting the
    source's Helm release name** so the restored Helm release, its storage record
    and the ``meta.helm.sh/release-*`` ownership annotations on the restored chart
    objects all line up (010 research D2 — a counterpart-named release would make
    Flux *install* over already-owned objects and fail Helm's ownership check).

    Args:
        context: The fully resolved GlobalContext for the deployment.
        release_reference: The Kubernetes release reference — the Helm release
            (and HelmRelease object) name, not the CR name.
        namespace: Target namespace; also the CR name.
        helm_chart_spec: Rendered Helm chart spec (optional, derived from context if not provided).
        helm_repo_spec: Rendered Helm repository spec (optional).
        internal: Whether this is an internal deployment (e.g., ingress controller). Defaults to False.
        instance_sequence: The instance's sequence, recorded in the
            ``styrmin.io/instance-sequence`` annotation (#386).

    Returns:
        Dict suitable for upsert_custom_resource.
    """
    metadata: dict[str, Any] = {
        "name": namespace,
        "namespace": namespace,
        "labels": {
            LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
        },
    }
    if instance_sequence is not None:
        metadata["annotations"] = {ANNOTATION_INSTANCE_SEQUENCE: str(instance_sequence)}
    return {
        "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
        "kind": CRD_KIND,
        "metadata": metadata,
        "spec": {
            "deploymentId": str(context.instance.deployment_id),
            "instanceId": (
                str(context.instance.id) if context.instance.id is not None else None
            ),
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
