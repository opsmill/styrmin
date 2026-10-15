"""Unit tests for ``ingress_class`` in the data of
``ApplicationHelmReleaseBuilder.render_value_template``
(023-ingress-class-post-render, T007, FR-003, research D-004).

FR-003: driver templates read the resolved ``ingress_class`` of every config
section with or without a dedicated ingress controller.
"""

from __future__ import annotations

from textwrap import dedent
from uuid import uuid4

import pytest

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DedicatedIngressConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import (
    ChartInfo,
    HelmInfo,
    RepositoryInfo,
)

PROBE_TEMPLATE = dedent(
    """
    instance_class: "{{ instance.config.ingress_class }}"
    cluster_class: "{{ cluster.config.ingress_class }}"
    environment_class: "{{ environment.config.ingress_class }}"
    deployment_class: "{{ deployment.config.ingress_class }}"
    """
).strip()

# One value per section, so a template that reads the wrong section fails.
CLASSES = {
    "instance_class": "instance-nginx",
    "cluster_class": "cluster-traefik",
    "environment_class": "environment-haproxy",
    "deployment_class": "deployment-contour",
}


def _make_global_context(
    *,
    dedicated_ingress: DedicatedIngressConfig | None,
    classes: dict[str, str | None],
) -> GlobalContext:
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(
                ingress_class=classes["cluster_class"],
                dedicated_ingress=dedicated_ingress,
            )
        ),
        environment=EnvironmentContext(
            name="test",
            config=EnvironmentConfig(ingress_class=classes["environment_class"]),
        ),
        deployment=DeploymentContext(
            config=DeploymentConfig(ingress_class=classes["deployment_class"])
        ),
        instance=InstanceContext(
            config=ResolvedConfig(
                ingress_class=classes["instance_class"],
                dedicated_ingress=dedicated_ingress,
            ),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="test-chart",
                    version="1.0.0",
                    values_template=PROBE_TEMPLATE,
                ),
                repository=RepositoryInfo(
                    id=uuid4(),
                    url="https://example.com/charts",
                ),
            ),
        ),
        deployed_services=[],
    )


def _render(context: GlobalContext) -> dict:
    return ApplicationHelmReleaseBuilder.render_value_template.fn(
        values_template=PROBE_TEMPLATE, context=context
    )


@pytest.mark.parametrize(
    "dedicated_ingress",
    [DedicatedIngressConfig(), None],
    ids=["dedicated-ingress", "shared-ingress"],
)
def test_template_reads_ingress_class_of_every_section(
    dedicated_ingress: DedicatedIngressConfig | None,
) -> None:
    """FR-003: a dedicated ingress controller no longer hides ``ingress_class``."""
    context = _make_global_context(dedicated_ingress=dedicated_ingress, classes=CLASSES)

    assert _render(context) == CLASSES


def test_unset_ingress_class_renders_empty() -> None:
    """With ``ingress_class=None`` at every level, the key is absent and renders empty."""
    context = _make_global_context(
        dedicated_ingress=None, classes=dict.fromkeys(CLASSES)
    )

    assert _render(context) == dict.fromkeys(CLASSES, "")
