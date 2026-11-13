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

from dataclasses import dataclass
from typing import Any

import strawberry

from styrmin_backend.api.definitions.config.inputs import (
    DedicatedIngressInput,
    EnvVarInput,
    ExternalDnsEndpointsType,
    ExternalUrlScheme,
    FastStorageInput,
    SchedulingInput,
    StandardStorageInput,
    _convert_value,
    _is_unset_or_none,
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
        "Per-component override block for a deployment: env vars, the "
        "container ``command``/``args``, the component container's "
        "``image``, and the component's ``replicas`` count."
    )
)
class ComponentConfigInput:
    name: str = strawberry.field(
        description=(
            "The component name as declared by the application-driver version "
            "the deployment is bound to after the write: the pinned one on "
            "updateDeployment, the target one on updateDeploymentVersion. "
            "Must match a known component: an unknown one raises the error "
            "of the override it carries, such as ``UNKNOWN_COMPONENT_ENV_VAR`` "
            "or ``UNKNOWN_COMPONENT_REPLICA_OVERRIDE``. "
            "Overrides on a component that declares no component container "
            "raise ``COMPONENT_CONTAINER_NOT_DECLARED`` (see ``envVars``)."
        )
    )
    env_vars: list[EnvVarInput] | None = strawberry.field(
        default=None,
        description=(
            "Environment-variable overrides scoped to this component. "
            "Submitted as a list of ``{name, value}`` rows; duplicates "
            "within the list raise ``DUPLICATE_ENV_VAR_NAME`` with the "
            "component scope in the payload. Adding or changing a value on "
            "a component that declares no component container raises "
            "``COMPONENT_CONTAINER_NOT_DECLARED``; removing values or "
            "re-submitting the stored ones unchanged is accepted."
        ),
    )
    command: list[str] | None = strawberry.field(
        default=None,
        description=(
            "Container entrypoint override for this component, scoped to this "
            "deployment, applied to the component container the driver "
            "declares. A non-empty list of strings; an empty list raises "
            "``INVALID_CONTAINER_COMMAND``. Under full-replacement semantics "
            "``null``/omitting it CLEARS the override (the chart/image default "
            "flows through) — clearing is never an empty list. Passed through "
            "verbatim — no templating. Adding or changing it on a component "
            "that declares no component container raises "
            "``COMPONENT_CONTAINER_NOT_DECLARED``; removing it or re-submitting "
            "the stored list unchanged is accepted."
        ),
    )
    args: list[str] | None = strawberry.field(
        default=None,
        description=(
            "Container args override for this component. Same shape and rules "
            "as ``command``, raising ``INVALID_CONTAINER_ARGS`` or "
            "``COMPONENT_CONTAINER_NOT_DECLARED``."
        ),
    )
    image: str | None = strawberry.field(
        default=None,
        description=(
            "Image reference for this component's component container, scoped "
            "to this deployment. A full reference with an explicit tag or "
            "digest; every ``{{ app.version }}`` token is replaced with the "
            "deployment's application version at render time, and a literal "
            "tag pins the image. Under full-replacement semantics "
            "``null``/omitting it CLEARS the override (the chart image "
            "applies). Raises ``UNKNOWN_COMPONENT_IMAGE_OVERRIDE``, "
            "``INVALID_IMAGE_REFERENCE``, or ``COMPONENT_CONTAINER_NOT_DECLARED`` "
            "(adding or changing it on a component without a component "
            "container; removing it is always accepted)."
        ),
    )
    replicas: int | None = strawberry.field(
        default=None,
        description=(
            "Replica count for this component, scoped to this deployment: an "
            "integer of 1 or more, applied to `spec.replicas` of every "
            "Deployment and StatefulSet that matches the component's label "
            "selector. Needs no component container. Under full-replacement "
            "semantics `null`/omitting it CLEARS the override, and the "
            "component returns to the driver default or to the chart's count. "
            "A value below 1 raises `INVALID_REPLICA_COUNT` (stop the component "
            "instead); a value above 1 on a singleton component raises "
            "`SINGLETON_REPLICA_OVERRIDE`; adding or changing it on a component "
            "the driver version does not declare raises "
            "`UNKNOWN_COMPONENT_REPLICA_OVERRIDE`; adding or changing it to a "
            "value above the server setting `STYRMIN_MAX_REPLICA_COUNT` raises "
            "`REPLICA_COUNT_ABOVE_MAXIMUM`."
        ),
    )


