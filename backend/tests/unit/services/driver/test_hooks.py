"""Unit tests for hook resolution (spec 029, contracts/hook-resolution.md).

The truth table of ``resolve_hook_flow``: a hook and mode with no declared
action resolves to None without a lookup; a declared one resolves to its
registered flow; a declared one without a registered flow raises
``ActionNotRegisteredError``, whose message names every declared action of
the pair and the command that loads the driver again (FR-005).
"""

from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest

from styrmin_backend.db.models import Action, ApplicationDriverVersion
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.exceptions import ActionNotRegisteredError
from styrmin_backend.services.driver.hooks import (
    ActionRegistrationKey,
    UpgradeHookFlows,
    load_command_for,
    resolve_hook_flow,
    resolve_setup_hooks,
    resolve_upgrade_hooks,
)
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.driver.models.structure.source import GitSource

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_SIMPLE_APP = _REPOSITORY_ROOT / "driver" / "examples" / "simple-app"

DRIVER = "my-app"
SUPPORTED_VERSIONS = ">=1.0.0"
CONTENT_HASH = "0a7d3f1" + "e" * 57
COMMIT_SHA = "9b1e2c4" + "f" * 33
LOCAL_PATH = "/styrmin/drivers/my-app"
REPOSITORY = "https://github.com/opsmill/drivers"

Mode = Literal["pre", "core", "post"]


class FakePrefectManager:
    """Records each user action lookup and answers from the registered flows."""

    def __init__(self, registered: dict[tuple[HookKind, Mode], UUID] | None = None):
        self.registered = registered or {}
        self.lookups: list[dict] = []

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
        self.lookups.append(
            {
                "application": application,
                "version": version,
                "hook": hook,
                "mode": mode,
                "fingerprint": fingerprint,
                "driver_directory": driver_directory,
            }
        )
        return self.registered.get((hook, mode))

    def looked_up(self) -> set[tuple[HookKind, str]]:
        return {(lookup["hook"], lookup["mode"]) for lookup in self.lookups}


def _local_version() -> ApplicationDriverVersion:
    return ApplicationDriverVersion(
        version="1",
        application_supported_versions=SUPPORTED_VERSIONS,
        source_type="local",
        source_repository="",
        source_path=LOCAL_PATH,
        content_hash=CONTENT_HASH,
    )


def _git_version(driver_directory: str | None = None) -> ApplicationDriverVersion:
    return ApplicationDriverVersion(
        version="1",
        application_supported_versions=SUPPORTED_VERSIONS,
        source_type="git",
        source_repository=REPOSITORY,
        source_branch="main",
        source_path=driver_directory,
        source_commit_sha=COMMIT_SHA,
    )


async def _declare(
    uow, driver_version: ApplicationDriverVersion, *actions: tuple[str, str, str]
) -> None:
    """Store the ``(name, hook, mode)`` actions that ``driver_version`` declares."""
    for name, hook, mode in actions:
        await uow.actions.create(
            Action(
                name=name,
                description=name,
                location=f"actions.py::{name}",
                hook=hook,
                mode=mode,
                application_driver_version_id=driver_version.id,
            )
        )


# --- resolve_hook_flow: the truth table -----------------------------------


async def test_no_declared_action_resolves_to_none_without_a_lookup(uow) -> None:
    driver_version = _local_version()
    # Actions of another hook and mode, and of another driver version, do not count.
    await _declare(uow, driver_version, ("post_setup", "setup", "post"))
    await _declare(uow, _local_version(), ("pre_setup", "setup", "pre"))
    prefect_manager = FakePrefectManager()

    flow = await resolve_hook_flow(
        driver_version,
        DRIVER,
        HookKind.SETUP,
        "pre",
        uow=uow,
        prefect_manager=prefect_manager,
    )

    assert flow is None
    assert prefect_manager.lookups == []


