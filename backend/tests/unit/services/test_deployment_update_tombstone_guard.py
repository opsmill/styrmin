"""Tombstone guard for the update mutations.

``update_deployment`` and ``update_deployment_version`` both call
``deployment.set_status(DeploymentState.PENDING)`` after fetching the
deployment. Without an explicit guard, calling either against a
deployment in the deletion lifecycle would silently revive it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from styrmin_backend.domain.models import (
    Deployment as DeploymentEntity,
    DeploymentState,
)
from styrmin_backend.services.deployment import (
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.exceptions import DeploymentAlreadyDeletedError


@pytest.fixture
def seeded_deployment(uow) -> DeploymentEntity:
    deployment = DeploymentEntity(
        id=uuid4(),
        name="test-deployment",
        application_version="1.0.0",
        config={},
        parameters={},
        application_driver_version_id=uuid4(),
        environment_id=uuid4(),
        status=DeploymentState.RUNNING,
    )
    uow.deployments._deployments.append(deployment)
    return deployment


@pytest.mark.parametrize(
    "deletion_state",
    [
        DeploymentState.DELETION_REQUESTED,
        DeploymentState.DELETION_IN_PROGRESS,
        DeploymentState.DELETED,
    ],
)
async def test_update_deployment_rejects_tombstoned(
    uow, seeded_deployment, deletion_state
):
    seeded_deployment.set_status(deletion_state)

    with pytest.raises(DeploymentAlreadyDeletedError) as exc:
        await update_deployment(
            deployment_id=seeded_deployment.id,
            uow=uow,
            deployment_name="renamed",
        )

    assert exc.value.error_metadata == {"deployment_id": str(seeded_deployment.id)}
    # Status MUST NOT regress to PENDING — that's the whole point.
    assert uow.deployments._deployments[0].status == deletion_state


@pytest.mark.parametrize(
    "deletion_state",
    [
        DeploymentState.DELETION_REQUESTED,
        DeploymentState.DELETION_IN_PROGRESS,
        DeploymentState.DELETED,
    ],
)
async def test_update_deployment_version_rejects_tombstoned(
    uow, seeded_deployment, deletion_state
):
    seeded_deployment.set_status(deletion_state)

    with pytest.raises(DeploymentAlreadyDeletedError) as exc:
        await update_deployment_version(
            deployment_id=seeded_deployment.id,
            version="2.0.0",
            uow=uow,
        )

    assert exc.value.error_metadata == {"deployment_id": str(seeded_deployment.id)}
    assert uow.deployments._deployments[0].status == deletion_state
