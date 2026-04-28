from typing import Any

import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    AnnotationPatch,
    SpecPatch,
    Target,
    TargetPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import PostRenderers
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
from styrmin_backend.agent.service.kubernetes.resources.utilities.environment import (
    get_jinja_environment,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.contexts import GlobalContext


class IngressUtility(Utility):
    def __init__(self) -> None:
        super().__init__(
            kind="ingress",
            values_template_file="ingress-controller-chart-values.j2.yaml",
        )

    def build_app_post_rendering_patches(
        self, context: GlobalContext, release_reference: str
    ) -> list[TargetPatch]:
        patches = []
        if not (context.instance.config.fqdn_suffix):
            raise ValueError("FQDN suffix is required to build the ingress patch.")
        annotations = {
            "traefik.ingress.kubernetes.io/router.entrypoints": "web,websecure",
            "external-dns.alpha.kubernetes.io/hostname": f"{release_reference}-{context.app.name}.{context.instance.config.fqdn_suffix}",
            "external-dns.alpha.kubernetes.io/cloudflare-proxied": "true",
        }
        if context.instance.config.ip_whitelist:
            namespace = get_kubernetes_reference(context.instance.deployment_id)
            annotations["traefik.ingress.kubernetes.io/router.middlewares"] = (
                f"{namespace}-acl@kubernetescrd"
            )
        if context.instance.config.dedicated_ingress:
            # Derive ingress class name from the dedicated ingress implementation
            ingress_class_name = (
                context.instance.config.dedicated_ingress.implementation
            )
            annotations["kubernetes.io/ingress.class"] = ingress_class_name
        elif context.instance.config.ingress_class:
            annotations["kubernetes.io/ingress.class"] = (
                context.instance.config.ingress_class
            )
            patches.append(
                TargetPatch(
                    target=Target(kind="Ingress"),
                    patch=SpecPatch(
                        specs={
                            "ingressClassName": context.instance.config.ingress_class
                        }
                    ),
                )
            )

        patches.append(
            TargetPatch(
                target=Target(kind="Ingress"),
                patch=AnnotationPatch(annotations=annotations),
            )
        )
        return patches

    def build_extra_spec(self, context: GlobalContext) -> list[PostRenderers]:
        # Traefik deployment is out of scope for this PR — no extra specs to add
        return []

    def build_resources(
        self, context: GlobalContext, release_reference: str, namespace: str
    ) -> list[dict[str, Any]]:
        """Generate native Kubernetes resources for the ingress utility.

        Renders the Jinja2 template and converts the structured values into
        proper Kubernetes resource manifests (Middlewares, Secrets, NetworkPolicies).
        """
        # Render the Jinja2 template using the shared environment (cached loader)
        env = get_jinja_environment()
        template = env.get_template(self.values_template_file)
        rendered = template.render(context=context, release_reference=release_reference)
        values = yaml.safe_load(rendered)

        resources: list[dict[str, Any]] = []

        # Generate core API resources first (Secrets, NetworkPolicies),
        # then CRDs (Middlewares) which may require Traefik CRDs to be installed.
        #
        # Resource names use the bare template names (no release-reference prefix)
        # because each deployment gets its own namespace, so names can't collide.
        # Prefixing would break internal cross-references within the template
        # (e.g., Middleware basicAuth.secret referencing a Secret by name).

        # Generate Secrets
        if "secrets" in values:
            for secret in values["secrets"]:
                resources.append(
                    {
                        "apiVersion": "v1",
                        "kind": "Secret",
                        "metadata": {
                            "name": secret["name"],
                            "namespace": namespace,
                        },
                        "type": secret.get("type", "Opaque"),
                        "data": secret.get("data", {}),
                    }
                )

        # Generate NetworkPolicies
        if "networkpolicies" in values:
            for netpol in values["networkpolicies"]:
                resources.append(
                    {
                        "apiVersion": "networking.k8s.io/v1",
                        "kind": "NetworkPolicy",
                        "metadata": {
                            "name": netpol["name"],
                            "namespace": namespace,
                        },
                        "spec": netpol["spec"],
                    }
                )

        # Generate Middleware CRDs (requires Traefik CRDs to be installed)
        if "ingress" in values and "middlewares" in values["ingress"]:
            for middleware in values["ingress"]["middlewares"]:
                resources.append(
                    {
                        "apiVersion": "traefik.io/v1alpha1",
                        "kind": "Middleware",
                        "metadata": {
                            "name": middleware["name"],
                            "namespace": namespace,
                        },
                        "spec": middleware["spec"],
                    }
                )

        return resources
