"""E2E tests for the deployment timeline feature."""

import asyncio
import time

import pytest
from styrmin_sdk import StyrminClient
from styrmin_sdk.exceptions import StyrminError

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
    styrmin_resources: dict,
    deployed_simple_app: dict,
) -> None:
    """Verify that a deployment timeline has entries after initial deploy."""
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = deployed_simple_app["deployment_id"]

    timeline = await client.deployments.get_timeline(deployment_id)

    assert len(timeline) >= 1, (
        f"Expected at least 1 timeline entry, got {len(timeline)}"
    )

    for entry in timeline:
        assert entry.task is not None
        assert entry.task.id is not None
        assert entry.task.type_ in VALID_TASK_TYPES, (
            f"Unexpected task type: {entry.task.type_}"
        )
        assert entry.task.status in VALID_TASK_STATUSES, (
            f"Unexpected task status: {entry.task.status}"
        )
        assert entry.task.created_on is not None

    # The initial deploy should have version 0.1.0
    versions = [e.application_version for e in timeline if e.application_version]
    assert "0.1.0" in versions, f"Expected version 0.1.0 in timeline, got {versions}"


@pytest.mark.ci
async def test_deployment_timeline_after_upgrade(
    styrmin_resources: dict,
    deployed_simple_app: dict,
    simple_app_image_v2: str,
    vcluster: dict,
) -> None:
    """Verify timeline reflects both deploy and upgrade operations."""
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = deployed_simple_app["deployment_id"]

    # Trigger upgrade to version 0.2.0
    await client.deployments.update_version(deployment_id, "0.2.0")

    # Poll deployment status until ready
    deadline = time.time() + 180
    deployment_ready = False
    while time.time() < deadline:
        try:
            deployment = await client.deployments.get(deployment_id)
            if deployment.status in ("deployed", "running"):
                deployment_ready = True
                break
        except StyrminError:
            pass
        await asyncio.sleep(10)

    assert deployment_ready, "Deployment did not reach ready state after upgrade"

    timeline = await client.deployments.get_timeline(deployment_id)

    # After deploy + upgrade, expect at least 2 timeline entries
    assert len(timeline) >= 2, (
        f"Expected at least 2 timeline entries after upgrade, got {len(timeline)}"
    )

    # Timeline is newest-first; the newest entry should reference version 0.2.0
    versions = [e.application_version for e in timeline if e.application_version]
    assert "0.2.0" in versions, f"Expected version 0.2.0 in timeline, got {versions}"
    assert "0.1.0" in versions, f"Expected version 0.1.0 in timeline, got {versions}"


@pytest.mark.ci
async def test_deployment_timeline_ordering(
    styrmin_resources: dict,
    deployed_simple_app: dict,
) -> None:
    """Verify that timeline entries are ordered newest-first by created_on."""
    client: StyrminClient = styrmin_resources["client"]
    deployment_id = deployed_simple_app["deployment_id"]

    timeline = await client.deployments.get_timeline(deployment_id)

    if len(timeline) < 2:
        pytest.skip("Need at least 2 timeline entries to verify ordering")

    timestamps = [e.task.created_on for e in timeline if e.task.created_on is not None]
    assert len(timestamps) >= 2

    for i in range(len(timestamps) - 1):
        assert timestamps[i] >= timestamps[i + 1], (
            f"Timeline not in newest-first order: {timestamps[i]} < {timestamps[i + 1]}"
        )
