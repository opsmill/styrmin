from uuid import uuid4

import pytest

from styrmin_backend.db.models import Cluster
from styrmin_backend.services.environments import (
    create_environment,
    delete_environment,
    get_environment,
    get_environments,
)
from styrmin_backend.services.exceptions import (
    EnvironmentAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
)
from tests.unit.services.fakes import FakeEnvironmentRepository, FakeUnitOfWork


async def test_create_environment(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    cluster_id = fake_cluster.id
    environment = await create_environment(
        name="test_environment", cluster_id=cluster_id, uow=uow
    )

    assert len(fake_environment_repository.models) == 1
    assert fake_environment_repository.models[0] == environment
    assert environment.name == "test_environment"
    assert environment.cluster_id == cluster_id

    assert uow.committed


async def test_create_environment_with_already_existing_name(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    cluster_id = fake_cluster.id

    await create_environment(name="test_environment", cluster_id=cluster_id, uow=uow)
    assert uow.committed

    with pytest.raises(EnvironmentAlreadyExistsError):
        await create_environment(
            name="test_environment", cluster_id=cluster_id, uow=uow
        )
    assert not uow.committed


async def test_create_environment_with_valid_config(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    cluster_id = fake_cluster.id
    config = {
        "ingress_class": "value",
        "db_size": "10Gi",
    }

    environment = await create_environment(
        name="test_environment", cluster_id=cluster_id, config=config, uow=uow
    )
    assert uow.committed

    assert len(fake_environment_repository.models) == 1
    assert fake_environment_repository.models[0] == environment
    assert environment.config == config


async def test_create_environment_with_wrong_config(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    config = {
        "ingress_class": "value",
        "db_size": "10Gi",
        "runtime_class": "value",
        "node_selector": "value",
        "dedicated_ingress": "value",
        "wrong_key": "value",
    }

    with pytest.raises(InvalidContextError):
        await create_environment(
            name="test_environment", cluster_id=fake_cluster.id, config=config, uow=uow
        )
    assert not uow.committed


async def test_get_environment(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_environment_repository: FakeEnvironmentRepository,
):
    environment = await create_environment(
        name="test_environment", cluster_id=fake_cluster.id, uow=uow
    )
    assert uow.committed

    result = await get_environment(environment_id=environment.id, uow=uow)

    assert result == environment


async def test_get_environment_that_does_not_exist(
    uow: FakeUnitOfWork,
):
    with pytest.raises(EnvironmentNotFoundError):
        await get_environment(environment_id=uuid4(), uow=uow)


async def test_get_all_environments(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    cluster_id = fake_cluster.id
    environment1 = await create_environment(
        name="test_environment1", cluster_id=cluster_id, uow=uow
    )
    assert uow.committed

    environment2 = await create_environment(
        name="test_environment2", cluster_id=cluster_id, uow=uow
    )
    assert uow.committed

    result = await get_environments(uow=uow)

    assert result == [environment1, environment2]


async def test_delete_environment(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    environment = await create_environment(
        name="test_environment", cluster_id=fake_cluster.id, uow=uow
    )
    assert uow.committed

    await delete_environment(environment_id=environment.id, uow=uow)
    assert uow.committed

    with pytest.raises(EnvironmentNotFoundError):
        await get_environment(environment_id=environment.id, uow=uow)


async def test_delete_environment_that_does_not_exist(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
):
    with pytest.raises(EnvironmentNotFoundError):
        await delete_environment(environment_id=fake_cluster.id, uow=uow)
    assert not uow.committed
