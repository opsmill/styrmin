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

The leaf input types and the generic recursive converter live in
:mod:`styrmin_backend.api.definitions.config.inputs` so they can be reused
by ``UpdateDeploymentInput`` without duplication; this module re-exports
them so existing import sites (``from
styrmin_backend.api.definitions.environment.inputs import EnvVarInput`` etc.)
keep working.
"""

from __future__ import annotations

from typing import Any

import strawberry

from styrmin_backend.api.definitions.config.inputs import (
    AffinityBlockInput,
    AffinityTermInput,
    DedicatedIngressInput,
    DeploymentReferenceInput,
    EnvVarInput,
    ExternalDnsEndpointsType,
    ExternalUrlScheme,
    IngressServiceConfigInput,
    LabelSelectorInput,
    LabelSelectorOperator,
    LabelSelectorRequirementInput,
    PostRenderInjectionInput,
    ResourceRequirementsInput,
    ResourceSpecInput,
    SchedulingInput,
    TolerationEffect,
    TolerationInput,
    TolerationOperator,
    TopologySpreadConstraintInput,
    WeightedAffinityTermInput,
    WhenUnsatisfiable,
    _convert_value,
)

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
    ingress_class: str | None = None
    db_size: str | None = None


# ---------------------------------------------------------------------------
# Conversion to dict (consumed by EnvironmentConfig.model_validate)
# ---------------------------------------------------------------------------


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