async def test_declared_and_registered_action_resolves_to_its_flow(uow) -> None:
    driver_version = _local_version()
    await _declare(uow, driver_version, ("pre_setup", "setup", "pre"))
    flow_id = uuid4()
    prefect_manager = FakePrefectManager({(HookKind.SETUP, "pre"): flow_id})

    flow = await resolve_hook_flow(
        driver_version,
        DRIVER,
        HookKind.SETUP,
        "pre",
        uow=uow,
        prefect_manager=prefect_manager,
    )

    assert flow == flow_id


async def test_declared_action_without_a_flow_raises_naming_every_action_of_the_pair(
    uow,
) -> None:
    driver_version = _local_version()
    await _declare(
        uow,
        driver_version,
        ("warm_cache", "upgrade", "core"),
        ("migrate_schema", "upgrade", "core"),
        ("pre_upgrade", "upgrade", "pre"),
    )

    with pytest.raises(ActionNotRegisteredError) as raised:
        await resolve_hook_flow(
            driver_version,
            DRIVER,
            HookKind.UPGRADE,
            "core",
            uow=uow,
            prefect_manager=FakePrefectManager(),
        )

    error = raised.value
    message = str(error)
    assert error.hook is HookKind.UPGRADE
    assert error.mode == "core"
    assert error.actions == ["migrate_schema", "warm_cache"]
    for part in (
        DRIVER,
        "1@0a7d3f1",
        "migrate_schema",
        "warm_cache",
        "upgrade hook",
        "mode core",
        "Load the driver again",
        f"styrminctl drivers load-local-version {LOCAL_PATH}",
        "request the change again",
    ):
        assert part in message
    # An action of another mode of the hook is not named.
    assert "pre_upgrade" not in message


# --- resolve_setup_hooks ----------------------------------------------------


async def test_setup_hooks_resolve_pre_and_post(uow) -> None:
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("pre_setup", "setup", "pre"),
        ("post_setup", "setup", "post"),
    )
    pre_id, post_id = uuid4(), uuid4()
    prefect_manager = FakePrefectManager(
        {
            (HookKind.SETUP, "pre"): pre_id,
            (HookKind.SETUP, "post"): post_id,
        }
    )

    flows = await resolve_setup_hooks(
        driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
    )

    assert flows == (pre_id, post_id)


async def test_setup_hooks_skip_an_undeclared_mode(uow) -> None:
    driver_version = _git_version()
    await _declare(uow, driver_version, ("pre_setup", "setup", "pre"))
    pre_id = uuid4()
    prefect_manager = FakePrefectManager({(HookKind.SETUP, "pre"): pre_id})

    flows = await resolve_setup_hooks(
        driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
    )

    assert flows == (pre_id, None)
    assert prefect_manager.looked_up() == {(HookKind.SETUP, "pre")}


async def test_setup_hooks_raise_for_a_declared_post_action_without_a_flow(
    uow,
) -> None:
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("pre_setup", "setup", "pre"),
        ("post_setup", "setup", "post"),
    )
    prefect_manager = FakePrefectManager({(HookKind.SETUP, "pre"): uuid4()})

    with pytest.raises(ActionNotRegisteredError) as raised:
        await resolve_setup_hooks(
            driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
        )

    assert raised.value.hook is HookKind.SETUP
    assert raised.value.mode == "post"
    assert raised.value.actions == ["post_setup"]


async def test_setup_hooks_name_pre_first_when_both_modes_lack_a_flow(uow) -> None:
    """The failed hook step is the same on every run: ``pre`` before ``post``."""
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("pre_setup", "setup", "pre"),
        ("post_setup", "setup", "post"),
    )

    with pytest.raises(ActionNotRegisteredError) as raised:
        await resolve_setup_hooks(
            driver_version, DRIVER, uow=uow, prefect_manager=FakePrefectManager()
        )

    assert raised.value.mode == "pre"


# --- resolve_upgrade_hooks --------------------------------------------------


