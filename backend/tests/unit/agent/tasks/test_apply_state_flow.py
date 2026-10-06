"""Pin the post-#237 Prefect-side apply_state behaviour.

The flow must:
- Open a UoW.
- Load the deployment, new instance, and (if provided) current
  instance from the freshly-committed DB.
- Build a DiffReport via Comparator.
- Generate a Remediation via Remediator.
- Call `remediation.apply()` (the existing sub-flow chain) with a
  freshly minted driver action token (ADR-059), after the UoW closes.
"""

from contextlib import asynccontextmanager
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.helpers.unit_of_work import yield_unit_of_work


@pytest.mark.asyncio
@patch("styrmin_backend.agent.tasks.orchestration.action_api_token")
@patch(
    "styrmin_backend.agent.tasks.orchestration._build_instance_entity",
    create=True,
)
@patch(
    "styrmin_backend.agent.tasks.orchestration.get_unit_of_work",
    create=True,
)
@patch(
    "styrmin_backend.agent.tasks.orchestration.Comparator",
    create=True,
)
@patch(
    "styrmin_backend.agent.tasks.orchestration.Remediator",
    create=True,
)
async def test_apply_state_flow_loads_fresh_and_remediates(
    mock_remediator_cls,
    mock_comparator_cls,
    mock_get_uow,
    mock_build_entity,
    mock_action_api_token,
) -> None:
    from styrmin_backend.agent.tasks.orchestration import apply_state

    deployment_id = uuid4()
    new_instance_id = uuid4()
    current_instance_id = uuid4()
    task_id = uuid4()

    fake_uow = AsyncMock()
    fake_uow.deployments.find = AsyncMock(return_value=MagicMock(id=deployment_id))
    fake_uow.application_instances = AsyncMock()
    fake_uow.application_instances.get = AsyncMock(
        side_effect=lambda *, id: MagicMock(id=id)
    )
    events: list[str] = []
    fake_uow.__aexit__.side_effect = lambda *_: events.append("uow closed")
    mock_get_uow.side_effect = yield_unit_of_work(fake_uow)

    @asynccontextmanager
    async def _fake_action_api_token():
        events.append("token created")
        yield "action-token"
        events.append("token revoked")

    mock_action_api_token.side_effect = _fake_action_api_token

    mock_build_entity.side_effect = lambda model: (
        MagicMock(id=model.id) if model is not None else None
    )

    diff_report = MagicMock()
    mock_comparator_cls.return_value.compare = MagicMock(return_value=diff_report)

    fake_remediation = MagicMock()
    flow_info = MagicMock(state=MagicMock(name="Completed"))

    def _apply(*, api_token: str) -> MagicMock:
        events.append("remediation applied")
        return flow_info

    fake_remediation.apply = AsyncMock(side_effect=_apply)
    mock_remediator_cls.return_value.generate_remediation = AsyncMock(
        return_value=fake_remediation
    )

    await apply_state(
        task_id=task_id,
        deployment_id=deployment_id,
        new_instance_id=new_instance_id,
        current_instance_id=current_instance_id,
    )

    fake_uow.deployments.find.assert_awaited_with(id=deployment_id)
    mock_comparator_cls.assert_called_once()
    mock_remediator_cls.assert_called_once()
    fake_remediation.apply.assert_awaited_once_with(api_token="action-token")
    # The UoW's connection must be released before the token and the remediation.
    assert events == [
        "uow closed",
        "token created",
        "remediation applied",
        "token revoked",
    ]


@pytest.mark.asyncio
@patch(
    "styrmin_backend.agent.tasks.orchestration._build_instance_entity",
    create=True,
)
@patch(
    "styrmin_backend.agent.tasks.orchestration.get_unit_of_work",
    create=True,
)
@patch(
    "styrmin_backend.agent.tasks.orchestration.Comparator",
    create=True,
)
@patch(
    "styrmin_backend.agent.tasks.orchestration.Remediator",
    create=True,
)
async def test_apply_state_flow_handles_no_remediation_needed(
    mock_remediator_cls,
    mock_comparator_cls,
    mock_get_uow,
    mock_build_entity,
) -> None:
    """If Remediator returns None, the flow should not error."""
    from styrmin_backend.agent.tasks.orchestration import apply_state

    fake_uow = AsyncMock()
    fake_uow.deployments.find = AsyncMock(return_value=MagicMock())
    fake_uow.application_instances = AsyncMock()
    fake_uow.application_instances.get = AsyncMock(return_value=MagicMock())
    mock_get_uow.side_effect = yield_unit_of_work(fake_uow)

    mock_build_entity.side_effect = lambda model: (
        MagicMock(id=model.id) if model is not None else None
    )

    mock_comparator_cls.return_value.compare = MagicMock(return_value=MagicMock())
    mock_remediator_cls.return_value.generate_remediation = AsyncMock(return_value=None)

    result = await apply_state(
        task_id=uuid4(),
        deployment_id=uuid4(),
        new_instance_id=uuid4(),
        current_instance_id=None,
    )
    # Either returns a Completed state or None — pin to the contract
    # the flow exposes after Task 2.4.
    assert result is None or "Completed" in (getattr(result, "name", "") or "")
