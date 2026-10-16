from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import Name
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    Install,
    Remediation,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.base import (
    build_minimal_helm_release,
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


def test_minimal_helm_release_leaves_the_helm_v4_defaults_to_flux():
    """The operator sets no Helm v4 field, so helm-controller's defaults apply (#435)."""
    spec = build_minimal_helm_release("rel", "chart").render()["spec"]

    assert spec["install"] == {"remediation": {"retries": 3}}
    assert spec["upgrade"] == {"remediation": {"retries": 3}}
    assert not {"waitStrategy", "postRenderStrategy", "rollback"} & spec.keys()
