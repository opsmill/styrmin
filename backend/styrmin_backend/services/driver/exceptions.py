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


class DeprecatedDriverFormatError(DriverError):
    """The driver directory uses a deprecated file format."""

    error_code = "DEPRECATED_FORMAT"
    default_message = "Driver uses deprecated file format"

    def __init__(self, old_files: list[str], message: str = "") -> None:
        self.old_files = old_files
        if not message:
            files_str = ", ".join(old_files)
            message = (
                f"Driver directory contains deprecated files: {files_str}. "
                "Migrate to the new format: driver.styrmin.yml + values.j2.yml"
            )
        super().__init__(message)


class AmbiguousDriverFormatError(DriverError):
    """The driver directory contains both old and new format files."""

    error_code = "AMBIGUOUS_FORMAT"
    default_message = "Driver directory contains both old and new format files"

    def __init__(self, conflicting_files: list[str], message: str = "") -> None:
        self.conflicting_files = conflicting_files
        if not message:
            files_str = ", ".join(conflicting_files)
            message = (
                f"Driver directory contains conflicting files: {files_str}. "
                "Remove old format files (styrmin_driver.yaml, actions.yaml, "
                "chart_values.j2.yaml) and use only the new format "
                "(driver.styrmin.yml, values.j2.yml)."
            )
        super().__init__(message)
