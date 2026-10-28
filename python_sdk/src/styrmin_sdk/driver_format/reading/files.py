"""Read one file of a driver directory: parse it, check it and build its model."""

from pathlib import Path

from styrmin_sdk.driver_format.checks import Validator, get_validator
from styrmin_sdk.driver_format.errors import (
    DeserializationError,
    DriverDefinitionError,
    DriverLoadingError,
    MissingDriverSpecificationError,
    ParsingError,
    ValidationError,
)
from styrmin_sdk.driver_format.models.resources import DriverResource
from styrmin_sdk.driver_format.models.structure.resource import ResourceFile
from styrmin_sdk.driver_format.reading.deserializers import Deserializer, get_deserializer
from styrmin_sdk.driver_format.reading.parsers import Parser, get_parser


class ResourceFileLoader:
    def __init__(
        self,
        path: Path,
        parser: Parser | None = None,
        validator: Validator | None = None,
        deserializer: Deserializer | None = None,
        fail_on_not_found: bool = True,
    ) -> None:
        self.path = path
        self.parser = parser
        self.validator = validator
        self.deserializer = deserializer
        self.fail_on_not_found = fail_on_not_found

    def load(self) -> DriverResource | None:
        """Load the driver resource.

        The loading workflow is as follows:
        1. Parse the file.
        2. Validate the parsed data.
        3. Deserialize the validated data.

        Returns:
            DriverResource: The loaded driver resource.
        """
        try:
            parsed_data = self.parser.parse(path=self.path)  # ty: ignore[unresolved-attribute]
        except FileNotFoundError as err:
            if not self.fail_on_not_found:
                return None
            raise MissingDriverSpecificationError(f"The driver specification file could not be found: {err!s}") from err
        except ParsingError as err:
            raise DriverLoadingError(str(err)) from err

        if self.validator:
            try:
                self.validator.validate(data=parsed_data)
            except ValidationError as err:
                raise DriverLoadingError(f"The driver resource validation failed: {err!s}") from err
        if self.deserializer is None:
            return parsed_data
        try:
            return self.deserializer.deserialize(data=parsed_data)
        except DeserializationError as err:
            raise DriverLoadingError(f"Error while deserializing the driver resource: {err!s}") from err


def get_resource_file_loader(
    resource_file: ResourceFile,
    parser: Parser | None = None,
    validator: Validator | None = None,
    deserializer: Deserializer | None = None,
) -> ResourceFileLoader:
    """Get the file loader for the resource file.

    Args:
        resource_file (ResourceFile): The resource file.
        parser (Parser | None): The parser to use. Defaults to None. If None, the parser will be fetched
            based on the syntax of the resource file against the parser factory function.
        validator (Validator | None): The validator to use. Defaults to None. If None, the validator will be
            fetched based on the role of the resource file against the validator factory function.
        deserializer (Deserializer | None): The deserializer to use. Defaults to None. If None, the deserializer
            will be fetched based on the role of the resource file against the deserializer factory function.

    Returns:
        FileLoader: The file loader.
    """
    try:
        return ResourceFileLoader(
            path=resource_file.path,
            parser=get_parser(resource_file.syntax) if parser is None else parser,
            validator=get_validator(resource_file.role) if validator is None else validator,
            deserializer=get_deserializer(resource_file.role) if deserializer is None else deserializer,
            fail_on_not_found=not resource_file.optional,
        )
    except ValueError as err:
        # This means we are trying to load a resource file with an unsupported role or syntax.
        raise DriverDefinitionError(str(err)) from err
