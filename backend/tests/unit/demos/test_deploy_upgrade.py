"""Demo 1's registration and the checks that fail the demo on a wrong result."""

from __future__ import annotations

import pytest

from tests.e2e.demos.catalog import DEMOS
from tests.e2e.demos.scenarios import deploy_upgrade
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import StepRef, TimelineEntry


def step(key: str, name: str, status: str = "SUCCEEDED") -> StepRef:
    return StepRef(
        id=f"step-{key}",
        key=key,
        name=name,
        kind="HOOK" if key.startswith("hook:") else "OPERATOR_PHASE",
        status=status,
        started_at=None,
        ended_at=None,
        attempt_count=1,
        errors=(),
        detail=None,
        has_output=False,
    )


PLAN = step("plan", "Plan the changes")
HELM = step("helm", "Install or upgrade the HelmRelease")
ACTION = step("hook:upgrade:core", "Run the upgrade hook")
LATEST = "1.11.7"


def entry(*steps: StepRef, version: str | None = LATEST) -> TimelineEntry:
    return TimelineEntry(
        task_id="task-2",
        task_type="upgrade_instance",
        task_status="success",
        application_version=version,
        created_on=None,
        steps=steps,
        result="SUCCEEDED",
    )


def test_demo_1_is_registered_with_its_environment() -> None:
    demo = next(demo for demo in DEMOS if demo.slug == "deploy-upgrade")

    assert demo.number == 1
    assert demo.environment_names == ("network-lab-upgrade",)
    assert demo.setup is deploy_upgrade.setup
    assert demo.record is deploy_upgrade.record


def test_check_upgrade_task_accepts_a_succeeded_action_and_the_latest_version() -> None:
    deploy_upgrade.check_upgrade_task(entry(PLAN, ACTION, HELM), LATEST)


def test_check_upgrade_task_names_the_steps_of_a_task_without_the_action() -> None:
    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_upgrade_task(entry(PLAN, HELM), LATEST)

    assert str(raised.value) == (
        "The upgrade task task-2 did not run the driver's upgrade action; "
        "its steps: Plan the changes, Install or upgrade the HelmRelease. "
        f"{deploy_upgrade.IMAGE_HINT}"
    )
    # The error points to the image as the likely cause.
    assert "#372 (PR #535" in deploy_upgrade.IMAGE_HINT
    assert "uv run invoke build" in deploy_upgrade.IMAGE_HINT


@pytest.mark.parametrize("status", ["FAILED", "PENDING", "RUNNING", "SUPERSEDED"])
def test_check_upgrade_task_refuses_an_action_that_did_not_succeed(status: str) -> None:
    action = step("hook:upgrade:core", "Run the upgrade hook", status=status)

    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_upgrade_task(entry(PLAN, action), LATEST)

    assert str(raised.value) == (
        f"The step 'Run the upgrade hook' of the upgrade task task-2 ended {status}, "
        "not SUCCEEDED"
    )


@pytest.mark.parametrize(
    ("version", "shown"), [("1.10.11", "1.10.11"), (None, "with no version")]
)
def test_check_upgrade_task_refuses_a_task_without_the_latest_version(
    version: str | None, shown: str
) -> None:
    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_upgrade_task(entry(PLAN, ACTION, version=version), LATEST)

    assert str(raised.value) == (
        f"The upgrade task task-2 shows Infrahub {shown}, not 1.11.7"
    )


def test_check_version_names_the_version_shown() -> None:
    deploy_upgrade.check_version("1.11.7", "1.11.7")
    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_version("1.10.11", "1.11.7")

    assert str(raised.value) == "The deployment shows Infrahub 1.10.11, not 1.11.7"
