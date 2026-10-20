"""Action registration when a driver is loaded (spec 029, FR-001, FR-002, FR-006).

The loads run against a real (in-memory SQLite) ``SqlModelUnitOfWork`` and a
fake ``PrefectManager`` that records each registration and answers the hook
lookups from them, so the tests check which actions a load registers, under
which driver directory and provenance fingerprint, and that a refused load
registers nothing and stores no driver version.
"""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from fast_depends import dependency_provider
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.db.models import ApplicationDriverVersion
from styrmin_backend.services.applications import (
    LoadedDriverVersion,
    ensure_action_registrations,
    load_application_driver_from_local_directory,
    load_application_driver_from_object,
)
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.exceptions import ServiceError
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import (
    GitSourceWorkflowDefinition,
    LocalDriverActionWorkflowDefinition,
    WorkflowDefinition,
)

_EXAMPLES = Path(__file__).resolve().parents[4] / "driver" / "examples"

type Mode = Literal["pre", "core", "post"]


@dataclass(frozen=True)
class _Registration:
    workflow: WorkflowDefinition
    application: str
    version: str
    hook: HookKind
    mode: Mode
    fingerprint: str | None
    driver_directory: str | None
    flow_id: UUID


class FakePrefectManager(PrefectManager):
    """Records registrations and answers lookups from them, with the key of ADR-080."""

    def __init__(self) -> None:  # noqa: D107 — no catalogue or executor is needed
        self.registrations: list[_Registration] = []
        self.tokens: list[tuple[str, str]] = []

    async def register_token(self, namespace: str, token: str) -> None:
        self.tokens.append((namespace, token))

    async def register_user_action(
        self,
        workflow: WorkflowDefinition,
        application: str,
        version: str,
        hook: HookKind,
        mode: Mode,
        fingerprint: str | None = None,
        *,
        driver_directory: str | None,
    ) -> None:
        self.registrations.append(
            _Registration(
                workflow=workflow,
                application=application,
                version=version,
                hook=hook,
                mode=mode,
                fingerprint=fingerprint,
                driver_directory=driver_directory,
                flow_id=uuid4(),
            )
        )

    async def get_user_action_deployment_id(
        self,
        application: str,
        version: str,
        hook: HookKind,
        mode: Mode,
        fingerprint: str | None = None,
        *,
        driver_directory: str | None,
    ) -> UUID | None:
        for registration in reversed(self.registrations):
            if (
                registration.application,
                registration.version,
                registration.hook,
                registration.mode,
                registration.fingerprint,
                registration.driver_directory,
            ) == (application, version, hook, mode, fingerprint, driver_directory):
                return registration.flow_id
        return None


@pytest.fixture
def prefect_manager() -> Iterator[FakePrefectManager]:
    manager = FakePrefectManager()

    def _get_fake_manager(catalogue=None, workflow_executor=None):  # noqa: ARG001
        return manager

    dependency_provider.override(get_manager.__wrapped__, _get_fake_manager)
    yield manager
    dependency_provider.clear()


