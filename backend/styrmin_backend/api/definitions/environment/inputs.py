"""Strawberry input types for the ``updateEnvironment`` mutation (009).

Hand-rolled input types mirror the source-of-truth Pydantic models in
:mod:`styrmin_backend.context.models.config`. Per
``specs/009-environment-update/research.md`` §1, we explicitly do NOT use
``strawberry.experimental.pydantic.input`` — keeping the GraphQL surface
hand-rolled lets us control GraphQL field names and enum values without
leaking unrelated Pydantic internals into the schema.

The :func:`update_environment_input_to_dict` helper converts a
:class:`UpdateEnvironmentInput` into a plain ``dict`` suitable for
``EnvironmentConfig.model_validate(...)``. ``None``-valued fields are
**omitted** from the output dict (full-replacement semantics: an omitted
field means "unset on the persisted row"); empty lists / dicts are kept
intact so operators can explicitly clear a list-valued field.
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
    description="Reference to another deployment in the same environment."
)
class DeploymentReferenceInput:
    deployment_id: str | None = None
    deployment_name: str | None = None
    components: list[str] | None = None


@strawberry.input(description="Single affinity term mirroring ``AffinityTerm``.")
class AffinityTermInput:
    topology_key: str
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
    env_vars: bool | None = None


@strawberry.input(
    description="Hierarchical pod scheduling & resource configuration section."
)
class SchedulingInput:
    pod_affinity: AffinityBlockInput | None = None
    pod_anti_affinity: AffinityBlockInput | None = None
    node_affinity: AffinityBlockInput | None = None
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


# ---------------------------------------------------------------------------
# Top-level input
# ---------------------------------------------------------------------------


@strawberry.input(
    description=(
        "Full-replacement input for environment configuration updates. "
        "Submit the complete desired configuration; any field omitted "
        "(``null``) is persisted as its unset state on the underlying "
        "EnvironmentConfig."
    )
)
class UpdateEnvironmentInput:
    env_vars: list[EnvVarInput] | None = None
    ip_whitelist: list[str] | None = None
    dedicated_ingress: DedicatedIngressInput | None = None
    scheduling: SchedulingInput | None = None
    fqdn_suffix: str | None = None
    external_url_scheme: ExternalUrlScheme | None = None
    external_url_port: int | None = None
    external_dns_endpoints_type: ExternalDnsEndpointsType | None = None


# ---------------------------------------------------------------------------
# Conversion to dict (consumed by EnvironmentConfig.model_validate)
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


def update_environment_input_to_dict(input: UpdateEnvironmentInput) -> dict[str, Any]:
    """Convert an :class:`UpdateEnvironmentInput` into a plain dict.

    Field semantics:

    * Top-level field ``None`` (or :data:`strawberry.UNSET`) → key omitted
      from the output dict (full-replacement: the persisted row will not
      carry the field).
    * Empty list / empty dict → preserved (operator explicitly cleared a
      list-valued field).
    * ``env_vars`` is special: the GraphQL input is a list of
      ``EnvVarInput`` rows but the persisted Pydantic model expects a
      ``dict[str, str]``. We flatten here so duplicate-name detection
      lands on the dedicated typed error rather than collapsing silently.

    The output dict is the input contract for ``EnvironmentConfig``'s
    Pydantic validators (``_validate_env_vars`` etc.) and downstream
    storage on ``Environment.config``.
    """
    result: dict[str, Any] = {}
    converted = _convert_value(input)
    if not isinstance(converted, dict):
        return result
    for key, value in converted.items():
        if key == "env_vars":
            # ``env_vars`` lands as a list of {name, value} dicts after the
            # generic conversion; flatten to the {name: value} dict shape
            # the Pydantic validator expects. Duplicate names are detected
            # below and raised as ``DuplicateEnvVarNameError`` so the typed
            # error code reaches the GraphQL boundary intact.
            if value is None:
                continue
            flattened: dict[str, str] = {}
            for entry in value:
                name = entry.get("name")
                entry_value = entry.get("value")
                if name in flattened:
                    from styrmin_backend.services.env_vars.exceptions import (
                        DuplicateEnvVarNameError,
                    )

                    raise DuplicateEnvVarNameError(scope="environment", name=name)
                flattened[name] = entry_value
            result["env_vars"] = flattened
        else:
            result[key] = value
    return result


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
    "SchedulingInput",
    "TolerationEffect",
    "TolerationInput",
    "TolerationOperator",
    "TopologySpreadConstraintInput",
    "UpdateEnvironmentInput",
    "WeightedAffinityTermInput",
    "WhenUnsatisfiable",
    "update_environment_input_to_dict",
]
