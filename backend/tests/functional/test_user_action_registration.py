"""User-action registrations against a real Prefect server (#373).

The unit tests mock the Prefect client, so they never see that Prefect
upserts deployments on ``(flow, name)``. Here every registration goes
through ``PrefectManager`` to a ``prefect_test_harness`` server, and each
(driver, driver version, action) must keep its own deployment.
"""

from __future__ import annotations

from typing import Literal

import pytest
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import WorkPoolCreate
from prefect.testing.utilities import prefect_test_harness

from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    HookKind,
)
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.user import ActionsWorkflowBuilder
from styrmin_backend.services.workflow.local import WorkflowLocalExecutor
from styrmin_backend.workflows.catalogue import PrefectCatalogue
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectWorkPool

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
