"""A restore of the backup of an earlier instance makes that instance the active one (#426).

The cluster runs the restored instance, so the deployment's version, config, parameters,
driver binding and active instance must be the instance's. The check that the deployment
equals the instance is the one the next update makes: an instance generated from the
deployment must match the active instance, so the same request changes nothing.
"""

from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest

from styrmin_backend.domain.models import (
    Component,
    Deployment,
    InstanceStatus,
    TaskType,
)
from styrmin_backend.services.deployment import (
    _update_is_noop,
    adopt_restored_instance,
    update_deployment_version,
)
from styrmin_backend.services.exceptions import DeploymentNotFoundError
from styrmin_backend.services.reconciliation import generate_instance_from_deployment
from tests.unit.services.test_update_deployment_noop import (
    _fake_apply_state,
    _make_uow,
    _seed_steady_state_deployment,
)

COMPONENT_CONFIG = {"identifier": {"label": {"app": "server"}}}
SERVICE = {
    "name": "web",
    "kind": "http",
    "scope": "internal",
    "port": 8080,
    "component": "server",
}


async def _activate_new_instance(uow, deployment: Deployment) -> None:
    """Persist an instance generated from the deployment as it is, and make it active."""
    instance = await generate_instance_from_deployment(deployment=deployment, uow=uow)
    deployment.set_active_instance(instance=instance)
    await uow.instances.create(instance)
    await uow.deployments.save(deployment)


async def _assert_matches_active_instance(uow, deployment: Deployment) -> None:
    candidate = await generate_instance_from_deployment(deployment=deployment, uow=uow)
    assert _update_is_noop(
        current_instance=deployment.active_instance, new_instance=candidate
    ), "an instance generated from the deployment must match the active instance"


@pytest.mark.asyncio
async def test_restored_instance_becomes_the_active_instance_with_its_state() -> None:
    uow = _make_uow()
    deployment_id, environment_id = uuid4(), uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=environment_id,
        config={"env_vars": {"FOO": "bar"}},
    )
    earlier = deployment.active_instance
    assert earlier is not None

    # A later instance: another version, config and parameters
    deployment.application_version = "1.5.0"
    deployment.config = {"env_vars": {"FOO": "changed", "NEW": "1"}}
    deployment.parameters = {"size": "large"}
    await _activate_new_instance(uow, deployment)
    assert deployment.active_instance.id != earlier.id

    changed = await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=earlier.id, uow=uow
    )

    assert changed is True
    async with uow:
        after = await uow.deployments.find(id=deployment_id)
    assert after is not None and after.active_instance is not None
    assert after.active_instance.id == earlier.id
    assert after.application_version == "1.0.0"
    assert after.config == {"env_vars": {"FOO": "bar"}}
    assert after.parameters == {}
    await _assert_matches_active_instance(uow, after)


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_asking_for_the_later_version_after_the_restore_is_an_upgrade(
    mock_apply_state: AsyncMock,
) -> None:
    mock_apply_state.side_effect = _fake_apply_state
    uow = _make_uow()
    deployment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow, deployment_id=deployment_id, environment_id=uuid4()
    )
    earlier = deployment.active_instance
    deployment.application_version = "1.5.0"
    await _activate_new_instance(uow, deployment)
    await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=earlier.id, uow=uow
    )

    # The later version is what the deployment ran before the restore, not what it runs now
    async with uow:
        task = await update_deployment_version(
            deployment_id=deployment_id, version="1.5.0", uow=uow
        )

    assert task is not None, (
        "asking for the later version after the restore must not be a no-op"
    )
    assert task.type == TaskType.UPGRADE_INSTANCE
    mock_apply_state.assert_called_once()
    assert mock_apply_state.call_args.kwargs["current_instance"].id == earlier.id
    async with uow:
        after = await uow.deployments.find(id=deployment_id)
    assert after.application_version == "1.5.0"
    assert after.active_instance.id != earlier.id


@pytest.mark.asyncio
async def test_restoring_an_instance_without_config_clears_the_later_config() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow, deployment_id=deployment_id, environment_id=uuid4(), config=None
    )
    earlier = deployment.active_instance
    deployment.config = {"env_vars": {"FOO": "bar"}}
    await _activate_new_instance(uow, deployment)

    await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=earlier.id, uow=uow
    )

    async with uow:
        after = await uow.deployments.find(id=deployment_id)
    assert not after.config
    await _assert_matches_active_instance(uow, after)


@pytest.mark.asyncio
async def test_the_active_instance_is_left_as_it_is() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow, deployment_id=deployment_id, environment_id=uuid4()
    )
    active = deployment.active_instance
    deployment.application_version = "1.5.0"  # not realised: must stay

    changed = await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=active.id, uow=uow
    )

    assert changed is False
    async with uow:
        after = await uow.deployments.find(id=deployment_id)
    assert after.active_instance.id == active.id
    assert after.application_version == "1.5.0"


