"""Unit tests for capability derivation logic."""

from uuid import uuid4

from styrmin_backend.db.models import BackupStorageLocation, Cluster, Environment
from styrmin_backend.services.capabilities import (
    compute_cluster_capabilities,
    compute_environment_capabilities,
)


# ===== US1: Cluster capability tests =====


def test_cluster_capabilities_storage_from_standard_storage():
    """T009: Storage capability derived from standard_storage config."""
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={"standard_storage": {"storage_class": "standard"}},
    )
    result = compute_cluster_capabilities(cluster)

    assert result is not None
    assert "storage" in result
    assert "standard" in result["storage"]
    assert result["storage"]["standard"]["storage_class"] == "standard"


def test_cluster_capabilities_ingress_from_ingress_class_and_fqdn():
    """T010: Ingress capability derived from ingress_class + fqdn_suffix."""
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={
            "ingress_class": "traefik",
            "fqdn_suffix": "apps.example.com",
        },
    )
    result = compute_cluster_capabilities(cluster)

    assert result is not None
    assert "ingress" in result
    assert "external" in result["ingress"]
    assert result["ingress"]["external"]["ingress_class"] == "traefik"
    assert result["ingress"]["external"]["fqdn_suffix"] == "apps.example.com"


def test_cluster_capabilities_ingress_absent_without_fqdn():
    """T010 (edge): No ingress capability when fqdn_suffix is missing."""
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={"ingress_class": "traefik"},
    )
    result = compute_cluster_capabilities(cluster)

    # May be None or a dict without ingress
    if result is not None:
        assert "ingress" not in result


def test_cluster_capabilities_empty_config_returns_none():
    """T011: Empty/null config returns None."""
    cluster = Cluster(id=uuid4(), name="test-cluster", config=None)
    result = compute_cluster_capabilities(cluster)
    assert result is None


def test_cluster_capabilities_empty_dict_config_returns_none():
    """T011: Empty dict config returns None."""
    cluster = Cluster(id=uuid4(), name="test-cluster", config={})
    result = compute_cluster_capabilities(cluster)
    assert result is None


def test_cluster_capabilities_combined_storage_and_ingress():
    """Both storage and ingress capabilities present."""
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={
            "standard_storage": {"storage_class": "fast-ssd"},
            "ingress_class": "nginx",
            "fqdn_suffix": "k8s.internal",
        },
    )
    result = compute_cluster_capabilities(cluster)

    assert result is not None
    assert "storage" in result
    assert "ingress" in result
    assert result["storage"]["standard"]["storage_class"] == "fast-ssd"
    assert result["ingress"]["external"]["ingress_class"] == "nginx"


def test_cluster_capabilities_dedicated_ingress():
    """Ingress capability derived from dedicated_ingress + fqdn_suffix."""
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={
            "dedicated_ingress": {"implementation": "traefik", "type": "ingress"},
            "fqdn_suffix": "apps.example.com",
        },
    )
    result = compute_cluster_capabilities(cluster)

    assert result is not None
    assert "ingress" in result
    assert result["ingress"]["external"]["ingress_class"] == "traefik"


def test_cluster_capabilities_empty_dedicated_ingress_uses_defaults():
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={"dedicated_ingress": {}, "fqdn_suffix": "apps.example.com"},
    )
    result = compute_cluster_capabilities(cluster)

    assert result is not None
    assert result["ingress"]["external"]["ingress_class"] == "traefik"


def test_cluster_capabilities_no_ingress_without_class_or_dedicated_ingress():
    cluster = Cluster(
        id=uuid4(),
        name="test-cluster",
        config={"fqdn_suffix": "apps.example.com"},
    )

    assert compute_cluster_capabilities(cluster) is None


# ===== US2: Environment capability tests =====


