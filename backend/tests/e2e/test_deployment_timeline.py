"""E2E tests for the deployment timeline feature."""

import asyncio
import time
from datetime import datetime

import pytest

from tests.e2e.drivers import ScenarioDriver, TimelineEntry

pytestmark = [
    pytest.mark.shard_general,
]

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

VALID_TASK_RESULTS = {"RUNNING", "FAILED", "SUCCEEDED", "SUPERSEDED"}

# Steps of a create, in start-time order (data-model.md "Step keys and names").
CREATE_STEP_KINDS = {
    "plan": "PLAN",
    "resource:styrmindeployment": "RESOURCE_WRITE",
    "operator:prerequisites": "OPERATOR_PHASE",
    "operator:helmrelease": "OPERATOR_PHASE",
    "operator:services": "OPERATOR_PHASE",
    "operator:ready": "OPERATOR_PHASE",
}


async def _wait_for_create_steps(
    scenario_driver: ScenarioDriver, deployment_id: str, timeout: float = 60.0
) -> list[TimelineEntry]:
    """Read the timeline until the create task's expected steps have all ended.

    Absorbs the lag between the deployment reaching Running and the last
    operator report reaching the steps, and the UI's refetch interval.
    """
    deadline = time.time() + timeout
    while True:
        timeline = await scenario_driver.get_deployment_timeline(
            deployment_id=deployment_id
        )
        creates = [e for e in timeline if e.task_type == "create_instance"]
        if len(creates) == 1:
            ended = {s.key for s in creates[0].steps if s.ended_at is not None}
            if ended >= CREATE_STEP_KINDS.keys():
                return timeline
        if time.time() >= deadline:
            return timeline
        await asyncio.sleep(2.0)


@pytest.mark.ci
async def test_deployment_timeline_has_entries(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    scenario_environment_id: str,
) -> None:
    """Verify that a deployment timeline has entries after initial deploy.

    Reuses the session-scoped ``deployed_simple_app`` (parametrized by
    driver_mode). This test only observes the timeline of an already-
    running deployment; no mutation, so no need for a fresh deploy.
    The create task carries its plan, CR-write and operator-phase steps
    (spec 019, US1).
    """
    scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
    timeline = await _wait_for_create_steps(
        scenario_driver, deployed_simple_app["deployment_id"]
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
        assert entry.result in VALID_TASK_RESULTS, (
            f"Task {entry.task_id} has no valid task result: {entry.result}"
        )

    # The initial deploy should have version 0.1.0
    versions = [e.application_version for e in timeline if e.application_version]
    assert "0.1.0" in versions, f"Expected version 0.1.0 in timeline, got {versions}"

    creates = [e for e in timeline if e.task_type == "create_instance"]
    assert len(creates) == 1, (
        f"Expected one create_instance task, got {[e.task_type for e in timeline]}"
    )
    # US3: every step of the create succeeded and its hooks started no task.
    assert creates[0].result == "SUCCEEDED", creates[0]
    steps = {step.key: step for step in creates[0].steps}
    keys = [step.key for step in creates[0].steps]
    missing = CREATE_STEP_KINDS.keys() - steps.keys()
    assert not missing, f"Create task is missing steps {missing}; it has {keys}"

    for key, kind in CREATE_STEP_KINDS.items():
        step = steps[key]
        assert step.kind == kind, f"Step {key} has kind {step.kind}, expected {kind}"
        assert step.status == "SUCCEEDED", f"Step {key} is {step.status}: {step}"
        assert step.name, f"Step {key} has no name"
        assert step.started_at is not None and step.ended_at is not None, (
            f"Succeeded step {key} lacks a start or end time: {step}"
        )

    # Steps are listed in start-time order.
    expected_order = [key for key in keys if key in CREATE_STEP_KINDS]
    assert expected_order == list(CREATE_STEP_KINDS), (
        f"Create steps out of order: {keys}"
    )
    started = [
        datetime.fromisoformat(step.started_at)
        for step in creates[0].steps
        if step.started_at is not None
    ]
    assert started == sorted(started), f"Steps not in start-time order: {keys}"


@pytest.mark.ci
async def test_deployment_timeline_after_upgrade(
    scenario_driver: ScenarioDriver,
    deployed_simple_app: dict,
    simple_app_image_v2: str,  # noqa: ARG001 — ensures v2 image is built
    scenario_environment_id: str,
) -> None:
    """Verify timeline reflects both deploy and upgrade operations.

    Upgrades the shared session deployment in place — idempotent if a
    previous test already did the upgrade. Timeline still retains the
    initial ``create_instance`` at 0.1.0 alongside the upgrade entry.
    """
    scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
    deployment_id = deployed_simple_app["deployment_id"]
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id, version="0.2.0"
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)

    timeline = await scenario_driver.get_deployment_timeline(
        deployment_id=deployment_id
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
    deployed_simple_app: dict,
    simple_app_image_v2: str,  # noqa: ARG001 — ensures v2 image is built
    scenario_environment_id: str,
) -> None:
    """Verify that timeline entries are ordered newest-first by created_on.

    A single deploy produces exactly one task (``create_instance``) — an
    upgrade is required to get a second entry so ordering is observable.
    The upgrade is idempotent, so this test works whether it runs before
    or after the other tests that upgrade the shared deployment. The poll
    loop absorbs DOM-render lag in the UI variant (FR-014).
    """
    scenario_driver.attach_to_deployment(environment_id=scenario_environment_id)
    deployment_id = deployed_simple_app["deployment_id"]
    await scenario_driver.upgrade_deployment(
        deployment_id=deployment_id, version="0.2.0"
    )
    await scenario_driver.wait_for_deployment_running(deployment_id=deployment_id)

    deadline = time.time() + 60.0
    timeline = []
    while time.time() < deadline:
        timeline = await scenario_driver.get_deployment_timeline(
            deployment_id=deployment_id
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
