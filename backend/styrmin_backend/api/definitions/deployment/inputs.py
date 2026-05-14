"""Strawberry input types for the ``updateDeployment`` mutation (011).

Hand-rolled input types mirror the source-of-truth Pydantic models in
:mod:`styrmin_backend.context.models.config`: ``DeploymentConfig`` (which
inherits ``EnvironmentConfig`` + ``ClusterConfig`` + ``BaseConfigSection``),
plus the four deployment-only mutation fields ``name`` / ``parameters`` /
``serviceNameOverrides`` / ``components``.

The leaf input types (``EnvVarInput``, ``SchedulingInput``,
``DedicatedIngressInput``, ``StandardStorageInput``, etc.) are imported
from :mod:`styrmin_backend.api.definitions.config.inputs` so they are
shared with ``UpdateEnvironmentInput`` without duplication (FR-002).

The :func:`update_deployment_input_to_dict` helper converts an
:class:`UpdateDeploymentInput` into a plain ``dict`` suitable for the
existing ``update_deployment`` service function. ``None``-valued fields
are **omitted** from the output dict (full-replacement semantics: an
omitted field means "do not touch the corresponding persisted state");
empty lists / dicts are preserved as explicit clears. The four list-shape
fields (``env_vars``, ``parameters``, ``components``,
``service_name_overrides``) are flattened to the dict shapes the service
layer expects, with typed duplicate-name detection.
"""

from __future__ import annotations

from typing import Any

import strawberry

from styrmin_backend.api.definitions.config.inputs import (
    DedicatedIngressInput,
    EnvVarInput,
    ExternalDnsEndpointsType,
    ExternalUrlScheme,
    SchedulingInput,
    StandardStorageInput,
    _convert_value,
)
from styrmin_backend.api.definitions.service.model import ServiceNameOverride
from styrmin_backend.api.scalars import JSON

# ---------------------------------------------------------------------------
# Leaf inputs new to this module
# ---------------------------------------------------------------------------


@strawberry.input(
    description=(
        "A single driver-defined parameter assignment. Parameter shapes "
        "are dynamic per driver version, so ``value`` remains JSON-typed."
    )
)
class ParameterValueInput:
    name: str = strawberry.field(
        description="The name of the parameter as declared by the driver."
    )
    value: JSON = strawberry.field(
        description=(
            "The JSON-typed value to assign to the parameter. The driver's "
            "parameter definition determines the accepted value shape "
            "(string, integer, boolean, or enum) at validation time."
        )
    )


