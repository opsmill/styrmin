"""Give the loader the files of a driver directory on the local filesystem."""

from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from styrmin_sdk.driver_format.errors import DriverLoadingError
from styrmin_sdk.driver_format.models.structure.source import DriverSource, LocalSource


class DriverProvider(ABC):
    """The driver provider class.

    The driver provider is responsible for providing the driver content to the driver loader.
    """

    @abstractmethod
    @contextmanager
    def provide(self) -> Generator[Any, Any, Path]:
        """Provide the driver content as a temporary directory."""
        raise NotImplementedError

    @abstractmethod
    def get_source(self) -> DriverSource:
        """Get the source of the driver."""
        raise NotImplementedError


class LocalDriverProvider(DriverProvider):
    """The local driver provider class.

    The local driver provider is responsible for providing the driver content from a
    local filesystem directory. The directory is yielded directly without copying.
    """

    def __init__(self, path: str) -> None:
        local_path = Path(path)
        if not local_path.exists():
            raise DriverLoadingError(f"The driver path does not exist: {path}")
        if not local_path.is_dir():
            raise DriverLoadingError(f"The driver path is not a directory: {path}")
        self.source = LocalSource(path=path)

    def get_source(self) -> LocalSource:
        return self.source

    @contextmanager
    def provide(self) -> Generator[Path, None, None]:
        """Yield the local directory path directly without copying."""
        yield Path(self.source.path)
