"""Service-layer no-op detection for deployment updates (spec 014).

`update_deployment` / `update_deployment_version` must detect when the
submitted desired state resolves to the deployment's current realised
instance and short-circuit: no new ``ApplicationInstance``, no reconcile
``Task`` (``apply_state`` not called), status and active-instance pointer
left untouched, and a ``None`` return so the caller can render "unchanged".

A genuine change must still dispatch exactly one reconcile (``apply_state``
called once) and return a ``Task``.
"""

from uuid import UUID, uuid4
from unittest.mock import AsyncMock, patch

import pytest

from styrmin_backend.domain.models import (
    Deployment,
    DeploymentState,
    Step,
    StepKind,
    StepParent,
    Task,
    TaskType,
)
from styrmin_backend.services.deployment import (
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.reconciliation import generate_instance_from_deployment
from styrmin_backend.services.steps.exceptions import (
    InvalidStartingStepError,
    StepNotFoundError,
)
from tests.unit.services.fakes import (
    FakeUnitOfWork,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmRepositoryRepository,
    FakeHelmChartRepository,
    FakeApplicationRepository,
    FakeApplicationDriverVersionRepository,
    FakeApplicationInstanceRepository,
    FakeActionRepository,
    FakeTaskRepository,
    FakeDeployedServiceRepository,
    FakeDeploymentRepository,
)


def _make_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork(
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
        application_drivers=FakeApplicationRepository(),
    )


async def _seed_steady_state_deployment(
    *,
    uow: FakeUnitOfWork,
    deployment_id: UUID,
    environment_id: UUID,
    config: dict | None = None,
    supported_versions: str = ">=1.0.0,<2.0.0",
    extra_versions: list[tuple[str, str]] | None = None,
) -> Deployment:
    """Seed a deployment that has already reached a steady state.

    Generates the active instance via the real
    :func:`generate_instance_from_deployment` so a subsequent re-apply of the
    same desired state diffs to ``None`` in the Comparator.
    """
    from styrmin_backend.db.models import (
        ApplicationDriver,
        ApplicationDriverVersion,
        Cluster,
        Environment,
        HelmChart,
        HelmRepository,
    )

    cluster = Cluster(name="test-cluster")
    await uow.clusters.create(cluster)

    env = Environment(name="test-env", cluster_id=cluster.id, id=environment_id)
    await uow.environments.create(env)

    helm_repo = HelmRepository(url="https://charts.example.com")
    await uow.helm_repositories.create(helm_repo)

    helm_chart = HelmChart(
        name="test-chart",
        version="1.0.0",
        values_template="",
        repository_id=helm_repo.id,
    )
    await uow.helm_charts.create(helm_chart)

    app_driver = ApplicationDriver(name="test-app")
    adv = ApplicationDriverVersion(
        id=uuid4(),
        version="1.0.0",
        application_supported_versions=supported_versions,
        helm_chart_id=helm_chart.id,
        source_type="git",
        source_repository="https://github.com/test/repo",
        source_branch="main",
        source_path=None,
        application_driver_id=app_driver.id,
        services=[],
        component_configs=[],
    )
    adv.application_driver = app_driver
    await uow.application_driver_versions.create(adv)

    for extra_version, extra_supported in extra_versions or []:
        extra_adv = ApplicationDriverVersion(
            id=uuid4(),
            version=extra_version,
            application_supported_versions=extra_supported,
            helm_chart_id=helm_chart.id,
            source_type="git",
            source_repository="https://github.com/test/repo",
            source_branch="main",
            source_path=None,
            application_driver_id=app_driver.id,
            services=[],
            component_configs=[],
        )
        extra_adv.application_driver = app_driver
        await uow.application_driver_versions.create(extra_adv)
        app_driver.versions.append(extra_adv)
    app_driver.versions.insert(0, adv)
    await uow.application_drivers.create(app_driver)

    deployment = Deployment.create(
        application_version="1.0.0",
        application_driver_version_id=adv.id,
        environment_id=environment_id,
        created_by_user_id=uuid4(),
        config=config or {},
        name="test-deploy",
    )
    object.__setattr__(deployment, "id", deployment_id)

    # Establish the steady-state active instance from the current desired
    # state so a re-apply of the same state is a no-op.
    instance = await generate_instance_from_deployment(deployment=deployment, uow=uow)
    deployment.set_active_instance(instance=instance)
    deployment.set_status(DeploymentState.RUNNING)
    await uow.instances.create(instance)
    await uow.deployments.save(deployment)
    return deployment


async def _fake_apply_state(
    deployment,
    current_instance,
    uow,
    task_type,
    started_by_step_id=None,  # noqa: ANN001
):
    stub = Task.create(
        type=task_type,
        deployment_id=deployment.id,
        started_by_step_id=started_by_step_id,
    )
    await uow.tasks.save(stub)
    return stub


# ---------------------------------------------------------------------------
# update_deployment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_noop_returns_none_no_side_effects(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    env_id = uuid4()
    mock_apply_state.side_effect = _fake_apply_state

    deployment = await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=env_id,
        config={"env_vars": {"FOO": "bar"}},
    )
    active_instance_id_before = deployment.active_instance.id
    status_before = deployment.status

    async with uow:
        result = await update_deployment(
            deployment_id=deployment_id,
            uow=uow,
            deployment_config={"env_vars": {"FOO": "bar"}},
        )

    assert result is None, "A no-op update must return None"
    mock_apply_state.assert_not_called()

    async with uow:
        after = await uow.deployments.find(id=deployment_id)
        instances = await uow.instances.find_by_deployment(deployment_id)

    assert after is not None
    assert after.active_instance is not None
    assert after.active_instance.id == active_instance_id_before, (
        "Active-instance pointer must be untouched on a no-op"
    )
    assert after.status == status_before, "Status must be untouched on a no-op"
    assert len(instances) == 1, "No new ApplicationInstance must be persisted"


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_change_dispatches_one_reconcile(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    env_id = uuid4()
    mock_apply_state.side_effect = _fake_apply_state

    await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=env_id,
        config={"env_vars": {"FOO": "bar"}},
    )

    async with uow:
        result = await update_deployment(
            deployment_id=deployment_id,
            uow=uow,
            deployment_config={"env_vars": {"FOO": "baz"}},
        )

    assert result is not None, "A real change must return a Task"
    assert mock_apply_state.call_count == 1, (
        "A real change must dispatch exactly one reconcile"
    )


