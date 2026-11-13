from typing import Any

from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
from styrmin_backend.context.models.contexts import GlobalContext


class UtilityResourceBuilder:
    """Builds native Kubernetes resources for a utility.

    Replaces the former UtilityHelmReleaseBuilder. Instead of building a HelmRelease CRD,
    this builder calls utility.build_resources() to generate native K8s manifests.
    """

    def __init__(self, context: GlobalContext):
        self.context = context

    def build(
        self,
        utility: Utility,
        release_reference: str,
        namespace: str,
    ) -> list[dict[str, Any]]:
        """Build all Kubernetes resources for a utility.

        Returns list of resource dicts ready for cluster application.
        """
        # The label below is how each reconciler finds the object again, so it must be one value
        # for the instance. An empty reference (the operator reads it from a label that a
        # HelmRelease of the StyrminDeployment pipeline does not have) takes the one of the instance.
        release_reference = release_reference or self.context.instance.release_reference

        resources = utility.build_resources(
            context=self.context,
            release_reference=release_reference,
            namespace=namespace,
        )

        # Add consistent ownership labels to all resources
        for resource in resources:
            metadata = resource.setdefault("metadata", {})
            labels = metadata.setdefault("labels", {})
            labels["app.kubernetes.io/managed-by"] = "styrmin"
            labels["styrmin.io/utility-kind"] = utility.kind
            labels["styrmin.io/release-reference"] = release_reference

        return resources
