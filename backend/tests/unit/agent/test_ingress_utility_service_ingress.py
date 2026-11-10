"""The Ingress that Styrmin builds for an external service, without an override (#598, T009).

Written before the implementation (Constitution V). Source: ``specs/033-service-ingress-override/``
``data-model.md`` ("Derived: the Ingress that Styrmin builds"), ``research.md`` D-001, D-003, D-005,
D-006, and FR-001 to FR-003, FR-007, FR-008.

``IngressUtility.build_resources`` returns one Ingress for every service of the deployment that is
``scope: external`` and of kind ``http`` or ``https``.

Assumption about the input, which the spec does not fix (see ``test_service_address.py`` for the same
contract): each entry of ``GlobalContext.deployed_services`` carries the keys that exist today plus
``driver_service_name``, ``scope``, ``ingress_class`` and ``fqdn_suffix`` (T015). The order of the
entries of this deployment is the order in which the driver declares its services. ``_service`` below
is the one place that builds such an entry; the implementation task (T017) may change that helper if
it reads the services differently.

The negative cases (no Ingress for an internal, ``tcp`` or ``udp`` service) always include an external
service in the same context, so they fail while no Ingress is built and do not pass for the wrong
reason.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import pytest

from styrmin_backend.agent.service.kubernetes.resources.builders.utility import (
    UtilityResourceBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.ingress import (
    IngressUtility,
)
from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
    ServiceConfigBlock,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo

RELEASE_REF = "test-release"
NAMESPACE = "test-namespace"
ENVIRONMENT_NAME = "test"
APP_NAME = "testapp"
SUFFIX = "test.styrmin.com"
DEPLOYMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
PEER_DEPLOYMENT_ID = UUID("00000000-0000-0000-0000-000000000002")

SERVICE_NAME_LABEL = "styrmin.io/service-name"


def _service(
    driver_service_name: str,
    *,
    resolved_name: str | None = None,
    port: int = 8080,
    kind: str = "http",
    scope: str = "external",
    deployment_id: UUID = DEPLOYMENT_ID,
    ingress_class: str | None = "traefik",
    fqdn_suffix: str | None = SUFFIX,
) -> dict[str, Any]:
    """One entry of ``GlobalContext.deployed_services`` (the contract assumed by this file)."""
    return {
        "driver_service_name": driver_service_name,
        "resolved_name": resolved_name or driver_service_name,
        "port": port,
        "kind": kind,
        "scope": scope,
        "deployment_id": str(deployment_id),
        "component": "server",
        "ingress_class": ingress_class,
        "fqdn_suffix": fqdn_suffix,
    }


def _with_override(
    service: dict[str, Any], override: ServiceConfigBlock | None
) -> dict[str, Any]:
    """The entry the context builder writes: the override value, else the resolved value."""
    if override is None:
        return service
    return {
        **service,
        "ingress_class": override.ingress_class or service["ingress_class"],
        "fqdn_suffix": override.fqdn_suffix or service["fqdn_suffix"],
    }


def _context(
    services: list[dict[str, Any]],
    *,
    ingress_class: str | None = "traefik",
    dedicated_ingress: DedicatedIngressConfig | None = None,
    fqdn_suffix: str | None = SUFFIX,
    ip_whitelist: list[str] | None = None,
    endpoints_type: Literal["NodeExternalIP", "ClusterIP"] | None = None,
    overrides: dict[str, ServiceConfigBlock] | None = None,
) -> GlobalContext:
    # An override is stored in ``DeploymentConfig.services`` under the driver service name, and the
    # context builder (T015) writes the effective class and suffix into the ``deployed_services``
    # entry. This helper does both, so the planned builder can read the override from either place.
    overrides = overrides or {}
    services = [
        _with_override(s, overrides.get(s["driver_service_name"])) for s in services
    ]
    context = GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(
                ingress_class=ingress_class,
                dedicated_ingress=dedicated_ingress,
                fqdn_suffix=fqdn_suffix,
            ),
        ),
        environment=EnvironmentContext(
            name=ENVIRONMENT_NAME,
            config=EnvironmentConfig(ip_whitelist=ip_whitelist),
        ),
        deployment=DeploymentContext(
            config=DeploymentConfig(services=overrides or None)
        ),
        instance=InstanceContext(
            config=ResolvedConfig(
                ip_whitelist=ip_whitelist,
                ingress_class=ingress_class,
                dedicated_ingress=dedicated_ingress,
                fqdn_suffix=fqdn_suffix,
                external_dns_endpoints_type=endpoints_type,
            ),
            deployment_id=DEPLOYMENT_ID,
            namespace=NAMESPACE,
            release_reference=RELEASE_REF,
        ),
        app=ApplicationContext(
            name=APP_NAME,
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=UUID(int=7), name=APP_NAME, version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(
                    id=UUID(int=8), url="oci://charts.example.com/test"
                ),
            ),
        ),
        deployed_services=services,
    )
    # ``services`` is the template data (ADR-022). Filled the way the planned context builder fills it.
    context.services = {
        s["driver_service_name"]: {
            "host": s["resolved_name"],
            "port": s["port"],
            "kind": s["kind"],
            "url": f"{s['kind']}://{s['resolved_name']}:{s['port']}",
            "primary_fqdn": compute_primary_fqdn(APP_NAME, DEPLOYMENT_ID, fqdn_suffix),
            "human_readable_fqdn": compute_human_readable_fqdn(
                s["resolved_name"], ENVIRONMENT_NAME, fqdn_suffix
            ),
            "ingress_class": s["ingress_class"],
            "overridden": s["driver_service_name"] in overrides
            and not overrides[s["driver_service_name"]].is_empty,
        }
        for s in services
    }
    return context


def _build(context: GlobalContext) -> list[dict[str, Any]]:
    resources = IngressUtility().build_resources(context, RELEASE_REF, NAMESPACE)
    return [r for r in resources if r["kind"] == "Ingress"]


def _by_service(ingresses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["metadata"]["labels"][SERVICE_NAME_LABEL]: i for i in ingresses}


def _hosts(ingress: dict[str, Any]) -> list[str]:
    return [rule["host"] for rule in ingress["spec"]["rules"]]


def _readable(resolved_name: str) -> str | None:
    return compute_human_readable_fqdn(resolved_name, ENVIRONMENT_NAME, SUFFIX)


OVERRIDE_CLASS = "tailscale"
OVERRIDE_SUFFIX = "tailnet.example.ts.net"
OVERRIDE = ServiceConfigBlock(ingress_class=OVERRIDE_CLASS, fqdn_suffix=OVERRIDE_SUFFIX)
_PRIMARY = compute_primary_fqdn(APP_NAME, DEPLOYMENT_ID, SUFFIX)


def _chart_patch_annotations(context: GlobalContext) -> dict[str, str]:
    patches = IngressUtility().build_app_post_rendering_patches(context, RELEASE_REF)
    annotation_patches = [p for p in patches if hasattr(p.patch, "annotations")]
    assert len(annotation_patches) == 1
    return dict(annotation_patches[0].patch.annotations)  # type: ignore[attr-defined]


class TestWhichServicesGetAnIngress:
    def test_one_ingress_per_external_http_or_https_service(self) -> None:
        context = _context(
            [
                _service("web", kind="http"),
                _service("api", kind="https", port=8443),
            ]
        )

        ingresses = _build(context)

        assert sorted(i["metadata"]["name"] for i in ingresses) == [
            "styrmin-svc-api",
            "styrmin-svc-web",
        ]

    def test_no_ingress_for_an_internal_service(self) -> None:
        context = _context(
            [_service("web"), _service("database", scope="internal", port=5432)]
        )

        assert set(_by_service(_build(context))) == {"web"}

    @pytest.mark.parametrize("kind", ["tcp", "udp"])
    def test_no_ingress_for_a_tcp_or_udp_service(self, kind: str) -> None:
        """research D-006: a ``tcp`` or ``udp`` service cannot sit behind an Ingress, even when declared external."""
        context = _context([_service("web"), _service("queue", kind=kind, port=5672)])

        assert set(_by_service(_build(context))) == {"web"}

    def test_no_ingress_for_a_service_of_another_deployment(self) -> None:
        """The ClusterIP Service of a peer lives in the peer's namespace."""
        context = _context(
            [
                _service("peer-web", deployment_id=PEER_DEPLOYMENT_ID),
                _service("web"),
            ]
        )

        assert set(_by_service(_build(context))) == {"web"}

    def test_no_external_service_gives_no_ingress_and_no_error_without_a_suffix(
        self,
    ) -> None:
        """A deployment without an external service needs no FQDN suffix (SC-003)."""
        context = _context(
            [_service("database", scope="internal", port=5432)], fqdn_suffix=None
        )

        assert _build(context) == []


