from dataclasses import dataclass

from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import Name
from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    AnnotationPatch,
    LabelPatch,
    Patch,
    SpecPatch,
    Target,
    TargetPatch,
    TemplateLabelPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    ChartRef,
    Install,
    Interval,
    PostRenderers,
    ReleaseName,
    Remediation,
    Timeout,
    Upgrade,
    Values,
)


@dataclass
class MockPatch(Patch):
    """A mock patch class for testing purposes."""

    _operation: str = "test-operation"
    _path: str = "/test/path"

    def render_value(self):
        return self._operation, self._path


def test_keyed_block():
    block = Name(value="test-name")

    assert block.key == "name"
    assert block.render_value() == "test-name"
    assert block.render() == {"name": "test-name"}


def test_install_block():
    block = Install(remediation=Remediation(retries=3))

    assert block.key == "install"
    assert block.render_value() == {"remediation": {"retries": 3}}
    assert block.render() == {"install": {"remediation": {"retries": 3}}}


def test_remediation_block():
    block = Remediation(retries=3)

    assert block.key == "remediation"
    assert block.render_value() == {"retries": 3}
    assert block.render() == {"remediation": {"retries": 3}}


def test_interval_block():
    block = Interval(value="1h")

    assert block.key == "interval"
    assert block.render_value() == "1h"
    assert block.render() == {"interval": "1h"}


def test_timeout_block():
    block = Timeout(value="5m")

    assert block.key == "timeout"
    assert block.render_value() == "5m"
    assert block.render() == {"timeout": "5m"}


def test_release_name_block():
    block = ReleaseName(value="my-release")

    assert block.key == "releaseName"
    assert block.render_value() == "my-release"
    assert block.render() == {"releaseName": "my-release"}


def test_upgrade_block():
    block = Upgrade(remediation=Remediation(retries=3))

    assert block.key == "upgrade"
    assert block.render_value() == {"remediation": {"retries": 3}}
    assert block.render() == {"upgrade": {"remediation": {"retries": 3}}}


def test_chart_ref_block():
    block = ChartRef(name="my-chart", namespace="styrmin")

    assert block.key == "chartRef"
    assert block.render_value() == {
        "name": "my-chart",
        "namespace": "styrmin",
        "kind": "HelmChart",
    }
    assert block.render() == {
        "chartRef": {"name": "my-chart", "namespace": "styrmin", "kind": "HelmChart"}
    }


def test_values_block():
    block = Values(value="test-values")

    assert block.key == "values"
    assert block.render_value() == "test-values"
    assert block.render() == {"values": "test-values"}


def test_post_renderers_block():
    block = PostRenderers(target_patches=[])
    assert block.key == "postRenderers"
    assert block.render_value() == [{"kustomize": {"patches": []}}]
    assert block.render() == {"postRenderers": [{"kustomize": {"patches": []}}]}


def test_target_block():
    block = Target(name="test-name", kind="test-kind")

    assert block.key == "target"
    assert block.render_value() == {"name": "test-name", "kind": "test-kind"}
    assert block.render() == {"target": {"name": "test-name", "kind": "test-kind"}}


def test_target_block_without_name():
    block = Target(kind="test-kind")

    assert block.key == "target"
    assert block.render_value() == {"kind": "test-kind"}
    assert block.render() == {"target": {"kind": "test-kind"}}


def test_target_block_without_kind():
    block = Target(name="test-name")

    assert block.key == "target"
    assert block.render_value() == {"name": "test-name"}
    assert block.render() == {"target": {"name": "test-name"}}


def test_target_block_with_no_args():
    block = Target()

    assert block.key == "target"
    assert block.render_value() == {}
    assert block.render() == {"target": {}}


def test_target_patch():
    target = Target(name="test-name", kind="test-kind")
    target_patch = TargetPatch(target=target, patch=MockPatch())

    assert target_patch.render_value() == {
        "target": {"name": "test-name", "kind": "test-kind"},
        "patch": ("test-operation", "/test/path"),
    }


def test_label_patch_without_prefix():
    label_key = "key"
    label_value = "value"
    expected_render_value = (
        f"- op: add\n  path: /metadata/labels/{label_key}\n  value: {label_value}\n"
    )
    patch = LabelPatch(labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_label_patch_with_prefix():
    label_key = "key"
    label_value = "value"
    expected_render_value = f"- op: add\n  path: /metadata/labels/test~1{label_key}\n  value: {label_value}\n"
    patch = LabelPatch(label_prefix="test", labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_label_patch_with_slash_in_key():
    label_key = "test/key"
    label_value = "value"
    expected_render_value = (
        f"- op: add\n  path: /metadata/labels/test~1key\n  value: {label_value}\n"
    )
    patch = LabelPatch(labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_label_patch_with_slash_in_key_and_prefix():
    label_key = "test/key"
    label_value = "value"
    expected_render_value = (
        f"- op: add\n  path: /metadata/labels/test~1test~1key\n  value: {label_value}\n"
    )
    patch = LabelPatch(label_prefix="test", labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_template_label_patch_without_prefix():
    label_key = "key"
    label_value = "value"
    expected_render_value = f"- op: add\n  path: /spec/template/metadata/labels/{label_key}\n  value: {label_value}\n"
    patch = TemplateLabelPatch(labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_template_label_patch_with_prefix():
    label_key = "key"
    label_value = "value"
    expected_render_value = f"- op: add\n  path: /spec/template/metadata/labels/test~1{label_key}\n  value: {label_value}\n"
    patch = TemplateLabelPatch(label_prefix="test", labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_template_label_patch_with_slash_in_key():
    label_key = "test/key"
    label_value = "value"
    expected_render_value = f"- op: add\n  path: /spec/template/metadata/labels/test~1key\n  value: {label_value}\n"
    patch = TemplateLabelPatch(labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_template_label_patch_with_slash_in_key_and_prefix():
    label_key = "test/key"
    label_value = "value"
    expected_render_value = f"- op: add\n  path: /spec/template/metadata/labels/test~1test~1key\n  value: {label_value}\n"
    patch = TemplateLabelPatch(label_prefix="test", labels={label_key: label_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_annotation_patch_without_slash():
    annotation_key = "key"
    annotation_value = "value"
    expected_render_value = f"- op: add\n  path: /metadata/annotations/{annotation_key}\n  value: {annotation_value}\n"
    patch = AnnotationPatch(annotations={annotation_key: annotation_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_annotation_patch_with_slash():
    annotation_key = "test/key"
    annotation_value = "value"
    expected_render_value = f"- op: add\n  path: /metadata/annotations/test~1key\n  value: {annotation_value}\n"
    patch = AnnotationPatch(annotations={annotation_key: annotation_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_spec_patch_without_slash():
    spec_key = "key"
    spec_value = "value"
    expected_render_value = (
        f"- op: add\n  path: /spec/{spec_key}\n  value: {spec_value}\n"
    )
    patch = SpecPatch(specs={spec_key: spec_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}


def test_spec_patch_with_slash():
    spec_key = "test/key"
    spec_value = "value"
    expected_render_value = (
        f"- op: add\n  path: /spec/test~1key\n  value: {spec_value}\n"
    )
    patch = SpecPatch(specs={spec_key: spec_value})

    assert patch.render_value() == expected_render_value
    assert patch.render() == {"patch": expected_render_value}
