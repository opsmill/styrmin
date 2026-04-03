from styrmin_backend.services.exceptions import ServiceError


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
