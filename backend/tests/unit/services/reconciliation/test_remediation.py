from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fast_depends import dependency_provider

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.db.models import ApplicationDriver, ApplicationDriverVersion
from styrmin_backend.domain.models import Instance, InstanceStatus
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.reconciliation.diffs.diffs import (
    ApplicationDriverVersionChange,
    ApplicationVersionChange,
    ContextChange,
    InstanceUpdate,
)
from styrmin_backend.services.reconciliation.remediation import (
    InstanceUpdateStrategy,
    RemediationType,
)
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction
from tests.unit.services.fakes import (
    FakeApplicationDriverRepository,
    FakeApplicationRepository,
    FakeClusterRepository,
    FakeEnvironmentRepository,
    FakeHelmChartRepository,
    FakeHelmRepositoryRepository,
    FakeActionRepository,
    FakeApplicationInstanceRepository,
    FakeTaskRepository,
    FakeUnitOfWork,
)


# ---- Fixtures ----


@pytest.fixture
def prefect_manager_mock(mocker):
    manager_mock = mocker.Mock(spec=PrefectManager)

    def get_fake_manager(catalogue=None, workflow_executor=None) -> PrefectManager:
        return manager_mock

    dependency_provider.override(get_manager, get_fake_manager)
    yield manager_mock
    dependency_provider.clear()


@pytest.fixture
def app_driver():
    return ApplicationDriver(name="test_app")


@pytest.fixture
def driver_version(app_driver):
    return ApplicationDriverVersion(
        version="1.0.0",
        application_supported_versions=">=1.0.0",
        helm_chart_id=uuid4(),
        source_repository="https://github.com/test/repo",
        source_branch="main",
        application_driver_id=app_driver.id,
    )


@pytest.fixture
def uow(app_driver, driver_version):
    app_driver_repo = FakeApplicationDriverRepository(models=[app_driver])
    app_driver_version_repo = FakeApplicationRepository(models=[driver_version])
    return FakeUnitOfWork(
        clusters=FakeClusterRepository(),
        environments=FakeEnvironmentRepository(),
        helm_repositories=FakeHelmRepositoryRepository(),
        helm_charts=FakeHelmChartRepository(),
        application_driver_versions=app_driver_version_repo,
        instances=FakeApplicationInstanceRepository(),
        actions=FakeActionRepository(),
        tasks=FakeTaskRepository(),
        application_drivers=app_driver_repo,
    )


@pytest.fixture
def instance(mocker, driver_version):
    context = mocker.Mock(spec=GlobalContext)
    return Instance(
        id=uuid4(),
        name="test-instance",
        application_version="2.0.0",
        status=InstanceStatus.PENDING,
        deployment_id=uuid4(),
        application_driver_version_id=driver_version.id,
        context=context,
    )


# ---- Tests ----