@pytest.fixture
async def db_session():
    """In-memory SQLite session with StaticPool (single connection)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest.fixture
def uow(db_session: AsyncSession) -> SqlModelUnitOfWork:
    return SqlModelUnitOfWork(session=db_session)


def _copy_driver(name: str, destination: Path) -> Path:
    """Copy the bundled driver ``name`` to ``destination``, so a test may edit it."""
    shutil.copytree(_EXAMPLES / name, destination)
    return destination


_COMMIT_SHA = "c" * 40


def _as_git_driver(path: Path) -> ApplicationDriver:
    """Load the driver at ``path`` as if it came from the driver directory of a git repository."""
    local = get_local_driver_loader(path=str(path)).load_driver()
    return dataclasses.replace(
        local,
        source=GitSource(
            repository="https://example.com/drivers.git",
            branch="main",
            token="git-token",
            driver_directory="drivers/semaphore",
        ),
        content_hash=None,
        source_commit_sha=_COMMIT_SHA,
    )


async def _stored_versions(session: AsyncSession) -> list[ApplicationDriverVersion]:
    return list((await session.exec(select(ApplicationDriverVersion))).all())


def _registered_actions(manager: FakePrefectManager) -> set[tuple[str, str, str]]:
    """The registered actions, as ``(entrypoint function, hook, mode)``."""
    return {(r.workflow.function, r.hook.value, r.mode) for r in manager.registrations}


def _content_hash_of(loaded: LoadedDriverVersion) -> str:
    content_hash = loaded.version.content_hash
    assert content_hash is not None
    return content_hash


SEMAPHORE_ACTIONS = {
    ("pre_setup", "setup", "pre"),
    ("post_setup", "setup", "post"),
    ("upgrade", "upgrade", "core"),
}


async def test_new_local_version_registers_its_three_actions_at_its_path(
    tmp_path: Path,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    path = _copy_driver("semaphore", tmp_path / "semaphore")

    loaded = await load_application_driver_from_local_directory(path=str(path), uow=uow)

    content_hash = loaded.version.content_hash
    assert content_hash is not None
    assert _registered_actions(prefect_manager) == SEMAPHORE_ACTIONS
    for registration in prefect_manager.registrations:
        assert registration.application == "semaphore"
        assert registration.version == ">=2.15,<2.17"
        assert registration.driver_directory == str(path)
        assert registration.fingerprint == content_hash[:7]
        assert isinstance(registration.workflow, LocalDriverActionWorkflowDefinition)
        assert registration.workflow.directory == str(path)
        assert registration.workflow.content_hash == content_hash
    # A local driver version's actions run from its path: no git token is saved.
    assert prefect_manager.tokens == []


async def test_new_git_version_registers_its_token_and_its_actions(
    tmp_path: Path,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    driver_object = _as_git_driver(path)

    await load_application_driver_from_object(driver_object=driver_object, uow=uow)

    assert prefect_manager.tokens == [("user", "git-token")]
    assert _registered_actions(prefect_manager) == SEMAPHORE_ACTIONS
    for registration in prefect_manager.registrations:
        assert registration.driver_directory == "drivers/semaphore"
        assert registration.fingerprint == _COMMIT_SHA[:7]
        assert isinstance(registration.workflow, GitSourceWorkflowDefinition)
        assert registration.workflow.commit_sha == _COMMIT_SHA


async def test_local_path_with_a_brace_is_refused_for_a_driver_with_actions(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    path = _copy_driver("semaphore", tmp_path / "semaphore-{{ env }}")

    with pytest.raises(DriverLoadingError) as exc_info:
        await load_application_driver_from_local_directory(path=str(path), uow=uow)

    message = str(exc_info.value)
    assert str(path) in message
    assert "'{' or '}'" in message
    assert prefect_manager.registrations == []
    assert await _stored_versions(db_session) == []


async def test_local_path_with_a_brace_is_accepted_for_a_driver_without_actions(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    path = _copy_driver("generic-app", tmp_path / "generic-app-{x}")

    loaded = await load_application_driver_from_local_directory(path=str(path), uow=uow)

    assert loaded.version.source_path == str(path)
    assert [v.id for v in await _stored_versions(db_session)] == [loaded.version.id]
    assert prefect_manager.registrations == []


async def test_relative_local_path_is_refused_for_a_driver_with_actions(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent runs each action from a temporary folder, where a relative path leads nowhere (#372 review)."""
    _copy_driver("semaphore", tmp_path / "semaphore")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(DriverLoadingError) as exc_info:
        await load_application_driver_from_local_directory(path="semaphore", uow=uow)

    assert str(exc_info.value) == (
        "Driver path 'semaphore' is refused: it is a relative path, and the driver "
        "declares actions. The Styrmin agent runs each action from a temporary "
        "working folder, where a relative path does not lead to the driver. Load the "
        "driver from an absolute path, such as /styrmin/drivers/semaphore."
    )
    assert prefect_manager.registrations == []
    assert await _stored_versions(db_session) == []