class TestIngressObject:
    def test_name_namespace_and_labels(self) -> None:
        """data-model: name ``styrmin-svc-<driver service name>``, label ``styrmin.io/service-name``."""
        context = _context(
            [_service("task-manager", resolved_name="tm-renamed", port=4200)]
        )

        (ingress,) = _build(context)

        assert ingress["apiVersion"] == "networking.k8s.io/v1"
        assert ingress["metadata"]["name"] == "styrmin-svc-task-manager"
        assert ingress["metadata"]["namespace"] == NAMESPACE
        assert ingress["metadata"]["labels"][SERVICE_NAME_LABEL] == "task-manager"

    def test_the_ownership_labels_are_added_by_the_utility_builder(self) -> None:
        context = _context([_service("web")])

        resources = UtilityResourceBuilder(context).build(
            IngressUtility(), RELEASE_REF, NAMESPACE
        )

        (ingress,) = [r for r in resources if r["kind"] == "Ingress"]
        labels = ingress["metadata"]["labels"]
        assert labels["app.kubernetes.io/managed-by"] == "styrmin"
        assert labels["styrmin.io/utility-kind"] == "ingress"
        assert labels["styrmin.io/release-reference"] == RELEASE_REF
        assert labels[SERVICE_NAME_LABEL] == "web"

    def test_backend_is_the_cluster_ip_service_on_the_declared_port(self) -> None:
        context = _context(
            [_service("task-manager", resolved_name="tm-renamed", port=4200)]
        )

        (ingress,) = _build(context)

        for rule in ingress["spec"]["rules"]:
            (path,) = rule["http"]["paths"]
            assert path["path"] == "/"
            assert path["pathType"] == "Prefix"
            assert path["backend"]["service"]["name"] == "tm-renamed"
            assert path["backend"]["service"]["port"]["number"] == 4200

    def test_no_tls_is_written(self) -> None:
        """FR-007."""
        (ingress,) = _build(_context([_service("web")]))

        assert "tls" not in ingress["spec"]


