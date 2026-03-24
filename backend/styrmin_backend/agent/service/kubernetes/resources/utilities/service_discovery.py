"""Service-discovery utility: generates ClusterIP Services for deployed services.

For each deployed service owned by the current deployment, a ClusterIP Service
is created in the deployment's namespace.  This makes the service reachable by
its ``resolved_name`` and is the target that cross-namespace ExternalName
aliases point to.
"""

from typing import Any

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import PostRenderers
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
from styrmin_backend.context.models.contexts import GlobalContext


class ServiceDiscoveryUtility(Utility):
    def __init__(self) -> None:
        super().__init__(kind="service-discovery", values_template_file="")

    def build_app_post_rendering_patches(
        self, context: GlobalContext, release_reference: str
    ) -> list[TargetPatch]:
        return []

    def build_extra_spec(self, context: GlobalContext) -> list[PostRenderers]:
        return []

    def build_resources(
        self, context: GlobalContext, release_reference: str, namespace: str
    ) -> list[dict[str, Any]]:
        """Generate ClusterIP Service manifests for this deployment's services.

        For each deployed service owned by THIS deployment, build a ClusterIP
        Service named ``resolved_name`` using the component's identifier labels
        as the pod selector.
        """
        this_deployment_id = str(context.instance.deployment_id)
        resources: list[dict[str, Any]] = []

        for svc in context.deployed_services:
            svc_deployment_id = svc.get("deployment_id")
            if (
                svc_deployment_id is None
                or str(svc_deployment_id) != this_deployment_id
            ):
                continue

            component_name = svc.get("component")
            if component_name is None or context.components is None:
                continue
            if component_name not in context.components:
                continue

            component = context.components[component_name]
            selector_labels = dict(component.config.identifier.label.items())
            protocol = "UDP" if svc["kind"] == "udp" else "TCP"

            resources.append(
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {
                        "name": svc["resolved_name"],
                        "namespace": namespace,
                    },
                    "spec": {
                        "type": "ClusterIP",
                        "ports": [
                            {
                                "port": svc["port"],
                                "targetPort": svc["port"],
                                "protocol": protocol,
                            }
                        ],
                        "selector": selector_labels,
                    },
                }
            )

        return resources
