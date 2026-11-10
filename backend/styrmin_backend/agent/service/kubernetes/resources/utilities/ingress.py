from dataclasses import dataclass
from typing import Any

import yaml

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    AnnotationPatch,
    IngressClassNameRemovalPatch,
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
from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_backend.context.models.contexts import GlobalContext

SERVICE_INGRESS_NAME_PREFIX = "styrmin-svc-"
SERVICE_NAME_LABEL = "styrmin.io/service-name"

# Only these kinds can sit behind an Ingress (research D-006).
_INGRESS_SERVICE_KINDS = frozenset({"http", "https"})


@dataclass(frozen=True)
class IngressSettings:
    """The annotations and the class of an Ingress that Styrmin configures.

    Attributes:
        annotations: Annotations to set on the Ingress.
        class_name: Value of ``spec.ingressClassName``, or ``None`` to set none.
        remove_class_name: ``True`` when a dedicated ingress controller serves the
            environment: it reads no IngressClass, so ``spec.ingressClassName`` must
            be absent (ADR-071).
    """

    annotations: dict[str, str]
    class_name: str | None
    remove_class_name: bool


def build_ingress_settings(
    context: GlobalContext, release_reference: str
) -> IngressSettings:
    """Return the annotation and class rules shared by the chart patch and the built Ingress.

    One function feeds both, so the chart Ingress and the Ingress that Styrmin builds for
    a service cannot drift (research D-006, FR-003).

    Raises:
        ValueError: when no FQDN suffix resolves.
    """
    config = context.instance.config
    if not config.fqdn_suffix:
        raise ValueError("FQDN suffix is required to build the ingress patch.")
    annotations = {
        "traefik.ingress.kubernetes.io/router.entrypoints": "web,websecure",
        "external-dns.alpha.kubernetes.io/hostname": f"{release_reference}-{context.app.name}.{config.fqdn_suffix}",
        "external-dns.alpha.kubernetes.io/cloudflare-proxied": "true",
    }
    if config.ip_whitelist:
        namespace = get_kubernetes_reference(context.instance.deployment_id)
        annotations["traefik.ingress.kubernetes.io/router.middlewares"] = (
            f"{namespace}-acl@kubernetescrd"
        )
    if config.external_dns_endpoints_type is not None:
        annotations["external-dns.alpha.kubernetes.io/endpoints-type"] = (
            config.external_dns_endpoints_type
        )
    class_name: str | None = None
    remove_class_name = False
    if config.dedicated_ingress is not None:
        # The dedicated controller reads no IngressClass, so it ignores any Ingress that sets spec.ingressClassName.
        annotations["kubernetes.io/ingress.class"] = (
            config.dedicated_ingress.implementation
        )
        remove_class_name = True
    elif config.ingress_class:
        annotations["kubernetes.io/ingress.class"] = config.ingress_class
        class_name = config.ingress_class
    return IngressSettings(
        annotations=annotations,
        class_name=class_name,
        remove_class_name=remove_class_name,
    )


class IngressUtility(Utility):
    def __init__(self) -> None:
        super().__init__(
            kind="ingress",
            values_template_file="ingress-controller-chart-values.j2.yaml",
        )

    def build_app_post_rendering_patches(
        self, context: GlobalContext, release_reference: str
    ) -> list[TargetPatch]:
        settings = build_ingress_settings(context, release_reference)
        patches = []
        if settings.remove_class_name:
            patches.append(
                TargetPatch(
                    target=Target(kind="Ingress"),
                    patch=IngressClassNameRemovalPatch(),
                )
            )
        elif settings.class_name:
            patches.append(
                TargetPatch(
                    target=Target(kind="Ingress"),
                    patch=SpecPatch(specs={"ingressClassName": settings.class_name}),
                )
            )

        patches.append(
            TargetPatch(
                target=Target(kind="Ingress"),
                patch=AnnotationPatch(annotations=settings.annotations),
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
        rendered = template.render(
            context=context, release_reference=release_reference, namespace=namespace
        )
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

        resources.extend(
            self._build_service_ingresses(context, release_reference, namespace)
        )

        return resources

    def _build_service_ingresses(
        self, context: GlobalContext, release_reference: str, namespace: str
    ) -> list[dict[str, Any]]:
        """Build one Ingress for each external ``http`` or ``https`` service of this deployment.

        The application address (``<app name>-<deployment id>.<suffix>``) goes to the
        first service that the driver declares, and only when that service gets an Ingress
        (research D-003). ``deployed_services`` lists the services of this deployment in
        driver declaration order.
        """
        own_services = [
            service
            for service in context.deployed_services
            if service["deployment_id"] == str(context.instance.deployment_id)
        ]
        buildable = [
            service
            for service in own_services
            if service["scope"] == "external"
            and service["kind"] in _INGRESS_SERVICE_KINDS
        ]
        if not buildable:
            return []

        settings = build_ingress_settings(context, release_reference)
        config = context.instance.config
        primary_fqdn = compute_primary_fqdn(
            context.app.name, context.instance.deployment_id, config.fqdn_suffix
        )
        first_declared = own_services[0]

        ingresses: list[dict[str, Any]] = []
        for service in buildable:
            hosts = [
                compute_human_readable_fqdn(
                    service["resolved_name"],
                    context.environment.name,
                    service["fqdn_suffix"],
                )
            ]
            if service is first_declared:
                hosts.append(primary_fqdn)
            unique_hosts = list(dict.fromkeys(host for host in hosts if host))
            if not unique_hosts:
                continue
            spec: dict[str, Any] = {
                "rules": [
                    {
                        "host": host,
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": service["resolved_name"],
                                            "port": {"number": service["port"]},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                    for host in unique_hosts
                ]
            }
            if settings.class_name:
                spec["ingressClassName"] = settings.class_name
            ingresses.append(
                {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "Ingress",
                    "metadata": {
                        "name": f"{SERVICE_INGRESS_NAME_PREFIX}{service['driver_service_name']}",
                        "namespace": namespace,
                        "labels": {SERVICE_NAME_LABEL: service["driver_service_name"]},
                        "annotations": dict(settings.annotations),
                    },
                    "spec": spec,
                }
            )
        return ingresses
