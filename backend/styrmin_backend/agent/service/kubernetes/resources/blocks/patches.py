import yaml

from dataclasses import dataclass, field
from functools import reduce
from operator import add
from typing import Any

from .base import GenericBlock, KeyedBlock


@dataclass
class Target(KeyedBlock):
    """
    Represents a target resource with optional attributes.

    Attributes:
        name (str | None): The name of the target resource.
        kind (str | None): The kind of the target resource.
        label_selector (str | None): The label selector for the target resource.
        version (str | None): The version of the target resource.

    Example:
        >>> target = Target(name="my-app", kind="Deployment", label_selector="app=my-app", version="v1")
        >>> target.render_value()
        {'name': 'my-app', 'kind': 'Deployment', 'labelSelector': 'app=my-app', 'version': 'v1'}
    """

    _key: str = field(init=False, default="target")
    name: str | None = None
    kind: str | None = None
    label_selector: str | None = None
    version: str | None = None

    def render_value(self) -> dict[str, Any]:
        result = {}
        if self.name:
            result["name"] = self.name
        if self.kind:
            result["kind"] = self.kind
        if self.label_selector:
            result["labelSelector"] = self.label_selector
        if self.version:
            result["version"] = self.version
        return result


@dataclass
class Patch(KeyedBlock):
    """
    Represents a generic patch operation.

    Attributes:
        _operation (str): The operation type (e.g., "add", "remove").
        _path (str): The JSON path where the operation is applied.

    Example:
        >>> patch = Patch(_operation="add", _path="/metadata/labels")
        >>> patch.operation
        'add'
        >>> patch.path
        '/metadata/labels'
    """

    _operation: str
    _path: str
    _key: str = field(init=False, default="patch")

    @property
    def operation(self) -> str:
        return self._operation

    @property
    def path(self) -> str:
        return self._path


@dataclass
class TargetPatch(GenericBlock):
    """
    Represents a patch applied to a specific target.

    Attributes:
        target (Target): The target resource.
        patch (Patch): The patch to apply.

    Example:
        >>> target = Target(name="my-app", kind="Deployment")
        >>> patch = Patch(_operation="add", _path="/metadata/labels")
        >>> target_patch = TargetPatch(target=target, patch=patch)
        >>> target_patch.render_value()
        {'target': {'name': 'my-app', 'kind': 'Deployment'}, 'patch': {}}
    """

    target: Target
    patch: Patch

    def render_value(self) -> dict[str, dict[str, Any]]:
        return {
            self.target.key: self.target.render_value(),
            self.patch.key: self.patch.render_value(),
        }


@dataclass
class MultiTargetPatch(GenericBlock):
    """
    Represents a patch applied to multiple targets.

    Attributes:
        targets (list[Target]): A list of target resources.
        patch (Patch): The patch to apply.

    Example:
        >>> target1 = Target(name="app1", kind="Deployment")
        >>> target2 = Target(name="app2", kind="Deployment")
        >>> patch = Patch(_operation="add", _path="/metadata/labels")
        >>> multi_target_patch = MultiTargetPatch(targets=[target1, target2], patch=patch)
        >>> multi_target_patch.render_value()
        [{'target': {'name': 'app1', 'kind': 'Deployment'}, 'patch': {}}, {'target': {'name': 'app2', 'kind': 'Deployment'}, 'patch': {}}]
    """

    targets: list[Target]
    patch: Patch

    def render_value(self) -> list[dict[str, dict[str, Any]]]:
        return [
            {
                target.key: target.render_value(),
                self.patch.key: self.patch.render_value(),
            }
            for target in self.targets
        ]


@dataclass
class LabelPatch(Patch):
    """
    Represents a patch for adding labels to a resource.

    Attributes:
        labels (dict[str, str]): The labels to add.
        label_prefix (str): An optional prefix for the label keys.

    Example:
        >>> label_patch = LabelPatch(labels={"env": "prod", "team": "devops"})
        >>> label_patch.render_value()
        '- op: add\n  path: /metadata/labels/env\n  value: prod\n- op: add\n  path: /metadata/labels/team\n  value: devops\n'
    """

    labels: dict[str, str]
    label_prefix: str = ""
    _path: str = field(init=False, default="/metadata/labels")
    _operation: str = field(init=False, default="add")

    def _render_label_path(self, key: str) -> str:
        rendered_label_path = key.replace("/", "~1")
        if self.label_prefix:
            rendered_label_path = (
                self.label_prefix.lstrip("/").rstrip("/") + "~1" + rendered_label_path
            )
        return rendered_label_path

    def render_value(self) -> str:
        return reduce(
            add,
            (
                f"- op: {self._operation}\n  path: {self._path}/{self._render_label_path(key=key)}\n  value: {value}\n"
                for key, value in self.labels.items()
            ),
        )


