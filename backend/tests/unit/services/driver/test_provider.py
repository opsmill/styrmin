import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from dulwich import porcelain
from dulwich.errors import GitProtocolError
from dulwich.repo import Repo

from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver import loaders as loaders_module
from styrmin_backend.services.driver import provider as provider_module
from styrmin_backend.services.driver.exceptions import (
    DriverLoadingError,
    MissingDriverSpecificationError,
)
from styrmin_backend.services.driver.loaders import DriverLoader
from styrmin_backend.services.driver.models.structure.source import (
    GitSource,
    LocalSource,
)
from styrmin_backend.services.driver.provider import (
    GitDriverProvider,
    LocalDriverProvider,
)


def test_local_driver_provider_yields_given_path(tmp_path: Path) -> None:
    provider = LocalDriverProvider(path=str(tmp_path))
    with provider.provide() as provided_path:
        assert provided_path == tmp_path


def test_local_driver_provider_get_source_returns_local_source(tmp_path: Path) -> None:
    provider = LocalDriverProvider(path=str(tmp_path))
    source = provider.get_source()
    assert isinstance(source, LocalSource)
    assert source.type == "local"
    assert source.path == str(tmp_path)


def test_local_driver_provider_raises_on_nonexistent_path() -> None:
    with pytest.raises(DriverLoadingError, match="does not exist"):
        LocalDriverProvider(path="/nonexistent/path/to/driver")


def test_local_driver_provider_raises_on_file_path(tmp_path: Path) -> None:
    driver_file = tmp_path / "driver.yaml"
    driver_file.write_text("name: test")
    with pytest.raises(DriverLoadingError, match="not a directory"):
        LocalDriverProvider(path=str(driver_file))


# --- Git driver provider: checks after the clone (spec 028, US3, FR-007 to FR-009) ---

_FIXTURE_DRIVER = Path(__file__).parent / "fixtures" / "local_driver_directory"


@dataclass(frozen=True)
class _Repository:
    url: str
    branch: str
    sha: str
    outside: Path


@pytest.fixture
def make_repository(tmp_path: Path) -> Callable[[Callable[[Path], None]], _Repository]:
    """Build a local git repository with the fixture driver in ``drivers/a/``.

    The returned function takes a callback that adds files and symlinks to the
    working tree before the single commit. ``outside`` is a folder next to the
    repository that holds ``secret.yml``.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.yml").write_text("secret: value\n")

    def build(setup: Callable[[Path], None]) -> _Repository:
        repo_path = tmp_path / "origin"
        shutil.copytree(_FIXTURE_DRIVER, repo_path / "drivers" / "a")
        setup(repo_path)
        # ``porcelain.add`` walks into a symlink to /etc; stage the paths directly.
        paths = sorted(
            p.relative_to(repo_path).as_posix()
            for p in repo_path.rglob("*")
            if p.is_symlink() or p.is_file()
        )
        with Repo.init(str(repo_path)) as repo:
            head = repo.refs.read_ref(b"HEAD")
            assert head is not None
            branch = head.decode("ascii").rsplit("/", 1)[-1]
            worktree = repo.get_worktree()
            worktree.stage(paths)
            sha = worktree.commit(
                message=b"drivers", author=b"t <t@t>", committer=b"t <t@t>"
            ).decode("ascii")
        return _Repository(str(repo_path), branch, sha, outside)

    return build


@pytest.fixture
def clone_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the temporary folder of each clone, to check messages never name it."""
    created: list[str] = []
    real = tempfile.TemporaryDirectory

    def recording(*args: Any, **kwargs: Any) -> tempfile.TemporaryDirectory[str]:
        tempdir = real(*args, **kwargs)
        created.append(tempdir.name)
        return tempdir

    monkeypatch.setattr(provider_module.tempfile, "TemporaryDirectory", recording)
    return created


