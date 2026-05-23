"""Pin the post-#237 FastAPI/Prefect boundary contract.

Server-side `apply_state` must:
- Create a Task row.
- Schedule the Prefect `apply_state` flow with deployment_id +
  new_instance_id + current_instance_id + task_id (no Remediation
  parameter).
- Return the Task.

It must NOT call Comparator or Remediator — that work belongs inside
the flow so a flow retry sees fresh DB state.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fast_depends import dependency_provider

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.domain.models import (
    Deployment,
    Instance,
    InstanceStatus,
)
from styrmin_backend.services.reconciliation import apply_state
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instance(deployment_id) -> Instance:
    """Create a minimal Instance domain object for testing."""
    context = MagicMock(spec=GlobalContext)
    context.instance = MagicMock()
    return Instance(
        id=uuid4(),
        name="test-instance",
        application_version="1.0.0",
        status=InstanceStatus.PENDING,
        deployment_id=deployment_id,
        application_driver_version_id=uuid4(),
        context=context,
    )


def _make_deployment_with_active_instance() -> Deployment:
    """Create a Deployment with one active instance already set."""
    deployment = Deployment(
        id=uuid4(),
        name="test-deployment",
        application_version="1.0.0",
        config={},
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        created_by_user_id=uuid4(),
    )
    instance = _make_instance(deployment.id)
    deployment.set_active_instance(instance)
    return deployment


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_state_passes_ids_not_remediation_to_prefect() -> None:
    """apply_state must send IDs (not a Remediation) to Prefect and must not
    instantiate Comparator or Remediator on the server side."""
    deployment = _make_deployment_with_active_instance()
    # Capture the active instance *before* we set a new one so we have the
    # "current" instance reference.
    current = deployment.active_instance
    new_instance = _make_instance(deployment.id)
    deployment.set_active_instance(new_instance)

    fake_prefect = MagicMock(spec=PrefectManager)
    fake_prefect.run_action = AsyncMock(
        return_value=MagicMock(id=uuid4(), state_name="Scheduled")
    )

    def get_fake_manager(catalogue=None, workflow_executor=None) -> PrefectManager:
        return fake_prefect

    fake_uow = FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        application_drivers=FakeApplicationDriverRepository(),
    )

    dependency_provider.override(get_manager.__wrapped__, get_fake_manager)
    try:
        with (
            patch(
                "styrmin_backend.services.reconciliation.Comparator"
            ) as mock_comparator,
            patch(
                "styrmin_backend.services.reconciliation.Remediator"
            ) as mock_remediator,
        ):
            # Configure mocked Remediator so execution reaches our assertions
            # even though the code incorrectly calls it today.
            mock_remediator.return_value.generate_remediation = AsyncMock(
                return_value=None
            )
            task = await apply_state(
                deployment=deployment,
                current_instance=current,
                uow=fake_uow,
            )
    finally:
        dependency_provider.clear()

    # The Prefect call must carry IDs, not a Remediation object.
    fake_prefect.run_action.assert_awaited_once()
    kwargs = fake_prefect.run_action.await_args.kwargs
    assert kwargs["action"] == PrefectAction.APPLY_STATE
    params = kwargs["parameters"]
    assert params["deployment_id"] == deployment.id
    assert params["new_instance_id"] == new_instance.id
    assert params["current_instance_id"] == (current.id if current else None)
    assert params["task_id"] == task.id
    assert "remediation" not in params

    # Server-side must never build a remediation.
    mock_comparator.assert_not_called()
    mock_remediator.assert_not_called()
