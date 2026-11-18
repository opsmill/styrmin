"""Errors of the driver format code.

``ServiceError`` is the base of every Styrmin service error. It lives here so that the
errors raised by the driver format code, which the server, the agent and styrmin-driver
share, keep the base that the server's GraphQL error extension recognises (ADR-0089).
The backend imports these names from ``styrmin_backend.services.exceptions``,
``styrmin_backend.services.driver.exceptions`` and
``styrmin_backend.agent.service.kubernetes.resources.builders.exceptions``.
"""

from __future__ import annotations

from typing import Any, Literal


class ServiceError(Exception):
    """Base class for exceptions in this module."""

    error_code: str = "OPERATION_FAILED"
    default_message: str = "An operation failed"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.default_message)

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {}


class UnknownComponentInConfigError(ServiceError):
    """A component-level scheduling payload references an undeclared component name.

    Raised when scheduling configuration targets a component that the
    active driver version does not declare. Catching this at config time
    prevents rendering-time surprises where the configured rules silently
    apply to nothing.
    """

    error_code = "VALIDATION_ERROR"
    default_message = "Scheduling configuration references an unknown component"

    def __init__(
        self,
        message: str = "",
        component_name: str = "",
        path: str | None = None,
    ) -> None:
        self.component_name = component_name
        self.path = path
        super().__init__(message or f"Scheduling configuration references unknown component: {component_name!r}")

    @property
    def error_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"component_name": self.component_name}
        if self.path is not None:
            meta["path"] = self.path
        return meta


ENV_VARS_MIGRATION_GUIDE_URL = "https://docs.styrmin.app/docs/drivers/migrating-env-vars"


CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL = "https://docs.styrmin.app/docs/drivers/migrating-container-overrides"


RetiredTemplateFilter = Literal["component_env_vars", "component_command", "component_args"]


_RETIRED_FILTER_MIGRATION_GUIDES: dict[RetiredTemplateFilter, str] = {
    "component_env_vars": ENV_VARS_MIGRATION_GUIDE_URL,
    "component_command": CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
    "component_args": CONTAINER_OVERRIDES_MIGRATION_GUIDE_URL,
}


def _retired_filter_message(filter_name: RetiredTemplateFilter, guide: str) -> str:
    if filter_name == "component_env_vars":
        return (
            "The 'component_env_vars' template filter was removed: Styrmin now injects "
            "env vars into each component's declared component container. Deployment "
            "users: upgrade this deployment to a driver version that declares component "
            "containers. Driver authors: remove the filter from values.j2.yml and declare "
            f"components.<name>.container in driver.styrmin.yml. Migration guide: {guide}"
        )
    return (
        f"The '{filter_name}' template filter was removed: Styrmin now applies container "
        "command and args overrides to each component's declared component container. "
        "Deployment users: move this deployment to a driver version that no longer calls "
        "the filter. Driver authors: remove the filter from values.j2.yml and declare "
        f"components.<name>.container in driver.styrmin.yml. Migration guide: {guide}"
    )


def retired_filter_load_message(filter_name: RetiredTemplateFilter, lineno: int) -> str:
    """The message for a driver ``values.j2.yml`` that calls a retired filter at load time."""
    guide = _RETIRED_FILTER_MIGRATION_GUIDES[filter_name]
    applied = (
        "injects env vars into"
        if filter_name == "component_env_vars"
        else "applies container command and args overrides to"
    )
    return (
        f"values.j2.yml line {lineno} calls the '{filter_name}' template filter, which "
        f"was removed: Styrmin now {applied} each component's declared component "
        "container. Remove the filter from values.j2.yml and declare "
        f"components.<name>.container in driver.styrmin.yml. Migration guide: {guide}"
    )


class RetiredTemplateFilterError(ServiceError):
    """A driver values template called a template filter Styrmin removed.

    The message names the filter and its migration guide, because only the message
    survives the StyrminDeployment CR hop (ADR-057 §4).
    """

    error_code = "RETIRED_TEMPLATE_FILTER"
    default_message = _retired_filter_message("component_env_vars", ENV_VARS_MIGRATION_GUIDE_URL)

    def __init__(
        self,
        message: str = "",
        filter_name: RetiredTemplateFilter = "component_env_vars",
        migration_guide: str | None = None,
    ) -> None:
        self.filter_name = filter_name
        self.migration_guide = migration_guide or _RETIRED_FILTER_MIGRATION_GUIDES[filter_name]
        super().__init__(message or _retired_filter_message(filter_name, self.migration_guide))

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"filter": self.filter_name, "migration_guide": self.migration_guide}


# Errors of reading and checking a driver directory.


class DriverError(ServiceError):
    """Base class for driver errors."""

    error_code = "VALIDATION_ERROR"
    default_message = "A driver error occurred"


class DriverDefinitionError(DriverError):
    """An error occurred while defining the driver.

    This error indicates an error in the driver definition itself.
    It is not related to the driver data and therefore not imputable to the user data.
    """


class ParsingError(DriverError):
    """An error occurred while parsing the driver data."""


class ValidationError(DriverError):
    """An error occurred while validating the driver data."""


class DeserializationError(DriverError):
    """An error occurred while deserializing the driver data."""


class DriverLoadingError(DriverError):
    """An error occurred while loading the driver."""


class MissingDriverSpecificationError(DriverError):
    """A piece of driver data is missing."""


# Errors of rendering a values template. They are plain exceptions, as in the agent.


class ChartValuesTemplateRenderingError(Exception):
    """Exception raised when the chart values template rendering fails."""


class InvalidChartValuesError(Exception):
    """Exception raised when the chart values are not valid YAML."""