@pytest.fixture
def no_driver_file_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the loader opens any driver file."""

    def fail(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        pytest.fail("the loader read a driver file")

    monkeypatch.setattr(loaders_module, "get_resource_file_loader", fail)


def _where(repository: _Repository) -> str:
    return (
        f"repository {repository.url!r} "
        f"(branch {repository.branch!r}, commit {repository.sha})"
    )


def _load(repository: _Repository, driver_directory: str | None) -> ApplicationDriver:
    provider = GitDriverProvider(
        repository=repository.url,
        branch=repository.branch,
        token="",
        driver_directory=driver_directory,
    )
    return DriverLoader(provider=provider).load_driver()


@pytest.mark.usefixtures("no_driver_file_read")
def test_driver_directory_symlinked_outside_is_refused(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
    clone_paths: list[str],
) -> None:
    repository = make_repository(
        lambda root: (root / "drivers" / "evil").symlink_to(
            "/etc", target_is_directory=True
        )
    )

    with pytest.raises(DriverLoadingError) as excinfo:
        _load(repository, "drivers/evil")

    message = str(excinfo.value)
    assert message == (
        f"Driver directory 'drivers/evil' of {_where(repository)} leads outside the "
        "repository: 'drivers/evil' is a symlink to a path outside it."
    )
    [clone] = clone_paths
    assert clone not in message
    assert "/etc" not in message


@pytest.mark.usefixtures("no_driver_file_read")
def test_root_driver_specification_symlinked_outside_is_refused_on_a_root_load(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
    clone_paths: list[str],
) -> None:
    def setup(root: Path) -> None:
        (root / "driver.styrmin.yml").symlink_to(root.parent / "outside" / "secret.yml")

    repository = make_repository(setup)

    with pytest.raises(DriverLoadingError) as excinfo:
        _load(repository, None)

    message = str(excinfo.value)
    assert message == (
        f"Driver directory 'the repository root' of {_where(repository)} leads "
        "outside the repository: 'driver.styrmin.yml' is a symlink to a path "
        "outside it."
    )
    [clone] = clone_paths
    assert clone not in message
    assert str(repository.outside) not in message


@pytest.mark.usefixtures("no_driver_file_read")
def test_values_template_symlinked_outside_is_refused(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
) -> None:
    def setup(root: Path) -> None:
        values = root / "drivers" / "a" / "values.j2.yml"
        values.unlink()
        values.symlink_to(root.parent / "outside" / "secret.yml")

    repository = make_repository(setup)

    with pytest.raises(DriverLoadingError) as excinfo:
        _load(repository, "drivers/a")

    assert str(excinfo.value) == (
        f"Driver directory 'drivers/a' of {_where(repository)} leads outside the "
        "repository: 'drivers/a/values.j2.yml' is a symlink to a path outside it."
    )


def test_driver_directory_symlinked_inside_is_accepted(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
) -> None:
    repository = make_repository(
        lambda root: (root / "drivers" / "inner").symlink_to(
            "../drivers/a", target_is_directory=True
        )
    )
    provider = GitDriverProvider(
        repository=repository.url,
        branch=repository.branch,
        token="",
        driver_directory="drivers/inner",
    )

    with provider.provide() as driver_dir:
        assert driver_dir.parts[-2:] == ("drivers", "a")
        assert (driver_dir / "driver.styrmin.yml").is_file()

    driver = _load(repository, "drivers/inner")
    assert isinstance(driver.source, GitSource)
    assert driver.source.driver_directory == "drivers/inner"
    assert driver.source_commit_sha == repository.sha


@pytest.mark.usefixtures("no_driver_file_read")
@pytest.mark.parametrize("driver_directory", ["drivers/missing", "drivers/a-file"])
def test_missing_or_file_driver_directory_does_not_exist(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
    driver_directory: str,
) -> None:
    repository = make_repository(
        lambda root: (root / "drivers" / "a-file").write_text("not a folder\n")
    )

    with pytest.raises(DriverLoadingError) as excinfo:
        _load(repository, driver_directory)

    assert str(excinfo.value) == (
        f"Driver directory {driver_directory!r} does not exist in {_where(repository)}."
    )
    assert len(repository.sha) == 40


@pytest.mark.usefixtures("no_driver_file_read")
def test_driver_directory_without_driver_specification_is_reported(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
) -> None:
    def setup(root: Path) -> None:
        (root / "drivers" / "empty").mkdir()
        (root / "drivers" / "empty" / "README.md").write_text("no driver here\n")

    repository = make_repository(setup)

    with pytest.raises(MissingDriverSpecificationError) as excinfo:
        _load(repository, "drivers/empty")

    assert str(excinfo.value) == (
        f"No driver.styrmin.yml in driver directory 'drivers/empty' of "
        f"{_where(repository)}."
    )


@pytest.mark.usefixtures("no_driver_file_read")
def test_root_without_driver_specification_is_reported(
    make_repository: Callable[[Callable[[Path], None]], _Repository],
) -> None:
    repository = make_repository(lambda root: None)

    with pytest.raises(MissingDriverSpecificationError) as excinfo:
        _load(repository, None)

    assert str(excinfo.value) == (
        f"No driver.styrmin.yml at the root of {_where(repository)}."
    )


def test_refused_driver_directory_raises_before_the_clone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        pytest.fail("porcelain.clone was called for a refused driver directory")

    monkeypatch.setattr(porcelain, "clone", fail)

    with pytest.raises(DriverLoadingError, match="is refused: it contains a '..'"):
        provider = GitDriverProvider(
            repository="https://github.com/o/r.git",
            branch="main",
            token="",
            driver_directory="../x",
        )
        with provider.provide():
            pass


def test_clone_failure_message_has_no_user_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://user:token@invalid.example/x.git"

    def unreachable(source: str, **kwargs: Any) -> None:  # noqa: ARG001
        # dulwich raises GitProtocolError; this one also repeats the URL as given.
        raise GitProtocolError(f"unable to reach {source}: Name or service not known")

    monkeypatch.setattr(porcelain, "clone", unreachable)
    provider = GitDriverProvider(
        repository=url, branch="main", token="", driver_directory="drivers/a"
    )

    with pytest.raises(DriverLoadingError) as excinfo:
        with provider.provide():
            pass

    message = str(excinfo.value)
    assert "token" not in message
    assert "user" not in message
    assert message.startswith(
        "Failed to clone git repository 'https://invalid.example/x.git' "
        "(branch='main', driver directory 'drivers/a'): unable to reach "
        "https://invalid.example/x.git"
    )
