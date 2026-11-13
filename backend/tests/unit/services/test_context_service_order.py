"""The services of this deployment are listed in the order its driver declares them (#598, T015).

The repository query has no ``ORDER BY``. The Ingress builder gives the application address to the
first declared service, so the order must not depend on how the database returns the rows.
"""

from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import DeployedService
from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services.context import generate_context_from_deployment
from tests.unit.services.test_context_deleting_peer_services import (
    _make_uow,
    _seed_environment,
)


async def _add_service(
    uow, deployment: Deployment, environment_id: UUID, name: str
) -> None:
    await uow.deployed_services.create(
        DeployedService(
            id=uuid4(),
            driver_service_name=name,
            resolved_name=name,
            kind="http",
            scope="external",
            port=8080,
            component="server",
            deployment_id=deployment.id,
            environment_id=environment_id,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row_order",
    [
        ["web", "api", "ui"],
        ["ui", "api", "web"],
        ["api", "ui", "web"],
    ],
    ids=["declared-order", "reversed", "shuffled"],
)
async def test_own_services_follow_the_driver_declaration_order(
    row_order: list[str],
) -> None:
    uow = _make_uow()
    environment_id, driver_version_id = await _seed_environment(uow)
    driver_version = await uow.application_driver_versions.get(driver_version_id)
    assert driver_version is not None
    # Declared order: web, api, ui (deliberately not alphabetical).
    driver_version.services = [{"name": "web"}, {"name": "api"}, {"name": "ui"}]
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=driver_version_id,
        environment_id=environment_id,
        created_by_user_id=uuid4(),
        name="deploy",
    )
    deployment.set_status(DeploymentState.RUNNING)
    await uow.deployments.save(deployment)
    for name in row_order:
        await _add_service(uow, deployment, environment_id, name)

    context = await generate_context_from_deployment(deployment, uow)

    own = [
        entry["driver_service_name"]
        for entry in context.deployed_services
        if entry["deployment_id"] == str(deployment.id)
    ]
    assert own == ["web", "api", "ui"]


@pytest.mark.asyncio
async def test_own_services_come_after_the_services_of_a_peer() -> None:
    uow = _make_uow()
    environment_id, driver_version_id = await _seed_environment(uow)
    driver_version = await uow.application_driver_versions.get(driver_version_id)
    assert driver_version is not None
    driver_version.services = [{"name": "app"}]
    deployments = []
    for name in ("one", "two"):
        deployment = Deployment.create(
            application_version="1.0.0",
            application_driver_version_id=driver_version_id,
            environment_id=environment_id,
            created_by_user_id=uuid4(),
            name=name,
        )
        deployment.set_status(DeploymentState.RUNNING)
        await uow.deployments.save(deployment)
        await uow.deployed_services.create(
            DeployedService(
                id=uuid4(),
                driver_service_name="app",
                resolved_name=f"app-{name}",
                kind="http",
                scope="external",
                port=8080,
                component="server",
                deployment_id=deployment.id,
                environment_id=environment_id,
            )
        )
        deployments.append(deployment)

    for current in deployments:
        context = await generate_context_from_deployment(current, uow)

        # Two deployments of one driver share the key ``app``: the current deployment wins it.
        assert context.services["app"]["host"] == f"app-{current.name}"
        assert context.deployed_services[-1]["deployment_id"] == str(current.id)
