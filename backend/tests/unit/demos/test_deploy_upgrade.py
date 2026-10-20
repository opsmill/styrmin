"""Demo 1's registration and the checks that fail the demo on a wrong result."""

from __future__ import annotations

import pytest

from tests.e2e.demos.catalog import DEMOS
from tests.e2e.demos.scenarios import deploy_upgrade
from tests.e2e.drivers.errors import ScenarioActionError
from tests.e2e.drivers.refs import StepRef


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


def test_demo_1_is_registered_with_its_environment() -> None:
    demo = next(demo for demo in DEMOS if demo.slug == "deploy-upgrade")

    assert demo.number == 1
    assert demo.environment_names == ("network-lab-upgrade",)
    assert demo.setup is deploy_upgrade.setup
    assert demo.record is deploy_upgrade.record


def test_check_upgrade_action_accepts_steps_whose_upgrade_action_succeeded() -> None:
    deploy_upgrade.check_upgrade_action((PLAN, ACTION, HELM), "task-2")


def test_check_upgrade_action_names_the_steps_of_a_task_without_the_action() -> None:
    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_upgrade_action((PLAN, HELM), "task-2")

    assert str(raised.value) == (
        "The upgrade task task-2 did not run the driver's upgrade action; "
        "its steps: Plan the changes, Install or upgrade the HelmRelease"
    )


def test_check_upgrade_action_refuses_an_action_that_did_not_succeed() -> None:
    failed = step("hook:upgrade:core", "Run the upgrade hook", status="FAILED")

    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_upgrade_action((PLAN, failed), "task-2")

    assert str(raised.value) == (
        "The step 'Run the upgrade hook' of the upgrade task task-2 ended FAILED, "
        "not SUCCEEDED"
    )


def test_check_version_names_the_version_shown() -> None:
    deploy_upgrade.check_version("1.11.7", "1.11.7")
    with pytest.raises(ScenarioActionError) as raised:
        deploy_upgrade.check_version("1.10.11", "1.11.7")

    assert str(raised.value) == "The deployment shows Infrahub 1.10.11, not 1.11.7"