class TestHosts:
    def test_every_external_service_has_its_readable_host(self) -> None:
        context = _context(
            [_service("web"), _service("api", resolved_name="api-renamed", port=9000)]
        )

        ingresses = _by_service(_build(context))

        assert _readable("web") in _hosts(ingresses["web"])
        assert _readable("api-renamed") in _hosts(ingresses["api"])

    def test_the_application_address_is_only_on_the_first_declared_service(
        self,
    ) -> None:
        """research D-003, FR-002 as changed."""
        context = _context([_service("web"), _service("api", port=9000)])

        ingresses = _by_service(_build(context))

        assert sorted(_hosts(ingresses["web"])) == sorted([_readable("web"), _PRIMARY])
        assert _hosts(ingresses["api"]) == [_readable("api")]

    def test_the_first_service_of_a_peer_does_not_take_the_application_address(
        self,
    ) -> None:
        context = _context(
            [
                _service("peer-web", deployment_id=PEER_DEPLOYMENT_ID),
                _service("web"),
                _service("api", port=9000),
            ]
        )

        ingresses = _by_service(_build(context))

        assert _PRIMARY in _hosts(ingresses["web"])
        assert _PRIMARY not in _hosts(ingresses["api"])

    def test_no_application_address_when_the_first_declared_service_is_internal(
        self,
    ) -> None:
        """research D-003: in ``infrahub`` the first service stays internal and its chart Ingress keeps the address."""
        context = _context(
            [
                _service("infrahub", scope="internal", port=8000),
                _service("task-manager", port=4200),
            ]
        )

        (ingress,) = _build(context)

        assert ingress["metadata"]["labels"][SERVICE_NAME_LABEL] == "task-manager"
        assert _hosts(ingress) == [_readable("task-manager")]

    def test_the_application_address_is_on_exactly_one_ingress(self) -> None:
        """FR-002: no two Ingresses claim one host."""
        context = _context(
            [_service("web"), _service("api", port=9000), _service("ui", port=3000)]
        )

        all_hosts = [h for i in _build(context) for h in _hosts(i)]

        assert all_hosts.count(_PRIMARY) == 1
        assert len(all_hosts) == len(set(all_hosts))

    def test_a_missing_suffix_raises_the_error_of_the_chart_patch(self) -> None:
        context = _context([_service("web", fqdn_suffix=None)], fqdn_suffix=None)

        with pytest.raises(ValueError, match="FQDN suffix is required"):
            IngressUtility().build_app_post_rendering_patches(context, RELEASE_REF)
        with pytest.raises(ValueError, match="FQDN suffix is required"):
            IngressUtility().build_resources(context, RELEASE_REF, NAMESPACE)


