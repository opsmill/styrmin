import yaml

from dataclasses import dataclass, field
from functools import reduce
from operator import add
from typing import Any

from styrmin_backend.context.models.config import (
    AffinityBlock,
    ResourceRequirements,
    Toleration,
    TopologySpreadConstraint,
)
from styrmin_backend.services.component_container.exceptions import GUARD_KEY_PREFIX

from .base import GenericBlock, KeyedBlock


_POD_TEMPLATE_SPEC_PATH: tuple[str, ...] = ("spec", "template", "spec")
_CRONJOB_TEMPLATE_SPEC_PATH: tuple[str, ...] = (
    "spec",
    "jobTemplate",
    "spec",
    "template",
    "spec",
)


def _snake_to_camel(name: str) -> str:
    # Keys that contain ``/`` or ``.`` are Kubernetes identifiers (label keys
    # like ``app.kubernetes.io/name`` or extended-resource keys like
    # ``nvidia.com/gpu``), not Pydantic field names — Pydantic identifiers
    # can't contain those characters. Preserve them as-is so values such as
    # ``styrmin/deployment_id`` in ``matchLabels`` don't get mangled into
    # ``styrmin/deploymentId`` when the patch is rendered.
    if "/" in name or "." in name:
        return name
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _drop_nulls_camel(value: Any) -> Any:  # noqa: ANN401
    """Recursively drop ``None`` values and rename snake_case → camelCase keys.

    Lists preserve ordering. Dicts skip keys whose value is ``None``. Leaf
    values are passed through unchanged.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if v is None:
                continue
            out[_snake_to_camel(k)] = _drop_nulls_camel(v)
        return out
    if isinstance(value, list):
        return [_drop_nulls_camel(v) for v in value]
    return value


def _affinity_block_to_k8s(block: AffinityBlock) -> dict[str, Any]:
    """Render an :class:`AffinityBlock` into the Kubernetes dict shape.

    ``required`` terms go into ``requiredDuringSchedulingIgnoredDuringExecution``;
    ``preferred`` weighted terms go into
    ``preferredDuringSchedulingIgnoredDuringExecution``. The per-block
    ``replace`` flag is intentionally dropped — it is consumed by the merge
    pass upstream and has no Kubernetes representation.
    """
    result: dict[str, Any] = {}
    if block.required:
        result["requiredDuringSchedulingIgnoredDuringExecution"] = [
            _drop_nulls_camel(
                term.model_dump(exclude_none=True, exclude={"deployment_ref"})
            )
            for term in block.required
        ]
    if block.preferred:
        result["preferredDuringSchedulingIgnoredDuringExecution"] = [
            {
                "weight": weighted.weight,
                "podAffinityTerm": _drop_nulls_camel(
                    weighted.term.model_dump(
                        exclude_none=True, exclude={"deployment_ref"}
                    )
                ),
            }
            for weighted in block.preferred
        ]
    return result


def _nested_dict(path: tuple[str, ...], leaf: dict[str, Any]) -> dict[str, Any]:
    """Return ``{path[0]: {path[1]: {... {path[-1]: leaf}}}}``."""
    node: dict[str, Any] = leaf
    for segment in reversed(path):
        node = {segment: node}
    return node


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
class AffinityPatch(Patch):
    """Strategic-merge YAML patch injecting pod affinity and/or anti-affinity.

    Scoped to ``spec.template.spec.affinity.podAffinity`` and
    ``spec.template.spec.affinity.podAntiAffinity`` ONLY — does NOT patch the
    whole ``affinity:`` object so that a separate ``NodeAffinityPatch`` (US3)
    can compose without clobbering this one. For ``CronJob`` the path nests
    under ``spec.jobTemplate.spec.template.spec.affinity``.

    ``pod_affinity`` and ``pod_anti_affinity`` accept pre-merged
    :class:`AffinityBlock` instances whose ``deployment_ref`` terms have
    already been expanded into ``label_selector`` by the validator.
    """

    pod_affinity: AffinityBlock | None = None
    pod_anti_affinity: AffinityBlock | None = None
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    _path: str = field(init=False, default="/spec/template/spec/affinity")
    _operation: str = field(init=False, default="add")

    def _spec_path(self) -> tuple[str, ...]:
        return (
            _CRONJOB_TEMPLATE_SPEC_PATH
            if self.kind == "CronJob"
            else _POD_TEMPLATE_SPEC_PATH
        )

    def render_value(self) -> str:
        affinity: dict[str, Any] = {}
        if self.pod_affinity is not None:
            affinity["podAffinity"] = _affinity_block_to_k8s(self.pod_affinity)
        if self.pod_anti_affinity is not None:
            affinity["podAntiAffinity"] = _affinity_block_to_k8s(self.pod_anti_affinity)

        leaf = {"affinity": affinity}
        spec_body = _nested_dict(self._spec_path(), leaf)

        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            **spec_body,
        }
        return yaml.dump(doc, default_flow_style=False, sort_keys=False)


def _toleration_to_k8s(tol: Toleration) -> dict[str, Any]:
    """Render a :class:`Toleration` into the Kubernetes dict shape."""
    out: dict[str, Any] = {}
    if tol.key is not None:
        out["key"] = tol.key
    if tol.operator is not None:
        out["operator"] = tol.operator
    if tol.value is not None:
        out["value"] = tol.value
    if tol.effect is not None:
        out["effect"] = tol.effect
    if tol.toleration_seconds is not None:
        out["tolerationSeconds"] = tol.toleration_seconds
    return out


def _topology_spread_to_k8s(c: TopologySpreadConstraint) -> dict[str, Any]:
    out: dict[str, Any] = {
        "maxSkew": c.max_skew,
        "topologyKey": c.topology_key,
        "whenUnsatisfiable": c.when_unsatisfiable,
    }
    if c.label_selector is not None:
        out["labelSelector"] = _drop_nulls_camel(
            c.label_selector.model_dump(exclude_none=True)
        )
    if c.min_domains is not None:
        out["minDomains"] = c.min_domains
    if c.node_affinity_policy is not None:
        out["nodeAffinityPolicy"] = c.node_affinity_policy
    if c.node_taints_policy is not None:
        out["nodeTaintsPolicy"] = c.node_taints_policy
    if c.match_label_keys is not None:
        out["matchLabelKeys"] = c.match_label_keys
    return out


def _node_affinity_block_to_k8s(block: AffinityBlock) -> dict[str, Any]:
    """Render a node-affinity :class:`AffinityBlock` into Kubernetes shape.

    Node affinity uses ``nodeSelectorTerms`` (list of ``matchExpressions``),
    unlike pod affinity. This implementation interprets each
    ``AffinityTerm.label_selector.match_expressions`` as a ``nodeSelectorTerm``
    (with ``matchFields`` not supported for now). ``topology_key`` is
    ignored per data-model §3 note.
    """
    result: dict[str, Any] = {}
    if block.required:
        terms = []
        for term in block.required:
            selector = term.label_selector
            node_term: dict[str, Any] = {}
            if selector is not None:
                if selector.match_expressions is not None:
                    node_term["matchExpressions"] = [
                        _drop_nulls_camel(req.model_dump(exclude_none=True))
                        for req in selector.match_expressions
                    ]
                if selector.match_labels is not None:
                    # Flatten matchLabels into matchExpressions (nodeSelectorTerm
                    # does not accept matchLabels directly).
                    expressions = node_term.setdefault("matchExpressions", [])
                    for k, v in selector.match_labels.items():
                        expressions.append({"key": k, "operator": "In", "values": [v]})
            if node_term:
                terms.append(node_term)
        if terms:
            result["requiredDuringSchedulingIgnoredDuringExecution"] = {
                "nodeSelectorTerms": terms
            }
    if block.preferred:
        preferred_list = []
        for weighted in block.preferred:
            term = weighted.term
            selector = term.label_selector
            preference: dict[str, Any] = {}
            if selector is not None:
                if selector.match_expressions is not None:
                    preference["matchExpressions"] = [
                        _drop_nulls_camel(req.model_dump(exclude_none=True))
                        for req in selector.match_expressions
                    ]
                if selector.match_labels is not None:
                    expressions = preference.setdefault("matchExpressions", [])
                    for k, v in selector.match_labels.items():
                        expressions.append({"key": k, "operator": "In", "values": [v]})
            if preference:
                preferred_list.append(
                    {"weight": weighted.weight, "preference": preference}
                )
        if preferred_list:
            result["preferredDuringSchedulingIgnoredDuringExecution"] = preferred_list
    return result


def _resource_spec_to_k8s(spec: Any) -> dict[str, Any]:
    """Render a :class:`ResourceSpec` into a Kubernetes dict.

    ``cpu``/``memory``/``ephemeral_storage`` become top-level keys
    (``cpu``, ``memory``, ``ephemeral-storage`` — Kubernetes uses a hyphen
    for the last one); the ``extended`` map is flattened into the same
    dict so that vendor and hugepages resources appear alongside the
    standard ones (e.g. ``nvidia.com/gpu: "1"``).
    """
    result: dict[str, Any] = {}
    if spec is None:
        return result
    if spec.cpu is not None:
        result["cpu"] = spec.cpu
    if spec.memory is not None:
        result["memory"] = spec.memory
    if spec.ephemeral_storage is not None:
        result["ephemeral-storage"] = spec.ephemeral_storage
    for key, value in spec.extended.items():
        result[key] = value
    return result


@dataclass
class ResourcesPatch(Patch):
    """JSON-patch setting container ``resources`` on the pod template.

    Kubernetes strategic-merge has no wildcard for containers (the merge key
    is ``name``), so emitting a strategic-merge patch that fits arbitrary
    charts without knowing container names is not possible. We fall back
    to a JSON patch targeting container index 0 — the pragmatic choice for
    single-container pods, which is the common case. Multi-container
    charts can still opt in via component-level scheduling and use the
    ``label_selector`` narrowing to emit one patch per container kind.

    For ``CronJob`` the path nests under ``spec.jobTemplate.spec.template``.
    """

    resources: ResourceRequirements
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    container_index: int = 0
    _path: str = field(init=False, default="/spec/template/spec/containers")
    _operation: str = field(init=False, default="replace")

    def _spec_path_str(self) -> str:
        if self.kind == "CronJob":
            return "/spec/jobTemplate/spec/template/spec"
        return "/spec/template/spec"

    def render_value(self) -> str:
        resources_dict: dict[str, Any] = {}
        if self.resources.requests is not None:
            requests = _resource_spec_to_k8s(self.resources.requests)
            if requests:
                resources_dict["requests"] = requests
        if self.resources.limits is not None:
            limits = _resource_spec_to_k8s(self.resources.limits)
            if limits:
                resources_dict["limits"] = limits

        patch_path = (
            f"{self._spec_path_str()}/containers/{self.container_index}/resources"
        )
        # Emit as a JSON-patch document (Kustomize accepts these alongside
        # strategic-merge patches in the same ``patches:`` list).
        ops = [{"op": "replace", "path": patch_path, "value": resources_dict}]
        return yaml.dump(ops, default_flow_style=False, sort_keys=False)


@dataclass
class TolerationsPatch(Patch):
    """Strategic-merge YAML patch injecting pod tolerations.

    Applies to ``spec.template.spec.tolerations``. For ``CronJob`` the path
    nests under ``spec.jobTemplate.spec.template.spec.tolerations``.
    Strategic merge on a scalar-keyed list replaces the list wholesale;
    because tolerations from all levels have already been merged upstream
    (FR-009 stable tuple union), emitting the merged list is the intended
    behaviour.
    """

    tolerations: list[Toleration]
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    _path: str = field(init=False, default="/spec/template/spec/tolerations")
    _operation: str = field(init=False, default="add")

    def _spec_path(self) -> tuple[str, ...]:
        return (
            _CRONJOB_TEMPLATE_SPEC_PATH
            if self.kind == "CronJob"
            else _POD_TEMPLATE_SPEC_PATH
        )

    def render_value(self) -> str:
        rendered = [_toleration_to_k8s(t) for t in self.tolerations]
        leaf = {"tolerations": rendered}
        spec_body = _nested_dict(self._spec_path(), leaf)

        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            **spec_body,
        }
        return yaml.dump(doc, default_flow_style=False, sort_keys=False)


@dataclass
class TopologySpreadPatch(Patch):
    """Strategic-merge YAML patch injecting ``topologySpreadConstraints``.

    Applies to ``spec.template.spec.topologySpreadConstraints``. CronJob
    nests under ``spec.jobTemplate.spec.template.spec``.
    """

    constraints: list[TopologySpreadConstraint]
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    _path: str = field(
        init=False, default="/spec/template/spec/topologySpreadConstraints"
    )
    _operation: str = field(init=False, default="add")

    def _spec_path(self) -> tuple[str, ...]:
        return (
            _CRONJOB_TEMPLATE_SPEC_PATH
            if self.kind == "CronJob"
            else _POD_TEMPLATE_SPEC_PATH
        )

    def render_value(self) -> str:
        rendered = [_topology_spread_to_k8s(c) for c in self.constraints]
        leaf = {"topologySpreadConstraints": rendered}
        spec_body = _nested_dict(self._spec_path(), leaf)

        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            **spec_body,
        }
        return yaml.dump(doc, default_flow_style=False, sort_keys=False)


@dataclass
class NodeAffinityPatch(Patch):
    """Strategic-merge YAML patch scoped to ``affinity.nodeAffinity`` only.

    Composes with :class:`AffinityPatch` (which scopes to ``podAffinity`` /
    ``podAntiAffinity``) so that both can be applied to the same resource
    without clobbering each other. CronJob uses
    ``spec.jobTemplate.spec.template.spec.affinity.nodeAffinity``.
    """

    node_affinity: AffinityBlock
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    _path: str = field(init=False, default="/spec/template/spec/affinity/nodeAffinity")
    _operation: str = field(init=False, default="add")

    def _spec_path(self) -> tuple[str, ...]:
        return (
            _CRONJOB_TEMPLATE_SPEC_PATH
            if self.kind == "CronJob"
            else _POD_TEMPLATE_SPEC_PATH
        )

    def render_value(self) -> str:
        node_affinity = _node_affinity_block_to_k8s(self.node_affinity)
        leaf = {"affinity": {"nodeAffinity": node_affinity}}
        spec_body = _nested_dict(self._spec_path(), leaf)

        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            **spec_body,
        }
        return yaml.dump(doc, default_flow_style=False, sort_keys=False)


@dataclass
class RuntimeClassPatch(Patch):
    """Strategic-merge YAML patch setting ``spec.template.spec.runtimeClassName``.

    CronJob nests under ``spec.jobTemplate.spec.template.spec``.
    """

    runtime_class_name: str
    api_version: str = "apps/v1"
    kind: str = "Deployment"
    name: str = "any"
    _path: str = field(init=False, default="/spec/template/spec/runtimeClassName")
    _operation: str = field(init=False, default="add")

    def _spec_path(self) -> tuple[str, ...]:
        return (
            _CRONJOB_TEMPLATE_SPEC_PATH
            if self.kind == "CronJob"
            else _POD_TEMPLATE_SPEC_PATH
        )

    def render_value(self) -> str:
        leaf = {"runtimeClassName": self.runtime_class_name}
        spec_body = _nested_dict(self._spec_path(), leaf)

        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            **spec_body,
        }
        return yaml.dump(doc, default_flow_style=False, sort_keys=False)


@dataclass
class ContainerMergePatch(Patch):
    """Strategic-merge YAML patch setting env, ``command`` and ``args`` on one named container.

    Containers merge by ``name`` and env entries by env ``name``, so chart
    entries the patch does not name survive. Every entry carries
    ``valueFrom: null`` so a same-name chart ``valueFrom`` is replaced by the
    literal ``value`` (017-post-render-env-vars research D-001). ``command``
    and ``args`` have no merge key, so a set list replaces the chart's list and
    an unset one (``None``) is left out, keeping the chart's value (022 research
    D-001). With nothing set the patch only names the container, which moves it
    to ``containers[0]`` for :class:`ComponentContainerPatch` (018 research D-001).

    Example:
        >>> patch = ContainerMergePatch(
        ...     container="app", env={"LOG_LEVEL": "debug"}, args=["--port", "8000"]
        ... )
        >>> print(patch.render_value())
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: any
        spec:
          template:
            spec:
              containers:
              - name: app
                env:
                - name: LOG_LEVEL
                  value: debug
                  valueFrom: null
                args:
                - --port
                - '8000'
        <BLANKLINE>
    """

    container: str
    env: dict[str, str] = field(default_factory=dict)
    command: list[str] | None = None
    args: list[str] | None = None
    kind: str = "Deployment"
    api_version: str = "apps/v1"
    name: str = "any"
    _path: str = field(init=False, default="/spec/template/spec/containers")
    _operation: str = field(init=False, default="add")

    def render_value(self) -> str:
        container: dict[str, Any] = {"name": self.container}
        if self.env:
            container["env"] = [
                {"name": key, "value": value, "valueFrom": None}
                for key, value in self.env.items()
            ]
        if self.command is not None:
            container["command"] = list(self.command)
        if self.args is not None:
            container["args"] = list(self.args)
        leaf = {"containers": [container]}
        doc: dict[str, Any] = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {"name": self.name},
            **_nested_dict(_POD_TEMPLATE_SPEC_PATH, leaf),
        }
        return yaml.dump(doc, default_flow_style=False, sort_keys=False)


def _escape_json_pointer(token: str) -> str:
    # RFC 6901: "~" first, so an escaped "/" is not escaped again.
    return token.replace("~", "~0").replace("/", "~1")


@dataclass
class ComponentContainerPatch(Patch):
    """JSON6902 patch guarding the component container and optionally setting its image.

    Applied after a :class:`ContainerMergePatch` naming the container, which moves it to
    ``containers[0]`` or, when the name is missing, adds an image-less container there. The ops
    move ``containers/0`` to a guard key naming the component and the container, remove its
    ``image`` (which fails the render when the container was added), set the override or restore
    the chart image, and move it back (018 contracts/post-render-patch.md).

    Example:
        >>> patch = ComponentContainerPatch(component="server", container="app", image="app:2")
        >>> print(patch.render_value())
        - op: move
          from: /spec/template/spec/containers/0
          path: /spec/template/spec/styrmin.io~1component-container~1server~1app
        - op: remove
          path: /spec/template/spec/styrmin.io~1component-container~1server~1app/image
        - op: add
          path: /spec/template/spec/styrmin.io~1component-container~1server~1app/image
          value: app:2
        - op: move
          from: /spec/template/spec/styrmin.io~1component-container~1server~1app
          path: /spec/template/spec/containers/0
        <BLANKLINE>
    """

    component: str
    container: str
    image: str | None = None
    kind: str = "Deployment"
    _path: str = field(init=False, default="/spec/template/spec/containers/0")
    _operation: str = field(init=False, default="move")

    @property
    def guard_path(self) -> str:
        """The temporary key the container is moved to; ``parse_guard_failure`` reads it back."""
        component = _escape_json_pointer(self.component)
        container = _escape_json_pointer(self.container)
        return f"/spec/template/spec/{GUARD_KEY_PREFIX}{component}~1{container}"

    def render_value(self) -> str:
        guard = self.guard_path
        image = f"{guard}/image"
        if self.image is not None:
            body: list[dict[str, Any]] = [
                {"op": "remove", "path": image},
                {"op": "add", "path": image, "value": self.image},
            ]
        else:
            saved = f"{guard}/styrmin-image"
            body = [
                {"op": "copy", "from": image, "path": saved},
                {"op": "remove", "path": image},
                {"op": "move", "from": saved, "path": image},
            ]
        ops = [
            {"op": "move", "from": self._path, "path": guard},
            *body,
            {"op": "move", "from": guard, "path": self._path},
        ]
        return yaml.dump(ops, default_flow_style=False, sort_keys=False)


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
