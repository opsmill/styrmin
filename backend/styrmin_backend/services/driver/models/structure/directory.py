"""The driver directory model, with the file names of the server's settings.

The model moved to ``styrmin_sdk.driver_format.models.structure.directory`` (ADR-0089).
The server's ``STYRMIN_DRIVER_*`` settings still choose the file names: this subclass
reads them each time a directory map is built, as the backend did before the move.
"""

from pathlib import Path

from styrmin_sdk.driver_format.models.structure.directory import (
    DriverDirectory as _SdkDriverDirectory,
)
from styrmin_sdk.driver_format.models.structure.directory import (
    DriverFileNames,
)

from styrmin_backend import config


def driver_file_names_from_settings() -> DriverFileNames:
    """The file names of a driver directory, from the server's driver settings."""
    settings = config.SETTINGS.driver
    return DriverFileNames(
        spec_file=settings.spec_file,
        values_template=settings.values_template,
        actions_code=settings.actions_code_file,
    )


class DriverDirectory(_SdkDriverDirectory):
    """A driver directory whose file names come from the server's settings."""

    def __init__(self, root_path: Path) -> None:
        super().__init__(root_path, file_names=driver_file_names_from_settings())


__all__ = ["DriverDirectory", "DriverFileNames", "driver_file_names_from_settings"]
