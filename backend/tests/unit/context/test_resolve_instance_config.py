"""Unit tests for the public ``resolve_instance_config`` entry point.

The cluster config fan-out (021-cluster-config-update, research D1) compares
this result with the resolved config stored on each active instance, so it
must apply the same merge rules as the full context resolution.
"""

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    SchedulingConfig,
    Toleration,
)
from styrmin_backend.context.resolvers import (
    _resolve_instance_config,
    resolve_instance_config,
)


def test_deepest_level_wins_for_each_key():
    cluster = ClusterConfig(
        ingress_class="traefik", fqdn_suffix="example.com", db_size="1Gi"
    )
    environment = EnvironmentConfig(ingress_class="nginx", db_size="2Gi")
    deployment = DeploymentConfig(db_size="5Gi")

    resolved = resolve_instance_config(cluster, environment, deployment)

    assert resolved.ingress_class == "nginx"
    assert resolved.db_size == "5Gi"
    assert resolved.fqdn_suffix == "example.com"


def test_env_vars_merge_per_key():
    environment = EnvironmentConfig(env_vars={"LOG_LEVEL": "info", "REGION": "eu"})
    deployment = DeploymentConfig(env_vars={"LOG_LEVEL": "debug", "WORKERS": "4"})

    resolved = resolve_instance_config(ClusterConfig(), environment, deployment)

    assert resolved.env_vars == {"LOG_LEVEL": "debug", "REGION": "eu", "WORKERS": "4"}


def test_cluster_scheduling_is_ignored():
    cluster = ClusterConfig(
        scheduling=SchedulingConfig(
            runtime_class="kata",
            tolerations=[Toleration(key="cluster-only", operator="Exists")],
        )
    )

    resolved = resolve_instance_config(cluster, EnvironmentConfig(), DeploymentConfig())

    assert resolved.scheduling is None


def test_cluster_scheduling_is_not_merged_into_environment_scheduling():
    cluster = ClusterConfig(
        scheduling=SchedulingConfig(
            runtime_class="kata",
            tolerations=[Toleration(key="cluster-only", operator="Exists")],
        )
    )
    environment = EnvironmentConfig(
        scheduling=SchedulingConfig(
            tolerations=[Toleration(key="env-only", operator="Exists")]
        )
    )

    resolved = resolve_instance_config(cluster, environment, DeploymentConfig())

    assert resolved.scheduling is not None
    assert resolved.scheduling.runtime_class is None
    assert [t.key for t in resolved.scheduling.tolerations or []] == ["env-only"]


def test_matches_the_private_resolver():
    cluster = ClusterConfig(ingress_class="traefik", runtime_class="default")
    environment = EnvironmentConfig(fqdn_suffix="env.example.com")
    deployment = DeploymentConfig(env_vars={"A": "1"})

    assert resolve_instance_config(
        cluster, environment, deployment
    ) == _resolve_instance_config(
        cluster=cluster, environment=environment, deployment=deployment
    )
