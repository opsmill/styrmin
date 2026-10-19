"""Unit tests for the typed errors of spec 029 (contracts/errors.md).

Each test builds an error with sample values and checks that the message
holds every part listed under "Must contain", so that a user can fix the
problem from the message alone (SC-003).
"""

import os
import subprocess
import sys

import pytest

from styrmin_backend.services.driver.exceptions import (
    ActionNotRegisteredError,
    DriverError,
    DriverFilesNotFoundError,
    DriverFingerprintMismatchError,
)
from styrmin_backend.services.driver.models.resources.actions import HookKind

PATH = "/styrmin/drivers/my-app"
IMAGE = "registry.opsmill.io/opsmill/styrmin:latest"
EXPECTED = "0a7d3f1" + "e" * 57
ACTUAL = "9b1e2c4" + "f" * 57


def test_driver_files_not_found_error_names_path_image_and_missing_files() -> None:
    error = DriverFilesNotFoundError(
        path=PATH, image=IMAGE, missing=["driver.styrmin.yml", "actions.py"]
    )

    message = str(error)
    assert isinstance(error, DriverError)
    assert error.error_code == "NOT_FOUND"
    for part in (PATH, IMAGE, "driver.styrmin.yml", "actions.py"):
        assert part in message
    assert error.error_metadata == {
        "path": PATH,
        "image": IMAGE,
        "work_pool": None,
        "missing": ["driver.styrmin.yml", "actions.py"],
    }


def test_driver_files_not_found_error_names_a_missing_directory() -> None:
    error = DriverFilesNotFoundError(path=PATH, image=IMAGE, missing=[PATH])

    assert f"{PATH} not found" in str(error)


def test_driver_fingerprint_mismatch_error_shows_both_short_fingerprints() -> None:
    error = DriverFingerprintMismatchError(
        path=PATH, image=IMAGE, expected=EXPECTED, actual=ACTUAL
    )

    message = str(error)
    assert isinstance(error, DriverError)
    assert error.error_code == "VALIDATION_ERROR"
    for part in (
        PATH,
        IMAGE,
        "9b1e2c4",
        "0a7d3f1",
        "Rebuild the image",
        "load the driver again",
    ):
        assert part in message
    # The message shows the short forms only, as driver version labels do.
    assert EXPECTED not in message
    assert ACTUAL not in message
    assert error.error_metadata == {
        "path": PATH,
        "image": IMAGE,
        "work_pool": None,
        "expected": EXPECTED,
        "actual": ACTUAL,
    }


# The image of the action's Job is named in a sentence that reads correctly
# whether the image, only its work pool, or neither is known (research R-006).
IMAGE_CASES = [
    pytest.param(IMAGE, "user-work-pool", f"the image {IMAGE}", id="image-known"),
    pytest.param(
        None,
        "user-work-pool",
        "the default image of the work pool user-work-pool",
        id="work-pool-known",
    ),
    pytest.param(None, None, "the image of this action's Job", id="nothing-known"),
]


@pytest.mark.parametrize(("image", "work_pool", "image_words"), IMAGE_CASES)
def test_driver_files_not_found_error_names_the_image_in_a_sentence(
    image: str | None, work_pool: str | None, image_words: str
) -> None:
    error = DriverFilesNotFoundError(
        path=PATH, image=image, work_pool=work_pool, missing=["actions.py"]
    )

    assert str(error).startswith(
        f"The driver files are not at {PATH} in {image_words}: actions.py not found. "
    )
    assert error.error_metadata["image"] == image
    assert error.error_metadata["work_pool"] == work_pool


@pytest.mark.parametrize(("image", "work_pool", "image_words"), IMAGE_CASES)
def test_driver_fingerprint_mismatch_error_names_the_image_in_a_sentence(
    image: str | None, work_pool: str | None, image_words: str
) -> None:
    error = DriverFingerprintMismatchError(
        path=PATH, image=image, work_pool=work_pool, expected=EXPECTED, actual=ACTUAL
    )

    assert str(error).startswith(
        f"The driver files at {PATH} in {image_words} are not the files of this "
        "driver version: "
    )
    assert error.error_metadata["image"] == image
    assert error.error_metadata["work_pool"] == work_pool


@pytest.mark.parametrize(
    "load_command",
    [
        pytest.param(
            "styrminctl drivers load-local-version /styrmin/drivers/my-app",
            id="local",
        ),
        pytest.param(
            "styrminctl drivers load-version https://github.com/opsmill/drivers main",
            id="git-repository-root",
        ),
        pytest.param(
            "styrminctl drivers load-version https://github.com/opsmill/drivers main"
            " --driver-directory drivers/my-app",
            id="git-driver-directory",
        ),
    ],
)
def test_action_not_registered_error_names_actions_hook_mode_and_load_command(
    load_command: str,
) -> None:
    error = ActionNotRegisteredError(
        driver_name="my-app",
        driver_version_label="1@0123abc",
        actions=["migrate_schema", "warm_cache"],
        hook=HookKind.UPGRADE,
        mode="core",
        load_command=load_command,
    )

    message = str(error)
    assert isinstance(error, DriverError)
    assert error.error_code == "NOT_FOUND"
    for part in (
        "my-app",
        "1@0123abc",
        "migrate_schema",
        "warm_cache",
        "upgrade hook",
        "mode core",
        "Load the driver again",
        load_command,
        "request the change again",
    ):
        assert part in message
    assert error.hook is HookKind.UPGRADE
    assert error.mode == "core"
    assert error.error_metadata == {
        "driver": "my-app",
        "driver_version": "1@0123abc",
        "actions": ["migrate_schema", "warm_cache"],
        "hook": "upgrade",
        "mode": "core",
    }


def test_exceptions_module_imports_with_an_empty_environment() -> None:
    """The action's Job imports the errors without server settings or a database."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import styrmin_backend.services.driver.exceptions; "
            "assert 'styrmin_backend.config' not in sys.modules; "
            "assert 'sqlalchemy' not in sys.modules",
        ],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
