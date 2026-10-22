"""Service-discovery utility: generates ClusterIP Services for deployed services.

For each deployed service owned by the current deployment, a ClusterIP Service
is created in the deployment's namespace.  This makes the service reachable by
its ``resolved_name`` and is the target that cross-namespace ExternalName
aliases point to.

For each component that serves one of these services, a NetworkPolicy admits
the other deployments of the environment on the services' ports (#557).
"""

import re
from typing import Any

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import PostRenderers
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.context.namespace_labels import NAMESPACE_LABEL_PREFIX

# A driver may name a component with characters that a Kubernetes name refuses.
_INVALID_NAME_CHARACTERS = re.compile(r"[^a-z0-9-]+")


def environment_policy_name(component_name: str) -> str:
    """Name of the NetworkPolicy that admits the environment to a component's services.

    The name is built from the component name, which the driver sets and a user cannot
    change, so a service-name override does not rename the policy.
    """
    suffix = _INVALID_NAME_CHARACTERS.sub("-", component_name.lower()).strip("-")
    return f"allow-environment-to-{suffix}"


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
        """Generate ClusterIP Service and NetworkPolicy manifests for this deployment's services.

        For each deployed service owned by THIS deployment, build a ClusterIP
        Service named ``resolved_name`` using the component's identifier labels
        as the pod selector. Then build one NetworkPolicy per component that
        serves a service (see ``_build_environment_policies``).
        """
        this_deployment_id = str(context.instance.deployment_id)
        resources: list[dict[str, Any]] = []
        # The ports of this deployment's services, by the component that serves them.
        ports_by_component: dict[str, list[dict[str, Any]]] = {}

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

            ports = ports_by_component.setdefault(component_name, [])
            port = {"port": svc["port"], "protocol": protocol}
            if port not in ports:
                ports.append(port)

        resources.extend(
            self._build_environment_policies(context, namespace, ports_by_component)
        )
        return resources

    @staticmethod
    def _build_environment_policies(
        context: GlobalContext,
        namespace: str,
        ports_by_component: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Admit the other deployments of the environment to this deployment's services.

        One NetworkPolicy per component that serves a service: it selects the component's
        pods and admits the namespaces of the environment on the services' ports only.
        A component that serves no service stays reachable from its own namespace only.
        Without an environment id, no policy is built: an empty selector would admit
        every namespace.
        """
        environment_id = context.labels.get("environment_id")
        if environment_id is None or context.components is None:
            return []

        environment_selector = {
            "matchLabels": {
                f"{NAMESPACE_LABEL_PREFIX}/environment_id": str(environment_id)
            }
        }
        policies: list[dict[str, Any]] = []
        for component_name, ports in ports_by_component.items():
            component = context.components[component_name]
            policies.append(
                {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "NetworkPolicy",
                    "metadata": {
                        "name": environment_policy_name(component_name),
                        "namespace": namespace,
                    },
                    "spec": {
                        "podSelector": {
                            "matchLabels": dict(
                                component.config.identifier.label.items()
                            )
                        },
                        "policyTypes": ["Ingress"],
                        "ingress": [
                            {
                                "from": [{"namespaceSelector": environment_selector}],
                                "ports": ports,
                            }
                        ],
                    },
                }
            )
        return policies
