from uuid import uuid4

import pytest

from styrmin_backend.db.models import Cluster, Environment
from styrmin_backend.services.clusters import (
    create_cluster,
    delete_cluster,
    get_cluster,
    get_clusters,
    resolve_cluster,
)
from styrmin_backend.services.exceptions import (
    AmbiguousIdentifierError,
    ClusterInUseError,
    ClusterLimitReachedError,
    ClusterNotFoundError,
    InvalidContextError,
)
from tests.unit.services.fakes import FakeClusterRepository, FakeUnitOfWork


async def test_create_cluster(
    uow: FakeUnitOfWork, fake_cluster_repository: FakeClusterRepository
):
    cluster = await create_cluster(name="test_cluster", uow=uow)

    assert len(fake_cluster_repository.models) == 1
    assert fake_cluster_repository.models[0] == cluster
    assert uow.committed

    # Verify default config values are applied
    assert cluster.config is not None
    assert "dedicated_ingress" not in cluster.config
    assert cluster.config["ingress_class"] == "traefik"
    assert cluster.config["runtime_class"] == "default"


async def test_create_cluster_keeps_empty_dedicated_ingress(uow: FakeUnitOfWork):
    cluster = await create_cluster(
        name="test_cluster", config={"dedicated_ingress": {}}, uow=uow
    )

    assert cluster.config is not None
    assert cluster.config["dedicated_ingress"] == {}


async def test_create_cluster_with_already_existing_cluster(
    uow: FakeUnitOfWork, fake_cluster: Cluster
):
    with pytest.raises(ClusterLimitReachedError):
        await create_cluster(name=fake_cluster.name, uow=uow)
    assert not uow.committed


async def test_create_cluster_with_valid_configuration(
    uow: FakeUnitOfWork, fake_cluster_repository: FakeClusterRepository
):
    config = {
        "ingress_class": "value",
        "db_size": "10Gi",
        "runtime_class": "value",
        "dedicated_ingress": {"implementation": "traefik", "type": "ingress"},
    }

    cluster = await create_cluster(name="test_cluster", config=config, uow=uow)
    assert uow.committed

    assert len(fake_cluster_repository.models) == 1
    assert fake_cluster_repository.models[0] == cluster


async def test_create_cluster_defaults_can_be_overridden(
    uow: FakeUnitOfWork, fake_cluster_repository: FakeClusterRepository
):
    config = {
        "ingress_class": "nginx",
        "runtime_class": "gvisor",
        "dedicated_ingress": {"implementation": "nginx", "type": "ingress"},
    }

    cluster = await create_cluster(name="test_cluster", config=config, uow=uow)
    assert uow.committed

    assert cluster.config is not None
    assert cluster.config["ingress_class"] == "nginx"
    assert cluster.config["runtime_class"] == "gvisor"
    assert cluster.config["dedicated_ingress"] == {
        "implementation": "nginx",
        "type": "ingress",
    }


async def test_create_cluster_with_wrong_context(uow: FakeUnitOfWork):
    with pytest.raises(InvalidContextError):
        await create_cluster(name="test_cluster", config={"db_size": 10}, uow=uow)
    assert not uow.committed


async def test_get_cluster(uow: FakeUnitOfWork, fake_cluster: Cluster):
    cluster_id = fake_cluster.id

    cluster = await get_cluster(cluster_id=cluster_id, uow=uow)

    assert cluster.id == cluster_id
    assert cluster.name == fake_cluster.name


async def test_get_cluster_that_does_not_exist(uow):
    with pytest.raises(ClusterNotFoundError):
        await get_cluster(cluster_id=uuid4(), uow=uow)


async def test_get_clusters(uow: FakeUnitOfWork, fake_cluster: Cluster):
    cluster_id = fake_cluster.id

    clusters = await get_clusters(uow=uow)

    assert len(clusters) == 1
    assert clusters[0].id == cluster_id
    assert clusters[0].name == fake_cluster.name