class TestAnnotationsAndClass:
    @pytest.mark.parametrize(
        "settings",
        [
            {"ingress_class": "traefik", "ip_whitelist": ["10.0.0.0/8"]},
            {"ingress_class": "traefik", "endpoints_type": "NodeExternalIP"},
            {"ingress_class": "traefik", "endpoints_type": "ClusterIP"},
            {"ingress_class": None},
            {
                "ingress_class": "cluster-traefik",
                "dedicated_ingress": DedicatedIngressConfig(implementation="traefik"),
            },
        ],
        ids=["ip-whitelist", "node-external-ip", "cluster-ip", "no-class", "dedicated"],
    )
    def test_annotations_equal_those_of_the_chart_patch(
        self, settings: dict[str, Any]
    ) -> None:
        """FR-003: the same rules feed the chart patch and the built Ingress."""
        context = _context([_service("web")], **settings)

        (ingress,) = _build(context)

        assert ingress["metadata"]["annotations"] == _chart_patch_annotations(context)

    def test_the_known_annotations_without_an_override(self) -> None:
        context = _context(
            [_service("web")],
            ip_whitelist=["10.0.0.0/8"],
            endpoints_type="NodeExternalIP",
        )

        (ingress,) = _build(context)

        assert ingress["metadata"]["annotations"] == {
            "traefik.ingress.kubernetes.io/router.entrypoints": "web,websecure",
            "external-dns.alpha.kubernetes.io/hostname": f"{RELEASE_REF}-{APP_NAME}.{SUFFIX}",
            "external-dns.alpha.kubernetes.io/cloudflare-proxied": "true",
            "traefik.ingress.kubernetes.io/router.middlewares": f"styrmin-{DEPLOYMENT_ID}-acl@kubernetescrd",
            "external-dns.alpha.kubernetes.io/endpoints-type": "NodeExternalIP",
            "kubernetes.io/ingress.class": "traefik",
        }

    def test_the_operator_without_a_release_reference_label_gets_the_context_one(
        self,
    ) -> None:
        """A HelmRelease managed through the StyrminDeployment CRD has no release-reference label.

        The operator's periodic reconciliation then builds the Ingress with an empty release
        reference. The external-dns host name must still start with the release reference of
        the instance, as the chart patch does, not with a bare ``-``.
        """
        context = _context([_service("web")])

        resources = IngressUtility().build_resources(context, "", NAMESPACE)
        (ingress,) = [r for r in resources if r["kind"] == "Ingress"]

        assert (
            ingress["metadata"]["annotations"][
                "external-dns.alpha.kubernetes.io/hostname"
            ]
            == f"{RELEASE_REF}-{APP_NAME}.{SUFFIX}"
        )

    def test_ip_whitelist_adds_the_acl_middleware_annotation(self) -> None:
        (ingress,) = _build(_context([_service("web")], ip_whitelist=["10.0.0.0/8"]))

        annotations = ingress["metadata"]["annotations"]
        assert (
            annotations["traefik.ingress.kubernetes.io/router.middlewares"]
            == f"styrmin-{DEPLOYMENT_ID}-acl@kubernetescrd"
        )

    @pytest.mark.parametrize("ip_whitelist", [None, []])
    def test_no_ip_whitelist_adds_no_acl_annotation(
        self, ip_whitelist: list[str] | None
    ) -> None:
        (ingress,) = _build(_context([_service("web")], ip_whitelist=ip_whitelist))

        annotations = ingress["metadata"]["annotations"]
        assert "traefik.ingress.kubernetes.io/router.middlewares" not in annotations

    @pytest.mark.parametrize("endpoints_type", ["NodeExternalIP", "ClusterIP"])
    def test_endpoints_type_is_set_when_configured(
        self, endpoints_type: Literal["NodeExternalIP", "ClusterIP"]
    ) -> None:
        (ingress,) = _build(_context([_service("web")], endpoints_type=endpoints_type))

        annotations = ingress["metadata"]["annotations"]
        assert (
            annotations["external-dns.alpha.kubernetes.io/endpoints-type"]
            == endpoints_type
        )

    def test_endpoints_type_is_omitted_when_unset(self) -> None:
        (ingress,) = _build(_context([_service("web")]))

        annotations = ingress["metadata"]["annotations"]
        assert "external-dns.alpha.kubernetes.io/endpoints-type" not in annotations

    def test_shared_ingress_controller_sets_the_class_in_both_places(self) -> None:
        (ingress,) = _build(_context([_service("web")], ingress_class="cluster-ts"))

        assert ingress["spec"]["ingressClassName"] == "cluster-ts"
        assert ingress["metadata"]["annotations"]["kubernetes.io/ingress.class"] == (
            "cluster-ts"
        )

    def test_no_class_resolved_sets_neither(self) -> None:
        (ingress,) = _build(_context([_service("web")], ingress_class=None))

        assert ingress["spec"].get("ingressClassName") is None
        assert "kubernetes.io/ingress.class" not in ingress["metadata"]["annotations"]

    @pytest.mark.parametrize("ingress_class", ["cluster-traefik", None])
    def test_dedicated_ingress_controller_sets_no_class_name(
        self, ingress_class: str | None
    ) -> None:
        """FR-008: the dedicated controller reads no IngressClass, so only the implementation annotation is set."""
        context = _context(
            [_service("web")],
            ingress_class=ingress_class,
            dedicated_ingress=DedicatedIngressConfig(implementation="traefik"),
        )

        (ingress,) = _build(context)

        assert ingress["spec"].get("ingressClassName") is None
        assert ingress["metadata"]["annotations"]["kubernetes.io/ingress.class"] == (
            "traefik"
        )


