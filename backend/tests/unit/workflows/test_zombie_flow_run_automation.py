from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from prefect.client.schemas.objects import StateType
from prefect.events.actions import ChangeFlowRunState
from prefect.events.schemas.automations import Automation, EventTrigger, Posture

from styrmin_backend.workflows.manager import PrefectManager

_AUTOMATION_NAME = "Crash zombie flow runs"


def _fake_manager() -> PrefectManager:
    # setup_zombie_flow_run_automation doesn't touch self, but PrefectManager
    # requires a catalogue/executor to construct -- Mocks are fine since the
    # method under test is unwrapped via `.fn` and never reads either attr.
    return PrefectManager.__new__(PrefectManager)


@pytest.fixture(autouse=True)
def _stub_run_logger(mocker):
    # get_run_logger() requires an active Prefect flow/task run context,
    # which calling the task's `.fn` directly bypasses. Stub it the same way
    # the function would use it in a real run -- a plain logger works fine
    # since these tests only assert on client calls, not log output.
    mocker.patch(
        "styrmin_backend.workflows.manager.get_run_logger",
        return_value=mocker.Mock(),
    )


async def test_creates_automation_when_none_exists(mocker):
    client = mocker.Mock()
    client.read_automations_by_name = AsyncMock(return_value=[])
    client.create_automation = AsyncMock(return_value=uuid4())
    client.update_automation = AsyncMock()

    await PrefectManager.setup_zombie_flow_run_automation.fn(
        _fake_manager(), client=client
    )

    client.read_automations_by_name.assert_awaited_once_with(name=_AUTOMATION_NAME)
    client.create_automation.assert_awaited_once()
    client.update_automation.assert_not_awaited()

    (automation_arg,) = client.create_automation.call_args.kwargs.values()
    assert automation_arg.name == _AUTOMATION_NAME
    assert isinstance(automation_arg.trigger, EventTrigger)
    assert automation_arg.trigger.posture == Posture.Proactive
    assert automation_arg.trigger.after == {"prefect.flow-run.heartbeat"}
    assert len(automation_arg.actions) == 1
    action = automation_arg.actions[0]
    assert isinstance(action, ChangeFlowRunState)
    assert action.state == StateType.CRASHED


async def test_updates_existing_automation_by_id(mocker):
    existing_id = uuid4()
    existing = mocker.Mock(spec=Automation)
    existing.id = existing_id

    client = mocker.Mock()
    client.read_automations_by_name = AsyncMock(return_value=[existing])
    client.create_automation = AsyncMock()
    client.update_automation = AsyncMock()

    await PrefectManager.setup_zombie_flow_run_automation.fn(
        _fake_manager(), client=client
    )

    client.create_automation.assert_not_awaited()
    client.update_automation.assert_awaited_once()
    call_kwargs = client.update_automation.call_args.kwargs
    assert call_kwargs["automation_id"] == existing_id
    assert call_kwargs["automation"].name == _AUTOMATION_NAME


async def test_registration_is_idempotent_across_repeated_calls(mocker):
    """Simulates two server startups in a row: the second call must see the
    first call's automation and update it, never create a duplicate."""
    created_id = uuid4()
    client = mocker.Mock()
    client.create_automation = AsyncMock(return_value=created_id)
    client.update_automation = AsyncMock()

    # First "startup": no automation exists yet.
    client.read_automations_by_name = AsyncMock(return_value=[])
    await PrefectManager.setup_zombie_flow_run_automation.fn(
        _fake_manager(), client=client
    )
    assert client.create_automation.await_count == 1

    # Second "startup": the one just created is now returned by the lookup.
    existing = mocker.Mock(spec=Automation)
    existing.id = created_id
    client.read_automations_by_name = AsyncMock(return_value=[existing])
    await PrefectManager.setup_zombie_flow_run_automation.fn(
        _fake_manager(), client=client
    )

    assert client.create_automation.await_count == 1
    assert client.update_automation.await_count == 1