async def test_upgrade_with_version_change_and_core_hook(
    uow, instance, prefect_manager_mock
):
    """When an ApplicationVersionChange is present and the driver defines an upgrade core hook,
    the strategy should return an UPGRADE_INSTANCE remediation."""
    upgrade_hook_id = uuid4()
    upgrade_flow_id = uuid4()
    update_helm_flow_id = uuid4()
    prehook_id = uuid4()
    posthook_id = uuid4()

    async def fake_get_user_action(application, hook, mode, version):
        if hook == HookKind.UPGRADE and mode == "core":
            return upgrade_hook_id
        if hook == HookKind.UPGRADE and mode == "pre":
            return prehook_id
        if hook == HookKind.UPGRADE and mode == "post":
            return posthook_id
        return None

    async def fake_get_action(action):
        if action == PrefectAction.UPGRADE_INSTANCE:
            return upgrade_flow_id
        if action == PrefectAction.UPDATE_HELM_RELEASE:
            return update_helm_flow_id
        if action == PrefectAction.APPLY_UTILITY_RESOURCES:
            return uuid4()
        return None

    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(
        side_effect=fake_get_user_action
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(
        side_effect=fake_get_action
    )

    diff = InstanceUpdate(
        instance=instance,
        diffs=[ApplicationVersionChange.create("1.0.0", "2.0.0")],
    )

    strategy = InstanceUpdateStrategy(uow=uow)
    remediation = await strategy.execute(diff)

    assert remediation is not None
    assert remediation.type == RemediationType.UPGRADE_INSTANCE
    assert remediation.flow_id == upgrade_flow_id
    assert remediation.parameters["upgrade_hook"] == upgrade_hook_id
    assert remediation.parameters["update_flow"] == update_helm_flow_id
    assert remediation.parameters["target_version"] == "2.0.0"
    assert remediation.parameters["prehook"] == prehook_id
    assert remediation.parameters["posthook"] == posthook_id
    assert remediation.parameters["instance"] is instance


async def test_upgrade_fallback_to_update_when_no_core_hook(
    uow, instance, prefect_manager_mock
):
    """When an ApplicationVersionChange is present but no upgrade core hook is defined,
    the strategy should fall back to UPDATE_INSTANCE."""
    update_flow_id = uuid4()
    update_helm_flow_id = uuid4()

    async def fake_get_user_action(application, hook, mode, version):
        return None  # No hooks defined

    async def fake_get_action(action):
        if action == PrefectAction.UPDATE_INSTANCE:
            return update_flow_id
        if action == PrefectAction.UPDATE_HELM_RELEASE:
            return update_helm_flow_id
        if action == PrefectAction.APPLY_UTILITY_RESOURCES:
            return uuid4()
        return None

    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(
        side_effect=fake_get_user_action
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(
        side_effect=fake_get_action
    )

    diff = InstanceUpdate(
        instance=instance,
        diffs=[ApplicationVersionChange.create("1.0.0", "2.0.0")],
    )

    strategy = InstanceUpdateStrategy(uow=uow)
    remediation = await strategy.execute(diff)

    assert remediation is not None
    assert remediation.type == RemediationType.UPDATE_INSTANCE
    assert remediation.flow_id == update_flow_id
    assert remediation.parameters["update_flow"] == update_helm_flow_id


async def test_update_with_context_change_only(uow, instance, prefect_manager_mock):
    """When only a ContextChange is present (no version change),
    the strategy should return UPDATE_INSTANCE without looking up upgrade hooks."""
    update_flow_id = uuid4()
    update_helm_flow_id = uuid4()

    async def fake_get_action(action):
        if action == PrefectAction.UPDATE_INSTANCE:
            return update_flow_id
        if action == PrefectAction.UPDATE_HELM_RELEASE:
            return update_helm_flow_id
        if action == PrefectAction.APPLY_UTILITY_RESOURCES:
            return uuid4()
        return None

    prefect_manager_mock.get_action_deployment_id = AsyncMock(
        side_effect=fake_get_action
    )
    # Should NOT be called since there's no version change
    prefect_manager_mock.get_user_action_deployment_id = AsyncMock()

    diff = InstanceUpdate(
        instance=instance,
        diffs=[ContextChange.create({"old": "config"}, {"new": "config"})],
    )

    strategy = InstanceUpdateStrategy(uow=uow)
    remediation = await strategy.execute(diff)

    assert remediation is not None
    assert remediation.type == RemediationType.UPDATE_INSTANCE
    assert remediation.flow_id == update_flow_id
    prefect_manager_mock.get_user_action_deployment_id.assert_not_called()


async def test_upgrade_without_pre_post_hooks(uow, instance, prefect_manager_mock):
    """When an upgrade core hook is defined but no pre/post hooks,
    prehook and posthook should be None in the parameters."""
    upgrade_hook_id = uuid4()
    upgrade_flow_id = uuid4()
    update_helm_flow_id = uuid4()

    async def fake_get_user_action(application, hook, mode, version):
        if hook == HookKind.UPGRADE and mode == "core":
            return upgrade_hook_id
        return None  # No pre/post hooks

    async def fake_get_action(action):
        if action == PrefectAction.UPGRADE_INSTANCE:
            return upgrade_flow_id
        if action == PrefectAction.UPDATE_HELM_RELEASE:
            return update_helm_flow_id
        if action == PrefectAction.APPLY_UTILITY_RESOURCES:
            return uuid4()
        return None

    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(
        side_effect=fake_get_user_action
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(
        side_effect=fake_get_action
    )

    diff = InstanceUpdate(
        instance=instance,
        diffs=[ApplicationVersionChange.create("1.0.0", "2.0.0")],
    )

    strategy = InstanceUpdateStrategy(uow=uow)
    remediation = await strategy.execute(diff)

    assert remediation is not None
    assert remediation.type == RemediationType.UPGRADE_INSTANCE
    assert remediation.parameters["prehook"] is None
    assert remediation.parameters["posthook"] is None
    assert remediation.parameters["upgrade_hook"] == upgrade_hook_id


async def test_update_with_driver_version_change(uow, instance, prefect_manager_mock):
    """An ApplicationDriverVersionChange without ApplicationVersionChange
    should produce a regular UPDATE_INSTANCE remediation."""
    update_flow_id = uuid4()
    update_helm_flow_id = uuid4()

    async def fake_get_action(action):
        if action == PrefectAction.UPDATE_INSTANCE:
            return update_flow_id
        if action == PrefectAction.UPDATE_HELM_RELEASE:
            return update_helm_flow_id
        if action == PrefectAction.APPLY_UTILITY_RESOURCES:
            return uuid4()
        return None

    prefect_manager_mock.get_action_deployment_id = AsyncMock(
        side_effect=fake_get_action
    )
    prefect_manager_mock.get_user_action_deployment_id = AsyncMock()

    diff = InstanceUpdate(
        instance=instance,
        diffs=[ApplicationDriverVersionChange.create(uuid4(), uuid4())],
    )

    strategy = InstanceUpdateStrategy(uow=uow)
    remediation = await strategy.execute(diff)

    assert remediation is not None
    assert remediation.type == RemediationType.UPDATE_INSTANCE
    prefect_manager_mock.get_user_action_deployment_id.assert_not_called()
