"""Propagation tests for the deleteDeployment GraphQL mutation.

Covers the constitutional §V "GraphQL ↔ Database Propagation Tests" gate
for the new schema surface introduced by the deployment-deletion feature
(spec 008): the ``deleteDeployment(id) -> Task!`` mutation, the
``Deployment.deletedAt`` scalar field, the
``Environment.deployments(includeDeleted)`` argument, and the
``DELETE_DEPLOYMENT`` task type.

The cluster-side patch (``spec.deletionRequested``) is mocked at the
service-module boundary — the test asserts on the call shape and the DB
state it leaves behind.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.db.models import (
    Deployment,
    DeploymentState,
    Step,
    StepStatus,
    Task,
    TaskStatus,
    TaskType,
)

from styrmin_backend.repository.deployment import SQLModelDeploymentRepository

from ._queries import load_query
from .conftest import gql
from .seeds import seed_deployment, seed_environment


@pytest.fixture
def patch_crd_mock(mocker):
    """Mock the cluster-side CRD patch issued by ``delete_deployment``.

    The service issues ``patch_custom_resource(...)`` via a fast_depends
    @inject wrapper. Patching the symbol imported at the service-module
    boundary intercepts the call without dragging in a real Kubernetes
    client. The returned mock lets tests assert on the call shape.
    """

    return mocker.patch(
        "styrmin_backend.services.deployment.patch_custom_resource",
        autospec=True,
    )


@pytest.mark.asyncio
async def test_delete_deployment_writes_task_and_patches_crd(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """Happy path: a RUNNING deployment is sent through the resolver →
    service → repo → DB; a DELETE_DEPLOYMENT task is persisted, the CRD
    patch is issued, and the deployment row is *not yet* tombstoned (the
    status reporter does that off the cluster's response)."""

    deployment = await seed_deployment(session, internal=False)
    deployment.status = DeploymentState.RUNNING
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    data = await gql(client, "delete_deployment", {"deploymentId": str(deployment_id)})
    payload = data["deleteDeployment"]

    assert payload["type"] == "delete_deployment"
    assert payload["status"] == "success"
    assert payload["deploymentId"] == str(deployment_id)

    # CRD patch was issued exactly once with the expected shape.
    patch_crd_mock.assert_called_once()
    kwargs = patch_crd_mock.call_args.kwargs
    assert kwargs["plural"] == "styrmindeployments"
    assert kwargs["group"] == "styrmin.io"
    assert kwargs["version"] == "v1alpha1"
    assert kwargs["reference"] == f"styrmin-{deployment_id}"
    assert kwargs["namespace"] == f"styrmin-{deployment_id}"
    assert kwargs["patch"] == [
        {"op": "add", "path": "/spec/deletionRequested", "value": True}
    ]

    # DB-side propagation: Task row exists with the new type.
    session.expire_all()
    task_db = await session.get(Task, UUID(payload["id"]))
    assert task_db is not None
    assert task_db.type == TaskType.DELETE_DEPLOYMENT
    assert task_db.status == TaskStatus.SUCCESS
    assert task_db.deployment_id == deployment_id

    # The mutation does NOT tombstone the row — that is the status
    # reporter's job once the cluster reports phase: Deleted.
    deployment_db = await session.get(Deployment, deployment_id)
    assert deployment_db is not None
    assert deployment_db.deleted_at is None
    assert deployment_db.status == DeploymentState.RUNNING


@pytest.mark.asyncio
async def test_delete_deployment_idempotent_on_deleting(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """A second mutation while DELETING returns the most recent existing
    DELETE_DEPLOYMENT task without re-patching the CRD."""

    deployment = await seed_deployment(session)
    deployment.status = DeploymentState.RUNNING
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id

    first = await gql(client, "delete_deployment", {"deploymentId": str(deployment_id)})

    # Simulate the cluster reporting "Deleting" back to the DB.
    deployment_db = await session.get(Deployment, deployment_id)
    assert deployment_db is not None
    deployment_db.status = DeploymentState.DELETING
    session.add(deployment_db)
    await session.commit()

    second = await gql(
        client, "delete_deployment", {"deploymentId": str(deployment_id)}
    )

    assert first["deleteDeployment"]["id"] == second["deleteDeployment"]["id"]
    # CRD only patched on the first call; second call is a no-op at the
    # cluster boundary.
    assert patch_crd_mock.call_count == 1


@pytest.mark.asyncio
async def test_delete_deployment_rejects_restoring(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """RESTORING deployments are protected for data-integrity reasons."""

    deployment = await seed_deployment(session)
    deployment.status = DeploymentState.RESTORING
    session.add(deployment)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_deployment"),
            "variables": {"deploymentId": str(deployment.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "DEPLOYMENT_RESTORING"
        for err in payload["errors"]
    ), payload["errors"]
    patch_crd_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_deployment_returns_not_found_on_tombstone(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """A delete on an already-tombstoned (DELETED, deleted_at set)
    deployment surfaces NOT_FOUND — intentional conflation with unknown
    id, per the platform contract."""

    deployment = await seed_deployment(session)
    deployment.status = DeploymentState.DELETED
    deployment.deleted_at = datetime.now(tz=timezone.utc)
    session.add(deployment)
    await session.commit()

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_deployment"),
            "variables": {"deploymentId": str(deployment.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "NOT_FOUND" for err in payload["errors"]
    ), payload["errors"]
    patch_crd_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_deployment_returns_not_found_on_unknown_id(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_deployment"),
            "variables": {"deploymentId": "00000000-0000-0000-0000-000000000000"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "NOT_FOUND" for err in payload["errors"]
    ), payload["errors"]
    patch_crd_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_deployment_rejects_internal_deployment(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """Internal (system-managed) deployments cannot be deleted via this
    mutation — same OPERATION_DENIED guard as update_deployment."""

    deployment = await seed_deployment(session, internal=True)

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_deployment"),
            "variables": {"deploymentId": str(deployment.id)},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(
        err["extensions"].get("code") == "OPERATION_DENIED" for err in payload["errors"]
    ), payload["errors"]
    patch_crd_mock.assert_not_called()


async def _step_statuses(session: AsyncSession, task_id: UUID) -> dict[str, StepStatus]:
    rows = (await session.exec(select(Step).where(Step.task_id == task_id))).all()
    return {step.key: step.status for step in rows}


async def _report_deleted(client: AsyncClient, deployment_id: UUID) -> None:
    await gql(
        client,
        "report_deployment_statuses",
        {
            "reports": [
                {
                    "deploymentId": str(deployment_id),
                    "phase": "Deleted",
                    "displayState": "Deleted",
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_last_app_tombstone_tears_down_ingress_controller(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """#252: tombstoning an environment's last app flags its internal ingress
    controller for deletion; the controller's own terminal report then
    tombstones it, and it no longer counts as the environment's controller."""

    environment = await seed_environment(session)
    app = await seed_deployment(session, environment=environment)
    ingress = await seed_deployment(
        session,
        environment=environment,
        name="styrmin-ingress-controller",
        internal=True,
    )
    app.status = DeploymentState.DELETING
    session.add(app)
    await session.commit()
    environment_id, app_id, ingress_id = environment.id, app.id, ingress.id

    await _report_deleted(client, app_id)

    patch_crd_mock.assert_called_once()
    assert patch_crd_mock.call_args.kwargs["reference"] == f"styrmin-{ingress_id}"
    session.expire_all()
    ingress_db = await session.get(Deployment, ingress_id)
    assert ingress_db is not None
    assert ingress_db.status == DeploymentState.DELETING
    assert ingress_db.deleted_at is None
    ingress_tasks = (
        await session.exec(select(Task).where(Task.deployment_id == ingress_id))
    ).all()
    assert [task.type for task in ingress_tasks] == [TaskType.DELETE_DEPLOYMENT]
    delete_task_id = ingress_tasks[0].id
    assert await _step_statuses(session, delete_task_id) == {
        "resource:delete-request": StepStatus.SUCCEEDED,
        "operator:teardown": StepStatus.PENDING,
    }

    await _report_deleted(client, ingress_id)

    session.expire_all()
    ingress_db = await session.get(Deployment, ingress_id)
    assert ingress_db is not None
    assert ingress_db.status == DeploymentState.DELETED
    assert ingress_db.deleted_at is not None
    assert (await _step_statuses(session, delete_task_id))[
        "operator:teardown"
    ] == StepStatus.SUCCEEDED
    assert patch_crd_mock.call_count == 1
    repository = SQLModelDeploymentRepository(session)
    assert await repository.find_internal_by_environment(environment_id) is None


@pytest.mark.asyncio
async def test_non_last_app_tombstone_keeps_ingress_controller(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """#252: another live app in the environment keeps the controller."""

    environment = await seed_environment(session)
    app = await seed_deployment(session, environment=environment)
    await seed_deployment(session, environment=environment)
    ingress = await seed_deployment(
        session,
        environment=environment,
        name="styrmin-ingress-controller",
        internal=True,
    )
    app.status = DeploymentState.DELETING
    session.add(app)
    await session.commit()
    ingress_id = ingress.id

    await _report_deleted(client, app.id)

    patch_crd_mock.assert_not_called()
    session.expire_all()
    ingress_db = await session.get(Deployment, ingress_id)
    assert ingress_db is not None
    assert ingress_db.status == DeploymentState.PENDING


@pytest.mark.asyncio
async def test_delete_deployment_without_styrmin_deployment_reaches_deleted(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """Spec 029, T052: a create that failed before it wrote the CR leaves
    nothing on the cluster, so the patch finds no CR. The mutation returns
    the delete task instead of an internal error, the deployment goes to
    DELETING, and the reporter's Deleted report tombstones it."""

    deployment = await seed_deployment(session)
    deployment.status = DeploymentState.FAILED
    session.add(deployment)
    await session.commit()
    deployment_id = deployment.id
    patch_crd_mock.side_effect = CustomResourceNotFound(
        f"Custom resource styrmindeployments/styrmin-{deployment_id} not found "
        f"in namespace styrmin-{deployment_id}"
    )

    data = await gql(client, "delete_deployment", {"deploymentId": str(deployment_id)})
    payload = data["deleteDeployment"]

    assert payload["type"] == "delete_deployment"
    assert payload["status"] == "success"
    session.expire_all()
    deployment_db = await session.get(Deployment, deployment_id)
    assert deployment_db is not None
    assert deployment_db.status == DeploymentState.DELETING
    assert deployment_db.deleted_at is None
    task_id = UUID(payload["id"])
    assert await _step_statuses(session, task_id) == {
        "resource:delete-request": StepStatus.SUCCEEDED,
        "operator:teardown": StepStatus.PENDING,
    }

    await _report_deleted(client, deployment_id)

    session.expire_all()
    deployment_db = await session.get(Deployment, deployment_id)
    assert deployment_db is not None
    assert deployment_db.status == DeploymentState.DELETED
    assert deployment_db.deleted_at is not None
    assert (await _step_statuses(session, task_id))[
        "operator:teardown"
    ] == StepStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_delete_deployment_without_styrmin_deployment_during_a_change_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    patch_crd_mock,
) -> None:
    """Spec 029, T052: while a change is applied, its flow can still write
    the CR, so the deletion is refused with a typed error."""

    deployment = await seed_deployment(session)  # PENDING
    deployment_id = deployment.id
    patch_crd_mock.side_effect = CustomResourceNotFound("not found")

    response = await client.post(
        "/graphql",
        json={
            "query": load_query("delete_deployment"),
            "variables": {"deploymentId": str(deployment_id)},
        },
    )

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert [error["extensions"]["code"] for error in errors] == [
        "ALREADY_IN_PROGRESS"
    ], errors
    assert "Delete the deployment again" in errors[0]["message"], errors
    session.expire_all()
    deployment_db = await session.get(Deployment, deployment_id)
    assert deployment_db is not None
    assert deployment_db.status == DeploymentState.PENDING
    tasks = (
        await session.exec(select(Task).where(Task.deployment_id == deployment_id))
    ).all()
    assert tasks == []
