"""Unit tests for the driver directory path rule (spec 028, FR-006, FR-007, FR-008)."""

from pathlib import Path

import pytest

from styrmin_backend.redaction import redact_user_info
from styrmin_backend.services.driver.driver_directory import (
    MAX_DRIVER_DIRECTORY_LENGTH,
    driver_directory_digest,
    normalise_driver_directory,
    resolve_inside,
)
from styrmin_backend.services.driver.exceptions import DriverLoadingError


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("drivers/infrahub", "drivers/infrahub"),
        ("./drivers/infrahub/", "drivers/infrahub"),
        ("drivers//./infrahub", "drivers/infrahub"),
        (" drivers/infrahub ", "drivers/infrahub"),
        (None, None),
        ("", None),
        (".", None),
        ("./", None),
        ("  ", None),
        ("a" * MAX_DRIVER_DIRECTORY_LENGTH, "a" * MAX_DRIVER_DIRECTORY_LENGTH),
        # Only the stored form counts towards the length.
        ("./" * 200 + "a", "a"),
    ],
)
def test_normalise_accepts_every_written_form(
    given: str | None, stored: str | None
) -> None:
    assert normalise_driver_directory(given) == stored


@pytest.mark.parametrize(
    ("given", "shown", "rule"),
    [
        ("/etc", "'/etc'", "it is an absolute path"),
        ("../x", "'../x'", "it contains a '..' segment"),
        ("a/../b", "'a/../b'", "it contains a '..' segment"),
        ("drivers\\infrahub", "'drivers\\infrahub'", "it contains a backslash"),
        ("a\x00b", "'a\\x00b'", "it contains a control character"),
        ("a\nb", "'a\\nb'", "it contains a control character"),
        ("a\tb", "'a\\tb'", "it contains a control character"),
        ("a\x7fb", "'a\\x7fb'", "it contains a control character"),
        ("a\x85b", "'a\\x85b'", "it contains a control character"),
        # Prefect fills in ``{{ ... }}`` in the working directory step (review item 1).
        (
            "drivers/{{ $SECRET_X }}",
            "'drivers/{{ $SECRET_X }}'",
            "it contains '{' or '}'",
        ),
        (
            "{{ prefect.blocks.secret.x }}",
            "'{{ prefect.blocks.secret.x }}'",
            "it contains '{' or '}'",
        ),
        ("a{b", "'a{b'", "it contains '{' or '}'"),
        ("a}b", "'a}b'", "it contains '{' or '}'"),
        (
            "a" * (MAX_DRIVER_DIRECTORY_LENGTH + 1),
            f"'{'a' * (MAX_DRIVER_DIRECTORY_LENGTH + 1)}'",
            f"it is longer than {MAX_DRIVER_DIRECTORY_LENGTH} characters",
        ),
    ],
)
def test_normalise_refuses_with_the_rule(given: str, shown: str, rule: str) -> None:
    with pytest.raises(DriverLoadingError) as excinfo:
        normalise_driver_directory(given)

    assert str(excinfo.value) == (
        f"Driver directory {shown} is refused: {rule}. "
        "Give a path relative to the repository root, such as 'drivers/infrahub'."
    )
    assert excinfo.value.error_code == "VALIDATION_ERROR"


@pytest.fixture
def clone_root(tmp_path: Path) -> Path:
    """A clone-like tree: a folder, a symlink inside, one to /etc and a dangling one."""
    root = tmp_path / "clone"
    (root / "drivers" / "a").mkdir(parents=True)
    (root / "drivers" / "inner").symlink_to(
        root / "drivers" / "a", target_is_directory=True
    )
    (root / "drivers" / "evil").symlink_to("/etc", target_is_directory=True)
    (root / "drivers" / "dangling").symlink_to(tmp_path / "missing")
    return root


def test_resolve_inside_accepts_the_root_and_a_folder(clone_root: Path) -> None:
    assert resolve_inside(clone_root, ".") == clone_root.resolve()
    assert (
        resolve_inside(clone_root, "drivers/a")
        == clone_root.resolve() / "drivers" / "a"
    )
    assert (
        resolve_inside(clone_root, Path("drivers") / "a")
        == clone_root.resolve() / "drivers" / "a"
    )


def test_resolve_inside_follows_a_symlink_that_stays_inside(clone_root: Path) -> None:
    assert (
        resolve_inside(clone_root, "drivers/inner")
        == clone_root.resolve() / "drivers" / "a"
    )


@pytest.mark.parametrize(
    "relative", ["drivers/evil", "drivers/evil/hostname", "drivers/dangling", ".."]
)
def test_resolve_inside_refuses_paths_that_leave_the_root(
    clone_root: Path, relative: str
) -> None:
    assert resolve_inside(clone_root, relative) is None


@pytest.mark.parametrize(
    ("text", "redacted"),
    [
        ("https://user:token@github.com/o/r.git", "https://github.com/o/r.git"),
        ("https://github.com/o/r.git", "https://github.com/o/r.git"),
        ("git://git-server/x.git", "git://git-server/x.git"),
        ("/tmp/repo", "/tmp/repo"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("https://[bad/x.git", "https://[bad/x.git"),
        ("https://user:token@[bad/x.git", "https://[bad/x.git"),
        ("https://user:tok@en@[bad", "https://[bad"),
        ("ssh://git@host:22/o/r.git", "ssh://host:22/o/r.git"),
        # A clone error can name several URLs (review item 16).
        (
            "unable to reach https://u:t@a.example/x.git, "
            "redirected to HTTPS://u:t@b.example/x.git",
            "unable to reach https://a.example/x.git, "
            "redirected to HTTPS://b.example/x.git",
        ),
        ("https://host/path@x", "https://host/path@x"),
    ],
)
def test_redact_user_info_removes_user_info(text: str, redacted: str) -> None:
    assert redact_user_info(text) == redacted


def test_driver_directory_digest_has_12_characters() -> None:
    digest = driver_directory_digest("drivers/infrahub")

    assert digest == "c8dc0c0d9f46"
    assert digest != driver_directory_digest("drivers/infrahub2")
