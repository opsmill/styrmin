"""Unit tests for `GitDriverProvider.get_resolved_commit_sha`.

Covers the new commit-SHA exposure added by T009. Uses a real on-disk
git repo (via dulwich) exposed over `file://` — no network, no external
fixture repos.
"""

from pathlib import Path

import pytest
from dulwich import porcelain
from dulwich.repo import Repo

from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.provider import GitDriverProvider


@pytest.fixture
def local_git_repo(tmp_path: Path) -> tuple[str, str, str]:
    """Create a tiny local git repo with one commit.

    The root holds a ``driver.styrmin.yml``: the provider refuses a root load
    without one (spec 028, FR-009). The provider does not parse it.

    Returns:
        (file_url, commit_sha, branch_name) tuple.
    """
    repo_path = tmp_path / "origin"
    repo_path.mkdir()
    Repo.init(str(repo_path))
    (repo_path / "README.md").write_text("hi")
    (repo_path / "driver.styrmin.yml").write_text("{}\n")
    porcelain.add(
        str(repo_path),
        paths=[str(repo_path / "README.md"), str(repo_path / "driver.styrmin.yml")],
    )
    sha_bytes = porcelain.commit(
        str(repo_path),
        message=b"init",
        author=b"t <t@t>",
        committer=b"t <t@t>",
    )
    sha = sha_bytes.decode("ascii")

    # Discover the default branch name created by `Repo.init()`.
    with Repo(str(repo_path)) as repo:
        head_ref = repo.refs.read_ref(b"HEAD")
        # head_ref is something like b"ref: refs/heads/master" → b"refs/heads/master"
        assert head_ref is not None
        branch_name = head_ref.decode("ascii").rsplit("/", 1)[-1]

    return f"file://{repo_path}", sha, branch_name


def test_provider_resolves_head_commit_sha(
    local_git_repo: tuple[str, str, str],
) -> None:
    """`get_resolved_commit_sha()` returns the expected 40-char SHA after `provide()`."""
    url, expected_sha, branch = local_git_repo
    provider = GitDriverProvider(repository=url, branch=branch, token="")

    # Before provide(): nothing resolved yet.
    assert provider.get_resolved_commit_sha() is None

    with provider.provide() as cloned_path:
        assert cloned_path.exists()

    resolved = provider.get_resolved_commit_sha()
    assert resolved is not None
    assert resolved == expected_sha
    assert len(resolved) == 40
    # 40-char lowercase hex
    int(resolved, 16)


def test_provider_resolves_same_sha_across_two_clones(
    local_git_repo: tuple[str, str, str],
) -> None:
    """Two separate provider instances against the same ref report the same SHA."""
    url, expected_sha, branch = local_git_repo

    provider_a = GitDriverProvider(repository=url, branch=branch, token="")
    with provider_a.provide():
        pass

    provider_b = GitDriverProvider(repository=url, branch=branch, token="")
    with provider_b.provide():
        pass

    assert provider_a.get_resolved_commit_sha() == expected_sha
    assert provider_b.get_resolved_commit_sha() == expected_sha


def test_provider_raises_driver_loading_error_for_unreachable_repo(
    tmp_path: Path,
) -> None:
    """An unreachable repo URL surfaces as `DriverLoadingError`."""
    missing = tmp_path / "does-not-exist"
    provider = GitDriverProvider(
        repository=f"file://{missing}",
        branch="master",
        token="",
    )

    with pytest.raises(DriverLoadingError):
        with provider.provide():
            pass

    # SHA must remain unresolved when the clone failed.
    assert provider.get_resolved_commit_sha() is None


def test_provider_raises_driver_loading_error_for_missing_branch(
    local_git_repo: tuple[str, str, str],
) -> None:
    """A valid repo but missing branch surfaces as `DriverLoadingError`."""
    url, _sha, _branch = local_git_repo
    provider = GitDriverProvider(
        repository=url,
        branch="this-branch-does-not-exist",
        token="",
    )

    with pytest.raises(DriverLoadingError):
        with provider.provide():
            pass

    assert provider.get_resolved_commit_sha() is None
