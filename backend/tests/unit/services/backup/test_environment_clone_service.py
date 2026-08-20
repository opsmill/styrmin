"""Unit tests for the environment clone service, guard and flow.

Four things are pinned here, all of them load-bearing for the 010 spec:

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
  without taking its peers down (FR-002, FR-011, research D5);
* **the config override's ordering** — the merge is the *creation input* of the
  cloned environment, and every counterpart is created after it, so no
  counterpart's first instance context can ever resolve against the captured
  (production) config (FR-006, research D7).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
    CLONE_REASON_CAPTURE_UNUSABLE,
    CLONE_REASON_DRIVER_VERSION_GONE,
    CLONE_REASON_INTERNAL,
    CLONE_REASON_NOT_ELIGIBLE,
    CLONE_REASON_NOT_SELECTED,
    CLONE_REASON_TOMBSTONED,
    CLONE_STEP_CAPTURE_FAILED,
    CLONE_STEP_CREATED_ENVIRONMENT_DELETED,
    CLONE_STEP_ENVIRONMENT_BACKUP_DELETED,
    CLONE_STEP_ENVIRONMENT_CREATION_FAILED,
    CLONE_STEP_TARGET_NAME_TAKEN,
    TERMINAL_ENVIRONMENT_CLONE_STATUSES,
    EnvironmentCloneDeploymentOutcome,
    EnvironmentCloneStatus,
    clone_environment,
    derive_environment_clone_status_from_record,
    find_clone_occupying_environment,
)
from styrmin_backend.services.backup.environment import (
    ConstituentError,
    DeploymentSnapshot,
    EnvironmentOperationStatus,
    create_environment_backup,
    delete_environment_backup,
)
from styrmin_backend.services.backup.service import (
    create_restore as create_restore_service,
)
from styrmin_backend.services.env_vars.exceptions import InvalidEnvVarNameError
from styrmin_backend.services.environments import delete_environment, update_environment
from styrmin_backend.services.exceptions import (
    EnvironmentAlreadyExistsError,
    EnvironmentBackupInUseByCloneError,
    EnvironmentOperationInProgressError,
    InvalidCloneDeploymentSelectionError,
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
# T026 — deployment selection semantics (FR-003 / FR-004 / FR-011)
# ---------------------------------------------------------------------------
#
# The selection splits into exactly three cases, and the whole point of this
# block is that they stay apart:
#
# * an id the source does not have (unknown, or another environment's) → an
#   upfront ``NOT_FOUND`` with zero side effects (FR-011);
# * an id the source has but cannot clone → an attributed skip with a reason,
#   never an error (FR-004);
# * an id the source has and can clone → captured and cloned (FR-003).


@pytest.mark.asyncio
async def test_unknown_selected_deployment_is_refused_with_zero_side_effects(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-011: an id that names no deployment at all costs a typed error only."""
    ghost = uuid4()

    with pytest.raises(InvalidCloneDeploymentSelectionError) as excinfo:
        await scenario.clone(deployment_ids=[scenario.first.id, ghost])

    assert excinfo.value.error_code == "NOT_FOUND"
    assert excinfo.value.error_metadata == {"deployment_ids": [str(ghost)]}
    assert scenario.uow.environment_clones.models == []
    assert scenario.uow.environment_backups.models == []
    assert scenario.uow.backups.models == []
    prefect_manager_mock.run_action.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_selected_deployment_is_refused_with_zero_side_effects(
    prefect_manager_mock,
) -> None:
    """FR-011: a deployment of *another* environment is not a skip, it is a typo.

    A foreign id is indistinguishable from an unknown one as far as the source
    is concerned — it is simply not one of its deployments — so it takes the
    same upfront ``NOT_FOUND`` rather than being quietly attributed.
    """
    cluster = Cluster(name="c1")
    source = Environment(name="prod", cluster_id=cluster.id)
    neighbour = Environment(name="staging", cluster_id=cluster.id)
    driver = ApplicationDriver(name="test-driver")
    adv = _driver_version(driver=driver)
    mine = _deployment(environment_id=source.id, adv=adv, name="api")
    theirs = _deployment(environment_id=neighbour.id, adv=adv, name="api")
    uow = _make_uow(
        cluster=cluster,
        environments=[source, neighbour],
        deployments=[mine, theirs],
        drivers=[driver],
        driver_versions=[adv],
    )

    with pytest.raises(InvalidCloneDeploymentSelectionError) as excinfo:
        await clone_environment(
            uow=uow,
            name="prod-copy",
            created_by_user_id=USER_ID,
            environment_id=source.id,
            deployment_ids=[theirs.id],
        )

    assert excinfo.value.deployment_ids == [str(theirs.id)]
    assert uow.environment_clones.models == []
    assert uow.environment_backups.models == []
    prefect_manager_mock.run_action.assert_not_called()