# ---------------------------------------------------------------------------
# update_deployment_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_version_same_version_is_noop(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    env_id = uuid4()
    mock_apply_state.side_effect = _fake_apply_state

    deployment = await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=env_id,
    )
    active_instance_id_before = deployment.active_instance.id
    status_before = deployment.status

    async with uow:
        result = await update_deployment_version(
            deployment_id=deployment_id,
            version="1.0.0",
            uow=uow,
        )

    assert result is None, "Requesting the current version must be a no-op"
    mock_apply_state.assert_not_called()

    async with uow:
        after = await uow.deployments.find(id=deployment_id)
        instances = await uow.instances.find_by_deployment(deployment_id)

    assert after is not None
    assert after.active_instance is not None
    assert after.active_instance.id == active_instance_id_before
    assert after.status == status_before
    assert len(instances) == 1, "No new ApplicationInstance must be persisted"


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_version_new_version_dispatches_reconcile(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    deployment_id = uuid4()
    env_id = uuid4()
    mock_apply_state.side_effect = _fake_apply_state

    await _seed_steady_state_deployment(
        uow=uow,
        deployment_id=deployment_id,
        environment_id=env_id,
    )

    async with uow:
        result = await update_deployment_version(
            deployment_id=deployment_id,
            version="1.1.0",
            uow=uow,
        )

    assert result is not None, "A new version must return a Task"
    assert mock_apply_state.call_count == 1, (
        "A version change must dispatch exactly one reconcile"
    )


class _Steps:
    """The one step read ``check_starting_step`` makes."""

    def __init__(self, *steps: Step) -> None:
        self._steps = {step.id: step for step in steps}

    async def get(self, id: UUID, for_update: bool = False) -> Step | None:  # noqa: A002, ARG002
        return self._steps.get(id)


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_version_noop_rejects_an_unknown_starting_step(
    mock_apply_state: AsyncMock,
) -> None:
    """The step check runs before the no-op return (spec 019, data-model "Validation rules")."""
    uow = _make_uow()
    uow.steps = _Steps()  # type: ignore[assignment]
    deployment_id = uuid4()
    await _seed_steady_state_deployment(
        uow=uow, deployment_id=deployment_id, environment_id=uuid4()
    )
    unknown = uuid4()

    with pytest.raises(StepNotFoundError, match=f"Step with id {unknown} not found"):
        async with uow:
            await update_deployment_version(
                deployment_id=deployment_id,
                version="1.0.0",
                uow=uow,
                started_by_step_id=unknown,
            )

    mock_apply_state.assert_not_called()


@pytest.mark.asyncio
@patch("styrmin_backend.services.deployment.apply_state", new_callable=AsyncMock)
async def test_update_deployment_version_noop_rejects_a_step_of_another_deployment(
    mock_apply_state: AsyncMock,
) -> None:
    uow = _make_uow()
    other_task = Task.create(type=TaskType.UPGRADE_INSTANCE, deployment_id=uuid4())
    await uow.tasks.save(other_task)
    hook = Step.create(
        StepParent.of_task(other_task.id),
        "hook:upgrade:core",
        "Run the upgrade hook",
        StepKind.HOOK,
    )
    uow.steps = _Steps(hook)  # type: ignore[assignment]
    deployment_id = uuid4()
    await _seed_steady_state_deployment(
        uow=uow, deployment_id=deployment_id, environment_id=uuid4()
    )

    with pytest.raises(InvalidStartingStepError):
        async with uow:
            await update_deployment_version(
                deployment_id=deployment_id,
                version="1.0.0",
                uow=uow,
                started_by_step_id=hook.id,
            )

    mock_apply_state.assert_not_called()