@strawberry.input(
    description=(
        "Per-component override block for a deployment. Carries env-var "
        "overrides today; future per-component knobs (e.g. replicas) slot "
        "into this same input without a schema renumber."
    )
)
class ComponentConfigInput:
    name: str = strawberry.field(
        description=(
            "The component name as declared by the deployment's currently "
            "pinned application-driver version. Must match a known "
            "component or the mutation raises ``UNKNOWN_COMPONENT_ENV_VAR``."
        )
    )
    env_vars: list[EnvVarInput] | None = strawberry.field(
        default=None,
        description=(
            "Environment-variable overrides scoped to this component. "
            "Submitted as a list of ``{name, value}`` rows; duplicates "
            "within the list raise ``DUPLICATE_ENV_VAR_NAME`` with the "
            "component scope in the payload."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level input
# ---------------------------------------------------------------------------


@strawberry.input(
    description=(
        "Full-replacement input for the ``updateDeployment`` mutation. "
        "Top-level fields use full-replacement semantics: an omitted "
        '(``null``) field means "do not touch the corresponding persisted '
        'state"; an empty list/dict means "explicitly clear". The '
        "single exception is ``parameters``, which uses merge semantics "
        "for backwards compatibility — entries in the input merge on top "
        "of the persisted parameters dict (existing keys not named in the "
        "input survive)."
    )
)
class UpdateDeploymentInput:
    name: str | None = strawberry.field(
        default=None,
        description=('New name for the deployment. Omitted means "do not rename".'),
    )
    parameters: list[ParameterValueInput] | None = strawberry.field(
        default=None,
        description=(
            "Driver-defined parameter assignments. **Merge semantics** "
            "(asymmetric with the rest of this input): entries in the "
            "list merge on top of the persisted parameters dict, so "
            "existing keys not named in the input survive. Duplicate "
            "``name`` entries within the list raise "
            "``DUPLICATE_PARAMETER_NAME``."
        ),
    )
    service_name_overrides: list[ServiceNameOverride] | None = strawberry.field(
        default=None,
        description=(
            "Full-replacement list of service-name overrides applied at "
            "deploy time. Each entry maps a driver-declared service name "
            "to the operator-chosen override name."
        ),
    )
    components: list[ComponentConfigInput] | None = strawberry.field(
        default=None,
        description=(
            "Full-replacement list of per-component override blocks. "
            "Flattened by the resolver to a dict keyed on ``name``; "
            "duplicate names raise ``DUPLICATE_COMPONENT_NAME``. An "
            "empty list explicitly clears every per-component block."
        ),
    )
    env_vars: list[EnvVarInput] | None = strawberry.field(
        default=None,
        description=(
            "Deployment-scoped environment-variable overrides. "
            "Submitted as a list of ``{name, value}`` rows; duplicates "
            'raise ``DUPLICATE_ENV_VAR_NAME`` with the ``"deployment"`` '
            "scope in the payload."
        ),
    )
    ip_whitelist: list[str] | None = strawberry.field(
        default=None,
        description=(
            "CIDR allowlist applied at the ingress layer. An empty list "
            "explicitly clears the persisted allowlist."
        ),
    )
    dedicated_ingress: DedicatedIngressInput | None = strawberry.field(
        default=None,
        description=(
            "Dedicated per-environment ingress controller configuration "
            "for this deployment."
        ),
    )
    scheduling: SchedulingInput | None = strawberry.field(
        default=None,
        description=(
            "Hierarchical pod scheduling & resource configuration "
            "(affinities, tolerations, topology spread, resource "
            "requests/limits, runtime class, post-render injection "
            "opt-outs)."
        ),
    )
    fqdn_suffix: str | None = strawberry.field(
        default=None,
        description=(
            "Suffix appended to the auto-derived FQDN for every service "
            "in this deployment."
        ),
    )
    external_url_scheme: ExternalUrlScheme | None = strawberry.field(
        default=None,
        description=(
            "URL scheme (``http`` or ``https``) used when constructing "
            "external URLs for services in this deployment."
        ),
    )
    external_url_port: int | None = strawberry.field(
        default=None,
        description=(
            "Port used when constructing external URLs for services in "
            "this deployment. Pydantic enforces ``1 <= port <= 65535`` "
            "at validation time."
        ),
    )
    external_dns_endpoints_type: ExternalDnsEndpointsType | None = strawberry.field(
        default=None,
        description=(
            "Endpoint source type used by external-DNS when publishing "
            "records for services in this deployment."
        ),
    )
    ingress_class: str | None = strawberry.field(
        default=None,
        description=("Name of the IngressClass used by services in this deployment."),
    )
    db_size: str | None = strawberry.field(
        default=None,
        description=(
            "Default database size hint applied to managed-database "
            "components in this deployment."
        ),
    )
    runtime_class: str | None = strawberry.field(
        default=None,
        description=(
            "Kubernetes RuntimeClass name applied to pods in this deployment."
        ),
    )
    node_selector: str | None = strawberry.field(
        default=None,
        description=("Node-selector expression applied to pods in this deployment."),
    )
    standard_storage: StandardStorageInput | None = strawberry.field(
        default=None,
        description=(
            "Standard storage configuration (default Kubernetes "
            "``StorageClass``) used by this deployment."
        ),
    )


# ---------------------------------------------------------------------------
# Conversion to dict (consumed by update_deployment service function)
# ---------------------------------------------------------------------------


def update_deployment_input_to_dict(input: UpdateDeploymentInput) -> dict[str, Any]:
    """Convert an :class:`UpdateDeploymentInput` into a plain dict.

    Mirrors :func:`update_environment_input_to_dict` (full-replacement
    semantics: ``None`` / :data:`strawberry.UNSET` top-level fields are
    omitted) with four list-flatten branches:

    * ``env_vars`` — list of ``{name, value}`` → ``dict[str, str]``
      with duplicate-name detection raising
      :class:`DuplicateEnvVarNameError` (scope ``"deployment"``).
    * ``parameters`` — list of ``{name, value}`` → ``dict[str, Any]``
      with duplicate-name detection raising
      :class:`DuplicateParameterNameError`.
    * ``components`` — list of ``{name, env_vars?}`` →
      ``dict[str, dict]`` with duplicate-name detection raising
      :class:`DuplicateComponentNameError`. Each component's
      ``env_vars`` sub-list is flattened recursively with scope
      ``f"component:{name}"``.
    * ``service_name_overrides`` — list of
      ``{driver_service_name, override_name}`` →
      ``dict[str, str]`` keyed on ``driver_service_name``.

    All other fields pass through the generic
    :func:`_convert_value` conversion unchanged.

    The output dict is the input contract for the ``update_deployment``
    service function: the resolver then splits it into the legacy
    ``deployment_name`` / ``deployment_parameters`` /
    ``service_name_overrides`` / ``deployment_config`` arguments.
    """
    result: dict[str, Any] = {}
    converted = _convert_value(input)
    if not isinstance(converted, dict):
        return result
    for key, value in converted.items():
        if key == "env_vars":
            if value is None:
                continue
            result["env_vars"] = _flatten_env_vars(value, scope="deployment")
        elif key == "parameters":
            if value is None:
                continue
            result["parameters"] = _flatten_parameters(value)
        elif key == "components":
            if value is None:
                continue
            result["components"] = _flatten_components(value)
        elif key == "service_name_overrides":
            if value is None:
                continue
            result["service_name_overrides"] = {
                row["driver_service_name"]: row["override_name"] for row in value
            }
        else:
            result[key] = value
    return result


def _flatten_env_vars(rows: list[dict[str, Any]], scope: str) -> dict[str, str]:
    """Flatten a list of ``{name, value}`` rows into ``dict[str, str]``.

    Duplicate names raise :class:`DuplicateEnvVarNameError` with the
    given ``scope`` so the typed error code reaches the GraphQL
    boundary intact (FR-008).
    """
    from styrmin_backend.services.env_vars.exceptions import DuplicateEnvVarNameError

    flattened: dict[str, str] = {}
    for entry in rows:
        name = entry.get("name")
        entry_value = entry.get("value")
        if name in flattened:
            raise DuplicateEnvVarNameError(scope=scope, name=name)
        flattened[name] = entry_value
    return flattened


def _flatten_parameters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten a list of ``{name, value}`` rows into ``dict[str, Any]``.

    Duplicate names raise :class:`DuplicateParameterNameError` (FR-009).
    """
    from styrmin_backend.services.parameters.exceptions import (
        DuplicateParameterNameError,
    )

    flattened: dict[str, Any] = {}
    for entry in rows:
        name = entry.get("name")
        if name in flattened:
            raise DuplicateParameterNameError(name=name)
        flattened[name] = entry.get("value")
    return flattened


def _flatten_components(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Flatten a list of component-config rows into ``dict[str, dict]``.

    The per-component ``env_vars`` sub-list is flattened recursively
    with scope ``f"component:{name}"`` so the eventual
    ``DUPLICATE_ENV_VAR_NAME`` payload identifies the offending
    component. Duplicate component names raise
    :class:`DuplicateComponentNameError` (FR-009).
    """
    from styrmin_backend.services.env_vars.exceptions import (
        DuplicateComponentNameError,
    )

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row["name"]
        if name in out:
            raise DuplicateComponentNameError(name=name)
        block: dict[str, Any] = {k: v for k, v in row.items() if k != "name"}
        if "env_vars" in block and block["env_vars"] is not None:
            block["env_vars"] = _flatten_env_vars(
                block["env_vars"], scope=f"component:{name}"
            )
        out[name] = block
    return out


__all__ = [
    "ComponentConfigInput",
    "ParameterValueInput",
    "UpdateDeploymentInput",
    "update_deployment_input_to_dict",
]
