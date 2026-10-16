"""Shared Strawberry input types for deployment-configuration GraphQL surfaces.

The leaf input types and the generic conversion helpers in this module are
consumed by both :mod:`styrmin_backend.api.definitions.environment.inputs`
(``UpdateEnvironmentInput``) and
:mod:`styrmin_backend.api.definitions.deployment.inputs`
(``UpdateDeploymentInput``). Hand-rolled (not
``strawberry.experimental.pydantic.input``-derived) so we control GraphQL
field names and enum values explicitly without leaking unrelated Pydantic
internals into the schema.

See ``specs/009-environment-update/research.md`` §1 for the original design
discussion and ``specs/011-typed-deployment-input/data-model.md`` §1 for the
new top-level input that joined this module's consumer list.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import strawberry

from styrmin_backend.api.scalars import JSON

# ---------------------------------------------------------------------------
# Enum mirrors
#
# Pydantic-side these are ``Literal`` types, not ``Enum`` classes. We mirror
# the schema-level values exactly (case-sensitive — see ``EnvironmentConfig``
# / ``Toleration`` / ``TopologySpreadConstraint``); the conversion helper
# translates from the GraphQL enum's ``.value`` back to the Pydantic-expected
# string form.
# ---------------------------------------------------------------------------


@strawberry.enum
class ExternalUrlScheme(Enum):
    HTTP = "http"
    HTTPS = "https"


@strawberry.enum
class ExternalDnsEndpointsType(Enum):
    NODE_EXTERNAL_IP = "NodeExternalIP"
    CLUSTER_IP = "ClusterIP"


@strawberry.enum
class TolerationOperator(Enum):
    EXISTS = "Exists"
    EQUAL = "Equal"


@strawberry.enum
class TolerationEffect(Enum):
    NO_SCHEDULE = "NoSchedule"
    PREFER_NO_SCHEDULE = "PreferNoSchedule"
    NO_EXECUTE = "NoExecute"


@strawberry.enum
class WhenUnsatisfiable(Enum):
    DO_NOT_SCHEDULE = "DoNotSchedule"
    SCHEDULE_ANYWAY = "ScheduleAnyway"


@strawberry.enum
class LabelSelectorOperator(Enum):
    IN = "In"
    NOT_IN = "NotIn"
    EXISTS = "Exists"
    DOES_NOT_EXIST = "DoesNotExist"


# ---------------------------------------------------------------------------
# Leaf inputs (no nested inputs of their own)
# ---------------------------------------------------------------------------


@strawberry.input(description="A single environment variable name/value pair.")
class EnvVarInput:
    name: str
    value: str


@strawberry.input(description="One ``matchExpressions`` entry on a label selector.")
class LabelSelectorRequirementInput:
    key: str
    operator: LabelSelectorOperator
    values: list[str] | None = None


@strawberry.input(description="Kubernetes-style label selector.")
class LabelSelectorInput:
    match_labels: JSON | None = None
    match_expressions: list[LabelSelectorRequirementInput] | None = None


@strawberry.input(
    description=(
        "Reference to another deployment in the same environment. Styrmin stores "
        "the id of the named deployment; a name given here is replaced with that "
        "id when the config is written."
    )
)
class DeploymentReferenceInput:
    deployment_id: str | None = strawberry.field(
        default=None, description="Id of a deployment in the same environment."
    )
    deployment_name: str | None = strawberry.field(
        default=None,
        description=(
            "Name of a deployment in the same environment. Styrmin stores the id "
            "of that deployment instead of the name when the config is written."
        ),
    )
    components: list[str] | None = None


@strawberry.input(description="Single affinity term mirroring ``AffinityTerm``.")
class AffinityTermInput:
    topology_key: str = strawberry.field(
        description=(
            "Node label that defines the topology domain for pod affinity and "
            "pod anti-affinity. Node affinity ignores it, so pass an empty string."
        )
    )
    namespaces: list[str] | None = None
    namespace_selector: LabelSelectorInput | None = None
    label_selector: LabelSelectorInput | None = None
    deployment_ref: DeploymentReferenceInput | None = None
    match_label_keys: list[str] | None = None
    mismatch_label_keys: list[str] | None = None


@strawberry.input(description="Weighted affinity term for a ``preferred`` rule.")
class WeightedAffinityTermInput:
    weight: int
    term: AffinityTermInput


@strawberry.input(
    description="Affinity block (required + preferred) for one affinity kind."
)
class AffinityBlockInput:
    required: list[AffinityTermInput] | None = None
    preferred: list[WeightedAffinityTermInput] | None = None
    replace: bool | None = None


@strawberry.input(
    description="Pod-container resource ``requests`` or ``limits`` payload."
)
class ResourceSpecInput:
    cpu: str | None = None
    memory: str | None = None
    ephemeral_storage: str | None = None
    extended: JSON | None = None


@strawberry.input(
    description="Container resource requirements (``requests`` and ``limits``)."
)
class ResourceRequirementsInput:
    requests: ResourceSpecInput | None = None
    limits: ResourceSpecInput | None = None


@strawberry.input(description="Single pod toleration entry.")
class TolerationInput:
    key: str | None = None
    operator: TolerationOperator | None = None
    value: str | None = None
    effect: TolerationEffect | None = None
    toleration_seconds: int | None = None


@strawberry.input(description="One topology-spread constraint on the pod template.")
class TopologySpreadConstraintInput:
    max_skew: int
    topology_key: str
    when_unsatisfiable: WhenUnsatisfiable
    label_selector: LabelSelectorInput | None = None
    min_domains: int | None = None
    node_affinity_policy: str | None = None
    node_taints_policy: str | None = None
    match_label_keys: list[str] | None = None


@strawberry.input(
    description="Per-feature opt-out flags for the post-render injection."
)
class PostRenderInjectionInput:
    pod_affinity: bool | None = None
    node_affinity: bool | None = None
    topology_spread: bool | None = None
    resources: bool | None = None
    tolerations: bool | None = None
    runtime_class: bool | None = None


@strawberry.input(
    description="Hierarchical pod scheduling & resource configuration section."
)
class SchedulingInput:
    pod_affinity: AffinityBlockInput | None = None
    pod_anti_affinity: AffinityBlockInput | None = None
    node_affinity: AffinityBlockInput | None = strawberry.field(
        default=None,
        description=(
            "Places pods on nodes by node label. Each term's labelSelector "
            "matches node labels, and its topologyKey is ignored. A pod goes "
            "to a node that matches at least one required term, and preferred "
            "terms are weighted. A cluster's value is ignored."
        ),
    )
    topology_spread_constraints: list[TopologySpreadConstraintInput] | None = None
    resources: ResourceRequirementsInput | None = None
    tolerations: list[TolerationInput] | None = None
    runtime_class: str | None = None
    inject: PostRenderInjectionInput | None = None


@strawberry.input(
    description="Configuration for the dedicated ingress Kubernetes Service."
)
class IngressServiceConfigInput:
    type: str | None = None
    annotations: JSON | None = None
    load_balancer_ip: str | None = None
    external_traffic_policy: str | None = None
    ip_families: list[str] | None = None
    ip_family_policy: str | None = None
    node_port: int | None = None


@strawberry.input(
    description="Dedicated per-environment ingress controller configuration."
)
class DedicatedIngressInput:
    implementation: str | None = None
    type: str | None = None
    service: IngressServiceConfigInput | None = None


@strawberry.input(
    description=(
        "Standard storage configuration for the cluster, naming the "
        "Kubernetes ``StorageClass`` used as the default for deployments."
    )
)
class StandardStorageInput:
    storage_class: str = strawberry.field(
        description=(
            "The Kubernetes storage class name used as the standard storage "
            "option for this cluster."
        )
    )


@strawberry.input(
    description=(
        "Fast storage configuration for the cluster, naming the "
        "Kubernetes ``StorageClass`` used as the fast (typically NVMe / "
        "local SSD) storage option for deployments."
    )
)
class FastStorageInput:
    storage_class: str = strawberry.field(
        description=(
            "The Kubernetes storage class name used as the fast storage "
            "option for this cluster."
        )
    )


# ---------------------------------------------------------------------------
# Generic conversion helpers (consumed by both top-level *_to_dict converters)
# ---------------------------------------------------------------------------


_UNSET = strawberry.UNSET


def _is_unset_or_none(value: Any) -> bool:
    return value is _UNSET or value is None


def _convert_value(value: Any) -> Any:
    """Recursively convert Strawberry input objects (and their nested
    inputs / lists / enums) into a plain JSON-compatible dict structure
    suitable for ``EnvironmentConfig.model_validate(...)``.

    Rules:

    * ``None`` / ``strawberry.UNSET`` → preserved as ``None`` (callers
      decide whether to omit the key based on whether the field was set).
    * ``Enum`` → ``.value`` (the Pydantic-side string form).
    * Strawberry input dataclass → ``dict`` with ``None``-valued fields
      omitted (full-replacement semantics for nested objects).
    * ``list`` → list of converted values, preserving empty lists.
    * Everything else → identity.
    """
    if _is_unset_or_none(value):
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_convert_value(item) for item in value]
    # Strawberry input: detect via the presence of ``__strawberry_definition__``.
    definition = getattr(type(value), "__strawberry_definition__", None)
    if definition is not None:
        result: dict[str, Any] = {}
        for field in definition.fields:
            field_value = getattr(value, field.python_name, None)
            if _is_unset_or_none(field_value):
                continue
            result[field.python_name] = _convert_value(field_value)
        return result
    return value


__all__ = [
    "AffinityBlockInput",
    "AffinityTermInput",
    "DedicatedIngressInput",
    "DeploymentReferenceInput",
    "EnvVarInput",
    "ExternalDnsEndpointsType",
    "ExternalUrlScheme",
    "IngressServiceConfigInput",
    "LabelSelectorInput",
    "LabelSelectorOperator",
    "LabelSelectorRequirementInput",
    "PostRenderInjectionInput",
    "ResourceRequirementsInput",
    "ResourceSpecInput",
    "FastStorageInput",
    "SchedulingInput",
    "StandardStorageInput",
    "TolerationEffect",
    "TolerationInput",
    "TolerationOperator",
    "TopologySpreadConstraintInput",
    "WeightedAffinityTermInput",
    "WhenUnsatisfiable",
    "_convert_value",
    "_is_unset_or_none",
]
