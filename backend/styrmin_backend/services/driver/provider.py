import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from dulwich import porcelain
from dulwich.repo import Repo

from styrmin_backend.services.driver.driver_directory import normalise_driver_directory
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
    It clones the whole repository and provides the driver directory, or the clone root when no
    driver directory is given.
    """

    def __init__(
        self,
        repository: str,
        branch: str,
        token: str,
        driver_directory: str | None = None,
    ):
        # Normalise here so a refused driver directory fails before any clone (FR-007).
        self.source = GitSource(
            repository=repository,
            branch=branch,
            token=token,
            driver_directory=normalise_driver_directory(driver_directory),
        )
        self._resolved_commit_sha: str | None = None

    def get_source(self) -> GitSource:
        return self.source

    def get_resolved_commit_sha(self) -> str | None:
        """Return the HEAD commit SHA resolved during the last `provide()` call.

        Returns None if `provide()` has not yet been called. After a successful
        clone, this returns the 40-character lowercase hex commit SHA.
        """
        return self._resolved_commit_sha

    @contextmanager
    def provide(self) -> Generator[Path, None, None]:
        """Provide the driver directory of a temporary clone of the repository."""
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir_path = Path(tempdir)
            # Clone the git repository
            try:
                porcelain.clone(
                    source=self.source.repository,
                    target=tempdir_path,
                    branch=self.source.branch,
                    username=self.source.token,
                )
            except Exception as exc:  # noqa: BLE001 — wrap any clone failure
                raise DriverLoadingError(
                    f"Failed to clone git repository "
                    f"{self.source.repository!r} (branch={self.source.branch!r}): {exc}"
                ) from exc
            # Resolve the HEAD commit SHA from the freshly cloned repo and stash
            # it on the provider so the caller can read it after the context
            # manager exits (the tempdir is gone by then).
            try:
                with Repo(str(tempdir_path)) as repo:
                    self._resolved_commit_sha = repo.head().decode("ascii")
            except Exception as exc:  # noqa: BLE001
                raise DriverLoadingError(
                    f"Failed to resolve HEAD commit SHA for "
                    f"{self.source.repository!r}: {exc}"
                ) from exc
            driver_directory = self.source.driver_directory
            yield (
                tempdir_path
                if driver_directory is None
                else tempdir_path / driver_directory
            )


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