def _overridden_readable(
    resolved_name: str, suffix: str = OVERRIDE_SUFFIX
) -> str | None:
    return compute_human_readable_fqdn(resolved_name, ENVIRONMENT_NAME, suffix)


class TestServiceOverride:
    """A service with an override (user story 1, FR-004, FR-008, SC-002).

    ``task-manager`` is the second declared service, as in the ``infrahub`` driver, so the
    application address stays with ``web`` unless a test says otherwise.
    """

    def test_the_hosts_use_the_override_suffix(self) -> None:
        context = _context(
            [_service("web"), _service("task-manager", port=4200)],
            overrides={"task-manager": OVERRIDE},
        )

        ingresses = _by_service(_build(context))

        assert _hosts(ingresses["task-manager"]) == [
            _overridden_readable("task-manager")
        ]
        assert sorted(_hosts(ingresses["web"])) == sorted([_readable("web"), _PRIMARY])

    def test_the_readable_host_uses_the_resolved_service_name(self) -> None:
        context = _context(
            [_service("web"), _service("task-manager", resolved_name="tm-renamed")],
            overrides={"task-manager": OVERRIDE},
        )

        ingress = _by_service(_build(context))["task-manager"]

        assert _hosts(ingress) == [_overridden_readable("tm-renamed")]

    @pytest.mark.parametrize(
        "settings",
        [
            {},
            {"ip_whitelist": ["10.0.0.0/8"], "endpoints_type": "NodeExternalIP"},
        ],
        ids=["plain", "allow-list-and-endpoints-type"],
    )
    def test_only_the_class_annotation_and_the_class_name_are_set(
        self, settings: dict[str, Any]
    ) -> None:
        """FR-004: no entry-point, external-dns, Cloudflare or allow-list annotation."""
        context = _context(
            [_service("web"), _service("task-manager", port=4200)],
            overrides={"task-manager": OVERRIDE},
            **settings,
        )

        ingress = _by_service(_build(context))["task-manager"]

        assert ingress["spec"]["ingressClassName"] == OVERRIDE_CLASS
        assert ingress["metadata"]["annotations"] == {
            "kubernetes.io/ingress.class": OVERRIDE_CLASS
        }

    def test_a_suffix_only_override_keeps_the_resolved_class_and_drops_the_other_annotations(
        self,
    ) -> None:
        context = _context(
            [_service("web"), _service("task-manager", port=4200)],
            overrides={"task-manager": ServiceConfigBlock(fqdn_suffix=OVERRIDE_SUFFIX)},
            ip_whitelist=["10.0.0.0/8"],
        )

        ingress = _by_service(_build(context))["task-manager"]

        assert _hosts(ingress) == [_overridden_readable("task-manager")]
        assert ingress["spec"]["ingressClassName"] == "traefik"
        assert ingress["metadata"]["annotations"] == {
            "kubernetes.io/ingress.class": "traefik"
        }

    def test_a_class_only_override_keeps_the_resolved_suffix(self) -> None:
        context = _context(
            [_service("web"), _service("task-manager", port=4200)],
            overrides={
                "task-manager": ServiceConfigBlock(ingress_class=OVERRIDE_CLASS)
            },
        )

        ingress = _by_service(_build(context))["task-manager"]

        assert _hosts(ingress) == [_readable("task-manager")]
        assert ingress["spec"]["ingressClassName"] == OVERRIDE_CLASS
        assert ingress["metadata"]["annotations"] == {
            "kubernetes.io/ingress.class": OVERRIDE_CLASS
        }

    def test_an_overridden_first_service_carries_no_application_address(self) -> None:
        """research D-003: the application address uses the resolved suffix, so no overridden Ingress holds it."""
        context = _context(
            [_service("web"), _service("api", port=9000)],
            overrides={"web": OVERRIDE},
        )

        ingresses = _by_service(_build(context))

        assert _hosts(ingresses["web"]) == [_overridden_readable("web")]
        assert _PRIMARY not in [h for i in ingresses.values() for h in _hosts(i)]

    def test_the_backend_and_the_name_do_not_change_with_an_override(self) -> None:
        context = _context(
            [_service("web"), _service("task-manager", resolved_name="tm", port=4200)],
            overrides={"task-manager": OVERRIDE},
        )

        ingress = _by_service(_build(context))["task-manager"]

        assert ingress["metadata"]["name"] == "styrmin-svc-task-manager"
        assert "tls" not in ingress["spec"]
        (rule,) = ingress["spec"]["rules"]
        backend = rule["http"]["paths"][0]["backend"]["service"]
        assert backend["name"] == "tm"
        assert backend["port"]["number"] == 4200

    @pytest.mark.parametrize("override_class", [OVERRIDE_CLASS, None])
    def test_the_override_class_replaces_the_dedicated_controller_rule_for_its_service(
        self, override_class: str | None
    ) -> None:
        """FR-008: an overridden Ingress gets the override's class fields instead of the dedicated-controller ones.

        With a suffix-only override (``override_class`` is ``None``) there is no override class, so the
        dedicated-controller rule of the resolved configuration still applies.
        """
        dedicated = DedicatedIngressConfig(implementation="traefik")
        context = _context(
            [_service("web"), _service("task-manager", port=4200)],
            ingress_class="cluster-traefik",
            dedicated_ingress=dedicated,
            overrides={
                "task-manager": ServiceConfigBlock(
                    ingress_class=override_class, fqdn_suffix=OVERRIDE_SUFFIX
                )
            },
        )

        ingress = _by_service(_build(context))["task-manager"]

        if override_class is None:
            assert ingress["spec"].get("ingressClassName") is None
            assert ingress["metadata"]["annotations"] == {
                "kubernetes.io/ingress.class": "traefik"
            }
        else:
            assert ingress["spec"]["ingressClassName"] == override_class
            assert ingress["metadata"]["annotations"] == {
                "kubernetes.io/ingress.class": override_class
            }

    def test_with_a_dedicated_controller_the_other_service_keeps_the_dedicated_rule(
        self,
    ) -> None:
        dedicated = DedicatedIngressConfig(implementation="traefik")
        context = _context(
            [_service("web"), _service("task-manager", port=4200)],
            ingress_class="cluster-traefik",
            dedicated_ingress=dedicated,
            overrides={"task-manager": OVERRIDE},
        )

        web = _by_service(_build(context))["web"]

        assert web["spec"].get("ingressClassName") is None
        assert web["metadata"]["annotations"] == _chart_patch_annotations(context)
        assert (
            web["metadata"]["annotations"]["kubernetes.io/ingress.class"] == "traefik"
        )

    @pytest.mark.parametrize(
        "settings",
        [
            {},
            {"ip_whitelist": ["10.0.0.0/8"], "endpoints_type": "ClusterIP"},
            {
                "ingress_class": "cluster-traefik",
                "dedicated_ingress": DedicatedIngressConfig(implementation="traefik"),
            },
        ],
        ids=["plain", "allow-list-and-endpoints-type", "dedicated"],
    )
    def test_the_other_services_ingresses_are_identical_with_and_without_the_override(
        self, settings: dict[str, Any]
    ) -> None:
        """SC-002: an override changes the Ingress of its own service only."""

        def services() -> list[dict[str, Any]]:
            return [
                _service("web"),
                _service("task-manager", port=4200),
                _service("api", resolved_name="api-renamed", port=9000),
            ]

        without = _by_service(_build(_context(services(), **settings)))
        with_override = _by_service(
            _build(
                _context(services(), overrides={"task-manager": OVERRIDE}, **settings)
            )
        )

        assert with_override["web"] == without["web"]
        assert with_override["api"] == without["api"]
        assert with_override["task-manager"] != without["task-manager"]

    def test_a_block_with_no_field_set_is_no_override(self) -> None:
        """data-model: a block with both fields ``None`` is the same as no override."""
        services = [_service("web"), _service("task-manager", port=4200)]

        with_empty_block = _build(
            _context(services, overrides={"task-manager": ServiceConfigBlock()})
        )

        assert with_empty_block == _build(_context(services))

    def test_an_override_on_an_internal_service_builds_no_ingress(self) -> None:
        """The override validation refuses it (FR-009), and the builder must not publish an internal service."""
        context = _context(
            [_service("web"), _service("database", scope="internal", port=5432)],
            overrides={"database": OVERRIDE},
        )

        assert set(_by_service(_build(context))) == {"web"}


