"""Unit tests for the create, upgrade and update remediations.

Spec 029 — the create and upgrade remediations run the hooks that the driver
version declares (``Action`` rows) through hook resolution: a declared action
without a registered flow raises ``ActionNotRegisteredError`` instead of
skipping its hook, and an upgrade falls back to an update only when the
driver version declares no ``upgrade``/``core`` action.
"""

from typing import Literal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fast_depends import dependency_provider

from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.db.models import (
    Action,
    ApplicationDriver,
    ApplicationDriverVersion,
)
from styrmin_backend.domain.models import Instance, InstanceStatus
from styrmin_backend.services.driver.exceptions import ActionNotRegisteredError
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.reconciliation.diffs.diffs import (
    ApplicationDriverVersionChange,
    ApplicationVersionChange,
    ContextChange,
    InstanceCreation,
    InstanceUpdate,
)
from styrmin_backend.services.reconciliation.remediation import (
    InstanceCreationStrategy,
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

type HookPair = tuple[HookKind, Literal["pre", "core", "post"]]

SETUP_ACTIONS: tuple[HookPair, ...] = (
    (HookKind.SETUP, "pre"),
    (HookKind.SETUP, "post"),
)
UPGRADE_ACTIONS: tuple[HookPair, ...] = (
    (HookKind.UPGRADE, "core"),
    (HookKind.UPGRADE, "pre"),
    (HookKind.UPGRADE, "post"),
)
LOCAL_PATH = "/srv/drivers/simple-app"
CONTENT_HASH = "0a7d3f1" + "e" * 57
COMMIT_SHA = "9b1e2c4" + "f" * 33


def declare_actions(
    uow: FakeUnitOfWork,
    driver_version: ApplicationDriverVersion,
    *pairs: HookPair,
) -> None:
    """Store one declared action of ``driver_version`` for each hook and mode, as a load does."""
    for hook, mode in pairs:
        uow.actions.models.append(
            Action(
                name=f"{hook.value}-{mode}",
                description=f"The {hook.value} {mode} action",
                location=f"actions/{hook.value}_{mode}.py",
                hook=hook.value,
                mode=mode,
                application_driver_version_id=driver_version.id,
            )
        )


def built_in_flow_lookups(prefect_manager_mock) -> list[PrefectAction]:
    """Return the built-in flows the remediation looked up, in order."""
    return [
        call.kwargs["action"]
        for call in prefect_manager_mock.get_action_deployment_id.await_args_list
    ]


# ---- Fixtures ----


@pytest.fixture
def prefect_manager_mock(mocker):
    manager_mock = mocker.Mock(spec=PrefectManager)

    def get_fake_manager(catalogue=None, workflow_executor=None) -> PrefectManager:
        return manager_mock

    dependency_provider.override(get_manager.__wrapped__, get_fake_manager)
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
    uow, instance, driver_version, prefect_manager_mock
):
    """When an ApplicationVersionChange is present and the driver defines an upgrade core hook,
    the strategy should return an UPGRADE_INSTANCE remediation."""
    declare_actions(uow, driver_version, *UPGRADE_ACTIONS)
    upgrade_hook_id = uuid4()
    upgrade_flow_id = uuid4()
    update_helm_flow_id = uuid4()
    prehook_id = uuid4()
    posthook_id = uuid4()

    async def fake_get_user_action(  # noqa: ARG001 — spec 013/028 disambiguators, mock-irrelevant here
        application, hook, mode, version, fingerprint=None, driver_directory=None
    ):
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
    assert remediation.parameters["target_version"] == "2.0.0"
    assert remediation.parameters["prehook"] == prehook_id
    assert remediation.parameters["posthook"] == posthook_id
    assert remediation.parameters["instance"] is instance


@pytest.mark.parametrize(
    "declared",
    [
        (),
        SETUP_ACTIONS,
        ((HookKind.UPGRADE, "pre"), (HookKind.UPGRADE, "post")),
    ],
    ids=["no-action", "setup-actions-only", "upgrade-pre-post-without-core"],
)
async def test_upgrade_falls_back_to_update_when_no_upgrade_core_action_is_declared(
    uow,
    instance,
    driver_version,
    prefect_manager_mock,
    declared: tuple[HookPair, ...],
):
    """A version change to a driver version that declares no ``upgrade``/``core`` action runs as an update.

    No upgrade action runs, also when the driver version declares
    ``upgrade``/``pre`` or ``upgrade``/``post`` (research R-012), and also
    when a flow would be found for every hook: what the driver version
    declares decides, not what is registered.
    """
    declare_actions(uow, driver_version, *declared)
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

    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(return_value=uuid4())
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
    assert "upgrade_hook" not in remediation.parameters


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


async def test_upgrade_without_pre_post_hooks(
    uow, instance, driver_version, prefect_manager_mock
):
    """When an upgrade core hook is defined but no pre/post hooks,
    prehook and posthook should be None in the parameters."""
    declare_actions(uow, driver_version, (HookKind.UPGRADE, "core"))
    upgrade_hook_id = uuid4()
    upgrade_flow_id = uuid4()
    update_helm_flow_id = uuid4()

    async def fake_get_user_action(  # noqa: ARG001 — spec 013/028 disambiguators, mock-irrelevant here
        application, hook, mode, version, fingerprint=None, driver_directory=None
    ):
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


