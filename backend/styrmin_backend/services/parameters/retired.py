"""The rule for parameters a target driver version no longer declares (023 FR-010, research D-007).

On a driver version change, a parameter the current version declares and the target version
does not is a retired parameter. Its value is dropped when it equals the current version's
default, which is the value the chart rendered when the user never changed it; any other value
raises :class:`RetiredParameterValueError` so a changed setting is never lost silently.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from styrmin_backend.services.driver.models.resources.parameters import (
    DriverParameterDefinition,
)
from styrmin_backend.services.parameters.exceptions import RetiredParameterValueError


def drop_retired_parameters(
    values: dict,
    *,
    current_definitions: list[DriverParameterDefinition],
    target_definitions: list[DriverParameterDefinition],
    checked_against: str,
) -> dict:
    """Return ``values`` without the retired parameters that hold their current default.

    Keys that neither version declares are kept, so ``validate_parameter_values`` still rejects
    them as unknown parameters. ``values`` is not modified.

    Args:
        values: The merged parameter map of the version change.
        current_definitions: The parameters of the driver version the deployment is bound to.
        target_definitions: The parameters of the target driver version.
        checked_against: The target driver version label, for the error.

    Raises:
        RetiredParameterValueError: A retired parameter holds a value that is not its current
            default (same type and value); the first such parameter by name is reported.
    """
    target_names = {definition.name for definition in target_definitions}
    retired = {
        definition.name: definition
        for definition in current_definitions
        if definition.name not in target_names
    }
    for name in sorted(values.keys() & retired.keys()):
        default = retired[name].default
        if not _equals_default(values[name], default):
            raise RetiredParameterValueError(
                parameter_name=name,
                value=values[name],
                default=default,
                checked_against=checked_against,
            )
        logger.info(
            "Dropping retired parameter {} at its default {!r}: {} does not declare it",
            name,
            default,
            checked_against,
        )
    return {name: value for name, value in values.items() if name not in retired}


def _equals_default(value: Any, default: Any) -> bool:
    # Strict: ``True``, ``1.0`` and ``"1"`` do not match an integer default of 1.
    return type(value) is type(default) and value == default