async def test_relative_local_path_is_accepted_for_a_driver_without_actions(
    tmp_path: Path,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copy_driver("generic-app", tmp_path / "generic-app")
    monkeypatch.chdir(tmp_path)

    loaded = await load_application_driver_from_local_directory(
        path="generic-app", uow=uow
    )

    assert loaded.version.source_path == "generic-app"
    assert prefect_manager.registrations == []


def _move_upgrade_location(path: Path, location: str) -> None:
    spec_file = path / "driver.styrmin.yml"
    spec = spec_file.read_text()
    assert 'location: "actions.py::upgrade"' in spec
    spec_file.write_text(
        spec.replace('location: "actions.py::upgrade"', f'location: "{location}"')
    )


async def test_local_action_located_outside_the_actions_file_is_refused(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    """The check before each action hashes only actions.py of the driver's code (#372 review)."""
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    _move_upgrade_location(path, "helpers.py::upgrade")

    with pytest.raises(DriverLoadingError) as exc_info:
        await load_application_driver_from_local_directory(path=str(path), uow=uow)

    assert str(exc_info.value) == (
        f"Action upgrade of the driver loaded from '{path}' is refused: its location "
        "helpers.py::upgrade is not in actions.py. Before an action of a driver "
        "loaded from a local directory runs, Styrmin checks only the driver "
        "specification, the values template and actions.py, so the code of another "
        "file could change without the check noticing. Move the function to "
        "actions.py, set the location to actions.py::upgrade, and load the driver "
        "again."
    )
    assert prefect_manager.registrations == []
    assert await _stored_versions(db_session) == []


async def test_git_action_located_outside_the_actions_file_is_registered(
    tmp_path: Path,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    """A git driver version's flow clones the commit it was loaded at, so any file of it is pinned."""
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    _move_upgrade_location(path, "helpers.py::upgrade")

    await load_application_driver_from_object(
        driver_object=_as_git_driver(path), uow=uow
    )

    assert ("upgrade", "upgrade", "core") in _registered_actions(prefect_manager)


@pytest.mark.parametrize("source_type", ["local", "git"])
async def test_two_actions_for_one_hook_and_mode_are_refused(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
    source_type: str,
) -> None:
    """They share one registration key, so only one of them would run (#372 review)."""
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    spec_file = path / "driver.styrmin.yml"
    spec_file.write_text(
        spec_file.read_text().replace(
            "    - name: post_setup\n      hook: setup\n      mode: post",
            "    - name: post_setup\n      hook: setup\n      mode: pre",
        )
    )

    with pytest.raises(DriverLoadingError) as exc_info:
        if source_type == "local":
            await load_application_driver_from_local_directory(path=str(path), uow=uow)
        else:
            await load_application_driver_from_object(
                driver_object=_as_git_driver(path), uow=uow
            )

    assert str(exc_info.value) == (
        "Driver semaphore declares 2 actions for the setup hook, mode pre: "
        "pre_setup, post_setup. Styrmin runs one action for each hook and mode. Keep "
        "one of them, or call the others from it, then load the driver again."
    )
    assert prefect_manager.registrations == []
    assert await _stored_versions(db_session) == []


@pytest.mark.parametrize("source_type", ["local", "git"])
async def test_load_refused_by_service_validation_registers_nothing(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
    source_type: str,
) -> None:
    """Critique E3: the load registers its actions only after the checks of the driver."""
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    spec_file = path / "driver.styrmin.yml"
    spec_file.write_text(
        spec_file.read_text().replace("component: server", "component: missing")
    )
    driver_object = (
        get_local_driver_loader(path=str(path)).load_driver()
        if source_type == "local"
        else _as_git_driver(path)
    )

    with pytest.raises(ServiceError, match="references undeclared component"):
        await load_application_driver_from_object(driver_object=driver_object, uow=uow)

    assert prefect_manager.registrations == []
    assert prefect_manager.tokens == []
    assert await _stored_versions(db_session) == []


async def test_pair_whose_lookup_finds_a_flow_is_not_registered_again(
    tmp_path: Path,
    prefect_manager: FakePrefectManager,
) -> None:
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    driver_object = get_local_driver_loader(path=str(path)).load_driver()
    assert driver_object.content_hash is not None
    fingerprint = driver_object.content_hash[:7]
    # The setup/pre action of this driver version is already registered.
    await prefect_manager.register_user_action(
        workflow=LocalDriverActionWorkflowDefinition(
            name="User Action: pre_setup",
            module="actions.py",
            function="pre_setup",
            directory=str(path),
            content_hash=driver_object.content_hash,
            spec_file="driver.styrmin.yml",
            values_template="values.j2.yml",
            actions_file="actions.py",
        ),
        application="semaphore",
        version=">=2.15,<2.17",
        hook=HookKind.SETUP,
        mode="pre",
        fingerprint=fingerprint,
        driver_directory=str(path),
    )

    registered = await ensure_action_registrations(driver_object, prefect_manager)

    assert registered == 2
    assert _registered_actions(prefect_manager) == SEMAPHORE_ACTIONS
    assert [r.workflow.function for r in prefect_manager.registrations].count(
        "pre_setup"
    ) == 1


async def test_loading_a_stored_version_again_registers_nothing_when_every_pair_resolves(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
) -> None:
    """FR-006: a repeated load makes no Prefect write when hooks find every action."""
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    first = await load_application_driver_from_local_directory(path=str(path), uow=uow)
    registrations = list(prefect_manager.registrations)

    again = await load_application_driver_from_local_directory(path=str(path), uow=uow)

    assert again.version.id == first.version.id
    assert prefect_manager.registrations == registrations
    assert [v.id for v in await _stored_versions(db_session)] == [first.version.id]


@pytest.mark.parametrize(
    "stale_info",
    [False, True],
    ids=["stored-version", "stored-version-with-stale-info"],
)
async def test_loading_a_stored_version_again_registers_the_actions_of_a_missing_pair(
    tmp_path: Path,
    db_session: AsyncSession,
    uow: SqlModelUnitOfWork,
    prefect_manager: FakePrefectManager,
    stale_info: bool,
) -> None:
    """FR-006: only the actions of the hook and mode without a registered flow are registered.

    Both returns of the stored-version path register: the plain return, and
    the one that first fills the info columns of an older row.
    """
    path = _copy_driver("semaphore", tmp_path / "semaphore")
    first = await load_application_driver_from_local_directory(path=str(path), uow=uow)
    if stale_info:
        stored = await db_session.get(ApplicationDriverVersion, first.version.id)
        assert stored is not None
        stored.description = None
        await db_session.commit()
    # The Prefect deployment of the upgrade/core action was deleted.
    prefect_manager.registrations = [
        r
        for r in prefect_manager.registrations
        if (r.hook, r.mode) != (HookKind.UPGRADE, "core")
    ]
    kept = list(prefect_manager.registrations)

    again = await load_application_driver_from_local_directory(path=str(path), uow=uow)

    assert again.version.id == first.version.id
    assert prefect_manager.registrations[: len(kept)] == kept
    new = prefect_manager.registrations[len(kept) :]
    assert [(r.workflow.function, r.hook.value, r.mode) for r in new] == [
        ("upgrade", "upgrade", "core")
    ]
    assert _content_hash_of(again) == _content_hash_of(first)
    assert new[0].driver_directory == str(path)
    assert new[0].fingerprint == _content_hash_of(first)[:7]
    assert [v.id for v in await _stored_versions(db_session)] == [first.version.id]
    if stale_info:
        assert again.version.description is not None