# ---- Driver directory (spec 028, spec 029) ----


@pytest.mark.parametrize(
    ("source_type", "source_path", "expected"),
    [
        ("git", "drivers/a", "drivers/a"),
        ("git", None, None),
        ("local", LOCAL_PATH, LOCAL_PATH),
    ],
    ids=["git-driver-directory", "git-root", "local-path"],
)
async def test_every_user_action_lookup_receives_the_driver_directory(
    uow,
    instance,
    driver_version,
    prefect_manager_mock,
    source_type: str,
    source_path: str | None,
    expected: str | None,
):
    """Create ``pre``/``post`` and upgrade ``core``/``pre``/``post`` lookups.

    A git driver version's ``source_path`` is its driver directory. A local
    driver version's is the path it was loaded from, under which the load
    registers its actions (spec 029), so the lookups find those flows.
    """
    driver_version.source_type = source_type
    driver_version.source_path = source_path
    declare_actions(uow, driver_version, *SETUP_ACTIONS, *UPGRADE_ACTIONS)
    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(return_value=uuid4())
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    await InstanceCreationStrategy(uow=uow).execute(InstanceCreation(instance=instance))
    await InstanceUpdateStrategy(uow=uow).execute(
        InstanceUpdate(
            instance=instance,
            diffs=[ApplicationVersionChange.create("1.0.0", "2.0.0")],
        )
    )

    calls = prefect_manager_mock.get_user_action_deployment_id.await_args_list
    assert sorted((c.kwargs["hook"].value, c.kwargs["mode"]) for c in calls) == [
        ("setup", "post"),
        ("setup", "pre"),
        ("upgrade", "core"),
        ("upgrade", "post"),
        ("upgrade", "pre"),
    ]
    assert [c.kwargs["driver_directory"] for c in calls] == [expected] * 5


# ---- Declared actions without a registered flow (spec 029, FR-005) ----


async def test_create_raises_when_the_declared_setup_pre_action_is_not_registered(
    uow, instance, driver_version, prefect_manager_mock
):
    """A create whose ``setup``/``pre`` action has no registered flow raises instead of skipping the hook.

    The error names the hook step that cannot run, and its message tells the
    user how to register the action (contracts/errors.md, "Must contain").
    """
    driver_version.source_type = "local"
    driver_version.source_path = LOCAL_PATH
    driver_version.content_hash = CONTENT_HASH
    declare_actions(uow, driver_version, *SETUP_ACTIONS)

    async def fake_get_user_action(  # noqa: ARG001 — spec 013/028 disambiguators, mock-irrelevant here
        application, hook, mode, version, fingerprint=None, driver_directory=None
    ):
        # Only the ``setup``/``post`` action has a registered flow.
        return uuid4() if (hook, mode) == (HookKind.SETUP, "post") else None

    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(
        side_effect=fake_get_user_action
    )
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    with pytest.raises(ActionNotRegisteredError) as exc_info:
        await InstanceCreationStrategy(uow=uow).execute(
            InstanceCreation(instance=instance)
        )

    error = exc_info.value
    assert (error.hook, error.mode) == (HookKind.SETUP, "pre")
    message = str(error)
    for part in (
        "test_app",
        "1.0.0@0a7d3f1",
        "setup-pre",
        "setup hook",
        "mode pre",
        "Load the driver again",
        f"styrminctl drivers load-local-version {LOCAL_PATH}",
        "request the change again",
    ):
        assert part in message, part


async def test_upgrade_raises_and_does_not_fall_back_when_the_declared_upgrade_core_action_is_not_registered(
    uow, instance, driver_version, prefect_manager_mock
):
    """An upgrade whose ``upgrade``/``core`` action has no registered flow raises.

    It does not run as an update instead: the update flow is never looked up.
    """
    driver_version.source_commit_sha = COMMIT_SHA
    declare_actions(uow, driver_version, *UPGRADE_ACTIONS)
    prefect_manager_mock.get_user_action_deployment_id = AsyncMock(return_value=None)
    prefect_manager_mock.get_action_deployment_id = AsyncMock(return_value=uuid4())

    with pytest.raises(ActionNotRegisteredError) as exc_info:
        await InstanceUpdateStrategy(uow=uow).execute(
            InstanceUpdate(
                instance=instance,
                diffs=[ApplicationVersionChange.create("1.0.0", "2.0.0")],
            )
        )

    error = exc_info.value
    assert (error.hook, error.mode) == (HookKind.UPGRADE, "core")
    message = str(error)
    for part in (
        "test_app",
        "1.0.0@9b1e2c4",
        "upgrade-core",
        "upgrade hook",
        "mode core",
        "Load the driver again",
        "styrminctl drivers load-version https://github.com/test/repo main",
        "request the change again",
    ):
        assert part in message, part
    assert PrefectAction.UPDATE_INSTANCE not in built_in_flow_lookups(
        prefect_manager_mock
    )
