"""The Ingress that Styrmin builds for an external service carries the labels of the deployment (#598).

Symptom (``specs/033-service-ingress-override/e2e-evidence.md``, section "T062"): in an environment
with a dedicated ingress controller, the host of the Prefect UI answered HTTP 404 through the
controller once the chart Ingress was gone, and kept doing so. Adding the label
``styrmin/environment_id`` to the Ingress by hand changed the answer to 200 within one second.

Cause under test: the dedicated Traefik starts with
``--providers.kubernetesingress.labelselector=styrmin/environment_id=<environment id>`` (template
``services/ingress_controller/templates/chart_values.j2.yaml``), so it serves only an Ingress that has
that label. The chart Ingresses get every entry of ``context.labels`` with the prefix ``styrmin/``
from the post-render label patch. The builder of ``IngressUtility`` set only
``styrmin.io/service-name``.

The selector is read from the rendered controller template, not written in this file, so the tests
fail if the template or the builder changes without the other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import jinja2
import pytest
import yaml

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.utility import (
    UtilityResourceBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.ingress import (
    IngressUtility,
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
SUFFIX = "test.styrmin.com"
DEPLOYMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
ENVIRONMENT_ID = UUID("00000000-0000-0000-0000-0000000000e1")

_CONTROLLER_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "styrmin_backend"
    / "services"
    / "ingress_controller"
    / "templates"
    / "chart_values.j2.yaml"
)
_SELECTOR_ARGUMENT = "--providers.kubernetesingress.labelselector="

OVERRIDE = ServiceConfigBlock(
    ingress_class="tailscale", fqdn_suffix="tailnet.example.ts.net"
)


def _service(name: str) -> dict[str, Any]:
    return {
        "driver_service_name": name,
        "resolved_name": name,
        "port": 8080,
        "kind": "http",
        "scope": "external",
        "deployment_id": str(DEPLOYMENT_ID),
        "component": "server",
        "ingress_class": "traefik",
        "fqdn_suffix": SUFFIX,
    }


def _context(
    *,
    labels: dict[str, Any] | None = None,
    overrides: dict[str, ServiceConfigBlock] | None = None,
) -> GlobalContext:
    """A deployment in an environment with a dedicated ingress controller and one external service ``web``."""
    dedicated = DedicatedIngressConfig(implementation="traefik")
    return GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(
                ingress_class="traefik",
                dedicated_ingress=dedicated,
                fqdn_suffix=SUFFIX,
            ),
        ),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig(services=overrides)),
        instance=InstanceContext(
            config=ResolvedConfig(
                ingress_class="traefik",
                dedicated_ingress=dedicated,
                fqdn_suffix=SUFFIX,
            ),
            deployment_id=DEPLOYMENT_ID,
            namespace=NAMESPACE,
            release_reference=RELEASE_REF,
        ),
        app=ApplicationContext(
            name="testapp",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=UUID(int=7), name="testapp", version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(
                    id=UUID(int=8), url="oci://charts.example.com/test"
                ),
            ),
        ),
        labels={"environment_id": ENVIRONMENT_ID, "deployment_id": DEPLOYMENT_ID}
        if labels is None
        else labels,
        deployed_services=[_service("web")],
    )


def _built_ingress(context: GlobalContext) -> dict[str, Any]:
    resources = IngressUtility().build_resources(context, RELEASE_REF, NAMESPACE)
    (ingress,) = [r for r in resources if r["kind"] == "Ingress"]
    return ingress


def _controller_selector(context: GlobalContext) -> dict[str, str]:
    """The label selector of the dedicated controller, read from its rendered chart values.

    Rendered the way production does it (``GlobalContext.model_dump(exclude_none=True)`` as the
    Jinja context), so the value is the one that the controller of this environment is started with.
    """
    rendered = jinja2.Environment().from_string(_CONTROLLER_TEMPLATE.read_text())
    values = yaml.safe_load(rendered.render(**context.model_dump(exclude_none=True)))
    (argument,) = [
        arg
        for arg in values["additionalArguments"]
        if arg.startswith(_SELECTOR_ARGUMENT)
    ]
    selector = {}
    for requirement in argument.removeprefix(_SELECTOR_ARGUMENT).split(","):
        key, _, value = requirement.partition("=")
        selector[key] = value
    return selector


def _chart_ingress_labels(context: GlobalContext) -> dict[str, str]:
    """The labels that the post-render patch gives every object of the chart, the chart Ingress included."""
    patches = ApplicationHelmReleaseBuilder(context).build_target_for_label_patches(
        labels=context.labels
    )
    (every_object,) = [p for p in patches if p.target.name == ".*"]
    document = yaml.safe_load(every_object.patch.render_value())
    return document["metadata"]["labels"]


class TestTheBuiltIngressIsServedByTheDedicatedController:
    def test_the_selector_is_the_environment_id(self) -> None:
        """Guards the premise: the controller selects by the environment id, so a missing label hides the Ingress."""
        context = _context()

        assert _controller_selector(context) == {
            "styrmin/environment_id": str(ENVIRONMENT_ID)
        }

    def test_the_built_ingress_has_every_label_of_the_controller_selector(
        self,
    ) -> None:
        context = _context()

        labels = _built_ingress(context)["metadata"]["labels"]

        for key, value in _controller_selector(context).items():
            assert labels.get(key) == value, (
                f"The dedicated controller selects {key}={value}; the Ingress has {labels}"
            )

    def test_the_built_ingress_has_the_labels_of_the_chart_ingress(self) -> None:
        context = _context()

        labels = _built_ingress(context)["metadata"]["labels"]
        chart_labels = _chart_ingress_labels(context)

        assert chart_labels == {
            "styrmin/environment_id": str(ENVIRONMENT_ID),
            "styrmin/deployment_id": str(DEPLOYMENT_ID),
        }
        assert {k: labels.get(k) for k in chart_labels} == chart_labels

    def test_the_operator_builds_the_labels_next_to_the_ownership_labels(
        self,
    ) -> None:
        """The operator calls ``UtilityResourceBuilder``, which adds the ownership labels."""
        context = _context()

        resources = UtilityResourceBuilder(context).build(
            IngressUtility(), RELEASE_REF, NAMESPACE
        )
        (ingress,) = [r for r in resources if r["kind"] == "Ingress"]

        labels = ingress["metadata"]["labels"]
        assert labels["styrmin/environment_id"] == str(ENVIRONMENT_ID)
        assert labels["styrmin/deployment_id"] == str(DEPLOYMENT_ID)
        assert labels["styrmin.io/service-name"] == "web"
        assert labels["styrmin.io/utility-kind"] == "ingress"
        assert labels["styrmin.io/release-reference"] == RELEASE_REF
        assert labels["app.kubernetes.io/managed-by"] == "styrmin"

    def test_an_overridden_ingress_has_the_same_labels(self) -> None:
        """An override changes the class and the host, not which deployment owns the Ingress."""
        context = _context(overrides={"web": OVERRIDE})

        ingress = _built_ingress(context)

        assert ingress["spec"]["ingressClassName"] == "tailscale"
        assert ingress["metadata"]["labels"]["styrmin/environment_id"] == str(
            ENVIRONMENT_ID
        )
        assert ingress["metadata"]["labels"]["styrmin/deployment_id"] == str(
            DEPLOYMENT_ID
        )

    @pytest.mark.parametrize("empty", [None, ""])
    def test_an_empty_context_label_gives_no_label(self, empty: str | None) -> None:
        """A label with no value would match nothing useful, and ``None`` would become the text ``None``."""
        context = _context(
            labels={"environment_id": ENVIRONMENT_ID, "deployment_id": empty}
        )

        labels = _built_ingress(context)["metadata"]["labels"]

        assert labels["styrmin/environment_id"] == str(ENVIRONMENT_ID)
        assert "styrmin/deployment_id" not in labels

    def test_a_context_without_labels_builds_the_ingress_with_its_own_label_only(
        self,
    ) -> None:
        labels = _built_ingress(_context(labels={}))["metadata"]["labels"]

        assert labels == {"styrmin.io/service-name": "web"}
