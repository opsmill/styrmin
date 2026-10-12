"""Unit tests for ``update_cluster`` (021-cluster-config-update, User Story 1).

The fan-out itself has its own suite (``test_cluster_config_fanout.py``); here
the redeploy is replaced by a recorder so each test observes what the update
saves, refuses and commits.
"""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import (
    Backup,
    BackupStatus,
    Cluster,
    Environment,
    EnvironmentBackup,
    EnvironmentClone,
    EnvironmentRestore,
    Restore,
    RestoreStatus,
)
from styrmin_backend.domain.models import Deployment, Task, TaskType
from styrmin_backend.services.backup.clone import find_clone_occupying_environment
from styrmin_backend.services.clusters import update_cluster
from styrmin_backend.services.exceptions import (
    ClusterNotFoundError,
    EnvironmentOperationInProgressError,
    InvalidContextError,
)
from tests.unit.services.fakes import FakeUnitOfWork

USER_ID = UUID("11111111-1111-1111-1111-111111111111")
REDEPLOY = (
    "styrmin_backend.services.cluster_config_fanout.redeploy_for_environment_update"
)


async def _seed_cluster(uow: FakeUnitOfWork, config: dict | None = None) -> Cluster:
    cluster = Cluster(
        name="default",
        config=config or {"ingress_class": "traefik", "runtime_class": "default"},
    )
    return await uow.clusters.create(cluster)


async def _seed_environment(
    uow: FakeUnitOfWork, cluster: Cluster, name: str
) -> Environment:
    return await uow.environments.create(
        Environment(name=name, cluster_id=cluster.id, config={})
    )


async def _seed_deployment(
    uow: FakeUnitOfWork, environment: Environment, name: str
) -> Deployment:
    # No active instance, so the fan-out finds it not at config and redeploys it.
    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=uuid4(),
        environment_id=environment.id,
        created_by_user_id=USER_ID,
        name=name,
    )
    await uow.deployments.save(deployment)
    return deployment


def _seed_clone_occupying(uow: FakeUnitOfWork, environment: Environment) -> None:
    """A clone whose capture of ``environment`` is still running occupies it."""
    capture = EnvironmentBackup(
        name=f"capture-{uuid4().hex[:6]}", environment_id=environment.id
    )
    uow.environment_backups.models.append(capture)
    uow.backups.models.append(
        Backup(
            name=f"backup-{uuid4().hex[:6]}",
            status=BackupStatus.IN_PROGRESS,
            instance_id=uuid4(),
            environment_backup_id=capture.id,
        )
    )
    uow.environment_clones.models.append(
        EnvironmentClone(
            name="rehearsal",
            source_environment_id=environment.id,
            source_environment_name=environment.name,
            environment_backup_id=capture.id,
        )
    )


def _seed_environment_backup_in_progress(
    uow: FakeUnitOfWork, environment: Environment
) -> None:
    capture = EnvironmentBackup(
        name=f"capture-{uuid4().hex[:6]}", environment_id=environment.id
    )
    uow.environment_backups.models.append(capture)
    uow.backups.models.append(
        Backup(
            name=f"backup-{uuid4().hex[:6]}",
            status=BackupStatus.IN_PROGRESS,
            instance_id=uuid4(),
            environment_backup_id=capture.id,
        )
    )


def _seed_environment_restore_in_progress(
    uow: FakeUnitOfWork, environment: Environment
) -> None:
    capture = EnvironmentBackup(
        name=f"capture-{uuid4().hex[:6]}", environment_id=environment.id
    )
    uow.environment_backups.models.append(capture)
    environment_restore = EnvironmentRestore(environment_backup_id=capture.id)
    uow.environment_restores.models.append(environment_restore)
    uow.restores.models.append(
        Restore(
            name=f"restore-{uuid4().hex[:6]}",
            status=RestoreStatus.IN_PROGRESS,
            target_namespace="styrmin-target",
            backup_id=uuid4(),
            environment_restore_id=environment_restore.id,
        )
    )


