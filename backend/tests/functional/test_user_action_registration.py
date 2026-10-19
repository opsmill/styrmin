"""User-action registrations against a real Prefect server (#373, spec 029).

The unit tests mock the Prefect client, so they never see that Prefect
upserts deployments on ``(flow, name)``. Here every registration goes
through ``PrefectManager`` to a ``prefect_test_harness`` server, and each
(driver, driver version, action) must keep its own deployment.

Spec 029 (FR-001, FR-002): the actions of a driver loaded from a local
directory are registered with the driver directory of that path and a pull
step that checks the driver files before the action runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import WorkPoolCreate
from prefect.client.schemas.filters import DeploymentFilter, DeploymentFilterTags
from prefect.client.schemas.responses import DeploymentResponse
from prefect.testing.utilities import prefect_test_harness

from styrmin_backend import config
from styrmin_backend.services.applications import ensure_action_registrations
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    HookKind,
)
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.user import ActionsWorkflowBuilder
from styrmin_backend.services.workflow.local import WorkflowLocalExecutor
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.local_driver import CHECK_LOCAL_DRIVER_STEP
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectWorkPool

_EXAMPLES = Path(__file__).resolve().parents[3] / "driver" / "examples"

# The bundled drivers that declare actions.
BUNDLED_DRIVERS_WITH_ACTIONS = [
    "infrahub",
    "infrahub-enterprise",
    "semaphore",
    "simple-app",
    "slurpit",
]

# Every bundled driver with actions declares these three.
ACTIONS: list[tuple[str, HookKind, Literal["pre", "core", "post"]]] = [
    ("pre_setup", HookKind.SETUP, "pre"),
    ("post_setup", HookKind.SETUP, "post"),
    ("upgrade", HookKind.UPGRADE, "core"),
]


@pytest.fixture(autouse=True, scope="module")
def prefect_server():
    with prefect_test_harness():
        yield


@pytest.fixture
async def manager() -> PrefectManager:
    catalogue = PrefectCatalogue()
    async with get_client() as client:
        await client.create_work_pool(
            work_pool=WorkPoolCreate(
                name=PrefectWorkPool.USER_WORK_POOL.value, type="process"
            ),
            overwrite=True,
        )
        for deployment in await client.read_deployments():
            await client.delete_deployment(deployment.id)
    manager = PrefectManager(
        catalogue=catalogue, workflow_executor=WorkflowLocalExecutor()
    )
    await manager.register_token(namespace="user", token="default")
    return manager


async def _load_driver(
    manager: PrefectManager, application: str, version: str, fingerprint: str | None
) -> None:
    """Register the driver's actions the way ``load_application_driver_from_object`` does."""
    builder = ActionsWorkflowBuilder(
        source=GitSource(
            repository=f"git://git-server/{application}.git",
            branch="master",
            token="default",
        )
    )
    for name, hook, mode in ACTIONS:
        action = ActionDefinition(
            name=name,
            description=name,
            hook=hook,
            mode=mode,
            location=f"actions.py::{name}",
        )
        await manager.register_user_action(
            workflow=builder.build_user_action_workflow_definition(action=action),
            application=application,
            version=version,
            hook=hook,
            mode=mode,
            fingerprint=fingerprint,
            driver_directory=None,
        )


async def _lookup(
    manager: PrefectManager, application: str, version: str, fingerprint: str | None
) -> dict[str, object]:
    return {
        name: await manager.get_user_action_deployment_id(
            application=application,
            version=version,
            hook=hook,
            mode=mode,
            fingerprint=fingerprint,
            driver_directory=None,
        )
        for name, hook, mode in ACTIONS
    }


async def test_two_drivers_with_the_same_action_names_keep_their_own_actions(
    manager: PrefectManager,
) -> None:
    await _load_driver(manager, "infrahub-enterprise", ">=1.5,<2.0", "d851c7e")
    await _load_driver(manager, "semaphore", ">=2.15,<2.17", "97e2903")

    enterprise = await _lookup(manager, "infrahub-enterprise", ">=1.5,<2.0", "d851c7e")
    semaphore = await _lookup(manager, "semaphore", ">=2.15,<2.17", "97e2903")

    assert all(enterprise.values()), enterprise
    assert all(semaphore.values()), semaphore
    assert set(enterprise.values()).isdisjoint(semaphore.values())


async def test_two_versions_of_one_driver_keep_their_own_actions(
    manager: PrefectManager,
) -> None:
    await _load_driver(manager, "lab-driver-a", ">=1.0.0", "555d155")
    await _load_driver(manager, "lab-driver-a", ">=1.0.0", "a1b2c3d")

    previous = await _lookup(manager, "lab-driver-a", ">=1.0.0", "555d155")
    latest = await _lookup(manager, "lab-driver-a", ">=1.0.0", "a1b2c3d")

    assert all(previous.values()), previous
    assert all(latest.values()), latest
    assert set(previous.values()).isdisjoint(latest.values())