class TestDeploymentWithoutAnyFqdnSuffix:
    """A service that gets an Ingress needs a host, so the builder never skips one silently (review F3)."""

    def test_a_class_only_override_without_any_suffix_raises(self) -> None:
        """The same configuration without the override raises, so the override must not hide the error."""
        context = _context(
            [_service("web", fqdn_suffix=None)],
            fqdn_suffix=None,
            overrides={"web": ServiceConfigBlock(ingress_class=OVERRIDE_CLASS)},
        )

        with pytest.raises(ValueError, match="FQDN suffix is required") as error:
            _build(context)

        assert "web" in str(error.value)
        assert str(DEPLOYMENT_ID) in str(error.value)

    def test_every_external_service_has_a_suffix_override_and_no_error_is_raised(
        self,
    ) -> None:
        context = _context(
            [
                _service("web", fqdn_suffix=None),
                _service("task-manager", port=4200, fqdn_suffix=None),
            ],
            fqdn_suffix=None,
            overrides={
                "web": ServiceConfigBlock(fqdn_suffix="a.example.net"),
                "task-manager": ServiceConfigBlock(fqdn_suffix="b.example.net"),
            },
        )

        ingresses = _by_service(_build(context))

        assert set(ingresses) == {"web", "task-manager"}
        assert _hosts(ingresses["web"]) == [
            compute_human_readable_fqdn("web", ENVIRONMENT_NAME, "a.example.net")
        ]

    def test_one_overridden_and_one_plain_service_without_a_cluster_suffix_raises(
        self,
    ) -> None:
        context = _context(
            [
                _service("web", fqdn_suffix=None),
                _service("task-manager", port=4200, fqdn_suffix=None),
            ],
            fqdn_suffix=None,
            overrides={"task-manager": ServiceConfigBlock(fqdn_suffix="b.example.net")},
        )

        with pytest.raises(ValueError, match="FQDN suffix is required"):
            _build(context)