@dataclass
class TemplateLabelPatch(LabelPatch):
    """
    Represents a patch for adding labels to a resource's template.

    Example:
        >>> template_label_patch = TemplateLabelPatch(labels={"env": "prod"})
        >>> template_label_patch.render_value()
        '- op: add\n  path: /spec/template/metadata/labels/env\n  value: prod\n'
    """

    labels: dict[str, str]
    label_prefix: str = ""
    _path: str = field(init=False, default="/spec/template/metadata/labels")
    _operation: str = field(init=False, default="add")


@dataclass
class AnnotationPatch(Patch):
    """
    Represents a patch for adding annotations to a resource.

    Attributes:
        annotations (dict[str, str]): The annotations to add.

    Example:
        >>> annotation_patch = AnnotationPatch(annotations={"description": "example"})
        >>> annotation_patch.render_value()
        '- op: add\n  path: /metadata/annotations/description\n  value: example\n'
    """

    annotations: dict[str, str]
    _path: str = field(init=False, default="/metadata/annotations")
    _operation: str = field(init=False, default="add")

    def render_value(self) -> str:
        return reduce(
            add,
            (
                f"- op: {self._operation}\n  path: {self._path}/{key.replace('/', '~1')}\n  value: {value}\n"
                for key, value in self.annotations.items()
            ),
        )


@dataclass
class TemplateAnnotationPatch(AnnotationPatch):
    """
    Represents a patch for adding annotations to a resource's pod template.

    This is used to inject annotations into the pod template spec of Deployments
    and StatefulSets (at /spec/template/metadata/annotations).

    Uses a strategic merge patch instead of JSON Patch so that missing
    intermediate keys (e.g. ``spec.template.metadata.annotations``) are
    created automatically.  Kustomize accepts both formats in the same
    ``patches`` list.

    Kustomize requires ``apiVersion``, ``kind``, and ``metadata.name`` in
    strategic merge patches so it can identify the resource schema.  When a
    ``target`` selector is used, ``metadata.name`` is required but not matched
    against resources, so a dummy value is used by default.

    Example:
        >>> patch = TemplateAnnotationPatch(annotations={"backup.velero.io/backup-volumes": "data,logs"})
        >>> print(patch.render_value())
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: any
        spec:
          template:
            metadata:
              annotations:
                backup.velero.io/backup-volumes: data,logs
        <BLANKLINE>
    """

    annotations: dict[str, str]
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    _path: str = field(init=False, default="/spec/template/metadata/annotations")
    _operation: str = field(init=False, default="add")

    def render_value(self) -> str:
        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": dict(self.annotations),
                    },
                },
            },
        }
        return yaml.dump(doc, default_flow_style=False)


@dataclass
class GenericPatch(Patch):
    """
    Represents a generic patch with a specific value.

    Attributes:
        value (str): The value to set at the specified path.

    Example:
        >>> generic_patch = GenericPatch(_path="/spec/replicas", value="3")
        >>> generic_patch.render_value()
        '- op: add\n  path: /spec/replicas\n  value: 3\n'
    """

    _path: str
    value: str
    _operation: str = field(init=False, default="add")

    def render_value(self) -> str:
        return f"- op: {self._operation}\n  path: {self._path}\n  value: {self.value}\n"


@dataclass
class SpecPatch(Patch):
    """
    Represents a patch for modifying the spec of a resource.

    Attributes:
        specs (dict[str, Any]): The spec modifications.

    Example:
        >>> spec_patch = SpecPatch(specs={"replicas": 3, "strategy": "RollingUpdate"})
        >>> spec_patch.render_value()
        '- op: add\n  path: /spec/replicas\n  value: 3\n- op: add\n  path: /spec/strategy\n  value: RollingUpdate\n'
    """

    specs: dict[str, Any]
    _path: str = field(init=False, default="/spec")
    _operation: str = field(init=False, default="add")

    def render_value(self) -> str:
        return reduce(
            add,
            (
                f"- op: {self._operation}\n  path: {self._path}/{key.replace('/', '~1')}\n  value: {value}\n"
                for key, value in self.specs.items()
            ),
        )