@strawberry.input(
    description=(
        "Per-service ingress override block for a deployment: the ingress "
        "class and the FQDN suffix of one service that the driver declares "
        "``scope: external``."
    )
)
class ServiceConfigInput:
    name: str = strawberry.field(
        description=(
            "The driver service name. It must be declared by the driver "
            "version the deployment is bound to after the write, with scope "
            "``external`` and kind ``http`` or ``https``. A service the version "
            "does not declare raises ``UNKNOWN_SERVICE_INGRESS_OVERRIDE``, and a "
            "service with scope ``internal``, or with kind ``tcp`` or ``udp``, "
            "raises ``SERVICE_INGRESS_NOT_BUILT``, because Styrmin does not build "
            "its Ingress."
        )
    )
    ingress_class: str | None = strawberry.field(
        default=None,
        description=(
            "Ingress class for this service only. Null or omitted: the "
            "resolved class applies."
        ),
    )
    fqdn_suffix: str | None = strawberry.field(
        default=None,
        description=(
            "FQDN suffix for this service only, used in its readable host. "
            "Null or omitted: the resolved suffix applies."
        ),
    )


# ---------------------------------------------------------------------------
# Shared deployment-config input
#
# Carries every field of the source-of-truth ``DeploymentConfig`` Pydantic
# model. Consumed by BOTH the ``deploy`` (create) mutation and — via
# inheritance — ``UpdateDeploymentInput``, so the two mutations cannot drift
# on the config shape (the original create/update format mismatch this design
# closes: create previously took a freeform ``JSON`` config, update took a
# typed list-based input). ``components`` / ``env_vars`` keep the
# ``[{name, value}]`` list shape so duplicate-name detection
# (``DUPLICATE_ENV_VAR_NAME`` / ``DUPLICATE_COMPONENT_NAME``) stays reachable.
# ---------------------------------------------------------------------------


