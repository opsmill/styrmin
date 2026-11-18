import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from dulwich import porcelain
from dulwich.repo import Repo
from loguru import logger
from styrmin_sdk.driver_format.reading.local import (
    DriverProvider,
    LocalDriverProvider as LocalDriverProvider,
)

from styrmin_backend import config
from styrmin_backend.services.driver.driver_directory import (
    normalise_driver_directory,
    quoted,
    redact_user_info,
    resolve_inside,
)
from styrmin_backend.services.driver.exceptions import (
    DriverLoadingError,
    MissingDriverSpecificationError,
)
from styrmin_backend.services.driver.models.structure.source import (
    GitSource,
)


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
        """Provide the driver directory of a temporary clone of the repository.

        Raises:
            DriverLoadingError: The clone fails, the driver directory or one of the
                driver files leads outside the clone, or the driver directory does
                not exist.
            MissingDriverSpecificationError: The driver directory holds no driver
                specification file.
        """
        repository = redact_user_info(self.source.repository)
        driver_directory = self.source.driver_directory
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
                for_directory = (
                    ""
                    if driver_directory is None
                    else f", driver directory {quoted(driver_directory)}"
                )
                # Some clone errors repeat a URL with its user info.
                raise DriverLoadingError(
                    f"Failed to clone git repository {quoted(repository)} "
                    f"(branch={quoted(self.source.branch)}{for_directory}): "
                    f"{redact_user_info(str(exc))}"
                ) from exc
            # Resolve the HEAD commit SHA from the freshly cloned repo and stash
            # it on the provider so the caller can read it after the context
            # manager exits (the tempdir is gone by then).
            try:
                with Repo(str(tempdir_path)) as repo:
                    commit_sha = repo.head().decode("ascii")
            except Exception as exc:  # noqa: BLE001
                raise DriverLoadingError(
                    f"Failed to resolve HEAD commit SHA for {quoted(repository)}: {exc}"
                ) from exc
            self._resolved_commit_sha = commit_sha
            yield self._check_driver_directory(tempdir_path, repository, commit_sha)

    def _check_driver_directory(
        self, clone: Path, repository: str, commit_sha: str
    ) -> Path:
        """Return the real path of the driver directory once every check passes.

        Checks, before any driver file is read, that the driver directory stays
        inside the clone and the three driver files stay inside the driver
        directory (FR-008), that each of them can be followed, and that the
        driver directory holds the driver specification file (FR-009).

        Args:
            clone: The root of the temporary clone.
            repository: The repository URL without user info, for messages.
            commit_sha: The commit SHA of the clone.

        Returns:
            The resolved driver directory, or the resolved clone root.
        """
        driver_directory = self.source.driver_directory
        where = (
            f"repository {quoted(repository)} "
            f"(branch {quoted(self.source.branch)}, commit {commit_sha})"
        )

        def unreadable(relative: str, exc: OSError) -> DriverLoadingError:
            # ``strerror`` leaves out the path, which is in the temporary clone.
            return DriverLoadingError(
                f"{quoted(relative)} in {where} cannot be read: {exc.strerror}."
            )

        resolved = resolve_inside(clone, driver_directory or ".")
        if resolved is None:
            # Only a driver directory can lead outside: the clone root cannot.
            shown = driver_directory or "."
            link = _first_link_outside(clone, shown)
            raise DriverLoadingError(
                f"Driver directory {quoted(shown)} of {where} leads "
                f"outside the repository: {quoted(link)} is a symlink to a path "
                "outside it."
            )
        if driver_directory is not None:
            if error := _follow_error(resolved):
                raise unreadable(driver_directory, error)
            if not resolved.is_dir():
                raise DriverLoadingError(
                    f"Driver directory {quoted(driver_directory)} does not exist "
                    f"in {where}."
                )
        outside = (
            "the repository"
            if driver_directory is None
            else f"driver directory {quoted(driver_directory)}"
        )
        settings = config.SETTINGS.driver
        for name in (
            settings.spec_file,
            settings.values_template,
            settings.actions_code_file,
        ):
            relative = (
                name if driver_directory is None else f"{driver_directory}/{name}"
            )
            if resolve_inside(resolved, name) is None:
                raise DriverLoadingError(
                    f"{quoted(relative)} in {where} is a symlink to a path "
                    f"outside {outside}."
                )
            if error := _follow_error(resolved / name):
                raise unreadable(relative, error)
        if not (resolved / settings.spec_file).is_file():
            if driver_directory is None:
                raise MissingDriverSpecificationError(
                    f"No {settings.spec_file} at the root of {where}."
                )
            raise MissingDriverSpecificationError(
                f"No {settings.spec_file} in driver directory "
                f"{quoted(driver_directory)} of {where}."
            )
        logger.info(
            "Checked git driver source: repository={} branch={} commit={} "
            "driver_directory={}",
            repository,
            self.source.branch,
            commit_sha,
            driver_directory,
        )
        return resolved


def _first_link_outside(root: Path, relative: str) -> str:
    """Return the shortest leading part of ``relative`` that resolves outside ``root``.

    The driver directory has no ``..`` segment, so that part is the symlink that
    leaves the clone.
    """
    parts = relative.split("/")
    for end in range(1, len(parts) + 1):
        prefix = "/".join(parts[:end])
        if resolve_inside(root, prefix) is None:
            return prefix
    return relative


def _follow_error(path: Path) -> OSError | None:
    """Return the error of following ``path``, such as a symlink loop.

    A missing path gives ``None``: the callers report it in their own words.
    """
    try:
        path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return exc
    return None