@pytest.mark.asyncio
async def test_selection_is_validated_before_the_concurrency_guard(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """A bad selection is a request error, so it does not depend on what is running.

    Ordering matters for the caller: an operator who typo'd a deployment id
    should be told about the typo, not about an unrelated capture that happens
    to be in flight — otherwise fixing the "busy" report reveals a second
    failure.
    """
    await scenario.clone()  # occupies the source for its capture window

    with pytest.raises(InvalidCloneDeploymentSelectionError):
        await scenario.clone(name="prod-rehearsal-2", deployment_ids=[uuid4()])


@pytest.mark.asyncio
async def test_selected_internal_deployment_is_attributed_as_skipped(
    prefect_manager_mock,
) -> None:
    """FR-004: an explicitly selected internal deployment is a skip, not an error.

    Unselected it stays off the list entirely (pinned by
    ``test_ineligible_and_unselected_deployments_are_attributed_as_skipped``);
    named by the caller it gets an answer, because SC-003 accounting must not
    silently drop something that was asked for.
    """
    cluster = Cluster(name="c1")
    source = Environment(name="prod", cluster_id=cluster.id)
    driver = ApplicationDriver(name="test-driver")
    adv = _driver_version(driver=driver)
    eligible = _deployment(environment_id=source.id, adv=adv, name="api")
    internal = _deployment(
        environment_id=source.id, adv=adv, name="ingress", internal=True
    )
    uow = _make_uow(
        cluster=cluster,
        environments=[source],
        deployments=[eligible, internal],
        drivers=[driver],
        driver_versions=[adv],
    )

    clone = await clone_environment(
        uow=uow,
        name="prod-copy",
        created_by_user_id=USER_ID,
        environment_id=source.id,
        deployment_ids=[eligible.id, internal.id],
    )

    entries = _results(clone)
    assert set(entries) == {"api", "ingress"}
    assert entries["ingress"]["outcome"] == "skipped"
    assert entries["ingress"]["reason"] == CLONE_REASON_INTERNAL
    # Selected or not, it contributes no constituent: the clone's environment
    # grows its own ingress controller.
    assert len(uow.backups.models) == 1


@pytest.mark.asyncio
async def test_selected_tombstoned_deployment_is_attributed_as_skipped(
    prefect_manager_mock,
) -> None:
    """FR-004: a deleted deployment is ineligible, not unknown."""
    cluster = Cluster(name="c1")
    source = Environment(name="prod", cluster_id=cluster.id)
    driver = ApplicationDriver(name="test-driver")
    adv = _driver_version(driver=driver)
    eligible = _deployment(environment_id=source.id, adv=adv, name="api")
    gone = _deployment(environment_id=source.id, adv=adv, name="retired")
    gone.deleted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    uow = _make_uow(
        cluster=cluster,
        environments=[source],
        deployments=[eligible, gone],
        drivers=[driver],
        driver_versions=[adv],
    )

    clone = await clone_environment(
        uow=uow,
        name="prod-copy",
        created_by_user_id=USER_ID,
        environment_id=source.id,
        deployment_ids=[eligible.id, gone.id],
    )

    entries = _results(clone)
    assert set(entries) == {"api", "retired"}
    assert entries["retired"]["outcome"] == "skipped"
    assert entries["retired"]["reason"] == CLONE_REASON_TOMBSTONED
    assert len(uow.backups.models) == 1


@pytest.mark.asyncio
async def test_selection_is_threaded_into_the_capture_filter(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-003: only the selected deployments are captured, not merely reported.

    The capture is the clone's only source of truth (FR-007), so a selection
    that reached the attribution list but not the snapshot would still clone the
    excluded deployment.
    """
    clone = await scenario.clone(deployment_ids=[scenario.first.id])

    capture = await scenario.uow.environment_backups.get(clone.environment_backup_id)
    assert capture is not None
    snapshots = [
        DeploymentSnapshot.model_validate(raw)
        for raw in capture.deployment_snapshots or []
    ]
    assert [snapshot.deployment_name for snapshot in snapshots] == ["postgres-main"]
    assert [backup.instance_id for backup in scenario.uow.backups.models] == [
        scenario.first.active_instance.id
    ]

    entries = _results(clone)
    assert entries["postgres-main"]["outcome"] == "pending"
    assert entries["api"]["outcome"] == "skipped"
    assert entries["api"]["reason"] == CLONE_REASON_NOT_SELECTED
    # One EXECUTE_BACKUP for the one constituent, plus the clone flow itself.
    actions = [
        call.kwargs["action"] for call in prefect_manager_mock.run_action.call_args_list
    ]
    assert actions.count(PrefectAction.EXECUTE_BACKUP) == 1


@pytest.mark.asyncio
async def test_omitted_selection_captures_every_eligible_deployment(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-003: no selection means all eligible, and nothing is marked unselected."""
    clone = await scenario.clone()

    capture = await scenario.uow.environment_backups.get(clone.environment_backup_id)
    assert capture is not None
    assert {raw["deployment_name"] for raw in capture.deployment_snapshots or []} == {
        "postgres-main",
        "api",
    }
    assert clone.requested_deployment_ids is None
    entries = _results(clone)
    assert {entry["outcome"] for entry in entries.values()} == {"pending"}
    assert all(entry["reason"] is None for entry in entries.values())


@pytest.mark.asyncio
async def test_empty_selection_is_legal_and_clones_nothing(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """``[]`` is a selection that selects nothing — distinct from ``None``.

    It is not rejected (it names no unknown id) and it is not read as "all":
    every deployment is attributed as unselected and no constituent is
    captured, so the clone produces an empty copy of the environment rather
    than an error or a full clone.
    """
    clone = await scenario.clone(deployment_ids=[])

    assert clone.requested_deployment_ids == []
    entries = _results(clone)
    assert {entry["outcome"] for entry in entries.values()} == {"skipped"}
    assert {entry["reason"] for entry in entries.values()} == {
        CLONE_REASON_NOT_SELECTED
    }
    assert scenario.uow.backups.models == []
    capture = await scenario.uow.environment_backups.get(clone.environment_backup_id)
    assert capture is not None
    assert capture.deployment_snapshots is None

    # Still IN_PROGRESS at registration — the environment itself has yet to
    # materialise — and COMPLETED once it has, because an all-skipped clone has
    # no failures (skips are not failures, FR-004).
    clone.environment_backup = capture
    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.IN_PROGRESS
    )
    clone.created_environment_id = uuid4()
    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.COMPLETED
    )


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

    Three extra recordings serve the US3 ordering guarantee (T029):

    * ``calls["order"]`` is the flow's step sequence, each step carrying the
      value that step was *given*: ``("merge", merged_config)``,
      ``("create_environment", config_passed_to_it)`` and
      ``("deploy", deployment_name)``. Recording the argument rather than only
      the step name is what makes the ordering assertion bite — an
      implementation that created the environment from the captured config and
      patched it afterwards has the same step order but a different
      ``create_environment`` input.
    * ``calls["observed_config"]`` is the created environment's config read
      back through the unit of work at the moment each counterpart is created
      — the config ``generate_instance_from_deployment`` resolves the
      counterpart's first instance context from (it re-reads the environment
      row).
    """
    calls: dict[str, list[Any]] = {
        "deploy": [],
        "restore": [],
        "dispatch": [],
        "order": [],
        "observed_config": [],
    }

    real_merge = clone_flow.merge_environment_config
    real_create_environment = clone_flow.create_environment

    async def _get_uow():
        return scenario.uow

    def _merge_environment_config(*args: Any, **kwargs: Any):
        merged = real_merge(*args, **kwargs)
        calls["order"].append(("merge", dict(merged)))
        return merged

    async def _create_environment(**kwargs: Any):
        calls["order"].append(("create_environment", dict(kwargs.get("config") or {})))
        return await real_create_environment(**kwargs)

    async def _deploy_application(**kwargs: Any):
        calls["order"].append(("deploy", kwargs["deployment_name"]))
        calls["deploy"].append(kwargs)
        async with scenario.uow:
            environment = await scenario.uow.environments.get(kwargs["environment_id"])
        assert environment is not None, "counterpart created without an environment"
        calls["observed_config"].append(dict(environment.config or {}))
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
    monkeypatch.setattr(
        clone_flow, "merge_environment_config", _merge_environment_config
    )
    monkeypatch.setattr(clone_flow, "create_environment", _create_environment)
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
async def test_fanout_runs_against_the_real_create_restore(
    scenario: _Scenario,
    prefect_manager_mock,
    flow_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one test in this file that does **not** stub ``create_restore``.

    Stubbing it is why a contradiction between two shipped services survived:
    the flow parks every counterpart in ``RESTORING`` (research D5) and
    ``create_restore`` used to read that same state as "a restore is already in
    progress", so every clone failed its whole fan-out with
    ``RestoreAlreadyInProgressError`` while these tests stayed green. Running
    the real service against the real counterpart rows is what makes that class
    of contradiction impossible to reintroduce silently.

    It also pins the same-backup guard against the fan-out: each counterpart is
    restored from its **own** per-instance constituent backup, so no two
    restores in one clone share a ``backup_id``.
    """

    async def _recording_create_restore(**kwargs: Any):
        flow_harness["restore"].append(kwargs)
        # Deliberately the service function itself, not
        # ``clone_flow.create_restore`` — the harness has already replaced that
        # attribute with its stub by the time this test body runs.
        return await create_restore_service(**kwargs)

    monkeypatch.setattr(clone_flow, "create_restore", _recording_create_restore)
    flow_harness["restore"].clear()

    clone = await scenario.clone()
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    entries = _results(refreshed)
    # Both deployments cloned — none attributed a restore failure.
    assert {name: entry["outcome"] for name, entry in entries.items()} == {
        "postgres-main": "cloned",
        "api": "cloned",
    }
    assert [entry.get("reason") for entry in entries.values()] == [None, None]

    # Two real Restore rows, one per counterpart, each from its own backup.
    restores = scenario.uow.restores.models
    assert len(restores) == 2
    assert len({restore.backup_id for restore in restores}) == 2
    assert {str(restore.id) for restore in restores} == {
        entry["restore_id"] for entry in entries.values()
    }

    for entry in entries.values():
        counterpart_id = UUID(entry["counterpart_deployment_id"])
        restore = next(r for r in restores if str(r.id) == entry["restore_id"])
        assert restore.status == RestoreStatus.PENDING
        assert restore.target_namespace == f"styrmin-{counterpart_id}"
        counterpart = await scenario.uow.deployments.find(counterpart_id)
        assert counterpart is not None
        assert counterpart.status == DeploymentState.RESTORING

    # The sources are untouched by their counterparts' restores (SC-002).
    for source_deployment in scenario.deployments:
        stored = await scenario.uow.deployments.find(source_deployment.id)
        assert stored is not None
        assert stored.status is DeploymentState.RUNNING


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