@strawberry.input(
    description=(
        "Typed deployment-configuration payload shared by the ``deploy`` "
        "(create) and ``updateDeployment`` mutations. Mirrors the "
        "source-of-truth ``DeploymentConfig`` Pydantic model field-for-field "
        "so both mutations accept an identical config shape."
    )
)
class DeploymentConfigInput:
    components: list[ComponentConfigInput] | None = strawberry.field(
        default=None,
        description=(
            "Full-replacement list of per-component override blocks. "
            "Flattened by the resolver to a dict keyed on ``name``; "
            "duplicate names raise ``DUPLICATE_COMPONENT_NAME``. An "
            "empty list explicitly clears every per-component block."
        ),
    )
    services: list[ServiceConfigInput] | None = strawberry.field(
        default=None,
        description=(
            "Full-replacement list of per-service ingress override blocks. "
            "Flattened by the resolver to a dict keyed on ``name``; duplicate "
            "names raise ``DUPLICATE_SERVICE_NAME``. A service that is not in "
            "the list has no override after the write, and an empty list "
            "explicitly clears every override. A row with both ``ingressClass`` "
            "and ``fqdnSuffix`` null is the same as no override. When the write "
            "changes the driver version, a stored override on a service that the "
            "target version removes or declares ``internal`` raises "
            "``SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED`` before any pod "
            "changes, unless the same write clears it."
        ),
    )
    env_vars: list[EnvVarInput] | None = strawberry.field(
        default=None,
        description=(
            "Deployment-scoped environment variables. "
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
    backup_ttl: str | None = strawberry.field(
        default=None,
        description=(
            "Retention applied to backups taken for this deployment, as a "
            "strictly positive Go duration in ``h``/``m``/``s`` units "
            '(e.g. ``"720h"``). Overrides the environment- and cluster-scope '
            "policy (deepest scope wins). Omitted means this deployment sets "
            "no policy and inherits the shallower scope, ultimately the "
            "built-in 720h default."
        ),
    )
    runtime_class: str | None = strawberry.field(
        default=None,
        description=(
            "Kubernetes RuntimeClass name applied to pods in this deployment."
        ),
    )
    standard_storage: StandardStorageInput | None = strawberry.field(
        default=None,
        description=(
            "Standard storage configuration (default Kubernetes "
            "``StorageClass``) used by this deployment."
        ),
    )
    fast_storage: FastStorageInput | None = strawberry.field(
        default=None,
        description=(
            "Fast storage configuration (Kubernetes ``StorageClass`` for "
            "the fast / NVMe tier) used by this deployment."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level input for updateDeployment
# ---------------------------------------------------------------------------


@strawberry.input(
    description=(
        "Full-replacement input for the ``updateDeployment`` mutation. "
        "Inherits every config field from ``DeploymentConfigInput`` (shared "
        "with the ``deploy`` create mutation) and adds the update-only "
        "``name`` / ``parameters`` / ``serviceNameOverrides`` fields. "
        "Top-level fields use full-replacement semantics: an omitted "
        '(``null``) field means "do not touch the corresponding persisted '
        'state"; an empty list/dict means "explicitly clear". The '
        "single exception is ``parameters``, which uses merge semantics "
        "for backwards compatibility — entries in the input merge on top "
        "of the persisted parameters dict (existing keys not named in the "
        "input survive)."
    )
)
class UpdateDeploymentInput(DeploymentConfigInput):
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
    * ``components`` — list of
      ``{name, env_vars?, command?, args?, image?, replicas?}``
      → ``dict[str, dict]`` with duplicate-name detection raising
      :class:`DuplicateComponentNameError`. Each component's
      ``env_vars`` sub-list is flattened recursively with scope
      ``f"component:{name}"``; ``command``/``args``/``image``/``replicas``
      pass through verbatim.
    * ``services`` — list of ``{name, ingress_class?, fqdn_suffix?}`` →
      ``dict[str, dict]`` keyed on ``name`` with duplicate-name detection
      raising :class:`DuplicateServiceNameError` (#598).
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
        elif key == "services":
            if value is None:
                continue
            result["services"] = _flatten_services(value)
        elif key == "service_name_overrides":
            if value is None:
                continue
            result["service_name_overrides"] = {
                row["driver_service_name"]: row["override_name"] for row in value
            }
        else:
            result[key] = value
    return result


@dataclass(frozen=True)
class DeploymentUpdate:
    """The fields of an :class:`UpdateDeploymentInput` as the deployment services take them."""

    config: dict[str, Any] | None = None
    name: str | None = None
    parameters: dict[str, Any] | None = None
    service_name_overrides: dict[str, str] | None = None


def split_update_deployment_input(
    input: UpdateDeploymentInput | None,
) -> DeploymentUpdate:
    """Split an :class:`UpdateDeploymentInput` into config, name, parameters and overrides.

    ``config`` is ``None`` when no config field is set, so the service does not read an
    empty dict as "clear the stored config".
    """
    if input is None:
        return DeploymentUpdate()
    payload = update_deployment_input_to_dict(input)
    name = payload.pop("name", None)
    parameters = payload.pop("parameters", None)
    service_name_overrides = payload.pop("service_name_overrides", None)
    return DeploymentUpdate(
        config=payload or None,
        name=name,
        parameters=parameters,
        service_name_overrides=service_name_overrides,
    )


def deployment_config_input_to_dict(input: DeploymentConfigInput) -> dict[str, Any]:
    """Convert a :class:`DeploymentConfigInput` into a plain config dict.

    The create (``deploy``) counterpart of
    :func:`update_deployment_input_to_dict`: it flattens the two list-shaped
    config fields (``env_vars`` / ``components`` / ``services``) into the maps the service
    layer and the source-of-truth ``DeploymentConfig`` Pydantic model expect,
    and passes every other field through :func:`_convert_value` unchanged.

    ``None`` / :data:`strawberry.UNSET` fields are omitted so an unset config
    field never reaches the service as an explicit ``null``. Duplicate names
    inside ``env_vars`` / a component's ``env_vars`` raise
    :class:`DuplicateEnvVarNameError`; duplicate component names raise
    :class:`DuplicateComponentNameError` — the same typed codes the update
    path emits.
    """
    result: dict[str, Any] = {}
    converted = _convert_value(input)
    if not isinstance(converted, dict):
        return result
    for key, value in converted.items():
        if value is None:
            continue
        if key == "env_vars":
            result["env_vars"] = _flatten_env_vars(value, scope="deployment")
        elif key == "components":
            result["components"] = _flatten_components(value)
        elif key == "services":
            result["services"] = _flatten_services(value)
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


def parameter_inputs_to_dict(
    parameters: list[ParameterValueInput] | None,
) -> dict[str, Any] | None:
    """Flatten a ``[ParameterValueInput!]`` list into a ``{name: value}`` map.

    Shared by the ``deploy`` (create) and ``updateDeployment`` resolvers so
    both accept the identical typed parameter shape. Returns ``None`` when
    ``parameters`` is ``None`` / unset (the resolver omits parameters in that
    case); duplicate names raise :class:`DuplicateParameterNameError`.
    """
    if _is_unset_or_none(parameters):
        return None
    rows = _convert_value(parameters)
    if not isinstance(rows, list):
        return None
    return _flatten_parameters(rows)


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
    component; the other slots (``command``, ``args``, ``image``,
    ``replicas``) pass through, and unset ones are already dropped by
    ``_convert_value``.
    Duplicate component names raise :class:`DuplicateComponentNameError`
    (FR-009).
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


def _flatten_services(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Flatten a list of service-config rows into ``dict[str, dict]`` keyed on ``name``.

    Unset fields are already dropped by ``_convert_value``. Duplicate service names
    raise :class:`DuplicateServiceNameError`. A row with no field set is not stored: it
    is the same as no override (data-model.md).
    """
    from styrmin_backend.services.service_ingress.exceptions import (
        DuplicateServiceNameError,
    )

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row["name"]
        if name in out:
            raise DuplicateServiceNameError(name=name)
        block = {key: value for key, value in row.items() if key != "name"}
        if block:
            out[name] = block
    return out


__all__ = [
    "ComponentConfigInput",
    "DeploymentConfigInput",
    "DeploymentUpdate",
    "ParameterValueInput",
    "ServiceConfigInput",
    "UpdateDeploymentInput",
    "deployment_config_input_to_dict",
    "parameter_inputs_to_dict",
    "split_update_deployment_input",
    "update_deployment_input_to_dict",
]
