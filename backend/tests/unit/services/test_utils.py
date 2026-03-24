import pytest

from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterConfig,
    EnvironmentConfig,
    GlobalContext,
    ResolvedConfig,
)
from styrmin_backend.services.utils import (
    get_chart_name_from_chart_url,
    get_chart_repository_from_chart_url,
    get_helm_repository_type,
)


@pytest.fixture
def runtime_context():
    return GlobalContext(
        cluster=ClusterConfig(
            ingress_class="nginx",
            runtime_class="k8s",
            node_selector="node-type=worker",
            dedicated_ingress="true",
        ),
        environment=EnvironmentConfig(
            ip_whitelist=["10.0.0.0/8"],
            db_size="1Gi",
        ),
        instance=ResolvedConfig(
            ip_whitelist=["10.0.0.0/8"],
            ingress_class="nginx",
            db_size="1Gi",
            runtime_class="k8s",
            node_selector="node-type=worker",
            dedicated_ingress="true",
        ),
        app=ApplicationContext(
            name="myapp",
            version="1.0.0",
        ),
    )


def test_get_chart_name_from_chart_url():
    chart_url = "https://test.com/test_chart"
    assert get_chart_name_from_chart_url(chart_url) == "test_chart"


def test_get_chart_name_from_chart_url_with_trailing_slash():
    chart_url = "https://test.com/test_chart/"
    assert get_chart_name_from_chart_url(chart_url) == "test_chart"


def test_get_chart_repository_from_chart_url():
    chart_url = "https://test.com/test_chart"
    assert get_chart_repository_from_chart_url(chart_url) == "https://test.com"


def test_get_chart_repository_from_chart_url_with_trailing_slash():
    chart_url = "https://test.com/test_chart/"
    assert get_chart_repository_from_chart_url(chart_url) == "https://test.com"


def test_get_helm_repository_type_oci():
    assert get_helm_repository_type("oci://registry.example.com/chart") == "oci"


def test_get_helm_repository_type_http():
    assert get_helm_repository_type("http://chart-server:8080") == "default"


def test_get_helm_repository_type_https():
    assert get_helm_repository_type("https://charts.bitnami.com/bitnami") == "default"
