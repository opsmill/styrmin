"""Pin the post-#237 Prefect-side apply_state behaviour.

The flow must:
- Open the "Plan the changes" step (spec 019).
- Open a UoW.
- Load the deployment, new instance, and (if provided) current
  instance from the freshly-committed DB.
- Build a DiffReport via Comparator.
- Generate a Remediation via Remediator, then end the plan step.
- Call `remediation.apply()` (the existing sub-flow chain) with a
  freshly minted driver action token (ADR-059) and the task id, after the
  UoW closes; when it fails, fail the task's open flow steps before raising.
"""

from collections.abc import Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from tests.helpers.unit_of_work import yield_unit_of_work

from styrmin_backend.domain import steps
from styrmin_backend.domain.models import StepParent
from styrmin_backend.services.reconciliation.exceptions import ReconciliationError

MODULE = "styrmin_backend.agent.tasks.orchestration"


@pytest.fixture
def flow() -> Iterator[SimpleNamespace]:
    """The flow's collaborators, logging into one ordered event list."""
    events: list[str] = []
    plan_step_id = uuid4()

    fake_uow = AsyncMock()
    fake_uow.deployments.find = AsyncMock(return_value=MagicMock())
    fake_uow.application_instances = AsyncMock()
    fake_uow.application_instances.get = AsyncMock(
        side_effect=lambda *, id: MagicMock(id=id)
    )
    fake_uow.__aexit__.side_effect = lambda *_: events.append("uow closed")

    @asynccontextmanager
    async def _fake_action_api_token():
        events.append("token created")
        try:
            yield "action-token"
        finally:
            events.append("token revoked")

    async def _open_task_step(task_id, step):
        events.append(f"{step.key} step opened")
        return plan_step_id

    async def _end_step(step_id, error=None):
        events.append("plan step failed" if error else "plan step succeeded")

    async def _fail_open_steps(parent, message):
        events.append("open steps failed")

    fake_remediation = MagicMock()
    fake_remediation.apply = AsyncMock(
        side_effect=lambda **_: (
            events.append("remediation applied")
            or MagicMock(state=MagicMock(name="Completed"))
        )
    )

    with (
        patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(fake_uow)),
        patch(f"{MODULE}._build_instance_entity") as build_entity,
        patch(f"{MODULE}.Comparator") as comparator_cls,
        patch(f"{MODULE}.Remediator") as remediator_cls,
        patch(f"{MODULE}.action_api_token", side_effect=_fake_action_api_token),
        patch(f"{MODULE}.open_task_step", side_effect=_open_task_step) as open_step,
        patch(f"{MODULE}.end_step", side_effect=_end_step) as end_step,
        patch(f"{MODULE}.fail_open_steps", side_effect=_fail_open_steps) as fail_open,
    ):
        build_entity.side_effect = lambda model: (
            MagicMock(id=model.id) if model is not None else None
        )
        comparator_cls.return_value.compare = MagicMock(return_value=MagicMock())
        remediator_cls.return_value.generate_remediation = AsyncMock(
            return_value=fake_remediation
        )
        yield SimpleNamespace(
            events=events,
            uow=fake_uow,
            plan_step_id=plan_step_id,
            comparator_cls=comparator_cls,
            remediator_cls=remediator_cls,
            remediation=fake_remediation,
            open_step=open_step,
            end_step=end_step,
            fail_open=fail_open,
        )


async def _apply_state(task_id=None, **options):
    from styrmin_backend.agent.tasks.orchestration import apply_state

    return await apply_state(
        task_id=task_id or uuid4(),
        deployment_id=uuid4(),
        new_instance_id=uuid4(),
        current_instance_id=None,
        **options,
    )


@pytest.mark.asyncio
async def test_apply_state_flow_loads_fresh_and_remediates(
    flow: SimpleNamespace,
) -> None:
    from styrmin_backend.agent.tasks.orchestration import apply_state

    deployment_id = uuid4()
    task_id = uuid4()

    await apply_state(
        task_id=task_id,
        deployment_id=deployment_id,
        new_instance_id=uuid4(),
        current_instance_id=uuid4(),
    )

    flow.uow.deployments.find.assert_awaited_with(id=deployment_id)
    flow.comparator_cls.assert_called_once()
    flow.remediator_cls.assert_called_once()
    flow.remediation.apply.assert_awaited_once_with(
        api_token="action-token", task_id=task_id
    )
    flow.open_step.assert_awaited_once_with(task_id, steps.PLAN)
    flow.end_step.assert_awaited_once_with(flow.plan_step_id)
    flow.fail_open.assert_not_awaited()
    # The plan step covers the planning; the UoW's connection is released
    # before the token and the remediation.
    assert flow.events == [
        "plan step opened",
        "uow closed",
        "plan step succeeded",
        "token created",
        "remediation applied",
        "token revoked",
    ]


