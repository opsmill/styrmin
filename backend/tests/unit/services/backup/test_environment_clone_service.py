"""Unit tests for the environment clone service, guard and flow.

Three things are pinned here, all of them load-bearing for the 010 spec:

* **registration is atomic and side-effect-free until it succeeds** — an
  invalid override, an unknown cleared field or a taken target name costs the
  caller a typed error and nothing else (FR-011), while a valid request writes
  the clone record, its attribution and the whole capture in one commit
  (research D4);
* **the environment-level guard** occupies the *source* only for the capture
  window and the *created* environment for the clone's whole lifetime
  (research D8);
* **the flow's error paths** — a wholly failed capture materialises nothing, a
  partial capture proceeds with what it has, a target name lost to a race ends
  the clone ``FAILED``, and a vanished driver version fails one deployment
  without taking its peers down (FR-002, FR-011, research D5).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest

from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.db.models import (
    ApplicationDriver,
    ApplicationDriverVersion,
    ApplicationInstance,
    Backup,
    BackupStatus,
    Cluster,
    Environment,
    EnvironmentBackup,
    EnvironmentClone,
    InstanceStatus,
    Restore,
    RestoreStatus,
)
from styrmin_backend.domain.models import Deployment as DeploymentEntity
from styrmin_backend.domain.models import DeploymentState
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity
from styrmin_backend.services.backup.clone import (
    CLONE_REASON_CAPTURE_FAILED,
    CLONE_REASON_DRIVER_VERSION_GONE,
    CLONE_REASON_NOT_ELIGIBLE,
    CLONE_REASON_NOT_SELECTED,
    CLONE_STEP_CAPTURE_FAILED,
    CLONE_STEP_TARGET_NAME_TAKEN,
    EnvironmentCloneDeploymentOutcome,
    EnvironmentCloneStatus,
    clone_environment,
    derive_environment_clone_status_from_record,
    find_clone_occupying_environment,
)
from styrmin_backend.services.backup.environment import (
    ConstituentError,
    DeploymentSnapshot,
    create_environment_backup,
)
from styrmin_backend.services.env_vars.exceptions import InvalidEnvVarNameError
from styrmin_backend.services.environments import update_environment
from styrmin_backend.services.exceptions import (
    EnvironmentAlreadyExistsError,
    EnvironmentOperationInProgressError,
    InvalidContextError,
    UnknownEnvironmentConfigFieldError,
)
from styrmin_backend.workflows.models import PrefectAction
from styrmin_backend.workflows.templates import clone as clone_flow
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverRepository,
    FakeApplicationInstanceRepository,
    FakeApplicationRepository,
    FakeBackupRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
    FakeEnvironmentBackupRepository,
    FakeEnvironmentCloneRepository,
    FakeEnvironmentRepository,
    FakeEnvironmentRestoreRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeRestoreRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)

USER_ID = UUID("11111111-1111-1111-1111-111111111111")
SOURCE_RELEASE_REFERENCE = "styrmin-source-release"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _global_context(release_reference: str = SOURCE_RELEASE_REFERENCE) -> GlobalContext:
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="prod", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=uuid4(),
            namespace="styrmin-source",
            release_reference=release_reference,
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="test-chart", version="0.1.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )


def _driver_version(
    *,
    driver: ApplicationDriver,
    version: str = "1.2.0",
    content_hash: str | None = "fingerprint-1",
) -> ApplicationDriverVersion:
    adv = ApplicationDriverVersion(
        application_driver_id=driver.id,
        version=version,
        application_supported_versions=">=1.0.0",
        source_type="local",
        source_repository="/drivers/test",
        content_hash=content_hash,
        helm_chart_id=uuid4(),
    )
    # Assigning the parent back-populates ``driver.versions``, which is what
    # ``_resolve_pinned_driver_version`` walks.
    adv.application_driver = driver
    return adv


def _deployment(
    *,
    environment_id: UUID,
    adv: ApplicationDriverVersion,
    name: str,
    with_instance: bool = True,
    internal: bool = False,
) -> DeploymentEntity:
    deployment = DeploymentEntity(
        id=uuid4(),
        name=name,
        application_version="1.6.0",
        config={"replicas": 2},
        parameters={},
        internal=internal,
        application_driver_version_id=adv.id,
        environment_id=environment_id,
        deleted_at=None,
        status=DeploymentState.RUNNING,
        created_by_user_id=USER_ID,
    )
    if with_instance:
        deployment.set_active_instance(
            InstanceEntity(
                id=uuid4(),
                name=f"{name}-instance",
                application_version="1.6.0",
                status=InstanceStatusEntity.RUNNING,
                deployment_id=deployment.id,
                application_driver_version_id=adv.id,
                context=_global_context(),
            )
        )
    return deployment


def _make_uow(
    *,
    cluster: Cluster,
    environments: list[Environment],
    deployments: list[DeploymentEntity],
    drivers: list[ApplicationDriver],
    driver_versions: list[ApplicationDriverVersion],
    backups: list[Backup] | None = None,
    restores: list[Restore] | None = None,
    environment_backups: list[EnvironmentBackup] | None = None,
    environment_clones: list[EnvironmentClone] | None = None,
) -> FakeUnitOfWork:
    instances = FakeApplicationInstanceRepository(
        [
            ApplicationInstance(
                id=deployment.active_instance.id,
                name=deployment.active_instance.name,
                application_version=deployment.active_instance.application_version,
                status=InstanceStatus.RUNNING,
                deployment_id=deployment.id,
                application_driver_version_id=deployment.application_driver_version_id,
            )
            for deployment in deployments
            if deployment.active_instance is not None
        ]
    )
    return FakeUnitOfWork(
        clusters=FakeClusterRepository([cluster]),
        environments=FakeEnvironmentRepository(environments),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_drivers=FakeApplicationDriverRepository(drivers),
        application_driver_versions=FakeApplicationRepository(driver_versions),
        instances=instances,
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployments=FakeDeploymentRepository(deployments),
        backups=FakeBackupRepository(backups or []),
        restores=FakeRestoreRepository(restores or []),
        environment_backups=FakeEnvironmentBackupRepository(environment_backups or []),
        environment_restores=FakeEnvironmentRestoreRepository([]),
        environment_clones=FakeEnvironmentCloneRepository(environment_clones or []),
        deployed_services=FakeDeployedServiceRepository([]),
    )


class _Scenario:
    """One source environment with two eligible deployments, in a cluster."""

    def __init__(self) -> None:
        self.cluster = Cluster(name="c1")
        self.source = Environment(
            name="prod",
            cluster_id=self.cluster.id,
            config={"fqdn_suffix": "prod.example.com"},
        )
        self.driver = ApplicationDriver(name="test-driver")
        self.adv = _driver_version(driver=self.driver)
        self.first = _deployment(
            environment_id=self.source.id, adv=self.adv, name="postgres-main"
        )
        self.second = _deployment(
            environment_id=self.source.id, adv=self.adv, name="api"
        )
        self.deployments = [self.first, self.second]
        self.uow = _make_uow(
            cluster=self.cluster,
            environments=[self.source],
            deployments=self.deployments,
            drivers=[self.driver],
            driver_versions=[self.adv],
        )

    def clone(self, **kwargs: Any):
        params: dict[str, Any] = {
            "uow": self.uow,
            "name": "prod-rehearsal",
            "created_by_user_id": USER_ID,
            "environment_id": self.source.id,
        }
        params.update(kwargs)
        return clone_environment(**params)


@pytest.fixture
def scenario() -> _Scenario:
    return _Scenario()


def _results(clone: EnvironmentClone) -> dict[str, dict[str, Any]]:
    """The attribution entries keyed by deployment name."""
    return {entry["deployment_name"]: entry for entry in clone.deployment_results or []}


# ---------------------------------------------------------------------------
# T017 — registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_writes_the_clone_and_its_capture_in_one_commit(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """research D4: record + attribution + capture become durable together."""
    clone = await scenario.clone()

    assert clone.name == "prod-rehearsal"
    assert clone.source_environment_id == scenario.source.id
    assert clone.source_environment_name == "prod"
    assert clone.created_environment_id is None
    assert clone.created_by_user_id == USER_ID

    # The capture is linked and carries one constituent per eligible deployment.
    assert clone.environment_backup_id is not None
    assert len(scenario.uow.backups.models) == 2
    assert {backup.environment_backup_id for backup in scenario.uow.backups.models} == {
        clone.environment_backup_id
    }

    # Every source deployment is accounted for (SC-003), all still pending.
    entries = _results(clone)
    assert set(entries) == {"postgres-main", "api"}
    assert {entry["outcome"] for entry in entries.values()} == {"pending"}

    # One commit: nothing is dispatched before the whole registration is durable.
    assert scenario.uow.commit_count == 1

    actions = [
        call.kwargs["action"] for call in prefect_manager_mock.run_action.call_args_list
    ]
    assert actions.count(PrefectAction.EXECUTE_BACKUP) == 2
    assert actions.count(PrefectAction.EXECUTE_ENVIRONMENT_CLONE) == 1
    clone_call = next(
        call
        for call in prefect_manager_mock.run_action.call_args_list
        if call.kwargs["action"] is PrefectAction.EXECUTE_ENVIRONMENT_CLONE
    )
    assert clone_call.kwargs["parameters"] == {"clone_id": str(clone.id)}


@pytest.mark.asyncio
async def test_capture_snapshots_the_source_release_reference(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """research D2: the counterpart adopts the source's Helm release name.

    It can only do that if the capture recorded it — recomputing
    ``styrmin-<deployment id>`` would be wrong for a source that is itself a
    clone counterpart.
    """
    clone = await scenario.clone()

    environment_backup = await scenario.uow.environment_backups.get(
        clone.environment_backup_id
    )
    assert environment_backup is not None
    snapshots = [
        DeploymentSnapshot.model_validate(raw)
        for raw in environment_backup.deployment_snapshots or []
    ]
    assert {snapshot.release_reference for snapshot in snapshots} == {
        SOURCE_RELEASE_REFERENCE
    }


@pytest.mark.asyncio
async def test_taken_target_name_is_refused_with_zero_side_effects(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-011: an upfront rejection writes nothing at all."""
    scenario.uow.environments.models.append(
        Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    )

    with pytest.raises(EnvironmentAlreadyExistsError):
        await scenario.clone()

    assert scenario.uow.environment_clones.models == []
    assert scenario.uow.environment_backups.models == []
    assert scenario.uow.backups.models == []
    prefect_manager_mock.run_action.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_cleared_config_field_is_refused_with_zero_side_effects(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-006/FR-011: the cleared-field names are validated before any write."""
    with pytest.raises(UnknownEnvironmentConfigFieldError) as excinfo:
        await scenario.clone(clear_config_fields=["not_a_field"])

    assert excinfo.value.fields == ["not_a_field"]
    assert scenario.uow.environment_clones.models == []
    assert scenario.uow.environment_backups.models == []
    prefect_manager_mock.run_action.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_config_override_is_refused_with_zero_side_effects(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-011: the override is canonicalised before the capture is registered."""
    with pytest.raises(InvalidContextError):
        await scenario.clone(config_override={"fqdn_suffix": {"nested": True}})

    assert scenario.uow.environment_clones.models == []
    assert scenario.uow.environment_backups.models == []
    prefect_manager_mock.run_action.assert_not_called()


@pytest.mark.asyncio
async def test_override_env_var_errors_keep_their_typed_code(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """An env-var name error must not collapse into the generic context code.

    ``EnvironmentConfig`` raises the typed error straight out of its field
    validator, so canonicalising the override upfront is enough to keep
    ``INVALID_ENV_VAR_NAME`` intact across the GraphQL boundary.
    """
    with pytest.raises(InvalidEnvVarNameError):
        await scenario.clone(config_override={"env_vars": {"not a name": "x"}})

    assert scenario.uow.environment_clones.models == []
    assert scenario.uow.environment_backups.models == []


@pytest.mark.asyncio
async def test_ineligible_and_unselected_deployments_are_attributed_as_skipped(
    prefect_manager_mock,
) -> None:
    """FR-003/FR-004: a skip is attributed with a reason, never an error."""
    cluster = Cluster(name="c1")
    source = Environment(name="prod", cluster_id=cluster.id)
    driver = ApplicationDriver(name="test-driver")
    adv = _driver_version(driver=driver)
    eligible = _deployment(environment_id=source.id, adv=adv, name="api")
    never_deployed = _deployment(
        environment_id=source.id, adv=adv, name="analytics", with_instance=False
    )
    excluded = _deployment(environment_id=source.id, adv=adv, name="reporting")
    internal = _deployment(
        environment_id=source.id, adv=adv, name="ingress", internal=True
    )
    uow = _make_uow(
        cluster=cluster,
        environments=[source],
        deployments=[eligible, never_deployed, excluded, internal],
        drivers=[driver],
        driver_versions=[adv],
    )

    clone = await clone_environment(
        uow=uow,
        name="prod-copy",
        created_by_user_id=USER_ID,
        environment_id=source.id,
        deployment_ids=[eligible.id, never_deployed.id],
    )

    entries = _results(clone)
    # Internal deployments are platform infrastructure, not part of the
    # environment's application topology, so they are not listed at all.
    assert set(entries) == {"api", "analytics", "reporting"}
    assert entries["api"]["outcome"] == "pending"
    assert entries["analytics"]["outcome"] == "skipped"
    assert entries["analytics"]["reason"] == CLONE_REASON_NOT_ELIGIBLE
    assert entries["reporting"]["outcome"] == "skipped"
    assert entries["reporting"]["reason"] == CLONE_REASON_NOT_SELECTED

    # Only the one usable selected deployment was captured.
    assert len(uow.backups.models) == 1
    assert clone.requested_deployment_ids == [
        str(eligible.id),
        str(never_deployed.id),
    ]


# ---------------------------------------------------------------------------
# T018 — the environment-level guard (research D8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_is_occupied_while_the_capture_is_in_flight(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """A second clone (or backup) of the same source is refused during capture."""
    first = await scenario.clone()

    occupying = await find_clone_occupying_environment(scenario.source.id, scenario.uow)
    assert occupying is not None
    assert occupying.id == first.id

    # A second clone — and the standalone environment-backup mutation — are
    # both refused. Which half of the guard reports it is not asserted: a
    # clone's capture *is* an in-flight environment backup of the source, so
    # the EXISTS half usually gets there first. The clone half above is what
    # makes the occupancy explicit rather than a side effect of that overlap.
    with pytest.raises(EnvironmentOperationInProgressError):
        await scenario.clone(name="prod-rehearsal-2")
    with pytest.raises(EnvironmentOperationInProgressError):
        await create_environment_backup(
            environment_id=scenario.source.id, uow=scenario.uow
        )


@pytest.mark.asyncio
async def test_source_is_released_once_the_capture_is_terminal(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """research D8: only the capture window serialises, not the whole clone."""
    first = await scenario.clone()
    for backup in scenario.uow.backups.models:
        backup.status = BackupStatus.COMPLETED

    assert (
        await find_clone_occupying_environment(scenario.source.id, scenario.uow) is None
    )

    second = await scenario.clone(name="prod-rehearsal-2")
    assert second.id != first.id


@pytest.mark.asyncio
async def test_created_environment_is_occupied_for_the_whole_clone(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The under-construction environment refuses operations and config updates."""
    clone = await scenario.clone()
    for backup in scenario.uow.backups.models:
        backup.status = BackupStatus.COMPLETED

    created = Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    clone.created_environment_id = created.id
    await scenario.uow.environment_clones.save(clone)

    occupying = await find_clone_occupying_environment(created.id, scenario.uow)
    assert occupying is not None and occupying.id == clone.id

    with pytest.raises(EnvironmentOperationInProgressError) as excinfo:
        await update_environment(
            environment_id=created.id, uow=scenario.uow, config={"db_size": "10Gi"}
        )
    assert excinfo.value.operation_kind == "environment_clone"

    # A no-op update is refused too: "busy" is a property of the environment,
    # not of the payload.
    with pytest.raises(EnvironmentOperationInProgressError):
        await update_environment(environment_id=created.id, uow=scenario.uow)


@pytest.mark.asyncio
async def test_created_environment_is_released_once_the_clone_is_terminal(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """A finished clone stops occupying the environment it built."""
    clone = await scenario.clone()
    for backup in scenario.uow.backups.models:
        backup.status = BackupStatus.COMPLETED

    created = Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    clone.created_environment_id = created.id
    clone.deployment_results = [
        {
            "deployment_id": str(scenario.first.id),
            "deployment_name": "postgres-main",
            "outcome": "skipped",
            "reason": "not included in the requested deployment selection",
        },
        {
            "deployment_id": str(scenario.second.id),
            "deployment_name": "api",
            "outcome": "skipped",
            "reason": "not included in the requested deployment selection",
        },
    ]
    await scenario.uow.environment_clones.save(clone)

    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.COMPLETED
    )
    assert await find_clone_occupying_environment(created.id, scenario.uow) is None

    refreshed = await update_environment(
        environment_id=created.id, uow=scenario.uow, config={"db_size": "10Gi"}
    )
    assert refreshed.config == {"db_size": "10Gi"}


# ---------------------------------------------------------------------------
# T020 — flow error paths
# ---------------------------------------------------------------------------


@pytest.fixture
def flow_harness(monkeypatch: pytest.MonkeyPatch, scenario: _Scenario):
    """Run the clone flow against the fake unit of work.

    ``deploy_application`` and ``create_restore`` are stubbed: what these tests
    pin is the flow's *attribution*, and both services have their own unit
    suites. Everything else — the capture gate, the config merge, the
    environment creation, the driver-version pin — runs for real.
    """
    calls: dict[str, list[Any]] = {"deploy": [], "restore": [], "dispatch": []}

    async def _get_uow():
        return scenario.uow

    async def _deploy_application(**kwargs: Any):
        calls["deploy"].append(kwargs)
        counterpart = DeploymentEntity(
            id=uuid4(),
            name=kwargs["deployment_name"],
            application_version=kwargs["version"],
            config=kwargs.get("deployment_config"),
            parameters=kwargs.get("deployment_parameters") or {},
            internal=False,
            application_driver_version_id=kwargs["driver_version_id"],
            environment_id=kwargs["environment_id"],
            deleted_at=None,
            status=DeploymentState.RESTORING,
            created_by_user_id=kwargs["created_by_user_id"],
        )
        await scenario.uow.deployments.save(counterpart)
        return None

    async def _create_restore(**kwargs: Any):
        calls["restore"].append(kwargs)
        restore = Restore(
            name=f"styrmin-{uuid4()}",
            status=RestoreStatus.PENDING,
            target_namespace=kwargs["target_namespace"],
            backup_id=kwargs["backup_id"],
        )
        await scenario.uow.restores.create(restore)
        return restore, kwargs["target_deployment_id"]

    class _Manager:
        async def run_action(self, **kwargs: Any) -> None:
            calls["dispatch"].append(kwargs)

    monkeypatch.setattr(clone_flow, "get_unit_of_work", _get_uow)
    monkeypatch.setattr(clone_flow, "get_run_logger", lambda: logging.getLogger("test"))
    monkeypatch.setattr(clone_flow, "deploy_application", _deploy_application)
    monkeypatch.setattr(clone_flow, "create_restore", _create_restore)
    monkeypatch.setattr(clone_flow, "get_manager", lambda: _Manager())
    return calls


async def _complete_capture(
    scenario: _Scenario, *, failed_deployment: DeploymentEntity | None = None
) -> None:
    """Drive the registered capture's constituents to a terminal state.

    ``failed_deployment`` marks that deployment's constituent ``FAILED``, which
    is what makes the capture derive ``PARTIAL``.
    """
    failed_instance_id = (
        failed_deployment.active_instance.id
        if failed_deployment is not None and failed_deployment.active_instance
        else None
    )
    for backup in scenario.uow.backups.models:
        backup.status = (
            BackupStatus.FAILED
            if backup.instance_id == failed_instance_id
            else BackupStatus.COMPLETED
        )


@pytest.mark.asyncio
async def test_wholly_failed_capture_materialises_nothing(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """FR-002: no environment, no deployments, one fatal entry, FAILED."""
    clone = await scenario.clone()
    for backup in scenario.uow.backups.models:
        backup.status = BackupStatus.FAILED

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.created_environment_id is None
    # No environment was created beyond the source, and no counterpart exists.
    assert [env.name for env in scenario.uow.environments.models] == ["prod"]
    assert flow_harness["deploy"] == []
    assert flow_harness["restore"] == []

    assert refreshed.clone_errors is not None
    assert [entry["step"] for entry in refreshed.clone_errors] == [
        CLONE_STEP_CAPTURE_FAILED
    ]
    assert all(entry["fatal"] for entry in refreshed.clone_errors)
    entries = _results(refreshed)
    assert {entry["outcome"] for entry in entries.values()} == {"failed"}
    assert all(
        entry["reason"] == CLONE_REASON_CAPTURE_FAILED for entry in entries.values()
    )
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )


@pytest.mark.asyncio
async def test_partial_capture_clones_the_usable_constituents(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """FR-002: failed constituents are attributed, the rest proceed → PARTIAL."""
    clone = await scenario.clone()
    await _complete_capture(scenario, failed_deployment=scenario.first)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.created_environment_id is not None

    entries = _results(refreshed)
    assert entries["postgres-main"]["outcome"] == "failed"
    assert entries["postgres-main"]["reason"] == "constituent backup did not complete"
    assert entries["api"]["outcome"] == "cloned"
    assert entries["api"]["counterpart_deployment_id"] is not None
    assert entries["api"]["restore_id"] is not None

    # Exactly one counterpart and one cross-target restore, for the usable one.
    assert [call["deployment_name"] for call in flow_harness["deploy"]] == ["api"]
    assert len(flow_harness["restore"]) == 1
    restore_call = flow_harness["restore"][0]
    counterpart_id = UUID(entries["api"]["counterpart_deployment_id"])
    assert restore_call["target_deployment_id"] == counterpart_id
    assert restore_call["target_namespace"] == f"styrmin-{counterpart_id}"

    # The restore is dispatched with the source identity travelling separately
    # from the status-write target (research D2.2).
    dispatch = flow_harness["dispatch"][0]
    assert dispatch["action"] is PrefectAction.EXECUTE_RESTORE
    assert dispatch["parameters"]["deployment_id"] == str(counterpart_id)
    assert dispatch["parameters"]["source_deployment_id"] == str(scenario.second.id)

    # While the dispatched restore is still PENDING the clone is IN_PROGRESS;
    # it settles on PARTIAL once the restore lands (the failed capture
    # constituent is the "partial" half).
    restores = {restore.id: restore for restore in scenario.uow.restores.models}
    assert (
        derive_environment_clone_status_from_record(refreshed, restores)
        is EnvironmentCloneStatus.IN_PROGRESS
    )
    for restore in restores.values():
        restore.status = RestoreStatus.COMPLETED
    assert (
        derive_environment_clone_status_from_record(refreshed, restores)
        is EnvironmentCloneStatus.PARTIAL
    )


@pytest.mark.asyncio
async def test_counterpart_adopts_the_captured_release_reference(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """research D2: the counterpart is created with the source's release name."""
    clone = await scenario.clone()
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    assert flow_harness["deploy"], "no counterpart was created"
    assert {call["release_reference"] for call in flow_harness["deploy"]} == {
        SOURCE_RELEASE_REFERENCE
    }
    assert all(call["skip_initial_reconcile"] for call in flow_harness["deploy"])


@pytest.mark.asyncio
async def test_target_name_lost_to_a_race_ends_the_clone_failed(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """FR-011: the TOCTOU case is attributed, not crashed."""
    clone = await scenario.clone()
    await _complete_capture(scenario)
    # Somebody else took the name between validation and creation.
    scenario.uow.environments.models.append(
        Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    )

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.created_environment_id is None
    assert refreshed.clone_errors is not None
    assert [entry["step"] for entry in refreshed.clone_errors] == [
        CLONE_STEP_TARGET_NAME_TAKEN
    ]
    assert refreshed.clone_errors[0]["fatal"] is True
    assert flow_harness["deploy"] == []
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )


@pytest.mark.asyncio
async def test_vanished_driver_version_fails_one_deployment_not_its_peers(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """research D5: an unresolvable driver pin is a per-deployment failure."""
    clone = await scenario.clone()
    await _complete_capture(scenario)

    # The captured driver content is no longer loaded: the version row that
    # remains carries a different fingerprint. Only ``postgres-main``'s
    # snapshot is rewritten, so its peer still resolves.
    environment_backup = await scenario.uow.environment_backups.get(
        clone.environment_backup_id
    )
    assert environment_backup is not None
    rewritten: list[dict[str, Any]] = []
    for raw in environment_backup.deployment_snapshots or []:
        snapshot = DeploymentSnapshot.model_validate(raw)
        if snapshot.deployment_name == "postgres-main":
            snapshot = snapshot.model_copy(
                update={"driver_fingerprint": "fingerprint-gone"}
            )
        rewritten.append(snapshot.model_dump(mode="json"))
    environment_backup.deployment_snapshots = rewritten

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.created_environment_id is not None
    assert refreshed.clone_errors is None

    entries = _results(refreshed)
    assert entries["postgres-main"]["outcome"] == "failed"
    assert entries["postgres-main"]["reason"] == CLONE_REASON_DRIVER_VERSION_GONE
    assert entries["api"]["outcome"] == "cloned"
    assert [call["deployment_name"] for call in flow_harness["deploy"]] == ["api"]
    restores = {restore.id: restore for restore in scenario.uow.restores.models}
    for restore in restores.values():
        restore.status = RestoreStatus.COMPLETED
    assert (
        derive_environment_clone_status_from_record(refreshed, restores)
        is EnvironmentCloneStatus.PARTIAL
    )


@pytest.mark.asyncio
async def test_clone_row_vanishing_mid_flight_ends_the_flow_quietly(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """research D9: deleting the source deletes non-terminal clone records."""
    clone = await scenario.clone()
    await _complete_capture(scenario)
    scenario.uow.environment_clones.models.clear()

    # No exception: there is nothing left to write and nothing went wrong.
    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    assert flow_harness["deploy"] == []


@pytest.mark.asyncio
async def test_merged_config_is_applied_to_the_created_environment(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """FR-006 / research D7: clear then override, over the captured config."""
    clone = await scenario.clone(
        config_override={"db_size": "5Gi"}, clear_config_fields=["fqdn_suffix"]
    )
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None and refreshed.created_environment_id is not None
    created = await scenario.uow.environments.get(refreshed.created_environment_id)
    assert created is not None
    assert created.name == "prod-rehearsal"
    assert created.cluster_id == scenario.cluster.id
    # The captured ``fqdn_suffix`` was cleared and the override applied; the
    # source is untouched (SC-002).
    assert created.config == {"db_size": "5Gi"}
    assert scenario.source.config == {"fqdn_suffix": "prod.example.com"}


@pytest.mark.asyncio
async def test_capture_constituent_error_is_attributed_as_a_failure(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """A constituent that never got a Backup row is a failed deployment."""
    clone = await scenario.clone()
    await _complete_capture(scenario)

    environment_backup = await scenario.uow.environment_backups.get(
        clone.environment_backup_id
    )
    assert environment_backup is not None
    environment_backup.constituent_errors = [
        ConstituentError(
            deployment_id=scenario.first.id,
            deployment_name="postgres-main",
            error="backup already in progress",
        ).model_dump(mode="json")
    ]

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    entries = _results(refreshed)
    assert entries["postgres-main"]["outcome"] == "failed"
    assert entries["postgres-main"]["reason"] == CLONE_REASON_CAPTURE_FAILED
    assert entries["api"]["outcome"] == "cloned"


def test_no_terminal_clone_keeps_a_pending_entry() -> None:
    """The coverage identity: ``_fail_pending`` leaves nothing pending."""
    from styrmin_backend.services.backup.clone import CloneDeploymentResult

    pending = CloneDeploymentResult(
        deployment_id=uuid4(),
        deployment_name="api",
        outcome=EnvironmentCloneDeploymentOutcome.PENDING,
    )
    cloned = pending.model_copy(
        update={"outcome": EnvironmentCloneDeploymentOutcome.CLONED}
    )

    updated = clone_flow._fail_pending([pending, cloned], "because")

    assert [entry.outcome for entry in updated] == [
        EnvironmentCloneDeploymentOutcome.FAILED,
        EnvironmentCloneDeploymentOutcome.CLONED,
    ]
    assert updated[0].reason == "because"