async def test_upgrade_hooks_are_none_without_a_declared_core_action(uow) -> None:
    """A version without ``upgrade``/``core`` is upgraded as a plain update (R-012)."""
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("pre_upgrade", "upgrade", "pre"),
        ("post_upgrade", "upgrade", "post"),
        ("pre_setup", "setup", "pre"),
    )
    prefect_manager = FakePrefectManager()

    flows = await resolve_upgrade_hooks(
        driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
    )

    assert flows is None
    assert prefect_manager.lookups == []


async def test_upgrade_hooks_resolve_core_pre_and_post(uow) -> None:
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("upgrade", "upgrade", "core"),
        ("pre_upgrade", "upgrade", "pre"),
        ("post_upgrade", "upgrade", "post"),
    )
    core_id, pre_id, post_id = uuid4(), uuid4(), uuid4()
    prefect_manager = FakePrefectManager(
        {
            (HookKind.UPGRADE, "core"): core_id,
            (HookKind.UPGRADE, "pre"): pre_id,
            (HookKind.UPGRADE, "post"): post_id,
        }
    )

    flows = await resolve_upgrade_hooks(
        driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
    )

    assert flows == UpgradeHookFlows(core=core_id, pre=pre_id, post=post_id)


async def test_upgrade_hooks_with_core_only_do_not_look_up_pre_or_post(uow) -> None:
    driver_version = _git_version()
    await _declare(uow, driver_version, ("upgrade", "upgrade", "core"))
    core_id = uuid4()
    prefect_manager = FakePrefectManager({(HookKind.UPGRADE, "core"): core_id})

    flows = await resolve_upgrade_hooks(
        driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
    )

    assert flows == UpgradeHookFlows(core=core_id, pre=None, post=None)
    assert prefect_manager.looked_up() == {(HookKind.UPGRADE, "core")}


async def test_upgrade_hooks_raise_for_core_before_pre_when_both_lack_a_flow(
    uow,
) -> None:
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("upgrade", "upgrade", "core"),
        ("pre_upgrade", "upgrade", "pre"),
    )

    with pytest.raises(ActionNotRegisteredError) as raised:
        await resolve_upgrade_hooks(
            driver_version, DRIVER, uow=uow, prefect_manager=FakePrefectManager()
        )

    assert raised.value.hook is HookKind.UPGRADE
    assert raised.value.mode == "core"
    assert raised.value.actions == ["upgrade"]


async def test_upgrade_hooks_raise_for_a_declared_pre_action_without_a_flow(
    uow,
) -> None:
    driver_version = _git_version()
    await _declare(
        uow,
        driver_version,
        ("upgrade", "upgrade", "core"),
        ("pre_upgrade", "upgrade", "pre"),
    )
    prefect_manager = FakePrefectManager({(HookKind.UPGRADE, "core"): uuid4()})

    with pytest.raises(ActionNotRegisteredError) as raised:
        await resolve_upgrade_hooks(
            driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
        )

    assert raised.value.mode == "pre"
    assert raised.value.actions == ["pre_upgrade"]


# --- the registration key of the lookup -------------------------------------


@pytest.mark.parametrize(
    ("driver_version", "fingerprint", "driver_directory"),
    [
        pytest.param(_local_version(), "0a7d3f1", LOCAL_PATH, id="local"),
        pytest.param(_git_version(), "9b1e2c4", None, id="git-repository-root"),
        pytest.param(
            _git_version("drivers/my-app"),
            "9b1e2c4",
            "drivers/my-app",
            id="git-driver-directory",
        ),
    ],
)
async def test_lookup_uses_the_registration_key_of_the_driver_version(
    uow,
    driver_version: ApplicationDriverVersion,
    fingerprint: str,
    driver_directory: str | None,
) -> None:
    await _declare(uow, driver_version, ("pre_setup", "setup", "pre"))
    prefect_manager = FakePrefectManager({(HookKind.SETUP, "pre"): uuid4()})

    await resolve_setup_hooks(
        driver_version, DRIVER, uow=uow, prefect_manager=prefect_manager
    )

    assert prefect_manager.lookups == [
        {
            "application": DRIVER,
            "version": SUPPORTED_VERSIONS,
            "hook": HookKind.SETUP,
            "mode": "pre",
            "fingerprint": fingerprint,
            "driver_directory": driver_directory,
        }
    ]