async def test_two_drivers_sharing_a_fingerprint_keep_their_own_actions(
    manager: PrefectManager,
) -> None:
    """The short fingerprint is a 7-char prefix: the driver is in the key too."""
    await _load_driver(manager, "lab-driver-a", ">=1.0.0", "555d155")
    await _load_driver(manager, "lab-driver-b", ">=1.0.0", "555d155")

    a = await _lookup(manager, "lab-driver-a", ">=1.0.0", "555d155")
    b = await _lookup(manager, "lab-driver-b", ">=1.0.0", "555d155")

    assert all(a.values()), a
    assert all(b.values()), b
    assert set(a.values()).isdisjoint(b.values())


async def test_two_drivers_without_a_fingerprint_keep_their_own_actions(
    manager: PrefectManager,
) -> None:
    """Rows predating ADR-053 register without a fingerprint."""
    await _load_driver(manager, "lab-driver-a", ">=1.0.0", None)
    await _load_driver(manager, "lab-driver-b", ">=1.0.0", None)

    a = await _lookup(manager, "lab-driver-a", ">=1.0.0", None)
    b = await _lookup(manager, "lab-driver-b", ">=1.0.0", None)

    assert all(a.values()), a
    assert all(b.values()), b
    assert set(a.values()).isdisjoint(b.values())


async def _local_deployments(directory: str) -> list[DeploymentResponse]:
    """The deployments registered for the local driver version loaded from ``directory``."""
    async with get_client() as client:
        return await client.read_deployments(
            deployment_filter=DeploymentFilter(
                tags=DeploymentFilterTags(all_=[f"directory/{directory}"])
            )
        )


async def _lookup_local(
    manager: PrefectManager, driver: ApplicationDriver, directory: str
) -> dict[str, UUID | None]:
    """Look up each action's flow with the key of the driver version at ``directory``."""
    assert driver.content_hash is not None
    return {
        name: await manager.get_user_action_deployment_id(
            application=driver.driver_spec.metadata.name,
            version=driver.driver_spec.spec.supported_versions,
            hook=hook,
            mode=mode,
            fingerprint=driver.content_hash[:7],
            driver_directory=directory,
        )
        for name, hook, mode in ACTIONS
    }


def _check_step(directory: str, content_hash: str) -> dict[str, dict[str, str]]:
    """The pull step that checks the driver files at ``directory`` before an action runs."""
    driver_settings = config.SETTINGS.driver
    return {
        CHECK_LOCAL_DRIVER_STEP: {
            "directory": directory,
            "content_hash": content_hash,
            "spec_file": driver_settings.spec_file,
            "values_template": driver_settings.values_template,
            "actions_file": driver_settings.actions_code_file,
        }
    }


@pytest.mark.parametrize("driver_name", BUNDLED_DRIVERS_WITH_ACTIONS)
async def test_local_load_of_a_bundled_driver_registers_its_three_actions(
    manager: PrefectManager, driver_name: str
) -> None:
    """FR-001, SC-001: each action runs from the path, after a check of its files."""
    directory = str(_EXAMPLES / driver_name)
    driver = get_local_driver_loader(path=directory).load_driver()
    assert driver.content_hash is not None

    registered = await ensure_action_registrations(driver, manager)

    assert registered == 3
    deployments = await _local_deployments(directory)
    assert len(deployments) == 3
    for deployment in deployments:
        assert f"fingerprint/{driver.content_hash[:7]}" in deployment.tags
        assert f"directory/{directory}" in deployment.tags
        assert deployment.pull_steps == [_check_step(directory, driver.content_hash)]
    flows = await _lookup_local(manager, driver, directory)
    assert set(flows.values()) == {deployment.id for deployment in deployments}


async def test_two_paths_with_the_same_driver_files_keep_their_own_actions(
    manager: PrefectManager, tmp_path: Path
) -> None:
    """FR-002: the same files at two paths are two driver versions, each with its own actions."""
    first = str(shutil.copytree(_EXAMPLES / "semaphore", tmp_path / "a" / "semaphore"))
    second = str(shutil.copytree(_EXAMPLES / "semaphore", tmp_path / "b" / "semaphore"))
    first_driver = get_local_driver_loader(path=first).load_driver()
    second_driver = get_local_driver_loader(path=second).load_driver()
    assert first_driver.content_hash == second_driver.content_hash

    assert await ensure_action_registrations(first_driver, manager) == 3
    assert await ensure_action_registrations(second_driver, manager) == 3

    first_flows = await _lookup_local(manager, first_driver, first)
    second_flows = await _lookup_local(manager, second_driver, second)
    assert all(first_flows.values()), first_flows
    assert all(second_flows.values()), second_flows
    assert set(first_flows.values()).isdisjoint(second_flows.values())
    for directory in (first, second):
        deployments = await _local_deployments(directory)
        assert len(deployments) == 3
        for deployment in deployments:
            assert deployment.pull_steps is not None
            (step,) = deployment.pull_steps
            assert step[CHECK_LOCAL_DRIVER_STEP]["directory"] == directory