# ---------------------------------------------------------------------------
# The fatal environment-creation branches (T4)
# ---------------------------------------------------------------------------
#
# ``_create_cloned_environment`` has four exits that end the clone without an
# environment. Only the TOCTOU one (above) was reached by a test; the other
# three were dead code as far as the suite was concerned, even though they are
# the handlers that stop a clone from sitting ``IN_PROGRESS`` forever with
# ``pending`` attribution entries — the permanently non-terminal record this
# whole design works to avoid. A handler that forgot ``_fail_pending``, or wrote
# ``fatal=False``, would have shipped green.


async def _assert_fatal_environment_creation_failure(
    scenario: _Scenario,
    clone_id: UUID,
    flow_harness: dict[str, list[Any]],
    *,
    error_contains: str,
) -> EnvironmentClone:
    """The invariant every fatal creation branch owes: terminal, and complete.

    Terminal (a fatal ``environment_creation_failed`` marker → ``FAILED``), with
    nothing materialised, and — the part a broken handler loses — **no
    ``pending`` entry left**, because those deployments will never be attempted.
    """
    refreshed = await scenario.uow.environment_clones.get(clone_id)
    assert refreshed is not None

    assert refreshed.created_environment_id is None
    assert flow_harness["deploy"] == [], "a counterpart was created anyway"
    assert flow_harness["restore"] == [], "a restore was dispatched anyway"

    assert refreshed.clone_errors is not None
    assert [entry["step"] for entry in refreshed.clone_errors] == [
        CLONE_STEP_ENVIRONMENT_CREATION_FAILED
    ]
    marker = refreshed.clone_errors[0]
    assert marker["fatal"] is True, (
        "a non-fatal marker leaves the clone reading IN_PROGRESS forever"
    )
    assert error_contains in marker["error"], marker["error"]

    entries = _results(refreshed)
    assert entries, "the attribution entries were lost"
    assert {entry["outcome"] for entry in entries.values()} == {"failed"}, (
        f"a terminal clone must carry no pending entry: {entries!r}"
    )
    assert all(
        entry["reason"] == CLONE_REASON_CAPTURE_UNUSABLE for entry in entries.values()
    ), entries

    status = derive_environment_clone_status_from_record(refreshed)
    assert status is EnvironmentCloneStatus.FAILED
    assert status in TERMINAL_ENVIRONMENT_CLONE_STATUSES
    return refreshed


