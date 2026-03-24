import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from dulwich import porcelain

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.models.structure.source import (
    DriverSource,
    GitSource,
    LocalSource,
)


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


class GitDriverProvider(DriverProvider):
    """The git driver provider class.

    The git driver provider is responsible for providing the driver content from a git repository.
    """

    def __init__(self, repository: str, branch: str, token: str):
        self.source = GitSource(repository=repository, branch=branch, token=token)

    def get_source(self) -> GitSource:
        return self.source

    @contextmanager
    def provide(self) -> Generator[Path, None, None]:
        """Provide the driver content as a temporary directory."""
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            # Clone the git repository
            porcelain.clone(
                source=self.source.repository,
                target=tempdir_path,
                branch=self.source.branch,
                username=self.source.token,
            )
            yield tempdir_path


class LocalDriverProvider(DriverProvider):
    """The local driver provider class.

    The local driver provider is responsible for providing the driver content from a
    local filesystem directory. The directory is yielded directly without copying.
    """

    def __init__(self, path: str):
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
