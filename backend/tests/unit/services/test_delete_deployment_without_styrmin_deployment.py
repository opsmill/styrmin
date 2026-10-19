"""Deleting a deployment whose ``StyrminDeployment`` was never written (spec 029, T052).

A create that fails at its ``hook:setup:pre`` step stops before it writes the
namespace and the ``StyrminDeployment``. The Kubernetes API then answers the
deletion request's patch with 404, which ``patch_custom_resource`` raises as
``CustomResourceNotFound``. The cluster holds nothing of the deployment, so
``delete_deployment`` moves it to ``DELETING``, and the agent's status reporter,
which finds no ``StyrminDeployment`` for a ``DELETING`` deployment, reports it
as ``Deleted``. While a change of the deployment is still being applied, its
flow can still write the ``StyrminDeployment``, so the deletion is refused.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.agent.service.kubernetes.primitives import patch_custom_resource
from styrmin_backend.db.models import Deployment as DeploymentModel
from styrmin_backend.db.models import DeploymentState
from styrmin_backend.db.models import Task as TaskModel
from styrmin_backend.domain.models import StepStatus, TaskStatus, TaskType
from styrmin_backend.services.deployment import delete_deployment
from styrmin_backend.services.deployment_status import report_deployment_statuses
from styrmin_backend.services.exceptions import DeploymentRolloutInProgressError
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from tests.unit.steps import conftest as step_fixtures
from tests.unit.steps.conftest import Parents

# The real database fixtures of the step tests (SQLite and PostgreSQL).
database_url = step_fixtures.database_url
session = step_fixtures.session
uow = step_fixtures.uow
parents = step_fixtures.parents

CUSTOM_OBJECTS_API = (
    "styrmin_backend.agent.service.kubernetes.primitives.kubeclient.CustomObjectsApi"
)


@pytest.fixture
def patch_crd(mocker):
    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource", autospec=True
    )


async def _set_status(
    uow: SqlModelUnitOfWork, parents: Parents, status: DeploymentState
) -> None:
    deployment = await uow.session.get(DeploymentModel, parents.deployment_id)
    assert deployment is not None
    deployment.status = status
    uow.session.add(deployment)
    await uow.commit()


async def _fail_the_create(uow: SqlModelUnitOfWork, parents: Parents) -> None:
    """The state that the task callback leaves after the create's flow failed."""
    for task in (parents.task, parents.other_task):
        model = await uow.session.get(TaskModel, task.id)
        assert model is not None
        model.status = TaskStatus.FAILED
        uow.session.add(model)
    await _set_status(uow, parents, DeploymentState.FAILED)


def _not_found(deployment_id: object) -> CustomResourceNotFound:
    name = f"styrmin-{deployment_id}"
    return CustomResourceNotFound(
        f"Custom resource styrmindeployments/{name} not found in namespace {name}"
    )


async def test_patch_of_a_styrmin_deployment_that_does_not_exist_raises_not_found() -> (
    None
):
    """The Kubernetes API answers 404 for a namespace or a ``StyrminDeployment`` that does not exist."""
    api = MagicMock()
    api.patch_namespaced_custom_object = AsyncMock(side_effect=ApiException(status=404))
    with (
        patch(CUSTOM_OBJECTS_API, return_value=api),
        pytest.raises(CustomResourceNotFound),
    ):
        # Undecorated function: a dummy client without fast_depends' type validation.
        await patch_custom_resource.__wrapped__(
            plural="styrmindeployments",
            reference="styrmin-1",
            group="styrmin.io",
            version="v1alpha1",
            namespace="styrmin-1",
            patch=[{"op": "add", "path": "/spec/deletionRequested", "value": True}],
            client=None,
        )


async def test_delete_of_a_create_that_failed_before_its_styrmin_deployment(
    uow: SqlModelUnitOfWork, parents: Parents, patch_crd
) -> None:
    await _fail_the_create(uow, parents)
    patch_crd.side_effect = _not_found(parents.deployment_id)

    task = await delete_deployment(parents.deployment_id, uow)

    patch_crd.assert_awaited_once()
    assert (task.type, task.status) == (TaskType.DELETE_DEPLOYMENT, TaskStatus.SUCCESS)
    await uow.rollback()  # Only committed writes remain.
    deployment = await uow.deployments.find(id=parents.deployment_id)
    assert deployment is not None
    assert deployment.status == DeploymentState.DELETING
    assert deployment.deleted_at is None
    listed = await uow.steps.list_by_task_ids([task.id])
    assert [(step.key, step.status) for step in listed] == [
        ("resource:delete-request", StepStatus.SUCCEEDED),
        ("operator:teardown", StepStatus.PENDING),
    ]

    # The status reporter finds no StyrminDeployment for the DELETING
    # deployment and reports it as Deleted (agent/status/reporter.py).
    await report_deployment_statuses(
        [
            {
                "deployment_id": parents.deployment_id,
                "instance_id": None,
                "phase": "Deleted",
                "display_state": "Deleted",
                "message": "Namespace removed; CR garbage-collected with it",
                "conditions": None,
                "managed_resource_counts": None,
            }
        ],
        uow,
    )

    deployment = await uow.deployments.find(id=parents.deployment_id)
    assert deployment is not None
    assert deployment.status == DeploymentState.DELETED
    assert deployment.deleted_at is not None
    listed = await uow.steps.list_by_task_ids([task.id])
    assert [(step.key, step.status) for step in listed] == [
        ("resource:delete-request", StepStatus.SUCCEEDED),
        ("operator:teardown", StepStatus.SUCCEEDED),
    ]


@pytest.mark.parametrize("status", [DeploymentState.PENDING, DeploymentState.DEPLOYING])
async def test_delete_without_styrmin_deployment_is_refused_while_a_change_is_applied(
    uow: SqlModelUnitOfWork,
    parents: Parents,
    patch_crd,
    status: DeploymentState,
) -> None:
    """The flow of the change can still write the ``StyrminDeployment`` after the deletion."""
    await _set_status(uow, parents, status)
    patch_crd.side_effect = _not_found(parents.deployment_id)

    with pytest.raises(DeploymentRolloutInProgressError) as refused:
        await delete_deployment(parents.deployment_id, uow)

    assert str(parents.deployment_id) in str(refused.value)
    assert status.value in str(refused.value)
    assert "Delete the deployment again" in str(refused.value)
    assert refused.value.error_code == "ALREADY_IN_PROGRESS"
    await uow.rollback()
    deployment = await uow.deployments.find(id=parents.deployment_id)
    assert deployment is not None
    assert deployment.status == status
    tasks = await uow.tasks.find_by_deployment(parents.deployment_id)
    assert TaskType.DELETE_DEPLOYMENT not in {task.type for task in tasks}
