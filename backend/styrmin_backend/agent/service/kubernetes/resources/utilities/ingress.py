from collections.abc import Mapping
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
from styrmin_backend.context.models.config import ResolvedConfig, ServiceConfigBlock
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.context.namespace_labels import build_namespace_labels

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


def _resolved_class_rules(
    config: ResolvedConfig,
) -> tuple[dict[str, str], str | None, bool]:
    """Return the class annotation, ``spec.ingressClassName`` and removal flag of the resolved config."""
    if config.dedicated_ingress is not None:
        # The dedicated controller reads no IngressClass, so it ignores any Ingress that sets spec.ingressClassName.
        return (
            {"kubernetes.io/ingress.class": config.dedicated_ingress.implementation},
            None,
            True,
        )
    if config.ingress_class:
        return (
            {"kubernetes.io/ingress.class": config.ingress_class},
            config.ingress_class,
            False,
        )
    return {}, None, False


def _missing_suffix_message(
    context: GlobalContext, service_name: str | None = None
) -> str:
    """Return the error text for a deployment that has no FQDN suffix to build an Ingress host from."""
    target = (
        f"the Ingress of service {service_name!r} of deployment "
        if service_name
        else "the Ingress of deployment "
    )
    return (
        f"FQDN suffix is required to build {target}{context.instance.deployment_id} "
        f"(application {context.app.name!r}): no FQDN suffix is set on the cluster, the "
        "environment or the deployment."
    )


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
        raise ValueError(_missing_suffix_message(context))
    # ``release_reference`` is empty when a caller has no label to read it from: use the instance's one.
    reference = release_reference or context.instance.release_reference
    annotations = {
        "traefik.ingress.kubernetes.io/router.entrypoints": "web,websecure",
        "external-dns.alpha.kubernetes.io/hostname": f"{reference}-{context.app.name}.{config.fqdn_suffix}",
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
    class_annotations, class_name, remove_class_name = _resolved_class_rules(config)
    annotations.update(class_annotations)
    return IngressSettings(
        annotations=annotations,
        class_name=class_name,
        remove_class_name=remove_class_name,
    )


def _override_class_rules(
    config: ResolvedConfig, override: ServiceConfigBlock
) -> tuple[dict[str, str], str | None, bool]:
    """Return the class rules of an overridden service.

    The override class replaces the resolved rules, the dedicated controller rule included
    (FR-008). Without an override class, the resolved rules apply.
    """
    if override.ingress_class:
        return (
            {"kubernetes.io/ingress.class": override.ingress_class},
            override.ingress_class,
            False,
        )
    return _resolved_class_rules(config)


def _deployment_labels(context: GlobalContext) -> dict[str, str]:
    """Return the labels that the post-render patch gives every object of the chart.

    ``styrmin/environment_id`` is the one that matters here: a dedicated ingress controller
    starts with ``--providers.kubernetesingress.labelselector=styrmin/environment_id=<id>``
    (``services/ingress_controller/templates/chart_values.j2.yaml``) and ignores an Ingress
    without it. ``styrmin/deployment_id`` is the other label that every chart object has.
    A context label with no value is left out, so no label has an empty value or the text ``None``.
    """
    return build_namespace_labels(
        {
            key: value
            for key, value in context.labels.items()
            if value is not None and value != ""
        }
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

    @staticmethod
    def _active_override(
        overrides: Mapping[str, ServiceConfigBlock], service: dict[str, Any]
    ) -> ServiceConfigBlock | None:
        """Return the override of a service, or ``None`` when it has none or a block with no field set."""
        name = service.get("driver_service_name")
        override = overrides.get(name) if name else None
        return None if override is None or override.is_empty else override

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
            if service.get("deployment_id") == str(context.instance.deployment_id)
        ]
        # A context that an earlier release stored (the StyrminDeployment resource of a deployment
        # that exists today) has no ``scope`` or ``driver_service_name`` in its entries, and neither do
        # the entries of a peer deployment. Such an entry is treated as not external, so no Ingress is
        # built for it: this release adds the Ingress to a service only once the context is regenerated.
        buildable = [
            service
            for service in own_services
            if service.get("scope") == "external"
            and service.get("driver_service_name")
            and service.get("kind") in _INGRESS_SERVICE_KINDS
        ]
        if not buildable:
            return []

        config = context.instance.config
        overrides = context.deployment.config.services or {}
        # The shared settings need a resolved FQDN suffix and raise without one. Build them
        # unless every Ingress has an override, so an override suffix alone is enough then.
        settings = (
            None
            if all(self._active_override(overrides, s) for s in buildable)
            else build_ingress_settings(context, release_reference)
        )
        primary_fqdn = compute_primary_fqdn(
            context.app.name, context.instance.deployment_id, config.fqdn_suffix
        )
        first_declared = own_services[0]

        ingresses: list[dict[str, Any]] = []
        for service in buildable:
            override = self._active_override(overrides, service)
            hosts = [
                compute_human_readable_fqdn(
                    service["resolved_name"],
                    context.environment.name,
                    service.get("fqdn_suffix"),
                )
            ]
            # The application address uses the resolved suffix, so an overridden Ingress
            # never holds it (research D-003).
            if service is first_declared and override is None:
                hosts.append(primary_fqdn)
            unique_hosts = list(dict.fromkeys(host for host in hosts if host))
            if not unique_hosts:
                # No host without an FQDN suffix: raise as the chart patch does, so an Ingress is never
                # left out silently (for example a class-only override with no suffix anywhere).
                raise ValueError(
                    _missing_suffix_message(context, service["driver_service_name"])
                )
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
            if override is not None:
                # FR-004: an overridden Ingress carries the class and nothing else
                # (no entry-point, external-dns, Cloudflare or allow-list annotation).
                annotations, class_name, _ = _override_class_rules(config, override)
            else:
                # ``settings`` is built whenever a service without an override exists.
                settings = settings or build_ingress_settings(
                    context, release_reference
                )
                annotations = dict(settings.annotations)
                class_name = settings.class_name
            if class_name:
                spec["ingressClassName"] = class_name
            ingresses.append(
                {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "Ingress",
                    "metadata": {
                        "name": f"{SERVICE_INGRESS_NAME_PREFIX}{service['driver_service_name']}",
                        "namespace": namespace,
                        "labels": {
                            **_deployment_labels(context),
                            SERVICE_NAME_LABEL: service["driver_service_name"],
                        },
                        "annotations": annotations,
                    },
                    "spec": spec,
                }
            )
        return ingresses