def test_key_of_a_loaded_local_driver_equals_the_key_of_its_stored_version() -> None:
    """The load registers under the key that hook resolution looks up (FR-006)."""
    driver_object = get_local_driver_loader(str(_SIMPLE_APP)).load_driver()
    assert driver_object.content_hash is not None
    stored = ApplicationDriverVersion(
        version=driver_object.driver_spec.spec.version,
        application_supported_versions=driver_object.driver_spec.spec.supported_versions,
        source_type="local",
        source_repository="",
        source_path=str(_SIMPLE_APP),
        content_hash=driver_object.content_hash,
    )

    key = ActionRegistrationKey.key_for_driver_object(driver_object)

    assert key == ActionRegistrationKey.key_for_version(
        stored, driver_object.driver_spec.metadata.name
    )
    assert key.directory == str(_SIMPLE_APP)
    assert key.fingerprint == driver_object.content_hash[:7]


@pytest.mark.parametrize("driver_directory", [None, "drivers/simple-app"])
def test_key_of_a_loaded_git_driver_equals_the_key_of_its_stored_version(
    driver_directory: str | None,
) -> None:
    local = get_local_driver_loader(str(_SIMPLE_APP)).load_driver()
    driver_object = ApplicationDriver(
        source=GitSource(
            repository=REPOSITORY,
            branch="main",
            token="token",
            driver_directory=driver_directory,
        ),
        driver_spec=local.driver_spec,
        values_template=local.values_template,
        source_commit_sha=COMMIT_SHA,
    )
    stored = ApplicationDriverVersion(
        version=local.driver_spec.spec.version,
        application_supported_versions=local.driver_spec.spec.supported_versions,
        source_type="git",
        source_repository=REPOSITORY,
        source_branch="main",
        source_path=driver_directory,
        source_commit_sha=COMMIT_SHA,
    )

    key = ActionRegistrationKey.key_for_driver_object(driver_object)

    assert key == ActionRegistrationKey.key_for_version(
        stored, local.driver_spec.metadata.name
    )
    assert key.directory == driver_directory
    assert key.fingerprint == COMMIT_SHA[:7]


# --- the load command in the error ------------------------------------------


@pytest.mark.parametrize(
    ("driver_version", "command"),
    [
        pytest.param(
            _local_version(),
            f"styrminctl drivers load-local-version {LOCAL_PATH}",
            id="local",
        ),
        pytest.param(
            _git_version(),
            f"styrminctl drivers load-version {REPOSITORY} main",
            id="git-repository-root",
        ),
        pytest.param(
            _git_version("drivers/my-app"),
            f"styrminctl drivers load-version {REPOSITORY} main"
            " --driver-directory drivers/my-app",
            id="git-driver-directory",
        ),
    ],
)
def test_load_command_has_the_form_of_the_source(
    driver_version: ApplicationDriverVersion, command: str
) -> None:
    assert load_command_for(driver_version) == command


def test_load_command_quotes_a_path_with_a_space() -> None:
    driver_version = _local_version()
    driver_version.source_path = "/srv/my drivers/my-app"

    assert (
        load_command_for(driver_version)
        == "styrminctl drivers load-local-version '/srv/my drivers/my-app'"
    )


def test_load_command_removes_the_user_info_of_the_repository() -> None:
    driver_version = _git_version()
    driver_version.source_repository = "https://user:secret@github.com/opsmill/drivers"

    command = load_command_for(driver_version)

    assert "secret" not in command
    assert command == f"styrminctl drivers load-version {REPOSITORY} main"