async def test_delete_cluster(uow: FakeUnitOfWork, fake_cluster: Cluster):
    cluster_id = fake_cluster.id

    await delete_cluster(cluster_id=cluster_id, uow=uow)
    assert uow.committed

    with pytest.raises(ClusterNotFoundError):
        await get_cluster(cluster_id=cluster_id, uow=uow)


async def test_delete_cluster_that_does_not_exist(uow: FakeUnitOfWork):
    with pytest.raises(ClusterNotFoundError):
        await delete_cluster(cluster_id=uuid4(), uow=uow)
    assert not uow.committed


async def test_delete_cluster_with_environments_is_refused(
    uow: FakeUnitOfWork,
    fake_cluster: Cluster,
    fake_cluster_repository: FakeClusterRepository,
):
    fake_cluster.environments = [
        Environment(name="env-b", cluster_id=fake_cluster.id),
        Environment(name="env-a", cluster_id=fake_cluster.id),
    ]

    with pytest.raises(ClusterInUseError) as exc_info:
        await delete_cluster(cluster_id=fake_cluster.id, uow=uow)

    assert exc_info.value.error_metadata == {"environment_names": ["env-a", "env-b"]}
    assert str(exc_info.value) == (
        "Cluster 'test_cluster' still has environments: env-a, env-b. "
        "Delete them before deleting the cluster."
    )
    assert not uow.committed
    assert fake_cluster_repository.models == [fake_cluster]


async def test_create_cluster_raises_error_when_cluster_exists(
    uow: FakeUnitOfWork, fake_cluster: Cluster
):
    with pytest.raises(ClusterLimitReachedError):
        await create_cluster(name="another_cluster", uow=uow)
    assert not uow.committed


async def test_create_cluster_uses_default_name(
    uow: FakeUnitOfWork, fake_cluster_repository: FakeClusterRepository
):
    cluster = await create_cluster(uow=uow)

    assert cluster.name == "default"
    assert len(fake_cluster_repository.models) == 1
    assert uow.committed


async def test_create_cluster_after_delete_succeeds(
    uow: FakeUnitOfWork, fake_cluster: Cluster
):
    await delete_cluster(cluster_id=fake_cluster.id, uow=uow)

    cluster = await create_cluster(name="new_cluster", uow=uow)

    assert cluster.name == "new_cluster"


# --- resolve_cluster tests ---


async def test_resolve_cluster_by_id(uow: FakeUnitOfWork, fake_cluster: Cluster):
    cluster = await resolve_cluster(uow, cluster_id=fake_cluster.id)
    assert cluster.id == fake_cluster.id
    assert cluster.name == fake_cluster.name


async def test_resolve_cluster_by_name(uow: FakeUnitOfWork, fake_cluster: Cluster):
    cluster = await resolve_cluster(uow, cluster_name=fake_cluster.name)
    assert cluster.id == fake_cluster.id
    assert cluster.name == fake_cluster.name


async def test_resolve_cluster_raises_when_both_provided(
    uow: FakeUnitOfWork, fake_cluster: Cluster
):
    with pytest.raises(AmbiguousIdentifierError, match="not both"):
        await resolve_cluster(
            uow, cluster_id=fake_cluster.id, cluster_name=fake_cluster.name
        )


async def test_resolve_cluster_raises_when_neither_provided(uow: FakeUnitOfWork):
    with pytest.raises(AmbiguousIdentifierError, match="required"):
        await resolve_cluster(uow)


async def test_resolve_cluster_not_found_by_id(uow: FakeUnitOfWork):
    with pytest.raises(ClusterNotFoundError):
        await resolve_cluster(uow, cluster_id=uuid4())


async def test_resolve_cluster_not_found_by_name(uow: FakeUnitOfWork):
    with pytest.raises(ClusterNotFoundError):
        await resolve_cluster(uow, cluster_name="nonexistent")
