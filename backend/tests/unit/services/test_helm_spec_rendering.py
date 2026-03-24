from uuid import uuid4

from styrmin_backend.services.helm.renderer import (
    render_helm_chart_spec,
    # render_helm_release_spec,
    render_helm_repository_spec,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference


def test_helm_repository_renderer():
    repository_id = uuid4()

    rendered = render_helm_repository_spec(
        repository_id=repository_id, repository_url="https://test.com"
    )

    assert rendered == {
        "apiVersion": "source.toolkit.fluxcd.io/v1",
        "kind": "HelmRepository",
        "metadata": {"name": get_kubernetes_reference(repository_id)},
        "spec": {
            "interval": "60m0s",
            "type": "oci",
            "url": "https://test.com",
        },
    }


def test_helm_repository_renderer_http():
    repository_id = uuid4()

    rendered = render_helm_repository_spec(
        repository_id=repository_id,
        repository_url="http://chart-server:8080",
        repository_type="default",
    )

    assert rendered == {
        "apiVersion": "source.toolkit.fluxcd.io/v1",
        "kind": "HelmRepository",
        "metadata": {"name": get_kubernetes_reference(repository_id)},
        "spec": {
            "interval": "60m0s",
            "type": "default",
            "url": "http://chart-server:8080",
        },
    }


def test_helm_chart_renderer():
    chart_uuid = uuid4()
    repository_uuid = uuid4()

    rendered = render_helm_chart_spec(
        helm_chart_id=chart_uuid,
        name="test-chart",
        version="1.0.0",
        repository_id=repository_uuid,
    )

    assert rendered == {
        "apiVersion": "source.toolkit.fluxcd.io/v1",
        "kind": "HelmChart",
        "metadata": {"name": get_kubernetes_reference(chart_uuid)},
        "spec": {
            "chart": "test-chart",
            "interval": "60m0s",
            "sourceRef": {
                "kind": "HelmRepository",
                "name": get_kubernetes_reference(repository_uuid),
            },
            "version": "1.0.0",
        },
    }


# def test_helm_release_renderer():
#     chart_uuid = uuid4()
#     instance_uuid = uuid4()
#     chart_values = {"key": "value"}
#     helm_chart = HelmChart(
#         id=chart_uuid,
#         name="test-chart",
#         version="1.0.0",
#         repository_id=uuid4(),
#     )

#     rendered = render_helm_release_spec(
#         helm_chart=helm_chart,
#         instance_id=instance_uuid,
#         chart_values=chart_values,
#     )

#     assert rendered == {
#         "apiVersion": "helm.toolkit.fluxcd.io/v2",
#         "kind": "HelmRelease",
#         "metadata": {"name": get_kubernetes_reference(instance_uuid)},
#         "spec": {
#             "chartRef": {
#                 "kind": "HelmChart",
#                 "name": get_kubernetes_reference(chart_uuid),
#                 "namespace": "styrmin",
#             },
#             "install": {"remediation": {"retries": 3}},
#             "interval": "1h",
#             "releaseName": get_kubernetes_reference(instance_uuid),
#             "timeout": "5m",
#             "upgrade": {"remediation": {"retries": 3}},
#             "values": chart_values,
#         },
#     }