class TestContextStoredBeforeThisRelease:
    """A context written by an earlier release has none of the keys that #598 added (review F1).

    The StyrminDeployment resource of every deployment that exists today holds such a context, and
    the drift timer of the operator rebuilds the utility resources from it.
    """

    @staticmethod
    def _old_shape(context: GlobalContext) -> GlobalContext:
        old_keys = ("resolved_name", "port", "kind", "deployment_id", "component")
        context.deployed_services = [
            {key: service[key] for key in old_keys}
            for service in context.deployed_services
        ]
        return context

    def test_the_builder_skips_entries_without_a_scope(self) -> None:
        context = self._old_shape(_context([_service("web"), _service("api")]))

        assert _build(context) == []

    def test_the_other_utility_resources_are_still_built(self) -> None:
        context = self._old_shape(
            _context([_service("web")], ip_whitelist=["10.0.0.0/8"])
        )

        resources = IngressUtility().build_resources(context, RELEASE_REF, NAMESPACE)

        assert resources
        assert all(resource["kind"] != "Ingress" for resource in resources)

    def test_an_old_entry_beside_a_new_one_builds_only_the_new_one(self) -> None:
        context = _context([_service("web"), _service("api")])
        context.deployed_services[0] = {
            key: context.deployed_services[0][key]
            for key in ("resolved_name", "port", "kind", "deployment_id", "component")
        }

        assert set(_by_service(_build(context))) == {"api"}
