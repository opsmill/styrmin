from typing import Type

from styrmin_sdk.driver_format.reading.files import (
    get_resource_file_loader,
)

from styrmin_backend import config
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.exceptions import (
    DriverLoadingError,
)
from styrmin_backend.services.driver.hash import compute_driver_directory_fingerprint
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.directory import DriverDirectory
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.driver.provider import (
    DriverProvider,
    GitDriverProvider,
    LocalDriverProvider,
)
from styrmin_backend.services.driver.validators import (
    build_user_actions_validator,
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