@pytest.mark.asyncio
async def test_apply_state_flow_handles_no_remediation_needed(
    flow: SimpleNamespace,
) -> None:
    """If Remediator returns None, the flow should not error."""
    flow.remediator_cls.return_value.generate_remediation = AsyncMock(return_value=None)

    state = await _apply_state(return_state=True)

    assert state.is_completed()
    assert state.message == "No remediation needed"
    flow.end_step.assert_awaited_once_with(flow.plan_step_id)
    assert flow.events == ["plan step opened", "uow closed", "plan step succeeded"]


@pytest.mark.asyncio
async def test_apply_state_flow_fails_the_plan_step_with_the_planning_error(
    flow: SimpleNamespace,
) -> None:
    flow.remediator_cls.return_value.generate_remediation = AsyncMock(
        side_effect=ReconciliationError("No upgrade hook for 2.0.0")
    )

    with pytest.raises(ReconciliationError, match="No upgrade hook"):
        await _apply_state()

    flow.end_step.assert_awaited_once_with(
        flow.plan_step_id, error="ReconciliationError: No upgrade hook for 2.0.0"
    )
    flow.remediation.apply.assert_not_awaited()
    assert flow.events == ["plan step opened", "uow closed", "plan step failed"]


@pytest.mark.asyncio
async def test_apply_state_flow_fails_open_steps_when_the_remediation_fails(
    flow: SimpleNamespace,
) -> None:
    task_id = uuid4()
    error = RuntimeError("Deployment flow run 1234 crashed: exit code 137")
    flow.remediation.apply = AsyncMock(side_effect=error)

    with pytest.raises(RuntimeError, match="crashed: exit code 137"):
        await _apply_state(task_id=task_id)

    flow.fail_open.assert_awaited_once_with(StepParent.of_task(task_id), str(error))
    assert flow.events[-3:] == ["token created", "open steps failed", "token revoked"]


@pytest.mark.asyncio
async def test_apply_state_flow_plans_without_a_plan_step(
    flow: SimpleNamespace,
) -> None:
    """When the plan step cannot be written, the reconcile still runs."""
    flow.open_step.side_effect = None
    flow.open_step.return_value = None

    await _apply_state()

    flow.end_step.assert_awaited_once_with(None)
    flow.remediation.apply.assert_awaited_once()


def test_the_instance_entity_carries_the_row_sequence() -> None:
    """The remediation flows order their StyrminDeployment writes by it (#386)."""
    from styrmin_backend.agent.tasks.orchestration import _build_instance_entity
    from styrmin_backend.db.models import ApplicationInstance, InstanceStatus

    from tests.unit.counterpart_crd_fixtures import make_context

    deployment_id = uuid4()
    context = make_context(
        deployment_id=deployment_id, namespace="ns", release_reference="rel"
    )
    model = ApplicationInstance(
        id=uuid4(),
        name="instance",
        application_version="1.0.0",
        status=InstanceStatus.PENDING,
        deployment_id=deployment_id,
        application_driver_version_id=uuid4(),
        context=context.model_dump(mode="json"),
        sequence=7,
    )

    entity = _build_instance_entity(model)

    assert entity is not None
    assert entity.sequence == 7


def test_the_instance_sequence_survives_the_flow_parameter_round_trip() -> None:
    """Prefect passes the instance to the remediation flow as JSON."""
    from styrmin_backend.domain.models import Instance

    from tests.unit.counterpart_crd_fixtures import make_context

    deployment_id = uuid4()
    instance = Instance.create(
        application_version="1.0.0",
        deployment_id=deployment_id,
        application_driver_version_id=uuid4(),
        context=make_context(
            deployment_id=deployment_id, namespace="ns", release_reference="rel"
        ),
    ).model_copy(update={"sequence": 7})

    assert Instance.model_validate_json(instance.model_dump_json()) == instance
