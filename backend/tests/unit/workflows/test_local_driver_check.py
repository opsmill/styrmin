"""An action of a driver version loaded from a local directory runs from its path.

Spec 029, user story 1 (FR-001, FR-002, research R-001): the Prefect deployment
of such an action has the entrypoint ``actions.py:<function>`` and one pull
step, ``check_local_driver``. When the driver files at the path have the
provenance fingerprint of the driver version, the step returns the path, and
Prefect imports the action from it. These tests run Prefect's own pull-step
runner and flow loader against a copy of the ``simple-app`` example driver.

The error paths are in user story 2 (task T025).
"""

from __future__ import annotations

import logging
import shutil
import sys
import uuid
from pathlib import Path

import pytest
from prefect.deployments.steps import core as steps_core
from prefect.deployments.steps.core import run_steps
from prefect.flows import load_flow_from_entrypoint
from prefect.settings import PREFECT_LOGGING_TO_API_ENABLED, temporary_settings

from styrmin_backend import config
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    HookKind,
)
from styrmin_backend.services.driver.models.structure.source import LocalSource
from styrmin_backend.services.user import ActionsWorkflowBuilder
from styrmin_backend.workflows.local_driver import FLOW_RUN_ID_ENV, check_local_driver
from styrmin_backend.workflows.models import LocalDriverActionWorkflowDefinition

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_SIMPLE_APP = _REPOSITORY_ROOT / "driver" / "examples" / "simple-app"
CHECK_STEP = "styrmin_backend.workflows.local_driver.check_local_driver"


@pytest.fixture
def driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A copy of ``simple-app``, which declares three actions, outside the repository.

    Restores the working directory, ``sys.path`` and ``sys.modules``, which
    Prefect's script loader changes. The step inputs hold no templates, so the
    resolvers that would need a Prefect API are replaced with the identity.
    """
    directory = Path(
        shutil.copytree(
            _SIMPLE_APP,
            tmp_path / "simple-app",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    )

    async def _identity(inputs):
        return inputs

    monkeypatch.setattr(steps_core, "resolve_block_document_references", _identity)
    monkeypatch.setattr(steps_core, "resolve_variables", _identity)
    monkeypatch.delenv(FLOW_RUN_ID_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    saved_path = list(sys.path)
    yield directory
    sys.path[:] = saved_path
    for name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", None)
        if module_file and Path(module_file).is_relative_to(tmp_path):
            del sys.modules[name]


def _content_hash(directory: Path) -> str:
    """The provenance fingerprint that loading the driver from ``directory`` stores."""
    content_hash = get_local_driver_loader(str(directory)).load_driver().content_hash
    assert content_hash is not None
    return content_hash


def _action(name: str, image: str | None = None) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        location=f"actions.py::{name}",
        description=name,
        hook=HookKind.SETUP,
        mode="pre",
        image=image,
    )


def _definition(
    directory: Path, action: ActionDefinition
) -> LocalDriverActionWorkflowDefinition:
    """The workflow definition that registering ``action`` of a local load builds."""
    builder = ActionsWorkflowBuilder(
        source=LocalSource(path=str(directory)),
        content_hash=_content_hash(directory),
    )
    workflow = builder.build_user_action_workflow_definition(action=action)
    assert isinstance(workflow, LocalDriverActionWorkflowDefinition)
    return workflow


def _check_inputs(directory: Path) -> dict[str, str]:
    driver_settings = config.SETTINGS.driver
    return {
        "directory": str(directory),
        "content_hash": _content_hash(directory),
        "spec_file": driver_settings.spec_file,
        "values_template": driver_settings.values_template,
        "actions_file": driver_settings.actions_code_file,
    }


# ---------------------------------------------------------------------------
# The pull step
# ---------------------------------------------------------------------------


def test_check_returns_the_driver_directory_and_logs_the_fingerprint(
    driver: Path, caplog: pytest.LogCaptureFixture
) -> None:
    inputs = _check_inputs(driver)
    caplog.set_level(logging.INFO)

    assert check_local_driver(**inputs) == {"directory": str(driver)}

    lines = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO
    ]
    assert len(lines) == 1
    assert str(driver) in lines[0]
    assert inputs["content_hash"][:7] in lines[0]


def test_check_logs_the_fingerprint_in_the_flow_run_of_the_job(
    driver: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the action's Job, the line belongs to the flow run, so it shows in the run's logs."""
    inputs = _check_inputs(driver)
    flow_run_id = uuid.uuid4()
    monkeypatch.setenv(FLOW_RUN_ID_ENV, str(flow_run_id))
    caplog.set_level(logging.INFO)

    with temporary_settings({PREFECT_LOGGING_TO_API_ENABLED: False}):
        assert check_local_driver(**inputs) == {"directory": str(driver)}

    (record,) = [record for record in caplog.records if record.levelno == logging.INFO]
    assert record.flow_run_id == str(flow_run_id)
    assert inputs["content_hash"][:7] in record.getMessage()


async def test_prefect_runs_the_pull_step_then_imports_the_action_from_the_path(
    driver: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deployment = await _definition(driver, _action("pre_setup")).to_deployment()

    output = await run_steps(deployment["pull_steps"])

    assert output["directory"] == str(driver)
    # Prefect's flow engine changes into the directory of the last step that returned one.
    monkeypatch.chdir(output["directory"])
    # ``use_placeholder_flow=False`` as in Prefect's flow engine.
    flow = load_flow_from_entrypoint(
        deployment["entrypoint"], use_placeholder_flow=False
    )
    assert flow.fn.__name__ == "pre_setup"
    assert (
        Path(flow.fn.__code__.co_filename).resolve()
        == (driver / "actions.py").resolve()
    )


# ---------------------------------------------------------------------------
# The Prefect deployment of a local driver version's action
# ---------------------------------------------------------------------------


async def test_deployment_has_the_entrypoint_and_the_single_check_step(
    driver: Path,
) -> None:
    deployment = await _definition(driver, _action("pre_setup")).to_deployment()

    assert deployment["entrypoint"] == "actions.py:pre_setup"
    assert deployment["pull_steps"] == [{CHECK_STEP: _check_inputs(driver)}]
    assert "job_variables" not in deployment


async def test_deployment_runs_in_the_image_of_the_action(driver: Path) -> None:
    action = _action(
        "post_setup", image="registry.example.com/simple-app-actions:1.2.3"
    )

    deployment = await _definition(driver, action).to_deployment()

    assert deployment["entrypoint"] == "actions.py:post_setup"
    assert deployment["job_variables"] == {
        "image": "registry.example.com/simple-app-actions:1.2.3"
    }
    assert deployment["pull_steps"] == [{CHECK_STEP: _check_inputs(driver)}]


def test_builder_with_a_local_source_builds_a_local_driver_action(driver: Path) -> None:
    workflow = _definition(driver, _action("pre_setup"))

    assert workflow.name == "User Action: pre_setup"
    assert workflow.directory == str(driver)
    assert workflow.content_hash == _content_hash(driver)


def test_get_function_imports_the_action_from_the_path(driver: Path) -> None:
    """The in-process executor runs the same check, then imports the action from the path."""
    function = _definition(driver, _action("pre_setup")).get_function()

    assert function.__name__ == "pre_setup"
    assert (
        Path(function.fn.__code__.co_filename).resolve()
        == (driver / "actions.py").resolve()
    )