@pytest.mark.asyncio
async def test_an_instance_of_another_deployment_is_ignored() -> None:
    uow = _make_uow()
    first_id, second_id = uuid4(), uuid4()
    first = await _seed_steady_state_deployment(
        uow=uow, deployment_id=first_id, environment_id=uuid4()
    )
    other_instance = first.active_instance
    second = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=first.application_driver_version_id,
        environment_id=first.environment_id,
        created_by_user_id=uuid4(),
        config={},
        name="second",
    )
    object.__setattr__(second, "id", second_id)
    await uow.deployments.save(second)

    changed = await adopt_restored_instance(
        deployment_id=second_id, instance_id=other_instance.id, uow=uow
    )

    assert changed is False
    async with uow:
        assert (await uow.deployments.find(id=second_id)).active_instance is None


@pytest.mark.asyncio
async def test_an_unknown_deployment_is_refused() -> None:
    uow = _make_uow()
    with pytest.raises(DeploymentNotFoundError):
        await adopt_restored_instance(
            deployment_id=uuid4(), instance_id=uuid4(), uow=uow
        )


@pytest.mark.asyncio
async def test_a_restore_to_another_driver_version_binds_it_with_its_components_and_services() -> (
    None
):
    uow = _make_uow()
    deployment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=uuid4(),
        extra_versions=[("2.0.0", ">=1.0.0,<2.0.0")],
    )
    first_driver, second_driver = uow.application_driver_versions.models
    if first_driver.id != deployment.application_driver_version_id:
        first_driver, second_driver = second_driver, first_driver
    first_driver.services = [SERVICE]

    # The earlier instance: first driver version, one disabled component, one service
    deployment.set_components(
        [Component.create(name="server", config=COMPONENT_CONFIG, enabled=False)]
    )
    deployment.config = {"env_vars": {"FOO": "bar"}}
    from styrmin_backend.services.services_discovery import (
        reconcile_services_on_upgrade,
    )
    from styrmin_backend.services.driver.models.resources.services import (
        ServiceDefinition,
    )

    await reconcile_services_on_upgrade(
        deployment_id=deployment_id,
        environment_id=deployment.environment_id,
        new_service_definitions=[ServiceDefinition(**SERVICE)],
        uow=uow,
        service_name_overrides={"web": "renamed-web"},
    )
    await _activate_new_instance(uow, deployment)
    earlier = deployment.active_instance

    # A later instance on the second driver version: the service on another port, another component
    deployment.application_driver_version_id = second_driver.id
    deployment.application_version = "1.5.0"
    deployment.set_components(
        [
            Component.create(
                name="server",
                config={"identifier": {"label": {"app": "other"}}},
                enabled=True,
            )
        ]
    )
    second_driver.services = [{**SERVICE, "port": 9090}]
    await reconcile_services_on_upgrade(
        deployment_id=deployment_id,
        environment_id=deployment.environment_id,
        new_service_definitions=[ServiceDefinition(**{**SERVICE, "port": 9090})],
        uow=uow,
        service_name_overrides={"web": "renamed-web"},
    )
    await _activate_new_instance(uow, deployment)

    assert await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=earlier.id, uow=uow
    )

    async with uow:
        after = await uow.deployments.find(id=deployment_id)
        services = await uow.deployed_services.get_by_deployment_id(deployment_id)
    assert after.application_driver_version_id == first_driver.id
    assert after.application_version == "1.0.0"
    assert [(c.name, c.enabled, c.config) for c in after.components] == [
        ("server", False, COMPONENT_CONFIG)
    ]
    # The name the deployment gave the service is kept, the port is the first driver version's
    assert [(s.driver_service_name, s.resolved_name, s.port) for s in services] == [
        ("web", "renamed-web", 8080)
    ]
    assert earlier.status in (InstanceStatus.PENDING, InstanceStatus.RUNNING)
    await _assert_matches_active_instance(uow, after)


@pytest.mark.asyncio
async def test_a_config_with_every_kind_of_setting_is_restored_as_it_was() -> None:
    rich_config = {
        "ip_whitelist": ["10.0.0.0/8"],
        "env_vars": {"A": "1"},
        "components": {
            "server": {
                "env_vars": {"B": "2"},
                "command": ["run"],
                "args": ["--flag"],
                "replicas": 2,
            }
        },
    }
    uow = _make_uow()
    deployment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=uuid4(),
        config=rich_config,
    )
    earlier = deployment.active_instance
    deployment.config = {"env_vars": {"A": "changed"}}
    await _activate_new_instance(uow, deployment)

    await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=earlier.id, uow=uow
    )

    async with uow:
        after = await uow.deployments.find(id=deployment_id)
    assert after.config == rich_config
    await _assert_matches_active_instance(uow, after)


@pytest.mark.asyncio
async def test_a_deployment_without_an_active_instance_is_not_given_one() -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    deployment = await _seed_steady_state_deployment(
        uow=uow, deployment_id=deployment_id, environment_id=uuid4()
    )
    instance = deployment.active_instance
    deployment.set_active_instance(instance=None)
    await uow.deployments.save(deployment)

    changed = await adopt_restored_instance(
        deployment_id=deployment_id, instance_id=instance.id, uow=uow
    )

    assert changed is False
    async with uow:
        assert (await uow.deployments.find(id=deployment_id)).active_instance is None