@pytest.mark.asyncio
async def test_a_vanished_source_environment_fails_the_clone_terminally(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """research D9: the record outlived its source by a race.

    Non-terminal clones are deleted with their source, so reaching the flow's
    ``source_environment is None`` branch means the deletion cascade and this
    flow interleaved. There is no cluster left to create an environment in, so
    the clone has to end terminal here rather than wait for one.
    """
    clone = await scenario.clone()
    await _complete_capture(scenario)
    scenario.uow.environments.models.remove(scenario.source)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    await _assert_fatal_environment_creation_failure(
        scenario,
        clone.id,
        flow_harness,
        error_contains="the source environment no longer exists",
    )
    assert scenario.uow.environments.models == [], (
        "nothing may be created once the source is gone"
    )


@pytest.mark.asyncio
async def test_a_captured_config_that_no_longer_validates_fails_the_clone(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """The merge is re-run at flow time, and the capture can have gone stale.

    A snapshot taken before a config field was removed no longer validates, and
    ``merge_environment_config`` says so loudly rather than silently creating an
    environment whose config differs from what was captured. The mutation
    validated the *override*, never the captured side, so this is only reachable
    here — and it must not crash the flow run, which would leave the clone
    non-terminal with the Prefect log as the only record of why.
    """
    clone = await scenario.clone()
    await _complete_capture(scenario)
    environment_backup = await scenario.uow.environment_backups.get(
        clone.environment_backup_id
    )
    assert environment_backup is not None
    environment_backup.environment_config = {"retired_field": "no longer exists"}

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    await _assert_fatal_environment_creation_failure(
        scenario,
        clone.id,
        flow_harness,
        error_contains="the cloned environment config is invalid",
    )
    assert [env.name for env in scenario.uow.environments.models] == ["prod"]


@pytest.mark.asyncio
async def test_an_unexpected_create_environment_failure_fails_the_clone(
    scenario: _Scenario,
    prefect_manager_mock,
    flow_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catch-all: anything ``create_environment`` can raise is attributed.

    Not ``EnvironmentAlreadyExistsError`` (that is the TOCTOU branch above) but
    the generic case — a capability computation blowing up, a constraint nobody
    anticipated. Unhandled it would fail the flow run and pin the clone
    ``IN_PROGRESS`` with ``pending`` entries and no recovery except deleting a
    capture that is already terminal.
    """
    clone = await scenario.clone()
    await _complete_capture(scenario)

    async def _explode(**kwargs: Any):
        raise RuntimeError("capability probe timed out")

    monkeypatch.setattr(clone_flow, "create_environment", _explode)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    await _assert_fatal_environment_creation_failure(
        scenario,
        clone.id,
        flow_harness,
        error_contains="capability probe timed out",
    )
    assert [env.name for env in scenario.uow.environments.models] == ["prod"]


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


# ---------------------------------------------------------------------------
# T029 — US3: nothing observes the config before the merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_merge_precedes_environment_creation_and_counterpart_creation(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """US3's ordering guarantee, pinned as an order rather than a value.

    The merge must run **before** ``create_environment``, and every counterpart
    must be created **after** it. Any implementation that created the
    environment from the captured config and patched it afterwards — or that
    generated counterparts first — would still end with the right environment
    row, but its counterparts' first instance contexts would have resolved
    against production configuration, which is exactly the interference US3
    exists to prevent.
    """
    clone = await scenario.clone(
        config_override={"db_size": "5Gi"}, clear_config_fields=["fqdn_suffix"]
    )
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    merged = {"db_size": "5Gi"}
    # Merged exactly once (the environment config is one decision, not one per
    # counterpart), then handed straight to ``create_environment`` as its
    # *creation* input, and only then are the two counterparts created.
    assert flow_harness["order"] == [
        ("merge", merged),
        ("create_environment", merged),
        ("deploy", "postgres-main"),
        ("deploy", "api"),
    ]


@pytest.mark.asyncio
async def test_counterparts_are_created_against_the_merged_environment_config(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """FR-006: the merged config is *persisted* before any counterpart exists.

    ``deploy_application`` runs ``generate_instance_from_deployment``, which
    re-reads the environment row through the unit of work to resolve the
    counterpart's first instance context. So the assertion that matters is not
    "the merge returned the right dict" but "the environment row already held
    the merged config when the counterpart was created" — which is what the
    harness records at each ``deploy_application`` call.
    """
    scenario.source.config = {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
        "db_size": "50Gi",
    }
    clone = await scenario.clone(
        config_override={"fqdn_suffix": "rehearsal.example.com"},
        clear_config_fields=["ingress_class"],
    )
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    merged = {"fqdn_suffix": "rehearsal.example.com", "db_size": "50Gi"}
    assert flow_harness["observed_config"] == [merged, merged]
    assert ("create_environment", merged) in flow_harness["order"]
    # And the row itself agrees — the observation above was not of a
    # not-yet-committed in-memory object.
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None and refreshed.created_environment_id is not None
    created = await scenario.uow.environments.get(refreshed.created_environment_id)
    assert created is not None and created.config == merged


@pytest.mark.asyncio
async def test_no_override_creates_the_environment_with_the_captured_config(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """FR-006 / spec US3 scenario 2: no override means a faithful copy."""
    scenario.source.config = {
        "fqdn_suffix": "prod.example.com",
        "ingress_class": "prod-nginx",
    }
    clone = await scenario.clone()
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    captured = {"fqdn_suffix": "prod.example.com", "ingress_class": "prod-nginx"}
    assert flow_harness["order"][:2] == [
        ("merge", captured),
        ("create_environment", captured),
    ]
    assert flow_harness["observed_config"] == [captured, captured]


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


# ---------------------------------------------------------------------------
# T032 — FR-008 delete guard and the environment-backup cascade (research D9)
# ---------------------------------------------------------------------------
#
# Three timing windows, and the whole point of D9 is that they behave
# differently: during the capture the deletion is refused, after the capture it
# is the escape hatch that ends a stuck clone, and after the clone itself
# finished it is routine TTL cleanup that must not rewrite history.


def _clone_errors_by_step(clone: EnvironmentClone) -> dict[str, dict[str, Any]]:
    """The recorded operation-level events keyed by step."""
    return {entry["step"]: entry for entry in clone.clone_errors or []}


async def _finish_clone(
    scenario: _Scenario, clone: EnvironmentClone, *, name: str = "prod-rehearsal"
) -> Environment:
    """Drive ``clone`` to a terminal ``COMPLETED`` without running the flow.

    The capture lands, the environment materialises, and both deployments are
    attributed — the shape a finished clone actually has, written directly so
    the deletion paths are tested against state they did not produce.
    """
    await _complete_capture(scenario)
    created = Environment(name=name, cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    clone.created_environment_id = created.id
    clone.deployment_results = [
        {
            "deployment_id": str(scenario.first.id),
            "deployment_name": "postgres-main",
            "outcome": "cloned",
            "reason": None,
            "counterpart_deployment_id": str(uuid4()),
            "restore_id": None,
        },
        {
            "deployment_id": str(scenario.second.id),
            "deployment_name": "api",
            "outcome": "skipped",
            "reason": CLONE_REASON_NOT_ELIGIBLE,
            "counterpart_deployment_id": None,
            "restore_id": None,
        },
    ]
    await scenario.uow.environment_clones.save(clone)
    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.COMPLETED
    )
    return created


@pytest.mark.asyncio
async def test_deleting_the_capture_during_the_capture_is_refused_as_in_use(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """Window 1 (FR-008): the one window where deletion strands work."""
    clone = await scenario.clone()
    assert clone.environment_backup_id is not None

    with pytest.raises(EnvironmentBackupInUseByCloneError) as excinfo:
        await delete_environment_backup(
            environment_backup_id=clone.environment_backup_id, uow=scenario.uow
        )

    assert excinfo.value.error_code == "IN_USE"
    assert excinfo.value.clone_id == str(clone.id)
    assert excinfo.value.clone_name == "prod-rehearsal"
    # Refused means refused: nothing about the snapshot or the clone moved.
    assert [parent.id for parent in scenario.uow.environment_backups.models] == [
        clone.environment_backup_id
    ]
    assert len(scenario.uow.backups.models) == 2
    assert clone.clone_errors is None


@pytest.mark.asyncio
async def test_deleting_the_capture_after_it_lands_fails_a_running_clone(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """Window 2 (FR-008): the escape hatch, attributed on the record."""
    clone = await scenario.clone()
    await _complete_capture(scenario)
    environment_backup_id = clone.environment_backup_id
    assert environment_backup_id is not None
    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.IN_PROGRESS
    )

    await delete_environment_backup(
        environment_backup_id=environment_backup_id, uow=scenario.uow
    )

    assert scenario.uow.environment_backups.models == []
    assert scenario.uow.backups.models == []
    # The record survives, released from the deleted capture and honest about
    # why it stopped.
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.environment_backup_id is None
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_ENVIRONMENT_BACKUP_DELETED]
    assert marker["fatal"] is True
    assert str(environment_backup_id) in marker["error"]
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )


@pytest.mark.asyncio
async def test_deleting_the_capture_of_a_finished_clone_keeps_its_outcome(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """Window 3 (FR-008): TTL cleanup must not rewrite history."""
    clone = await scenario.clone()
    await _finish_clone(scenario, clone)
    environment_backup_id = clone.environment_backup_id
    assert environment_backup_id is not None

    await delete_environment_backup(
        environment_backup_id=environment_backup_id, uow=scenario.uow
    )

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.environment_backup_id is None
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_ENVIRONMENT_BACKUP_DELETED]
    assert marker["fatal"] is False
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_deleting_the_capture_of_a_mid_restore_clone_is_attributed_fatally(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """Terminality is snapshotted before the cascade eats its own inputs.

    A clone whose counterpart restore is still running is non-terminal *because
    of that restore row* — and the cascade deletes it along with the constituent
    backup it was taken from. Re-deriving afterwards would read the clone as
    having finished; the deletion has to be judged against the state the
    operator asked about.
    """
    clone = await scenario.clone()
    await _complete_capture(scenario)
    created = Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    constituent = scenario.uow.backups.models[0]
    restore = Restore(
        name="cross-target-restore",
        status=RestoreStatus.IN_PROGRESS,
        target_namespace="styrmin-counterpart",
        backup_id=constituent.id,
    )
    scenario.uow.restores.models.append(restore)
    clone.created_environment_id = created.id
    clone.deployment_results = [
        {
            "deployment_id": str(scenario.first.id),
            "deployment_name": "postgres-main",
            "outcome": "cloned",
            "reason": None,
            "counterpart_deployment_id": str(uuid4()),
            "restore_id": str(restore.id),
        }
    ]
    await scenario.uow.environment_clones.save(clone)
    assert (
        derive_environment_clone_status_from_record(clone, {restore.id: restore})
        is EnvironmentCloneStatus.IN_PROGRESS
    )

    await delete_environment_backup(
        environment_backup_id=clone.environment_backup_id, uow=scenario.uow
    )

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_ENVIRONMENT_BACKUP_DELETED]
    assert marker["fatal"] is True
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )


@pytest.mark.asyncio
async def test_a_terminal_clone_never_blocks_deleting_its_capture(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The guard's second conjunct: terminality releases it unconditionally.

    A clone that recorded a fatal error while its capture was still queued is
    terminal with a non-terminal capture. It has nothing in flight left to
    strand, so refusing here would recreate the wedge D9 exists to prevent.
    """
    clone = await scenario.clone()
    clone.clone_errors = [
        {
            "step": CLONE_STEP_TARGET_NAME_TAKEN,
            "error": "the name was taken in the meantime",
            "fatal": True,
        }
    ]
    await scenario.uow.environment_clones.save(clone)
    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.FAILED
    )

    await delete_environment_backup(
        environment_backup_id=clone.environment_backup_id, uow=scenario.uow
    )

    assert scenario.uow.environment_backups.models == []
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert (
        _clone_errors_by_step(refreshed)[CLONE_STEP_ENVIRONMENT_BACKUP_DELETED]["fatal"]
        is False
    )


@pytest.mark.asyncio
async def test_deleting_an_unrelated_capture_leaves_the_clone_alone(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The cascade is keyed on the capture, not on the environment."""
    clone = await scenario.clone()
    await _complete_capture(scenario)
    unrelated = await create_environment_backup(
        environment_id=scenario.source.id, uow=scenario.uow
    )

    await delete_environment_backup(
        environment_backup_id=unrelated.id, uow=scenario.uow
    )

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.environment_backup_id == clone.environment_backup_id
    assert refreshed.clone_errors is None


# ---------------------------------------------------------------------------
# T033 — clone-aware ``delete_environment`` (research D9, spec SC-005)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discarding_the_created_environment_fails_a_running_clone(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The discard path always works, and drives a stuck clone terminal."""
    clone = await scenario.clone()
    await _complete_capture(scenario)
    created = Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    clone.created_environment_id = created.id
    await scenario.uow.environment_clones.save(clone)
    assert (
        derive_environment_clone_status_from_record(clone)
        is EnvironmentCloneStatus.IN_PROGRESS
    )

    await delete_environment(environment_id=created.id, uow=scenario.uow)

    assert created.id not in {
        environment.id for environment in scenario.uow.environments.models
    }
    # The clone record survives as history — nulled FK plus the marker that
    # tells "deleted" apart from "not yet created".
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.created_environment_id is None
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_CREATED_ENVIRONMENT_DELETED]
    assert marker["fatal"] is True
    assert str(created.id) in marker["error"]
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )


@pytest.mark.asyncio
async def test_discarding_the_environment_of_a_finished_clone_keeps_its_outcome(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """Deleting a finished clone's environment records the event, not a failure."""
    clone = await scenario.clone()
    created = await _finish_clone(scenario, clone)

    await delete_environment(environment_id=created.id, uow=scenario.uow)

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.created_environment_id is None
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_CREATED_ENVIRONMENT_DELETED]
    assert marker["fatal"] is False
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_discarding_a_clone_frees_the_name_for_an_immediate_re_clone(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """SC-005: nothing a discarded clone leaves behind blocks re-cloning it.

    Three things have to be true at once for this to work, and each has bitten
    a design before: the environment row is gone (so the name is free), the
    clone record is terminal (so it no longer occupies the source), and
    ``EnvironmentClone.name`` carries no unique constraint (so the history of
    the failed attempt can coexist with the retry).
    """
    first = await scenario.clone()
    await _complete_capture(scenario)
    created = Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    first.created_environment_id = created.id
    await scenario.uow.environment_clones.save(first)

    await delete_environment(environment_id=created.id, uow=scenario.uow)

    second = await scenario.clone()

    assert second.id != first.id
    assert second.name == first.name == "prod-rehearsal"
    assert {clone.id for clone in scenario.uow.environment_clones.models} == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_deleting_the_source_keeps_a_finished_clone_as_provenance(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """A created environment outlives its source; its provenance must too."""
    clone = await scenario.clone()
    created = await _finish_clone(scenario, clone)

    await delete_environment(environment_id=scenario.source.id, uow=scenario.uow)

    assert created.id in {
        environment.id for environment in scenario.uow.environments.models
    }
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.source_environment_id is None
    assert refreshed.source_environment_name == "prod"
    assert refreshed.created_environment_id == created.id
    # The source's snapshots cascaded, which detached the capture too — but on a
    # terminal clone that is history, not a failure.
    assert refreshed.environment_backup_id is None
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_deleting_the_source_mid_capture_removes_the_clone_without_wedging(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The ordering guarantee: clone records are settled *before* backups.

    The clone's capture is in flight, so the FR-008 guard would refuse to delete
    the snapshot the environment cascade has to remove. Settling the clone
    records first means the guard has nothing left to refuse — and a
    non-terminal clone has no outcome worth keeping, so it goes.
    """
    clone = await scenario.clone()

    await delete_environment(environment_id=scenario.source.id, uow=scenario.uow)

    assert scenario.uow.environments.models == []
    assert scenario.uow.environment_backups.models == []
    assert scenario.uow.backups.models == []
    assert await scenario.uow.environment_clones.get(clone.id) is None


@pytest.mark.asyncio
async def test_deleting_the_source_of_a_terminal_clone_with_a_live_capture(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The same no-wedge guarantee for a clone the guard's first conjunct sees.

    A terminal clone is *kept*, so it is still referencing the capture when the
    cascade reaches it. Only the guard's terminality conjunct keeps that from
    refusing the environment deletion.
    """
    clone = await scenario.clone()
    clone.clone_errors = [
        {
            "step": CLONE_STEP_TARGET_NAME_TAKEN,
            "error": "the name was taken in the meantime",
            "fatal": True,
        }
    ]
    await scenario.uow.environment_clones.save(clone)

    await delete_environment(environment_id=scenario.source.id, uow=scenario.uow)

    assert scenario.uow.environments.models == []
    assert scenario.uow.environment_backups.models == []
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.source_environment_id is None
    assert refreshed.environment_backup_id is None


@pytest.mark.asyncio
async def test_deleting_an_unrelated_environment_leaves_clone_records_alone(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """Both cascades are scoped by id, in both clone roles."""
    clone = await scenario.clone()
    created = await _finish_clone(scenario, clone)
    bystander = Environment(name="staging", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(bystander)

    await delete_environment(environment_id=bystander.id, uow=scenario.uow)

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.source_environment_id == scenario.source.id
    assert refreshed.created_environment_id == created.id
    assert refreshed.clone_errors is None


# ---------------------------------------------------------------------------
# Review fixes — the escape hatch, provenance, and dispatch atomicity
# ---------------------------------------------------------------------------


async def _no_sleep(_seconds: float) -> None:
    """Stand in for ``asyncio.sleep`` so the poll loop runs at test speed."""
    return None


@pytest.mark.asyncio
async def test_deleting_a_capture_that_can_never_terminalise_is_allowed(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """FR-008's escape hatch has to be reachable, not merely documented.

    The state under test is what a Prefect outage produces: the constituent
    ``EXECUTE_BACKUP`` dispatches never happened, so every constituent stays
    ``PENDING``, the capture derives ``PENDING`` for ever, and the clone derives
    non-terminal for ever with it. A guard keyed on that state alone refused the
    deletion permanently — the source stayed occupied for every environment-level
    operation *and* ``update_environment``, the capture was undeletable, and
    there was no created environment to discard, so the only way out was hand
    -deleting each constituent ``Backup`` row.

    Past the clone flow's own wait budget nothing is left waiting on the
    capture, so the deletion is allowed and does what FR-008 says it does:
    the clone ends ``FAILED`` with the deletion attributed, and the source is
    released.
    """
    clone = await scenario.clone()
    environment_backup_id = clone.environment_backup_id
    assert environment_backup_id is not None
    capture = await scenario.uow.environment_backups.get(environment_backup_id)
    assert capture is not None
    # Nothing ever picked the constituents up.
    assert {backup.status for backup in scenario.uow.backups.models} == {
        BackupStatus.PENDING
    }
    # And that has been true for longer than the flow waits.
    capture.created_on = datetime.now(timezone.utc) - timedelta(hours=3)

    await delete_environment_backup(
        environment_backup_id=environment_backup_id, uow=scenario.uow
    )

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert refreshed.environment_backup_id is None
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_ENVIRONMENT_BACKUP_DELETED]
    assert marker["fatal"] is True
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )
    # The source is free again: a released clone occupies nothing.
    assert (
        await find_clone_occupying_environment(scenario.source.id, scenario.uow) is None
    )


@pytest.mark.asyncio
async def test_a_young_capture_in_flight_is_still_protected(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """The other half of the time bound: a live capture keeps its protection.

    Same state as above minus the age, so the narrowing cannot be mistaken for
    "the guard was dropped".
    """
    clone = await scenario.clone()
    assert clone.environment_backup_id is not None
    capture = await scenario.uow.environment_backups.get(clone.environment_backup_id)
    assert capture is not None
    capture.created_on = datetime.now(timezone.utc) - timedelta(minutes=5)

    with pytest.raises(EnvironmentBackupInUseByCloneError):
        await delete_environment_backup(
            environment_backup_id=clone.environment_backup_id, uow=scenario.uow
        )


@pytest.mark.asyncio
async def test_deleting_the_source_keeps_a_clone_that_already_created_an_environment(
    scenario: _Scenario, prefect_manager_mock
) -> None:
    """A live environment's provenance must not die with the source (D9).

    A clone whose counterparts are mid-restore is non-terminal, and deleting
    such a record outright destroyed the only link between the environment it
    created and where that environment came from — while the backup cascade
    behind it deleted the constituent backups *and the in-flight restores* of
    counterparts nothing was left to attribute.

    Kept instead, with the deletion attributed fatally: the clone comes to rest
    (it can never progress — its capture goes with the source), so it stops
    occupying the environment it created, and the record still says what it was
    cloned from.
    """
    from styrmin_backend.services.backup.clone import (
        CLONE_STEP_SOURCE_ENVIRONMENT_DELETED,
    )

    clone = await scenario.clone()
    await _complete_capture(scenario)
    created = Environment(name="prod-rehearsal", cluster_id=scenario.cluster.id)
    scenario.uow.environments.models.append(created)
    constituent = scenario.uow.backups.models[0]
    restore = Restore(
        name="cross-target-restore",
        status=RestoreStatus.IN_PROGRESS,
        target_namespace="styrmin-counterpart",
        backup_id=constituent.id,
    )
    scenario.uow.restores.models.append(restore)
    clone.created_environment_id = created.id
    clone.deployment_results = [
        {
            "deployment_id": str(scenario.first.id),
            "deployment_name": "postgres-main",
            "outcome": "cloned",
            "reason": None,
            "counterpart_deployment_id": str(uuid4()),
            "restore_id": str(restore.id),
        }
    ]
    await scenario.uow.environment_clones.save(clone)
    assert (
        derive_environment_clone_status_from_record(clone, {restore.id: restore})
        is EnvironmentCloneStatus.IN_PROGRESS
    )

    await delete_environment(environment_id=scenario.source.id, uow=scenario.uow)

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None, "the created environment lost its provenance"
    assert refreshed.source_environment_id is None
    assert refreshed.source_environment_name == "prod"
    assert refreshed.created_environment_id == created.id
    marker = _clone_errors_by_step(refreshed)[CLONE_STEP_SOURCE_ENVIRONMENT_DELETED]
    assert marker["fatal"] is True
    assert (
        derive_environment_clone_status_from_record(refreshed)
        is EnvironmentCloneStatus.FAILED
    )
    # Terminal, so it no longer occupies the environment it created.
    assert await find_clone_occupying_environment(created.id, scenario.uow) is None
    # The created environment itself is untouched — it is an ordinary environment.
    assert created.id in {
        environment.id for environment in scenario.uow.environments.models
    }


@pytest.mark.asyncio
async def test_a_failed_restore_dispatch_is_settled_and_attributed(
    scenario: _Scenario,
    prefect_manager_mock,
    flow_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dispatch failure must leave nothing nameless and nothing wedged.

    ``create_restore`` commits a ``PENDING`` row and parks the counterpart in
    ``RESTORING`` *before* the flow run is dispatched. When the dispatch then
    fails, the clone still derives terminal and looks settled — so unless the
    row is closed out and both ids recorded, a real counterpart sits
    ``RESTORING`` for ever behind an invisible ``PENDING`` restore, and the
    in-flight-restore guard refuses every future restore into it while naming a
    restore that never ran.
    """

    class _FailingManager:
        async def run_action(self, **kwargs: Any) -> None:
            if kwargs["action"] is PrefectAction.EXECUTE_RESTORE:
                raise RuntimeError("prefect is down")

    monkeypatch.setattr(clone_flow, "get_manager", lambda: _FailingManager())

    clone = await scenario.clone(deployment_ids=[scenario.first.id])
    await _complete_capture(scenario)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    entry = _results(refreshed)["postgres-main"]
    assert entry["outcome"] == "failed"
    assert "never dispatched" in entry["reason"]
    # Both orphans are nameable from the record itself.
    assert entry["counterpart_deployment_id"] is not None
    assert entry["restore_id"] is not None

    # The stranded row is settled, so the in-flight guard cannot wedge the
    # counterpart, and the counterpart is not left claiming to be restoring.
    restore = next(
        row
        for row in scenario.uow.restores.models
        if str(row.id) == entry["restore_id"]
    )
    assert restore.status is RestoreStatus.FAILED
    counterpart = await scenario.uow.deployments.find(
        UUID(entry["counterpart_deployment_id"])
    )
    assert counterpart is not None
    # Compared by value: the fake repository holds domain entities, whose
    # ``DeploymentState`` is a different class from the db-model one the
    # settle path writes.
    assert counterpart.status.value == DeploymentState.FAILED.value
    # And the clone is terminal rather than pinned by a PENDING restore row.
    restores = {row.id: row for row in scenario.uow.restores.models}
    assert derive_environment_clone_status_from_record(refreshed, restores) in (
        EnvironmentCloneStatus.FAILED,
        EnvironmentCloneStatus.PARTIAL,
    )


@pytest.mark.asyncio
async def test_an_unreadable_attribution_entry_is_never_erased_from_the_record(
    scenario: _Scenario, prefect_manager_mock, flow_harness
) -> None:
    """The flow updates ``deployment_results``; it must not rewrite it.

    An entry the flow cannot parse is skipped for the flow's own purposes, but
    rebinding the column to the flow's reduced list *deleted it from the
    database* — leaving the Prefect log as the only record that a source
    deployment was ever there, and letting the clone derive ``COMPLETED`` with
    it unaccounted for (spec SC-003).
    """
    clone = await scenario.clone(deployment_ids=[scenario.first.id])
    await _complete_capture(scenario)
    # A row a future (or broken) writer left behind, alongside the real ones.
    clone.deployment_results = [*(clone.deployment_results or []), "nonsense"]
    await scenario.uow.environment_clones.save(clone)

    await clone_flow.execute_environment_clone_workflow.fn(str(clone.id))

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert "nonsense" in (refreshed.deployment_results or []), (
        "the flow erased an entry it could not read"
    )
    # The readable entries still landed.
    readable = {
        entry["deployment_name"]: entry
        for entry in refreshed.deployment_results or []
        if isinstance(entry, dict)
    }
    assert readable["postgres-main"]["outcome"] == "cloned"
    # And the unreadable one keeps the clone honest: it is counted, so the
    # clone cannot read COMPLETED with a deployment unaccounted for.
    restores = {row.id: row for row in scenario.uow.restores.models}
    for row in restores.values():
        row.status = RestoreStatus.COMPLETED
    assert (
        derive_environment_clone_status_from_record(refreshed, restores)
        is EnvironmentCloneStatus.PARTIAL
    )


@pytest.mark.asyncio
async def test_the_capture_poll_reuses_one_unit_of_work(
    scenario: _Scenario, prefect_manager_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing closes an ``AsyncSession``, so the poll may not open one per turn.

    At the shipped poll interval and timeout a single clone could churn 720
    sessions against a pool of a few dozen. The loop therefore holds one unit of
    work and rolls it back between turns — which is also what makes the poll
    *see* the capture terminalise, instead of the identity map's first read.
    """
    sessions: list[Any] = []
    rollbacks: list[int] = []
    real_rollback = scenario.uow.rollback

    async def _get_uow():
        sessions.append(scenario.uow)
        return scenario.uow

    async def _rollback() -> None:
        rollbacks.append(1)
        # Terminalise on the second turn, the way a real capture would land
        # between two reads.
        for backup in scenario.uow.backups.models:
            backup.status = BackupStatus.COMPLETED
        await real_rollback()

    monkeypatch.setattr(clone_flow, "get_unit_of_work", _get_uow)
    monkeypatch.setattr(clone_flow, "get_run_logger", lambda: logging.getLogger("test"))
    monkeypatch.setattr(clone_flow.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(scenario.uow, "rollback", _rollback)

    clone = await scenario.clone()
    sessions.clear()

    capture_status, _ = await clone_flow._await_capture_terminal(clone.id)

    assert capture_status is EnvironmentOperationStatus.COMPLETED
    assert rollbacks, "the loop never discarded a read, so it would poll a stale one"
    assert len(sessions) == 1, (
        f"the poll opened {len(sessions)} units of work; one is enough and "
        "nothing ever closes them"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "deployment_ids",
    [
        pytest.param(None, id="all-eligible"),
        pytest.param([], id="empty-selection-everything-skipped"),
    ],
)
async def test_registration_never_returns_a_terminal_clone(
    scenario: _Scenario, prefect_manager_mock, deployment_ids: list[UUID] | None
) -> None:
    """What the mutation returns is always still moving (documented contract).

    Registration writes no ``clone_errors`` and always returns with
    ``created_environment_id IS NULL``, so the derivation falls through to
    ``PENDING``/``IN_PROGRESS`` — ``PARTIAL`` and ``FAILED`` are unreachable
    here, and even an all-skipped, configuration-only clone reads
    ``IN_PROGRESS`` rather than ``COMPLETED`` until its environment exists.
    Pinned because three places documented the opposite: the CLI's terminal
    check and the ``env-clones`` exit-code reference both promised operators a
    terminal status straight from the mutation.
    """
    clone = await scenario.clone(deployment_ids=deployment_ids)

    status = derive_environment_clone_status_from_record(clone)
    assert status not in TERMINAL_ENVIRONMENT_CLONE_STATUSES
    assert status in (
        EnvironmentCloneStatus.PENDING,
        EnvironmentCloneStatus.IN_PROGRESS,
    )
    assert clone.created_environment_id is None
    assert clone.clone_errors is None


@pytest.mark.asyncio
async def test_a_failed_environment_deletion_converges_on_retry(
    scenario: _Scenario, prefect_manager_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``delete_environment`` is multi-transaction; the retry has to converge.

    The clone settlement commits in its own transaction before the backup
    cascade runs, so a later step failing leaves a clone already reporting "the
    created environment was deleted" while the environment is still there. That
    window is inherent to a cascade that spans several transactions (the backup
    cascade is itself many), and the property that makes it safe is recorded
    here: the marker lands **with** the FK release, so a retry finds no clone by
    that environment id, attributes nothing a second time, and finishes the job.
    """
    from styrmin_backend.services import environments as environments_service

    clone = await scenario.clone()
    created = await _finish_clone(scenario, clone)
    real_cascade = environments_service.delete_environment_backups_for_environment
    attempts = {"count": 0}

    async def _failing_cascade(environment_id: UUID, uow: Any) -> int:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("the snapshot store was unreachable")
        return await real_cascade(environment_id, uow)

    monkeypatch.setattr(
        environments_service,
        "delete_environment_backups_for_environment",
        _failing_cascade,
    )

    with pytest.raises(RuntimeError):
        await delete_environment(environment_id=created.id, uow=scenario.uow)

    # The honest description of the window: attributed already, not deleted yet.
    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    assert [entry["step"] for entry in refreshed.clone_errors or []] == [
        CLONE_STEP_CREATED_ENVIRONMENT_DELETED
    ]
    assert created.id in {
        environment.id for environment in scenario.uow.environments.models
    }

    await delete_environment(environment_id=created.id, uow=scenario.uow)

    refreshed = await scenario.uow.environment_clones.get(clone.id)
    assert refreshed is not None
    steps = [entry["step"] for entry in refreshed.clone_errors or []]
    assert steps.count(CLONE_STEP_CREATED_ENVIRONMENT_DELETED) == 1, (
        "the retry attributed the same deletion twice"
    )
    assert created.id not in {
        environment.id for environment in scenario.uow.environments.models
    }