@pytest.fixture
def redeploy_recorder(mocker):
    """Replace the redeploy with a recorder that returns a task for each call."""
    calls: list[Deployment] = []

    async def _record(deployment: Deployment, uow: FakeUnitOfWork) -> Task:
        calls.append(deployment)
        return Task.create(type=TaskType.UPDATE_INSTANCE, deployment_id=deployment.id)

    mocker.patch(REDEPLOY, side_effect=_record)
    return calls


async def test_update_cluster_commits_the_cluster_row_before_the_first_task(
    uow: FakeUnitOfWork, mocker
):
    """FR-001: the new config is committed before any redeploy creates a task."""
    cluster = await _seed_cluster(uow)
    environment = await _seed_environment(uow, cluster, "staging")
    await _seed_deployment(uow, environment, "web")

    committed: list[tuple[dict, dict | None]] = []
    original_commit = uow.commit

    async def _recording_commit() -> None:
        stored = await uow.clusters.get(cluster.id)
        assert stored is not None
        committed.append((deepcopy(stored.config), deepcopy(stored.capabilities)))
        await original_commit()

    mocker.patch.object(uow, "commit", side_effect=_recording_commit)

    committed_when_task_created: list[list[tuple[dict, dict | None]]] = []

    async def _record(deployment: Deployment, uow: FakeUnitOfWork) -> Task:
        committed_when_task_created.append(list(committed))
        return Task.create(type=TaskType.UPDATE_INSTANCE, deployment_id=deployment.id)

    mocker.patch(REDEPLOY, side_effect=_record)

    new_config = {
        "ingress_class": "nginx",
        "runtime_class": "default",
        "fqdn_suffix": "apps.example.com",
    }
    await update_cluster(uow, cluster.id, new_config, USER_ID)

    # FR-007: the capabilities are committed in the same commit as the config.
    capabilities = {
        "ingress": {
            "external": {"ingress_class": "nginx", "fqdn_suffix": "apps.example.com"}
        }
    }
    assert committed_when_task_created == [[(new_config, capabilities)]]


