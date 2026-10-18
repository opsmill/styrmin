"""User actions are registered per driver version, never overwritten.

Companion to ``test_git_source_commit_pinning.py`` (issue #375). Pinning
the commit on the pull step is only half the story: Prefect upserts
deployments on ``(flow, name)``, so a driver reloaded at a newer commit
used to replace the earlier version's deployment — tags, pull step and
all — under the shared ``User Action: <name>`` name, and so did another
driver declaring the same action (#373). The application and the
fingerprint now name the deployment, and lookups take the newest match so
a commit-pinned re-registration outranks a pre-existing branch-tip one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from prefect.client.schemas.sorting import DeploymentSort

from styrmin_backend.services.driver.driver_directory import driver_directory_digest
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import (
    PrefectWorkPool,
    WorkflowDefinition,
    WorkPoolDefinition,
)


class _Workflow(WorkflowDefinition):
    """Minimal concrete definition; ``save`` is what we observe."""

    def get_function(self):  # pragma: no cover - never called here
        raise NotImplementedError


@pytest.fixture
def manager(mocker) -> PrefectManager:
    manager = PrefectManager.__new__(PrefectManager)
    manager.catalogue = mocker.Mock()
    manager.catalogue.get_work_pool.return_value = WorkPoolDefinition(
        name=PrefectWorkPool.USER_WORK_POOL.value
    )
    return manager


@pytest.fixture
def client(mocker):
    client = mocker.Mock()
    client.create_flow_from_name = AsyncMock(return_value=uuid4())
    client.create_deployment = AsyncMock(return_value=uuid4())
    client.read_deployments = AsyncMock(return_value=[])
    context = mocker.MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("styrmin_backend.workflows.manager.get_client", return_value=context)
    return client


async def _register(
    manager: PrefectManager,
    fingerprint: str | None,
    application: str = "lab-driver-a",
    driver_directory: str | None = None,
) -> _Workflow:
    workflow = _Workflow(
        name="User Action: post_setup", module="actions", function="post_setup"
    )
    await manager.register_user_action(
        workflow=workflow,
        application=application,
        version=">=1.0.0",
        hook=HookKind.SETUP,
        mode="post",
        fingerprint=fingerprint,
        driver_directory=driver_directory,
    )
    return workflow


async def test_two_driver_versions_register_distinct_deployments(
    manager: PrefectManager, client
) -> None:
    """Same action, two fingerprints → two deployment names under one flow."""
    await _register(manager, fingerprint="555d155")
    await _register(manager, fingerprint="a1b2c3d")

    names = [c.kwargs["name"] for c in client.create_deployment.await_args_list]
    assert names == [
        "User Action: post_setup (lab-driver-a@555d155)",
        "User Action: post_setup (lab-driver-a@a1b2c3d)",
    ]
    flows = [c.args for c in client.create_flow_from_name.await_args_list]
    assert flows == [("User Action: post_setup",)] * 2

    tags = [c.kwargs["tags"] for c in client.create_deployment.await_args_list]
    assert "fingerprint/555d155" in tags[0]
    assert "fingerprint/a1b2c3d" in tags[1]


async def test_two_drivers_register_distinct_deployments(
    manager: PrefectManager, client
) -> None:
    """Same action and short fingerprint, two drivers → two deployment names."""
    await _register(manager, fingerprint="555d155", application="lab-driver-a")
    await _register(manager, fingerprint="555d155", application="lab-driver-b")

    names = [c.kwargs["name"] for c in client.create_deployment.await_args_list]
    assert names == [
        "User Action: post_setup (lab-driver-a@555d155)",
        "User Action: post_setup (lab-driver-b@555d155)",
    ]


async def test_legacy_registration_without_fingerprint_is_named_per_driver(
    manager: PrefectManager, client
) -> None:
    await _register(manager, fingerprint=None)

    assert client.create_deployment.await_args.kwargs["name"] == (
        "User Action: post_setup (lab-driver-a)"
    )
    assert not any(
        tag.startswith("fingerprint/")
        for tag in client.create_deployment.await_args.kwargs["tags"]
    )


async def test_lookup_prefers_the_newest_matching_deployment(
    manager: PrefectManager, client, mocker
) -> None:
    """Newest first, so a pinned re-registration beats a branch-tip leftover."""
    newest = mocker.Mock(id=uuid4(), tags=[])
    client.read_deployments.return_value = [newest, mocker.Mock(id=uuid4(), tags=[])]

    found = await manager.get_user_action_deployment_id(
        application="lab-driver-a",
        version=">=1.0.0",
        hook=HookKind.SETUP,
        mode="post",
        fingerprint="555d155",
        driver_directory=None,
    )

    assert found == newest.id
    call = client.read_deployments.await_args
    assert call.kwargs["sort"] == DeploymentSort.CREATED_DESC
    assert set(call.kwargs["deployment_filter"].tags.all_) == {
        "application/lab-driver-a",
        "hook/setup",
        "mode/post",
        "version/>=1.0.0",
        "fingerprint/555d155",
    }


async def test_lookup_returns_none_when_nothing_matches(
    manager: PrefectManager, client
) -> None:
    assert (
        await manager.get_user_action_deployment_id(
            application="lab-driver-a",
            version=">=1.0.0",
            hook=HookKind.SETUP,
            mode="post",
            fingerprint="555d155",
            driver_directory=None,
        )
        is None
    )


# ---------------------------------------------------------------------------
# Driver directory (spec 028, research R-003)
# ---------------------------------------------------------------------------


async def test_registration_with_driver_directory_is_tagged_and_named(
    manager: PrefectManager, client
) -> None:
    await _register(manager, fingerprint="555d155", driver_directory="drivers/a")

    kwargs = client.create_deployment.await_args.kwargs
    assert "directory/drivers/a" in kwargs["tags"]
    assert kwargs["name"] == (
        f"User Action: post_setup (lab-driver-a@555d155 "
        f"{driver_directory_digest('drivers/a')})"
    )
    assert kwargs["name"].endswith("@555d155 99a4d0ee170e)")


async def test_registration_with_driver_directory_and_no_fingerprint(
    manager: PrefectManager, client
) -> None:
    await _register(manager, fingerprint=None, driver_directory="drivers/a")

    assert client.create_deployment.await_args.kwargs["name"] == (
        "User Action: post_setup (lab-driver-a 99a4d0ee170e)"
    )


async def test_two_driver_directories_at_one_commit_register_distinct_deployments(
    manager: PrefectManager, client
) -> None:
    """US1-6: same driver name and commit, two driver directories."""
    await _register(manager, fingerprint="555d155", driver_directory="drivers/a")
    await _register(manager, fingerprint="555d155", driver_directory="drivers/b")

    calls = client.create_deployment.await_args_list
    names = [c.kwargs["name"] for c in calls]
    assert len(set(names)) == 2, names
    assert "directory/drivers/a" in calls[0].kwargs["tags"]
    assert "directory/drivers/b" in calls[1].kwargs["tags"]


async def test_registration_without_driver_directory_has_no_directory_tag(
    manager: PrefectManager, client
) -> None:
    """US4-3: a root registration keeps its name and its five tags."""
    await _register(manager, fingerprint="555d155")

    kwargs = client.create_deployment.await_args.kwargs
    assert kwargs["name"] == "User Action: post_setup (lab-driver-a@555d155)"
    assert len(kwargs["tags"]) == 5, kwargs["tags"]
    assert set(kwargs["tags"]) == {
        "application/lab-driver-a",
        "version/>=1.0.0",
        "hook/setup",
        "mode/post",
        "fingerprint/555d155",
    }


async def test_lookup_with_driver_directory_filters_on_its_tag(
    manager: PrefectManager, client, mocker
) -> None:
    match = mocker.Mock(id=uuid4(), tags=["directory/drivers/a"])
    client.read_deployments.return_value = [match]

    found = await manager.get_user_action_deployment_id(
        application="lab-driver-a",
        version=">=1.0.0",
        hook=HookKind.SETUP,
        mode="post",
        fingerprint="555d155",
        driver_directory="drivers/a",
    )

    assert found == match.id
    tags = client.read_deployments.await_args.kwargs["deployment_filter"].tags.all_
    assert "directory/drivers/a" in tags


async def test_lookup_without_driver_directory_skips_driver_directory_deployments(
    manager: PrefectManager, client, mocker
) -> None:
    """A root driver version never runs another driver directory's action."""
    newer_tagged = mocker.Mock(id=uuid4(), tags=["directory/drivers/a"])
    older_root = mocker.Mock(id=uuid4(), tags=["application/lab-driver-a"])
    client.read_deployments.return_value = [newer_tagged, older_root]

    found = await manager.get_user_action_deployment_id(
        application="lab-driver-a",
        version=">=1.0.0",
        hook=HookKind.SETUP,
        mode="post",
        fingerprint="555d155",
        driver_directory=None,
    )

    assert found == older_root.id
    tags = client.read_deployments.await_args.kwargs["deployment_filter"].tags.all_
    assert not any(tag.startswith("directory/") for tag in tags)


async def test_lookup_without_driver_directory_returns_none_when_only_tagged_match(
    manager: PrefectManager, client, mocker
) -> None:
    client.read_deployments.return_value = [
        mocker.Mock(id=uuid4(), tags=["directory/drivers/a"])
    ]

    assert (
        await manager.get_user_action_deployment_id(
            application="lab-driver-a",
            version=">=1.0.0",
            hook=HookKind.SETUP,
            mode="post",
            fingerprint="555d155",
            driver_directory=None,
        )
        is None
    )
