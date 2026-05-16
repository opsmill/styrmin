"""Provides parameter validation and resolution for deployments.

Validates user-provided parameter values against driver parameter definitions
and applies default values for omitted optional parameters.
"""

from styrmin_backend.services.driver.models.resources.parameters import (
    DriverParameterDefinition,
    DriverParameterKind,
)
from styrmin_backend.services.exceptions import ServiceError

# Expected Python types for each parameter kind
_KIND_TYPES: dict[DriverParameterKind, type] = {
    DriverParameterKind.STRING: str,
    DriverParameterKind.INTEGER: int,
    DriverParameterKind.BOOLEAN: bool,
    DriverParameterKind.ENUM: str,
}


def parse_parameter_definitions(
    raw: list[dict] | None,
) -> list[DriverParameterDefinition]:
    """Parse raw JSON dicts from the database into validated parameter definitions."""
    if not raw:
        return []
    return [DriverParameterDefinition.model_validate(d) for d in raw]


def validate_parameter_values(
    definitions: list[DriverParameterDefinition],
    values: dict | None,
) -> dict:
    """Validate parameter values against driver parameter definitions.

    Args:
        definitions: List of validated parameter definitions.
        values: User-provided parameter values dict, or None.

    Returns:
        Resolved parameter values dict with defaults applied.

    Raises:
        ServiceError: If validation fails (type mismatch, unknown param, missing required, etc.).
    """
    if values is None:
        values = {}

    if not definitions:
        if values:
            unknown = sorted(values.keys())
            raise ServiceError(
                f"Unknown parameter(s): {', '.join(repr(k) for k in unknown)}. "
                "This driver does not define any parameters."
            )
        return {}

    errors: list[str] = []
    definitions_by_name = {d.name: d for d in definitions}

    # Check for unknown parameters
    for param_name in values:
        if param_name not in definitions_by_name:
            errors.append(f"Unknown parameter: '{param_name}'")

    if errors:
        raise ServiceError("; ".join(errors))

    # Validate provided values and apply defaults
    resolved: dict = {}
    for defn in definitions:
        if defn.name in values:
            value = values[defn.name]
            error = _validate_value_type(defn, value)
            if error:
                errors.append(error)
            else:
                resolved[defn.name] = value
        elif defn.default is not None:
            resolved[defn.name] = defn.default
        else:
            errors.append(f"Missing required parameter: '{defn.name}'")

    if errors:
        raise ServiceError("; ".join(errors))

    return resolved


def _validate_value_type(
    defn: DriverParameterDefinition,
    value: object,
) -> str | None:
    """Validate a single parameter value against its definition.

    Returns an error message string, or None if valid.
    """
    expected_type = _KIND_TYPES[defn.kind]

    # bool is a subclass of int in Python — reject bools for integer kind
    if defn.kind == DriverParameterKind.INTEGER and isinstance(value, bool):
        return f"Parameter '{defn.name}': expected integer, got bool"

    if not isinstance(value, expected_type):
        return (
            f"Parameter '{defn.name}': expected {defn.kind.value}, "
            f"got {type(value).__name__}"
        )

    if defn.kind == DriverParameterKind.ENUM and defn.values:
        if value not in defn.values:
            return (
                f"Parameter '{defn.name}': value '{value}' is not in "
                f"allowed values {defn.values}"
            )

    return None