async def test_update_cluster_clears_omitted_values_and_applies_defaults(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    """FR-005: the update replaces the whole config; only the create defaults come back."""
    cluster = await _seed_cluster(
        uow,
        {
            "ingress_class": "nginx",
            "runtime_class": "gvisor",
            "fqdn_suffix": "apps.example.com",
            "db_size": "10Gi",
        },
    )

    updated = await update_cluster(uow, cluster.id, {"db_size": "20Gi"}, USER_ID)

    assert updated.config == {
        "ingress_class": "traefik",
        "runtime_class": "default",
        "db_size": "20Gi",
    }
    stored = await uow.clusters.get(cluster.id)
    assert stored is not None
    assert "fqdn_suffix" not in (stored.config or {})


async def test_update_cluster_keeps_submitted_ingress_and_runtime_class(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    cluster = await _seed_cluster(uow)

    updated = await update_cluster(
        uow, cluster.id, {"ingress_class": "nginx", "runtime_class": "gvisor"}, USER_ID
    )

    assert updated.config == {"ingress_class": "nginx", "runtime_class": "gvisor"}


async def test_update_cluster_adding_fqdn_suffix_adds_the_ingress_capability(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    """FR-007: the capabilities are recomputed in the same transaction as the config."""
    cluster = await _seed_cluster(uow)
    assert cluster.capabilities is None

    updated = await update_cluster(
        uow, cluster.id, {"fqdn_suffix": "apps.example.com"}, USER_ID
    )

    assert updated.capabilities == {
        "ingress": {
            "external": {
                "ingress_class": "traefik",
                "fqdn_suffix": "apps.example.com",
            }
        }
    }
    assert uow.commit_count >= 1


@pytest.mark.parametrize(
    "config",
    [
        pytest.param({"db_size": 10}, id="wrong-type"),
        pytest.param({"fqdn_sufix": "apps.example.com"}, id="unknown-key"),
        pytest.param({"dedicated_ingress": {"servce": {}}}, id="unknown-nested-key"),
    ],
)
async def test_update_cluster_refuses_an_invalid_config_and_keeps_the_stored_one(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment], config: dict
):
    """FR-008: ``InvalidContextError`` (``VALIDATION_ERROR``) and nothing saved."""
    original = {
        "ingress_class": "nginx",
        "runtime_class": "default",
        "fqdn_suffix": "apps.example.com",
    }
    cluster = await _seed_cluster(uow, deepcopy(original))
    environment = await _seed_environment(uow, cluster, "staging")
    await _seed_deployment(uow, environment, "web")

    with pytest.raises(InvalidContextError) as excinfo:
        await update_cluster(uow, cluster.id, config, USER_ID)

    assert excinfo.value.error_code == "VALIDATION_ERROR"
    stored = await uow.clusters.get(cluster.id)
    assert stored is not None
    assert stored.config == original
    assert uow.commit_count == 0
    assert redeploy_recorder == []


async def test_update_cluster_refused_while_a_clone_occupies_any_environment(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    """FR-006: a clone in progress on one environment refuses the whole update."""
    original = {"ingress_class": "traefik", "runtime_class": "default"}
    cluster = await _seed_cluster(uow, deepcopy(original))
    free = await _seed_environment(uow, cluster, "staging")
    occupied = await _seed_environment(uow, cluster, "production")
    await _seed_deployment(uow, free, "web")
    _seed_clone_occupying(uow, occupied)
    assert await find_clone_occupying_environment(occupied.id, uow) is not None

    with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
        await update_cluster(uow, cluster.id, {"ingress_class": "nginx"}, USER_ID)

    assert excinfo.value.operation_kind == "environment_clone"
    stored = await uow.clusters.get(cluster.id)
    assert stored is not None
    assert stored.config == original
    assert uow.commit_count == 0
    assert redeploy_recorder == []


async def test_update_cluster_accepted_while_an_environment_backup_is_in_progress(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    """FR-006: environment backups do not block a config update."""
    cluster = await _seed_cluster(uow)
    environment = await _seed_environment(uow, cluster, "staging")
    _seed_environment_backup_in_progress(uow, environment)
    assert (
        await uow.environment_backups.has_in_progress_environment_backup(environment.id)
        is not None
    )

    updated = await update_cluster(uow, cluster.id, {"ingress_class": "nginx"}, USER_ID)

    assert updated.config is not None
    assert updated.config["ingress_class"] == "nginx"


async def test_update_cluster_accepted_while_an_environment_restore_is_in_progress(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    """FR-006: environment restores do not block a config update."""
    cluster = await _seed_cluster(uow)
    environment = await _seed_environment(uow, cluster, "staging")
    _seed_environment_restore_in_progress(uow, environment)
    assert (
        await uow.environment_restores.has_in_progress_environment_restore(
            environment.id
        )
        is not None
    )

    updated = await update_cluster(uow, cluster.id, {"ingress_class": "nginx"}, USER_ID)

    assert updated.config is not None
    assert updated.config["ingress_class"] == "nginx"


async def test_update_cluster_runs_the_fan_out_after_saving(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    cluster = await _seed_cluster(uow)
    environment = await _seed_environment(uow, cluster, "staging")
    deployment = await _seed_deployment(uow, environment, "web")

    await update_cluster(uow, cluster.id, {"ingress_class": "nginx"}, USER_ID)

    assert [d.id for d in redeploy_recorder] == [deployment.id]


async def test_update_cluster_unknown_cluster_raises_not_found(
    uow: FakeUnitOfWork, redeploy_recorder: list[Deployment]
):
    with pytest.raises(ClusterNotFoundError):
        await update_cluster(uow, uuid4(), {"ingress_class": "nginx"}, USER_ID)

    assert uow.commit_count == 0
