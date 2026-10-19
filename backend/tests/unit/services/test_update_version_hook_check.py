"""The upgrade request checks the upgrade actions of the target driver version (spec 029, R-009).

``update_deployment_version`` looks up the registered flows of the target
driver version's ``upgrade`` actions when the application version changes,
before it writes anything. When a declared action has no registered flow,
the request returns a failed ``upgrade_instance`` task whose
``hook:upgrade:core`` step holds the error, starts no flow run, and leaves the
deployment as it was, so the same request starts a new task once the driver
is loaded again (FR-005, FR-007).

The setup follows ``test_update_deployment_noop.py``: fake repositories, the
real ``generate_instance_from_deployment``, and a patched ``apply_state``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import (
    Action,
    ApplicationDriver,
    ApplicationDriverVersion,
    Cluster,
    Environment,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
    Instance,
    Step,
    StepKind,
    StepParent,
    StepStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.services.deployment import update_deployment_version
from styrmin_backend.services.driver.hooks import resolve_upgrade_hooks
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.reconciliation import generate_instance_from_deployment
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator
from styrmin_backend.services.reconciliation.diffs.diffs import (
    ApplicationVersionChange,
    InstanceUpdate,
)
from styrmin_backend.workflows.manager import PrefectManager
from tests.unit.services.fakes import (
    FakeActionRepository,
    FakeApplicationDriverRepository,
    FakeApplicationDriverVersionRepository,
    FakeApplicationInstanceRepository,
    FakeClusterRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)

MODULE = "styrmin_backend.services.deployment"
DRIVER = "local-actions"

type Mode = Literal["pre", "core", "post"]


class _FakeSteps:
    """The step reads and writes of ``check_starting_step``, ``open_step`` and ``fail_step``."""

    def __init__(self) -> None:
        self.steps: dict[UUID, Step] = {}

    async def get(self, id: UUID, for_update: bool = False) -> Step | None:  # noqa: A002, ARG002
        return self.steps.get(id)

    async def find_by_key(
        self,
        parent: StepParent,
        key: str,
        for_update: bool = False,  # noqa: ARG002
    ) -> Step | None:
        return next(
            (s for s in self.steps.values() if (s.parent, s.key) == (parent, key)),
            None,
        )

    async def insert_if_absent(self, step: Step) -> bool:
        if await self.find_by_key(step.parent, step.key) is not None:
            return False
        self.steps[step.id] = step
        return True

    async def save(self, step: Step) -> None:
        self.steps[step.id] = step

    def of_task(self, task_id: UUID) -> list[Step]:
        return [s for s in self.steps.values() if s.task_id == task_id]


class _FakePrefectManager(PrefectManager):
    """Answers the hook lookups from the hook and mode pairs that have a registered flow."""

    def __init__(self, registered: Sequence[tuple[HookKind, Mode]] = ()) -> None:  # noqa: D107
        self.flows = {pair: uuid4() for pair in registered}
        self.lookups: list[tuple[HookKind, Mode]] = []

    async def get_user_action_deployment_id(
        self,
        application: str,  # noqa: ARG002
        version: str,  # noqa: ARG002
        hook: HookKind,
        mode: Mode,
        fingerprint: str | None = None,  # noqa: ARG002
        *,
        driver_directory: str | None,  # noqa: ARG002
    ) -> UUID | None:
        self.lookups.append((hook, mode))
        return self.flows.get((hook, mode))


@dataclass
class _Seeded:
    uow: FakeUnitOfWork
    steps: _FakeSteps
    deployment: Deployment
    current: ApplicationDriverVersion
    target: ApplicationDriverVersion
    """Another driver version of the same driver, which declares the actions of the test."""


SETUP_AND_UPGRADE: list[tuple[str, HookKind, Mode]] = [
    ("pre_setup", HookKind.SETUP, "pre"),
    ("post_setup", HookKind.SETUP, "post"),
    ("upgrade", HookKind.UPGRADE, "core"),
]


def _driver_version(
    driver: ApplicationDriver, helm_chart: HelmChart, version: str, path: str
) -> ApplicationDriverVersion:
    driver_version = ApplicationDriverVersion(
        id=uuid4(),
        version=version,
        application_supported_versions=">=0.1,<1.0",
        helm_chart_id=helm_chart.id,
        source_type="local",
        source_repository="",
        source_path=path,
        content_hash=version * 64,
        application_driver_id=driver.id,
        services=[],
        component_configs=[],
    )
    driver_version.application_driver = driver
    return driver_version


async def _seed(
    *,
    application_version: str = "0.1.0",
    target_actions: Sequence[tuple[str, HookKind, Mode]] = SETUP_AND_UPGRADE,
) -> _Seeded:
    """A running deployment of ``application_version`` bound to the ``current`` driver version."""
    uow = FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=FakeApplicationDriverVersionRepository(),
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        deployed_services=FakeDeployedServiceRepository(),
        deployments=FakeDeploymentRepository(),
        application_drivers=FakeApplicationDriverRepository(),
    )
    steps = _FakeSteps()
    uow.steps = steps  # type: ignore[assignment]

    cluster = Cluster(name="test-cluster")
    await uow.clusters.create(cluster)
    environment = Environment(name="test-env", cluster_id=cluster.id)
    await uow.environments.create(environment)
    helm_repository = HelmRepository(url="https://charts.example.com")
    await uow.helm_repositories.create(helm_repository)
    helm_chart = HelmChart(
        name="simple-app",
        version="0.1.0",
        values_template="",
        repository_id=helm_repository.id,
    )
    await uow.helm_charts.create(helm_chart)

    driver = ApplicationDriver(name=DRIVER)
    current = _driver_version(driver, helm_chart, "1", "/drivers/local-actions-1")
    target = _driver_version(driver, helm_chart, "2", "/drivers/local-actions-2")
    for driver_version in (current, target):
        await uow.application_driver_versions.create(driver_version)
        driver.versions.append(driver_version)
    await uow.application_drivers.create(driver)
    for action_name, hook, mode in target_actions:
        await uow.actions.create(
            Action(
                name=action_name,
                description=action_name,
                location=f"actions.py::{action_name}",
                hook=hook.value,
                mode=mode,
                application_driver_version_id=target.id,
            )
        )

    deployment = Deployment.create(
        application_version=application_version,
        application_driver_version_id=current.id,
        environment_id=environment.id,
        created_by_user_id=uuid4(),
        config={},
        name="test-deploy",
    )
    instance = await generate_instance_from_deployment(deployment=deployment, uow=uow)
    deployment.set_active_instance(instance=instance)
    deployment.set_status(DeploymentState.RUNNING)
    await uow.instances.create(instance)
    await uow.deployments.save(deployment)
    return _Seeded(
        uow=uow, steps=steps, deployment=deployment, current=current, target=target
    )


async def _fake_apply_state(
    deployment,  # noqa: ANN001
    current_instance,  # noqa: ANN001, ARG001
    uow,  # noqa: ANN001
    task_type,  # noqa: ANN001
    started_by_step_id=None,  # noqa: ANN001
) -> Task:
    task = Task.create(
        type=task_type,
        deployment_id=deployment.id,
        prefect_flow_run_id=uuid4(),
        instance_id=deployment.active_instance.id,
        started_by_step_id=started_by_step_id,
    )
    await uow.tasks.save(task)
    return task


async def _starting_step(seeded: _Seeded) -> Step:
    """A running upgrade hook step of an earlier task of the deployment, as a driver action has."""
    earlier = Task.create(
        type=TaskType.UPGRADE_INSTANCE, deployment_id=seeded.deployment.id
    )
    await seeded.uow.tasks.save(earlier)
    step = Step.create(
        StepParent.of_task(earlier.id),
        "hook:upgrade:core",
        "Run the upgrade hook",
        StepKind.HOOK,
        StepStatus.RUNNING,
    )
    await seeded.steps.save(step)
    return step


async def _request_upgrade_to_target(
    seeded: _Seeded,
    manager: _FakePrefectManager,
    *,
    version: str = "0.2.0",
    started_by_step_id: UUID | None = None,
) -> Task | None:
    async with seeded.uow:
        return await update_deployment_version(
            deployment_id=seeded.deployment.id,
            version=version,
            uow=seeded.uow,
            driver_version_id=seeded.target.id,
            started_by_step_id=started_by_step_id,
            prefect_manager=manager,
        )


@pytest.mark.asyncio
@patch(f"{MODULE}._ensure_ingress_controller", new_callable=AsyncMock)
@patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
async def test_upgrade_whose_upgrade_action_has_no_registered_flow_returns_a_failed_task(
    mock_apply_state: AsyncMock,
    mock_ensure_ingress_controller: AsyncMock,
) -> None:
    seeded = await _seed()
    manager = _FakePrefectManager(
        registered=[(HookKind.SETUP, "pre"), (HookKind.SETUP, "post")]
    )

    task = await _request_upgrade_to_target(seeded, manager)

    assert task is not None
    assert task.type is TaskType.UPGRADE_INSTANCE
    assert task.status is TaskStatus.FAILED
    assert task.prefect_flow_run_id is None
    assert task.instance_id is None
    assert await seeded.uow.tasks.find(task.id) == task
    (step,) = seeded.steps.of_task(task.id)
    assert step.key == "hook:upgrade:core"
    assert step.name == "Run the upgrade hook"
    assert step.status is StepStatus.FAILED
    (error,) = step.errors
    assert error.message == f"ActionNotRegisteredError: {task.message}"
    assert task.message is not None
    for part in (
        f"Driver version {DRIVER} 2@2222222",
        "declares the action upgrade for the upgrade hook, mode core",
        "Load the driver again",
        "styrminctl drivers load-local-version /drivers/local-actions-2",
        "request the change again",
    ):
        assert part in task.message
    # No flow run starts: neither the reconcile nor the ingress controller's.
    mock_apply_state.assert_not_called()
    mock_ensure_ingress_controller.assert_not_awaited()
    assert seeded.uow.commit_count == 1


@pytest.mark.asyncio
@patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
async def test_upgrade_whose_upgrade_action_has_no_registered_flow_leaves_the_deployment_unchanged(
    mock_apply_state: AsyncMock,
) -> None:
    """FR-007: the deployment keeps what the next request for the same upgrade compares with."""
    seeded = await _seed()
    before = seeded.deployment.model_copy(deep=True)

    await _request_upgrade_to_target(seeded, _FakePrefectManager())

    async with seeded.uow:
        after = await seeded.uow.deployments.find(id=seeded.deployment.id)
        instances = await seeded.uow.instances.find_by_deployment(seeded.deployment.id)
    assert after is not None
    assert after.application_version == "0.1.0"
    assert after.application_driver_version_id == seeded.current.id
    assert after.status is DeploymentState.RUNNING
    assert after.active_instance is not None
    assert before.active_instance is not None
    assert after.active_instance.id == before.active_instance.id
    assert after == before
    assert len(instances) == 1
    mock_apply_state.assert_not_called()


@pytest.mark.asyncio
@patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
async def test_failed_upgrade_task_keeps_the_step_that_started_it(
    mock_apply_state: AsyncMock,
) -> None:
    """An upgrade that a driver action requests shows which hook step requested it."""
    seeded = await _seed()
    starting_step = await _starting_step(seeded)

    task = await _request_upgrade_to_target(
        seeded, _FakePrefectManager(), started_by_step_id=starting_step.id
    )

    assert task is not None
    assert task.status is TaskStatus.FAILED
    assert task.started_by_step_id == starting_step.id
    mock_apply_state.assert_not_called()


@pytest.mark.asyncio
@patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
async def test_driver_only_change_at_the_same_application_version_runs_no_check(
    mock_apply_state: AsyncMock,
) -> None:
    """The flow updates the instance without the upgrade hook, so nothing is looked up."""
    mock_apply_state.side_effect = _fake_apply_state
    seeded = await _seed()
    manager = _FakePrefectManager()

    with patch(
        f"{MODULE}.resolve_upgrade_hooks", side_effect=resolve_upgrade_hooks
    ) as check:
        task = await _request_upgrade_to_target(seeded, manager, version="0.1.0")

    check.assert_not_awaited()
    assert manager.lookups == []
    assert task is not None
    assert task.prefect_flow_run_id is not None
    mock_apply_state.assert_called_once()
    after = await seeded.uow.deployments.find(id=seeded.deployment.id)
    assert after is not None
    assert after.application_driver_version_id == seeded.target.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_actions", "registered"),
    [
        (SETUP_AND_UPGRADE[:2], []),
        ([], []),
        (SETUP_AND_UPGRADE, [(HookKind.UPGRADE, "core")]),
    ],
    ids=[
        "declares-no-upgrade-action",
        "declares-no-action",
        "upgrade-action-registered",
    ],
)
@patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
async def test_upgrade_whose_upgrade_actions_resolve_starts_the_reconcile(
    mock_apply_state: AsyncMock,
    target_actions: list[tuple[str, HookKind, Mode]],
    registered: list[tuple[HookKind, Mode]],
) -> None:
    """A target without an ``upgrade``/``core`` action is a plain update in the flow; it passes."""
    mock_apply_state.side_effect = _fake_apply_state
    seeded = await _seed(target_actions=target_actions)
    manager = _FakePrefectManager(registered=registered)

    with patch(
        f"{MODULE}.resolve_upgrade_hooks", side_effect=resolve_upgrade_hooks
    ) as check:
        task = await _request_upgrade_to_target(seeded, manager)

    check.assert_awaited_once()
    assert task is not None
    assert task.status is TaskStatus.PENDING
    assert task.prefect_flow_run_id is not None
    mock_apply_state.assert_called_once()
    after = await seeded.uow.deployments.find(id=seeded.deployment.id)
    assert after is not None
    assert after.application_version == "0.2.0"
    assert after.application_driver_version_id == seeded.target.id


def _yields_application_version_change(
    current_instance: Instance, new_instance: Instance
) -> bool:
    """Whether the flow's diff takes the upgrade path (``InstanceUpdateStrategy``)."""
    diff = Comparator(
        current_instance=current_instance, new_instance=new_instance
    ).compare()
    return isinstance(diff.diff, InstanceUpdate) and any(
        isinstance(entry, ApplicationVersionChange) for entry in diff.diff.diffs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_version", "requested_version", "driver_change", "expected"),
    [
        ("0.1.0", "0.2.0", False, True),
        ("0.2.0", "0.1.0", False, True),
        ("0.1.0", "0.1.0", True, False),
        ("0.1.0", "0.1.0", False, False),
    ],
    ids=["version-increase", "version-decrease", "driver-only-change", "no-change"],
)
@patch(f"{MODULE}.apply_state", new_callable=AsyncMock)
async def test_the_check_runs_exactly_when_the_flow_takes_the_upgrade_path(
    mock_apply_state: AsyncMock,
    current_version: str,
    requested_version: str,
    driver_change: bool,
    expected: bool,
) -> None:
    """Critique X1: the request and the flow decide "this is an upgrade" by the same rule."""
    mock_apply_state.side_effect = _fake_apply_state
    seeded = await _seed(application_version=current_version)
    current_instance = seeded.deployment.active_instance
    assert current_instance is not None
    # Both driver versions declare and register the upgrade action, so the check passes.
    await seeded.uow.actions.create(
        Action(
            name="upgrade",
            description="upgrade",
            location="actions.py::upgrade",
            hook=HookKind.UPGRADE.value,
            mode="core",
            application_driver_version_id=seeded.current.id,
        )
    )
    manager = _FakePrefectManager(registered=[(HookKind.UPGRADE, "core")])
    new_instances: list[Instance] = []

    async def _generate(**kwargs) -> Instance:  # noqa: ANN003
        instance = await generate_instance_from_deployment(**kwargs)
        new_instances.append(instance)
        return instance

    with (
        patch(f"{MODULE}.generate_instance_from_deployment", side_effect=_generate),
        patch(
            f"{MODULE}.resolve_upgrade_hooks", side_effect=resolve_upgrade_hooks
        ) as check,
    ):
        async with seeded.uow:
            await update_deployment_version(
                deployment_id=seeded.deployment.id,
                version=requested_version,
                uow=seeded.uow,
                driver_version_id=(
                    seeded.target.id if driver_change else seeded.current.id
                ),
                prefect_manager=manager,
            )

    (new_instance,) = new_instances
    upgrade_path = _yields_application_version_change(current_instance, new_instance)
    assert upgrade_path is expected
    assert check.await_count == (1 if upgrade_path else 0)
