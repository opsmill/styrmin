from pathlib import Path
from typing import Type

from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.deserializers import (
    Deserializer,
    get_deserializer,
)
from styrmin_backend.services.driver.exceptions import (
    DeserializationError,
    DriverDefinitionError,
    DriverLoadingError,
    MissingDriverSpecificationError,
    ParsingError,
    ValidationError,
)
from styrmin_backend.services.driver.models.resources import DriverResource
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.directory import DriverDirectory
from styrmin_backend.services.driver.models.structure.resource import ResourceFile
from styrmin_backend.services.driver.parsers import Parser, get_parser
from styrmin_backend.services.driver.provider import (
    DriverProvider,
    GitDriverProvider,
    LocalDriverProvider,
)
from styrmin_backend.services.driver.validators import (
    Validator,
    build_user_actions_validator,
    get_validator,
)


class DriverLoader:
    """The driver loader class.

    Responsible for loading an application driver from a path, the driver loader uses its map of
    an application driver directory to properly load and return the driver.

    Attributes:
        provider (DriverProvider): The driver provider.
        directory_map_model (Type[DriverDirectory]): The directory map model to use while loading the driver.
    """

    def __init__(
        self,
        provider: DriverProvider,
        directory_map_model: Type[DriverDirectory] = DriverDirectory,
    ):
        self.provider = provider
        self.directory_map_model = directory_map_model

    def load_driver(self) -> ApplicationDriver:
        """Load the application driver.

        Returns:
            ApplicationDriver: The loaded application driver.
        """

        with self.provider.provide() as driver_dir:
            # Set the directory map to point to the cloned repository
            directory_map = self.directory_map_model(root_path=driver_dir)

            # Load the resource files
            driver_spec = get_resource_file_loader(directory_map.driver_spec).load()
            values_template = get_resource_file_loader(
                directory_map.values_template
            ).load()

            # Post-deserialization: validate actions against actions.py if present
            if isinstance(driver_spec, DriverSpec) and driver_spec.spec.actions:
                validator = build_user_actions_validator(
                    actions=driver_spec.spec.actions
                )
                get_resource_file_loader(
                    resource_file=directory_map.actions_code,
                    validator=validator,
                ).load()

            return ApplicationDriver(
                source=self.provider.get_source(),
                driver_spec=driver_spec,  # type: ignore[arg-type]
                values_template=values_template
                if isinstance(values_template, str)
                else "",
            )


class ResourceFileLoader:
    def __init__(
        self,
        path: Path,
        parser: Parser | None = None,
        validator: Validator | None = None,
        deserializer: Deserializer | None = None,
        fail_on_not_found: bool = True,
    ):
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
            parsed_data = self.parser.parse(path=self.path)  # type: ignore[union-attr]
        except FileNotFoundError as err:
            if not self.fail_on_not_found:
                return None
            raise MissingDriverSpecificationError(
                f"The driver specification file could not be found: {err!s}"
            ) from err
        except ParsingError as err:
            raise DriverLoadingError(str(err)) from err

        if self.validator:
            try:
                self.validator.validate(data=parsed_data)
            except ValidationError as err:
                raise DriverLoadingError(
                    f"The driver resource validation failed: {err!s}"
                ) from err
        if self.deserializer is None:
            return parsed_data
        try:
            return self.deserializer.deserialize(data=parsed_data)
        except DeserializationError as err:
            raise DriverLoadingError(
                f"Error while deserializing the driver resource: {err!s}"
            ) from err


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
            validator=get_validator(resource_file.role)
            if validator is None
            else validator,
            deserializer=get_deserializer(resource_file.role)
            if deserializer is None
            else deserializer,
            fail_on_not_found=not resource_file.optional,
        )
    except ValueError as err:
        # This means we are trying to load a resource file with an unsupported role or syntax.
        raise DriverDefinitionError(str(err)) from err


def get_local_driver_loader(path: str) -> DriverLoader:
    """Get the driver loader for a local filesystem directory.

    Args:
        path (str): The absolute path to the local driver directory.

    Returns:
        DriverLoader: The driver loader.
    """
    return DriverLoader(provider=LocalDriverProvider(path=path))


def get_git_driver_loader(repository: str, branch: str, token: str) -> DriverLoader:
    """Get the driver loader for the git repository.

    Args:
        repository (str): The git repository.
        branch (str): The git branch.
        token (str): The git token.

    Returns:
        DriverLoader: The driver loader.
    """
    return DriverLoader(
        provider=GitDriverProvider(repository=repository, branch=branch, token=token)
    )
