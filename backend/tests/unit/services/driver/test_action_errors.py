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
AGENT_POD = "styrmin-agent-7c9d8-x2k4q"
EXPECTED = "0a7d3f1" + "e" * 57
ACTUAL = "9b1e2c4" + "f" * 57


def test_driver_files_not_found_error_names_path_agent_pod_and_missing_files() -> None:
    error = DriverFilesNotFoundError(
        path=PATH, missing=["driver.styrmin.yml", "actions.py"], agent_pod=AGENT_POD
    )

    assert isinstance(error, DriverError)
    assert error.error_code == "NOT_FOUND"
    assert str(error) == (
        f"The driver files are not at {PATH} in the Styrmin agent pod {AGENT_POD}: "
        "driver.styrmin.yml, actions.py not found. The agent pod runs every driver "
        "action, so it must hold the driver at the same path as the Styrmin server. "
        f"Mount or copy the driver into the agent pod at {PATH}, or load the driver "
        "from a path that both the server and the agent pod hold."
    )
    assert error.error_metadata == {
        "path": PATH,
        "agent_pod": AGENT_POD,
        "missing": ["driver.styrmin.yml", "actions.py"],
    }


def test_driver_files_not_found_error_names_a_missing_directory() -> None:
    error = DriverFilesNotFoundError(path=PATH, missing=[PATH])

    assert f"{PATH} not found" in str(error)


def test_driver_fingerprint_mismatch_error_shows_both_short_fingerprints_and_the_fix() -> (
    None
):
    error = DriverFingerprintMismatchError(
        path=PATH, expected=EXPECTED, actual=ACTUAL, agent_pod=AGENT_POD
    )

    assert isinstance(error, DriverError)
    assert error.error_code == "VALIDATION_ERROR"
    # The message shows the short forms only, as driver version labels do.
    assert str(error) == (
        f"The driver files at {PATH} in the Styrmin agent pod {AGENT_POD} are not the "
        "files of this driver version: their provenance fingerprint is 9b1e2c4, and "
        "the driver version was loaded with 0a7d3f1. If the files changed after the "
        "driver was loaded, load the driver again and use the new driver version: "
        f"styrminctl drivers load-local-version {PATH}. If the agent pod holds other "
        f"files at {PATH} than the Styrmin server, give both the same files first."
    )
    assert error.error_metadata == {
        "path": PATH,
        "agent_pod": AGENT_POD,
        "expected": EXPECTED,
        "actual": ACTUAL,
    }


def test_the_errors_name_the_agent_pod_without_its_name_when_it_is_not_known() -> None:
    missing = DriverFilesNotFoundError(path=PATH, missing=["actions.py"])
    mismatch = DriverFingerprintMismatchError(
        path=PATH, expected=EXPECTED, actual=ACTUAL
    )

    assert str(missing).startswith(
        f"The driver files are not at {PATH} in the Styrmin agent pod: actions.py "
        "not found. "
    )
    assert str(mismatch).startswith(
        f"The driver files at {PATH} in the Styrmin agent pod are not the files of "
        "this driver version: "
    )


def test_the_load_command_in_the_fingerprint_error_quotes_the_path() -> None:
    error = DriverFingerprintMismatchError(
        path="/srv/my drivers/app", expected=EXPECTED, actual=ACTUAL
    )

    assert "styrminctl drivers load-local-version '/srv/my drivers/app'." in str(error)


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
    """The action's process imports the errors without server settings or a database."""
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
