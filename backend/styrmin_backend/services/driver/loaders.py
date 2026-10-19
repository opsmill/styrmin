from pathlib import Path
from typing import Type

from styrmin_backend import config
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.hash import compute_driver_directory_fingerprint
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
from styrmin_backend.services.driver.models.structure.source import GitSource
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
    validate_driver_backup_configs_for_spec,
    validate_driver_env_var_docs,
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

            # Post-deserialization: cross-field validation that needs the
            # whole spec. Run env-var-doc validation early so registration
            # aborts with a precise error before action validation runs
            # (FR-014).
            if isinstance(driver_spec, DriverSpec):
                validate_driver_env_var_docs(driver_spec.spec)
                # Fail loudly on misconfigured backups (e.g. `kind: disk`
                # with no volume) instead of silently capturing nothing.
                validate_driver_backup_configs_for_spec(driver_spec.spec)

            # Post-deserialization: validate actions against actions.py if present
            has_actions = bool(
                isinstance(driver_spec, DriverSpec) and driver_spec.spec.actions
            )
            if has_actions:
                validator = build_user_actions_validator(
                    actions=driver_spec.spec.actions  # type: ignore[union-attr]
                )
                get_resource_file_loader(
                    resource_file=directory_map.actions_code,
                    validator=validator,
                ).load()

            # Spec 013 — branch on the typed source discriminator (not a
            # duck-typed ``getattr`` on the provider). Git-sourced drivers
            # carry the commit SHA as their fingerprint dimension and skip
            # the per-byte hash entirely; local-sourced drivers compute the
            # content hash from the canonical three files. The two
            # fingerprint columns are mutually exclusive per source type,
            # so the discriminator is the right axis to branch on — see
            # ``DriverSource`` in models/structure/source.py.
            source = self.provider.get_source()
            content_hash: str | None = None
            source_commit_sha: str | None = None

            if isinstance(source, GitSource):
                # Git rows match on SHA; do not compute or persist
                # ``content_hash`` for them. The provider records the SHA
                # during ``provide()``; the GitDriverProvider type
                # guarantees this accessor exists.
                source_commit_sha = self.provider.get_resolved_commit_sha()  # type: ignore[attr-defined]
            else:
                # Local-sourced driver: compute the content-hash
                # fingerprint from the raw bytes of the three driver
                # files. The provider's ``driver_dir`` is still valid
                # inside this ``with`` block. ``actions.py`` participates
                # in the hash iff the spec declares any actions. Spec 029:
                # the check before a local driver version's action calls
                # the same function with the same file names, so both
                # compute the same fingerprint for the same files.
                driver_settings = config.SETTINGS.driver
                try:
                    content_hash = compute_driver_directory_fingerprint(
                        driver_dir,
                        spec_file=driver_settings.spec_file,
                        values_template=driver_settings.values_template,
                        actions_file=driver_settings.actions_code_file,
                        include_actions=has_actions,
                    )
                except OSError as err:
                    # If we cannot re-read the bytes we already parsed, the
                    # driver source is broken in ways that should surface
                    # as a load-time failure rather than silently producing
                    # a row with no fingerprint.
                    raise DriverLoadingError(
                        f"Failed to read driver source files for content hash: {err!s}"
                    ) from err

            return ApplicationDriver(
                source=source,
                driver_spec=driver_spec,  # type: ignore[arg-type]
                values_template=values_template
                if isinstance(values_template, str)
                else "",
                content_hash=content_hash,
                source_commit_sha=source_commit_sha,
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


def get_git_driver_loader(
    repository: str, branch: str, token: str, driver_directory: str | None = None
) -> DriverLoader:
    """Get the driver loader for the git repository.

    Args:
        repository (str): The git repository.
        branch (str): The git branch.
        token (str): The git token.
        driver_directory (str | None): The folder of the repository that holds the
            driver, relative to the repository root; None for the repository root.

    Returns:
        DriverLoader: The driver loader.

    Raises:
        DriverLoadingError: The driver directory is refused (absolute, ``..``
            segment, backslash or NUL character).
    """
    return DriverLoader(
        provider=GitDriverProvider(
            repository=repository,
            branch=branch,
            token=token,
            driver_directory=driver_directory,
        )
    )
