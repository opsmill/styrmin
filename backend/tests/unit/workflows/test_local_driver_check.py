"""An action of a driver version loaded from a local directory runs from its path.

Spec 029, user story 1 (FR-001, FR-002, research R-001): the Prefect deployment
of such an action has the entrypoint ``actions.py:<function>`` and one pull
step, ``check_local_driver``. When the driver files at the path have the
provenance fingerprint of the driver version, the step returns the path, and
Prefect imports the action from it. These tests run Prefect's own pull-step
runner and flow loader against a copy of the ``simple-app`` example driver.

User story 2 (FR-003, FR-004, research R-006): when the files are missing or
differ, the check raises an error that names the path, the image of the
action's Job and, for changed files, both short provenance fingerprints
(contracts/errors.md, "Must contain").
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from prefect.deployments.steps import core as steps_core
from prefect.deployments.steps.core import run_steps
from prefect.flows import load_flow_from_entrypoint
from prefect.settings import PREFECT_LOGGING_TO_API_ENABLED, temporary_settings

from styrmin_backend import config
from styrmin_backend.services.driver.exceptions import (
    DriverFilesNotFoundError,
    DriverFingerprintMismatchError,
)
from styrmin_backend.services.driver.hash import compute_driver_directory_fingerprint
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    HookKind,
)
from styrmin_backend.services.driver.models.structure.source import LocalSource
from styrmin_backend.services.user import ActionsWorkflowBuilder
from styrmin_backend.workflows import local_driver
from styrmin_backend.workflows.local_driver import (
    FLOW_RUN_ID_ENV,
    check_local_driver,
)
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


# ---------------------------------------------------------------------------
# Missing driver files (FR-004)
# ---------------------------------------------------------------------------

# Outside an action's Job, no flow run tells which image runs the check.
UNKNOWN_IMAGE_WORDS = "in the image of this action's Job"


def _assert_names_the_fix(message: str, path: str) -> None:
    """The missing-files error says how to fix the image or the load."""
    assert "An action's image must hold the driver at the same path" in message
    assert f"Add the driver to the image at {path}" in message
    assert "load the driver from a path that the image holds" in message


def test_missing_directory_raises_the_missing_files_error(driver: Path) -> None:
    inputs = _check_inputs(driver)
    shutil.rmtree(driver)

    with pytest.raises(DriverFilesNotFoundError) as raised:
        check_local_driver(**inputs)

    message = str(raised.value)
    assert message.startswith(
        f"The driver files are not at {driver} {UNKNOWN_IMAGE_WORDS}: "
        f"{driver} not found. "
    )
    _assert_names_the_fix(message, str(driver))
    assert raised.value.missing == [str(driver)]


@pytest.mark.parametrize(
    "file_name",
    [
        pytest.param("actions.py", id="actions-file"),
        pytest.param("driver.styrmin.yml", id="driver-specification-file"),
    ],
)
def test_missing_driver_file_raises_the_missing_files_error(
    driver: Path, file_name: str
) -> None:
    inputs = _check_inputs(driver)
    (driver / file_name).unlink()

    with pytest.raises(DriverFilesNotFoundError) as raised:
        check_local_driver(**inputs)

    message = str(raised.value)
    assert message.startswith(
        f"The driver files are not at {driver} {UNKNOWN_IMAGE_WORDS}: "
        f"{file_name} not found. "
    )
    _assert_names_the_fix(message, str(driver))
    assert raised.value.missing == [file_name]


# ---------------------------------------------------------------------------
# Changed driver files (FR-003)
# ---------------------------------------------------------------------------


def _assert_fingerprint_error(
    error: DriverFingerprintMismatchError,
    *,
    driver: Path,
    expected: str,
    image_words: str,
) -> None:
    """The error names the path, the image, both short fingerprints and the fix."""
    actual = compute_driver_directory_fingerprint(
        driver,
        spec_file=config.SETTINGS.driver.spec_file,
        values_template=config.SETTINGS.driver.values_template,
        actions_file=config.SETTINGS.driver.actions_code_file,
        include_actions=True,
    )
    assert actual != expected
    message = str(error)
    assert message.startswith(
        f"The driver files at {driver} {image_words} are not the files of this "
        f"driver version: their provenance fingerprint is {actual[:7]}, and the "
        f"driver version was loaded with {expected[:7]}. "
    )
    assert "Rebuild the image with the files you loaded" in message
    assert f"load the driver again from {driver}" in message
    assert (error.expected, error.actual) == (expected, actual)


@pytest.mark.parametrize(
    "file_name",
    [
        pytest.param("actions.py", id="actions-file"),
        pytest.param("values.j2.yml", id="values-template"),
        pytest.param("driver.styrmin.yml", id="driver-specification-file"),
    ],
)
def test_edited_driver_file_raises_the_fingerprint_error(
    driver: Path, file_name: str
) -> None:
    inputs = _check_inputs(driver)
    with (driver / file_name).open("a") as file:
        file.write("\n# edited after the driver was loaded\n")

    with pytest.raises(DriverFingerprintMismatchError) as raised:
        check_local_driver(**inputs)

    _assert_fingerprint_error(
        raised.value,
        driver=driver,
        expected=inputs["content_hash"],
        image_words=UNKNOWN_IMAGE_WORDS,
    )


def test_removed_values_template_raises_the_fingerprint_error(driver: Path) -> None:
    """A missing values template hashes as empty, as in the loader: the files differ."""
    inputs = _check_inputs(driver)
    (driver / inputs["values_template"]).unlink()

    with pytest.raises(DriverFingerprintMismatchError) as raised:
        check_local_driver(**inputs)

    _assert_fingerprint_error(
        raised.value,
        driver=driver,
        expected=inputs["content_hash"],
        image_words=UNKNOWN_IMAGE_WORDS,
    )


# ---------------------------------------------------------------------------
# The image named in the errors (research R-006)
# ---------------------------------------------------------------------------

WORK_POOL = "user-work-pool"
ACTION_IMAGE = "registry.example.com/simple-app-actions:1.2.3"
WORK_POOL_IMAGE = "registry.opsmill.io/opsmill/styrmin:1.4.0"


class FakePrefectClient:
    """The synchronous Prefect client of the action's Job, with one flow run.

    The flow run belongs to a deployment whose job variables hold
    ``job_variables`` and to the work pool ``work_pool``, whose base job
    template has the default image ``work_pool_image``. A read named in
    ``failing_reads`` raises.
    """

    def __init__(
        self,
        flow_run_id: uuid.UUID,
        *,
        job_variables: dict[str, Any] | None = None,
        work_pool: str | None = WORK_POOL,
        work_pool_image: str | None = None,
        failing_reads: tuple[str, ...] = (),
    ) -> None:
        self.flow_run_id = flow_run_id
        self.deployment_id = uuid.uuid4()
        self.job_variables = job_variables or {}
        self.work_pool = work_pool
        self.work_pool_image = work_pool_image
        self.failing_reads = failing_reads

    def __enter__(self) -> FakePrefectClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def _read(self, name: str) -> None:
        if name in self.failing_reads:
            raise RuntimeError(f"Prefect API is unreachable ({name})")

    def read_flow_run(self, flow_run_id: uuid.UUID) -> SimpleNamespace:
        self._read("flow_run")
        assert flow_run_id == self.flow_run_id
        return SimpleNamespace(
            deployment_id=self.deployment_id, work_pool_name=self.work_pool
        )

    def read_deployment(self, deployment_id: uuid.UUID) -> SimpleNamespace:
        self._read("deployment")
        assert deployment_id == self.deployment_id
        return SimpleNamespace(
            job_variables=self.job_variables, work_pool_name=self.work_pool
        )

    def read_work_pool(self, work_pool_name: str) -> SimpleNamespace:
        self._read("work_pool")
        assert work_pool_name == self.work_pool
        properties = (
            {"image": {"type": "string", "default": self.work_pool_image}}
            if self.work_pool_image
            else {}
        )
        return SimpleNamespace(
            base_job_template={"variables": {"properties": properties}}
        )


@pytest.fixture
def job_flow_run_id(monkeypatch: pytest.MonkeyPatch):
    """The check runs in an action's Job: ``PREFECT__FLOW_RUN_ID`` is set.

    Flow run logs stay local, because no Prefect API takes them.
    """
    flow_run_id = uuid.uuid4()
    monkeypatch.setenv(FLOW_RUN_ID_ENV, str(flow_run_id))
    with temporary_settings({PREFECT_LOGGING_TO_API_ENABLED: False}):
        yield flow_run_id


def _use_prefect_client(
    monkeypatch: pytest.MonkeyPatch, client: FakePrefectClient
) -> None:
    def _get_client(sync_client: bool = False) -> FakePrefectClient:
        assert sync_client
        return client

    monkeypatch.setattr(local_driver, "get_client", _get_client)


@pytest.mark.parametrize(
    ("client_options", "image_words", "image", "work_pool"),
    [
        pytest.param(
            {"job_variables": {"image": ACTION_IMAGE}},
            f"in the image {ACTION_IMAGE}",
            ACTION_IMAGE,
            WORK_POOL,
            id="image-of-the-action",
        ),
        pytest.param(
            {"work_pool_image": WORK_POOL_IMAGE},
            f"in the image {WORK_POOL_IMAGE}",
            WORK_POOL_IMAGE,
            WORK_POOL,
            id="default-image-of-the-work-pool",
        ),
        pytest.param(
            {},
            f"in the default image of the work pool {WORK_POOL}",
            None,
            WORK_POOL,
            id="work-pool-without-a-default-image",
        ),
        pytest.param(
            {"work_pool_image": WORK_POOL_IMAGE, "failing_reads": ("deployment",)},
            f"in the default image of the work pool {WORK_POOL}",
            None,
            WORK_POOL,
            id="deployment-read-fails",
        ),
        pytest.param(
            {"work_pool": None},
            "in the image of this action's Job",
            None,
            None,
            id="unknown-work-pool",
        ),
        pytest.param(
            {"failing_reads": ("flow_run",)},
            "in the image of this action's Job",
            None,
            None,
            id="flow-run-read-fails",
        ),
    ],
)
def test_missing_files_error_names_the_image_of_the_job(
    driver: Path,
    job_flow_run_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    client_options: dict[str, Any],
    image_words: str,
    image: str | None,
    work_pool: str | None,
) -> None:
    inputs = _check_inputs(driver)
    (driver / "actions.py").unlink()
    _use_prefect_client(
        monkeypatch, FakePrefectClient(job_flow_run_id, **client_options)
    )

    with pytest.raises(DriverFilesNotFoundError) as raised:
        check_local_driver(**inputs)

    assert str(raised.value).startswith(
        f"The driver files are not at {driver} {image_words}: actions.py not found. "
    )
    assert (raised.value.image, raised.value.work_pool) == (image, work_pool)


def test_failed_image_read_is_logged_and_the_error_still_raises(
    driver: Path,
    job_flow_run_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    inputs = _check_inputs(driver)
    (driver / "actions.py").unlink()
    _use_prefect_client(
        monkeypatch, FakePrefectClient(job_flow_run_id, failing_reads=("deployment",))
    )
    caplog.set_level(logging.WARNING)

    with pytest.raises(DriverFilesNotFoundError):
        check_local_driver(**inputs)

    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert record.getMessage() == (
        "Could not read the image of this action's Job from the Prefect API; the "
        f"error names the default image of the work pool {WORK_POOL} instead."
    )
    assert record.flow_run_id == str(job_flow_run_id)


def test_fingerprint_error_names_the_image_of_the_action(
    driver: Path, job_flow_run_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _check_inputs(driver)
    with (driver / "actions.py").open("a") as file:
        file.write("\n# edited after the driver was loaded\n")
    _use_prefect_client(
        monkeypatch,
        FakePrefectClient(job_flow_run_id, job_variables={"image": ACTION_IMAGE}),
    )

    with pytest.raises(DriverFingerprintMismatchError) as raised:
        check_local_driver(**inputs)

    _assert_fingerprint_error(
        raised.value,
        driver=driver,
        expected=inputs["content_hash"],
        image_words=f"in the image {ACTION_IMAGE}",
    )


# ---------------------------------------------------------------------------
# The in-process executor runs the same check before it imports (critique E2)
# ---------------------------------------------------------------------------


def _imported_from(directory: Path) -> list[str]:
    return [
        name
        for name, module in sys.modules.items()
        if getattr(module, "__file__", None)
        and Path(module.__file__).is_relative_to(directory)
    ]


def test_get_function_raises_the_missing_files_error_before_it_imports(
    driver: Path,
) -> None:
    definition = _definition(driver, _action("pre_setup"))
    (driver / "actions.py").unlink()

    with pytest.raises(DriverFilesNotFoundError) as raised:
        definition.get_function()

    assert raised.value.missing == ["actions.py"]
    assert str(driver) in str(raised.value)


def test_get_function_raises_the_fingerprint_error_before_it_imports(
    driver: Path,
) -> None:
    """The edited ``actions.py`` would raise when imported; the check raises first."""
    definition = _definition(driver, _action("pre_setup"))
    with (driver / "actions.py").open("a") as file:
        file.write('\nraise RuntimeError("the edited actions.py was imported")\n')

    with pytest.raises(DriverFingerprintMismatchError) as raised:
        definition.get_function()

    _assert_fingerprint_error(
        raised.value,
        driver=driver,
        expected=definition.content_hash,
        image_words=UNKNOWN_IMAGE_WORDS,
    )
    assert _imported_from(driver) == []


# ---------------------------------------------------------------------------
# The action's Job has no server settings and no database (critique E1)
# ---------------------------------------------------------------------------


def test_check_module_imports_with_an_empty_environment() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import styrmin_backend.workflows.local_driver; "
            "assert 'styrmin_backend.config' not in sys.modules; "
            "assert 'sqlalchemy' not in sys.modules",
        ],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
