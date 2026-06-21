"""E2E regression: redeploying after deletion must not collide on service names.

Reproduces the bug where, after deploying an application into an environment
and deleting it, recreating a deployment that resolves to the *same* service
name fails with ``ServiceNameConflictError`` ("service name already exists").

Root cause under test: deployments are soft-deleted (tombstoned via
``deleted_at``), but their ``DeployedService`` rows are never cleaned up, and
the service-name uniqueness check does not exclude services belonging to
tombstoned deployments. The deployment-*name* check already filters
``deleted_at IS NULL`` — service names must behave the same way.

``api_only``: every action goes through the SDK; the ``[ui-chromium]`` variant
would re-run identical SDK call paths without adding coverage.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from styrmin_sdk import StyrminClient

from tests.e2e.drivers import ScenarioDriver

pytestmark = [
    pytest.mark.shard_general,
]


async def _wait_for_status(
    client: StyrminClient,
    deployment_id: str,
    expected: str,
    timeout: float = 300.0,
) -> None:
    """Poll ``Deployment.status`` until it equals *expected* or we time out."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        deployment = await client.deployments.get(deployment_id)
        last = deployment.status
        if last == expected:
            return
        await asyncio.sleep(2)
    raise AssertionError(
        f"Deployment {deployment_id} never reached status {expected!r} "
        f"within {timeout}s. Last observed: {last!r}."
    )


@pytest.mark.api_only(
    reason="Drives deploy → delete → redeploy entirely through the SDK; the "
    "[ui-chromium] variant would re-run identical SDK call paths without "
    "adding coverage."
)
@pytest.mark.ci
async def test_redeploy_with_same_service_name_after_delete(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,
    simple_app_image: str,  # noqa: ARG001 — ensures image is built
) -> None:
    """deploy → delete → recreate with the same service name must succeed."""
    client: StyrminClient = styrmin_resources["client"]

    # A unique-per-test service-name override, reused across BOTH create
    # calls. The first deployment occupies `override` in this environment;
    # after deletion the second deployment must be free to claim it again.
    override = f"redeploy-{uuid.uuid4().hex[:6]}"
    overrides = [{"driverServiceName": "simple-app", "overrideName": override}]

    # 1. Deploy into the shared scenario env and wait for it to run.
    first = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=overrides,
    )
    first = await scenario_driver.wait_for_deployment_running(
        deployment_id=first.id, timeout=300.0
    )
    first_id = first.id

    # 2. Delete it and wait for the tombstone (status flips to DELETED only
    #    after cluster teardown completes, gated server-side).
    await client.deployments.delete(first_id)
    await _wait_for_status(client, first_id, "deleted", timeout=480.0)

    tombstoned = await client.deployments.get(first_id)
    assert tombstoned.deleted_at is not None, (
        "Setup precondition: first deployment must be tombstoned before redeploy"
    )

    # 3. Recreate with the SAME service-name override in the SAME environment.
    #    This currently raises ServiceNameConflictError because the tombstoned
    #    deployment's DeployedService row still occupies `override`.
    second = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
        service_name_overrides=overrides,
    )
    second = await scenario_driver.wait_for_deployment_running(
        deployment_id=second.id, timeout=300.0
    )

    assert second.id != first_id, "Redeploy must create a distinct deployment"
    assert second.status == "running", (
        f"Redeploy with a freed service name must reach running; got {second.status!r}"
    )