def test_environment_capabilities_backup_from_bsl():
    """T016: Backup capability derived from backup_storage_location."""
    bsl = BackupStorageLocation(
        id=uuid4(),
        name="main-backup",
        endpoint="s3.example.com",
        bucket="backups",
        region="us-east-1",
        access_key_id="key",
        secret_access_key="secret",
    )
    environment = Environment(
        id=uuid4(),
        name="production",
        cluster_id=uuid4(),
        config={},
    )
    environment.backup_storage_location = bsl

    result = compute_environment_capabilities(environment)

    assert result is not None
    assert "backup" in result
    assert "velero" in result["backup"]
    assert result["backup"]["velero"]["storage_location"] == "main-backup"


def test_environment_capabilities_no_backup_without_bsl():
    """T016 (edge): No backup capability when BSL not assigned."""
    environment = Environment(
        id=uuid4(),
        name="staging",
        cluster_id=uuid4(),
        config={},
    )
    environment.backup_storage_location = None

    result = compute_environment_capabilities(environment)

    if result is not None:
        assert "backup" not in result


def test_environment_capabilities_storage_scoped_to_env():
    """T017: Environment storage derived from env's own config, not cluster."""
    environment = Environment(
        id=uuid4(),
        name="production",
        cluster_id=uuid4(),
        config={},
    )
    environment.backup_storage_location = None

    # Environment has no standard_storage in its own config
    result = compute_environment_capabilities(environment)

    # Should not inherit cluster storage — env-scoped view
    if result is not None:
        assert "storage" not in result


def test_environment_capabilities_ingress_scoped():
    """T018: Ingress derivation scoped to environment config."""
    environment = Environment(
        id=uuid4(),
        name="production",
        cluster_id=uuid4(),
        config={
            "ingress_class": "nginx",
            "fqdn_suffix": "prod.example.com",
        },
    )
    environment.backup_storage_location = None

    result = compute_environment_capabilities(environment)

    assert result is not None
    assert "ingress" in result
    assert result["ingress"]["external"]["ingress_class"] == "nginx"
    assert result["ingress"]["external"]["fqdn_suffix"] == "prod.example.com"


def test_environment_capabilities_no_ingress_without_fqdn():
    """T018 (edge): No ingress when fqdn_suffix missing from env config."""
    environment = Environment(
        id=uuid4(),
        name="staging",
        cluster_id=uuid4(),
        config={"ingress_class": "traefik"},
    )
    environment.backup_storage_location = None

    result = compute_environment_capabilities(environment)

    if result is not None:
        assert "ingress" not in result


# ===== US3: Context model tests =====


def test_cluster_context_includes_capabilities():
    """T023: ClusterContext model_dump includes capabilities field."""
    from styrmin_backend.context.models.config import ClusterConfig
    from styrmin_backend.context.models.contexts import ClusterContext

    ctx = ClusterContext(
        config=ClusterConfig(),
        capabilities={"storage": {"standard": {"storage_class": "standard"}}},
    )
    dumped = ctx.model_dump(exclude_none=True)

    assert "capabilities" in dumped
    assert dumped["capabilities"]["storage"]["standard"]["storage_class"] == "standard"


def test_cluster_context_empty_capabilities():
    """T023: ClusterContext with empty capabilities."""
    from styrmin_backend.context.models.config import ClusterConfig
    from styrmin_backend.context.models.contexts import ClusterContext

    ctx = ClusterContext(config=ClusterConfig(), capabilities={})
    dumped = ctx.model_dump(exclude_none=True)

    assert "capabilities" in dumped
    assert dumped["capabilities"] == {}


def test_environment_context_includes_capabilities():
    """T024: EnvironmentContext model_dump includes capabilities field."""
    from styrmin_backend.context.models.config import EnvironmentConfig
    from styrmin_backend.context.models.contexts import EnvironmentContext

    ctx = EnvironmentContext(
        name="production",
        config=EnvironmentConfig(),
        capabilities={"backup": {"velero": {"storage_location": "main"}}},
    )
    dumped = ctx.model_dump(exclude_none=True)

    assert "capabilities" in dumped
    assert dumped["capabilities"]["backup"]["velero"]["storage_location"] == "main"
