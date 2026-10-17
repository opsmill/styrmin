"""An action of a driver directory imports only from that directory.

Spec 028 (US1-3, US1-4, FR-004, research R-001): the Prefect deployment of
such an action runs ``set_working_directory`` into the driver directory after
``git_clone``. Prefect's script loader then puts only the driver directory on
``sys.path``, so a module next to ``actions.py`` imports and a module at the
repository root does not. This test runs Prefect's own pull-step runner and
flow loader against a folder tree that stands for the clone.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from prefect.deployments.steps import core as steps_core
from prefect.deployments.steps.core import run_steps
from prefect.exceptions import ScriptError
from prefect.flows import load_flow_from_entrypoint

from styrmin_backend.workflows.utils import set_directory_pull_step

ACTIONS = """\
from prefect import flow

import helpers


@flow
def run_action():
    return helpers.MARKER
"""

ACTIONS_SHARED = """\
from prefect import flow

import shared


@flow
def run_shared_action():
    return shared.MARKER
"""


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``tmp_path/clone`` with ``drivers/a`` and a ``shared.py`` at its root.

    Restores the working directory, ``sys.path`` and ``sys.modules``, which
    ``set_working_directory`` and Prefect's script loader change. The step
    inputs hold no templates, so the resolvers that would need a Prefect API
    are replaced with the identity.
    """
    driver_directory = tmp_path / "clone" / "drivers" / "a"
    driver_directory.mkdir(parents=True)
    (driver_directory / "actions.py").write_text(ACTIONS)
    (driver_directory / "actions_shared.py").write_text(ACTIONS_SHARED)
    (driver_directory / "helpers.py").write_text('MARKER = "drivers/a helpers"\n')
    (tmp_path / "clone" / "shared.py").write_text('MARKER = "root shared"\n')

    async def _identity(inputs):
        return inputs

    monkeypatch.setattr(steps_core, "resolve_block_document_references", _identity)
    monkeypatch.setattr(steps_core, "resolve_variables", _identity)
    for name in ("helpers", "shared"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.chdir(tmp_path)
    saved_path = list(sys.path)
    yield tmp_path / "clone"
    sys.path[:] = saved_path
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if module_file and Path(module_file).is_relative_to(tmp_path):
            del sys.modules[name]


async def _set_working_directory() -> None:
    await run_steps(
        [set_directory_pull_step(directory="drivers/a", clone_directory_name="clone")]
    )


async def test_action_imports_a_module_of_its_driver_directory(clone: Path) -> None:
    await _set_working_directory()

    assert Path(os.getcwd()) == (clone / "drivers" / "a").resolve()
    # ``use_placeholder_flow=False`` as in Prefect's flow engine.
    flow = load_flow_from_entrypoint(
        "actions.py:run_action", use_placeholder_flow=False
    )
    assert flow.fn() == "drivers/a helpers"
    assert str(clone) not in sys.path
    assert str(clone.resolve()) not in sys.path


async def test_action_cannot_import_a_module_outside_its_driver_directory(
    clone: Path,
) -> None:
    await _set_working_directory()

    with pytest.raises((ScriptError, ModuleNotFoundError)) as excinfo:
        load_flow_from_entrypoint(
            "actions_shared.py:run_shared_action", use_placeholder_flow=False
        )

    error = excinfo.value
    cause = error.user_exc if isinstance(error, ScriptError) else error
    assert isinstance(cause, ModuleNotFoundError)
    assert cause.name == "shared"
