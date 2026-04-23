"""E2E tests for the deployment timeline feature."""

import asyncio
import time

import pytest

from tests.e2e.drivers import ScenarioDriver

VALID_TASK_TYPES = {
    "noop",
    "run_job",
    "deployment",
    "create_instance",
    "delete_instance",
    "update_instance",
    "upgrade_instance",
    "stop_components",
    "start_components",
}

VALID_TASK_STATUSES = {"pending", "running", "failed", "success"}


@pytest.mark.ci
async def test_deployment_timeline_has_entries(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
) -> None:
    """Verify that a deployment timeline has entries after initial deploy.

    Reuses the session-scoped ``deployed_simple_app`` (parametrized by
    driver_mode). This test only observes the timeline of an already-
    running deployment; no mutation, so no need for a fresh deploy.
    """
    timeline = await scenario_driver.get_deployment_timeline(
        deployment_id=deployed_simple_app["deployment_id"]
    )

    assert len(timeline) >= 1, (
        f"Expected at least 1 timeline entry, got {len(timeline)}"
    )

    for entry in timeline:
        assert entry.task_id, f"Timeline entry missing task_id: {entry}"
        assert entry.task_type in VALID_TASK_TYPES, (
            f"Unexpected task type: {entry.task_type}"
        )
        assert entry.task_status in VALID_TASK_STATUSES, (
            f"Unexpected task status: {entry.task_status}"
        )
        assert entry.created_on is not None, (
            f"Timeline entry missing created_on: {entry}"
        )

    # The initial deploy should have version 0.1.0
    versions = [e.application_version for e in timeline if e.application_version]
    assert "0.1.0" in versions, f"Expected version 0.1.0 in timeline, got {versions}"


@pytest.mark.ci
async def test_deployment_timeline_after_upgrade(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001
    simple_app_image: str,  # noqa: ARG001
    simple_app_image_v2: str,  # noqa: ARG001 — ensures v2 image is built
) -> None:
    """Verify timeline reflects both deploy and upgrade operations."""
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id
    )

    # Trigger upgrade to version 0.2.0
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment.id, version="0.2.0"
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment.id)

    timeline = await scenario_driver.get_deployment_timeline(
        deployment_id=deployment.id
    )

    # After deploy + upgrade, expect at least 2 timeline entries
    assert len(timeline) >= 2, (
        f"Expected at least 2 timeline entries after upgrade, got {len(timeline)}"
    )

    versions = [e.application_version for e in timeline if e.application_version]
    assert "0.2.0" in versions, f"Expected version 0.2.0 in timeline, got {versions}"
    assert "0.1.0" in versions, f"Expected version 0.1.0 in timeline, got {versions}"


@pytest.mark.ci
async def test_deployment_timeline_ordering(
    scenario_driver: ScenarioDriver,
    scenario_environment_id: str,
    styrmin_resources: dict,  # noqa: ARG001
    simple_app_image: str,  # noqa: ARG001
    simple_app_image_v2: str,  # noqa: ARG001 — ensures v2 image is built
) -> None:
    """Verify that timeline entries are ordered newest-first by created_on.

    A single deploy produces exactly one task (``create_instance``) — an
    upgrade is required to get a second entry so ordering is observable.
    The poll loop absorbs DOM-render lag in the UI variant (FR-014).
    """
    deployment = await scenario_driver.create_deployment(
        driver="simple-app",
        version="0.1.0",
        environment_id=scenario_environment_id,
    )
    deployment = await scenario_driver.wait_for_deployment_running(
        deployment_id=deployment.id
    )
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment.id, version="0.2.0"
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment.id)

    deadline = time.time() + 60.0
    timeline = []
    while time.time() < deadline:
        timeline = await scenario_driver.get_deployment_timeline(
            deployment_id=deployment.id
        )
        if len(timeline) >= 2:
            break
        await asyncio.sleep(2.0)
    assert len(timeline) >= 2, (
        f"timeline never populated ≥2 entries within 60s (got {len(timeline)})"
    )

    timestamps = [e.created_on for e in timeline if e.created_on is not None]
    assert len(timestamps) >= 2

    for i in range(len(timestamps) - 1):
        assert timestamps[i] >= timestamps[i + 1], (
            f"Timeline not in newest-first order: {timestamps[i]} < {timestamps[i + 1]}"
        )
