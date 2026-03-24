from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import Name
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    Install,
    Remediation,
)
from styrmin_backend.agent.service.kubernetes.resources.custom_resource import (
    HelmRelease,
)


def test_helm_release_without_spec_or_metadata():
    helm_release = HelmRelease(
        apiVersion="test-api-version",
        metadata=[],
        spec=[],
    )
    assert helm_release.render() == {
        "apiVersion": "test-api-version",
        "kind": "HelmRelease",
        "metadata": {},
        "spec": {},
    }


def test_helm_release_with_spec_and_metadata():
    helm_release = HelmRelease(
        apiVersion="test-api-version",
        metadata=[Name(value="test-name")],
        spec=[Install(remediation=Remediation(retries=3))],
    )
    assert helm_release.render() == {
        "apiVersion": "test-api-version",
        "kind": "HelmRelease",
        "metadata": {"name": "test-name"},
        "spec": {"install": {"remediation": {"retries": 3}}},
    }
