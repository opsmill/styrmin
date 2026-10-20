"""Hook resolution: the registered flows of the actions a driver version declares.

Spec 029 (FR-005, FR-006) — one place decides what "declared but not
registered" means. A driver version declares an action for a hook and mode
with an ``Action`` row; the load registers a Prefect deployment for it under
the driver version's :class:`ActionRegistrationKey`. Resolution reads the
declared actions, looks up only the declared hook and mode pairs, and raises
:class:`ActionNotRegisteredError` when a declared pair has no registered flow,
so a hook is never skipped silently. See
``specs/029-local-driver-actions/contracts/hook-resolution.md``.
"""

import asyncio
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from styrmin_backend.services.driver.driver_directory import redact_user_info
from styrmin_backend.services.driver.exceptions import ActionNotRegisteredError
from styrmin_backend.services.driver.labels import (
    action_directory_of,
    format_driver_version_label,
    short_fingerprint,
)
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.driver.models.structure.source import GitSource

if TYPE_CHECKING:
    from styrmin_backend.db.models import Action, ApplicationDriverVersion
    from styrmin_backend.services.driver import ApplicationDriver
    from styrmin_backend.services.unit_of_work import UnitOfWork
    from styrmin_backend.workflows.manager import PrefectManager

type HookMode = Literal["pre", "core", "post"]


@dataclass(frozen=True)
class ActionRegistrationKey:
    """The key under which the actions of one driver version are registered and looked up.

    Built from a driver version row (hook resolution) or from a loaded driver
    object (registration), so both use the same key (FR-006).
    """

    application: str
    """The driver name."""
    version: str
    """The application versions the driver version supports."""
    fingerprint: str | None
    """The short provenance fingerprint (``content_hash`` or ``source_commit_sha``)."""
    directory: str | None
    """The git driver directory, or the path of a local driver version; None for a git root."""

    @classmethod
    def key_for_version(
        cls, driver_version: ApplicationDriverVersion, application_name: str
    ) -> Self:
        """Return the key of a stored driver version of the driver ``application_name``."""
        return cls(
            application=application_name,
            version=driver_version.application_supported_versions,
            fingerprint=short_fingerprint(
                content_hash=driver_version.content_hash,
                source_commit_sha=driver_version.source_commit_sha,
            ),
            directory=action_directory_of(
                source_type=driver_version.source_type,
                source_path=driver_version.source_path,
            ),
        )

    @classmethod
    def key_for_driver_object(cls, driver_object: ApplicationDriver) -> Self:
        """Return the key of a loaded driver, before or after its version is stored."""
        source = driver_object.source
        source_path = (
            source.driver_directory if isinstance(source, GitSource) else source.path
        )
        return cls(
            application=driver_object.driver_spec.metadata.name,
            version=driver_object.driver_spec.spec.supported_versions,
            fingerprint=short_fingerprint(
                content_hash=driver_object.content_hash,
                source_commit_sha=driver_object.source_commit_sha,
            ),
            directory=action_directory_of(
                source_type=source.type, source_path=source_path
            ),
        )


@dataclass(frozen=True)
class UpgradeHookFlows:
    """The registered flows of the upgrade hook of a driver version that declares ``upgrade``/``core``."""

    core: UUID
    pre: UUID | None
    post: UUID | None


def load_command_for(driver_version: ApplicationDriverVersion) -> str:
    """Return the ``styrminctl`` command that loads ``driver_version`` again.

    Loading the driver again registers the actions it declares. The three
    forms of ``contracts/errors.md``:

    - local: ``styrminctl drivers load-local-version <source_path>``;
    - git from the repository root: ``styrminctl drivers load-version <repository> <branch>``;
    - git from a driver directory: the same, then ``--driver-directory <source_path>``.

    Each value is shell-quoted when it needs to be, and the repository URL has
    its user info removed. Raises ``ValueError`` for a source type that
    ``styrminctl`` does not load (``internal``); such driver versions declare
    no action, so hook resolution never asks for their command.
    """
    if driver_version.source_type == "local" and driver_version.source_path:
        return shlex.join(
            ["styrminctl", "drivers", "load-local-version", driver_version.source_path]
        )
    if driver_version.source_type == "git":
        arguments = [
            "styrminctl",
            "drivers",
            "load-version",
            redact_user_info(driver_version.source_repository),
        ]
        if driver_version.source_branch:
            arguments.append(driver_version.source_branch)
        if driver_version.source_path:
            arguments += ["--driver-directory", driver_version.source_path]
        return shlex.join(arguments)
    msg = (
        f"No styrminctl command loads a driver version of source type "
        f"{driver_version.source_type!r}"
    )
    raise ValueError(msg)


def _declared_action_names(
    actions: Sequence[Action], hook: HookKind, mode: HookMode
) -> list[str]:
    """Return the names of the declared actions of one hook and mode, in the order given."""
    return [
        action.name
        for action in actions
        if action.hook == hook.value and action.mode == mode
    ]


async def _resolve_pairs(
    driver_version: ApplicationDriverVersion,
    application_name: str,
    pairs: Sequence[tuple[HookKind, HookMode]],
    *,
    declared: Sequence[Action],
    prefect_manager: PrefectManager,
) -> list[UUID | None]:
    """Resolve each hook and mode pair of ``pairs``, in order.

    A pair with no declared action resolves to None without a lookup. The
    lookups of the declared pairs run together; the first declared pair of
    ``pairs`` without a registered flow raises ``ActionNotRegisteredError``,
    so the error names the same hook step on every run.
    """
    key = ActionRegistrationKey.key_for_version(driver_version, application_name)
    names = [_declared_action_names(declared, hook, mode) for hook, mode in pairs]

    async def lookup(
        hook: HookKind, mode: HookMode, action_names: list[str]
    ) -> UUID | None:
        if not action_names:
            return None
        return await prefect_manager.get_user_action_deployment_id(
            application=key.application,
            version=key.version,
            hook=hook,
            mode=mode,
            fingerprint=key.fingerprint,
            driver_directory=key.directory,
        )

    flows = await asyncio.gather(
        *(
            lookup(hook, mode, action_names)
            for (hook, mode), action_names in zip(pairs, names, strict=True)
        )
    )
    for (hook, mode), action_names, flow in zip(pairs, names, flows, strict=True):
        if action_names and flow is None:
            raise ActionNotRegisteredError(
                driver_name=application_name,
                driver_version_label=format_driver_version_label(
                    version=driver_version.version,
                    content_hash=driver_version.content_hash,
                    source_commit_sha=driver_version.source_commit_sha,
                ),
                actions=action_names,
                hook=hook,
                mode=mode,
                load_command=load_command_for(driver_version),
            )
    return list(flows)


async def resolve_setup_hooks(
    driver_version: ApplicationDriverVersion,
    application_name: str,
    *,
    uow: UnitOfWork,
    prefect_manager: PrefectManager,
) -> tuple[UUID | None, UUID | None]:
    """Return the ``(pre, post)`` flows of the setup hook of a driver version.

    Each is None when the driver version declares no action for it. Raises
    ``ActionNotRegisteredError`` for the first of ``pre`` and ``post`` that is
    declared and has no registered flow.
    """
    declared = await uow.actions.list_by_driver_version(driver_version.id)
    pre, post = await _resolve_pairs(
        driver_version,
        application_name,
        [(HookKind.SETUP, "pre"), (HookKind.SETUP, "post")],
        declared=declared,
        prefect_manager=prefect_manager,
    )
    return pre, post


async def resolve_upgrade_hooks(
    driver_version: ApplicationDriverVersion,
    application_name: str,
    *,
    uow: UnitOfWork,
    prefect_manager: PrefectManager,
) -> UpgradeHookFlows | None:
    """Return the flows of the upgrade hook of a driver version.

    None when the driver version declares no ``upgrade``/``core`` action: the
    change is then a plain update, and ``pre`` and ``post`` are not looked up
    (research R-012). Otherwise resolves ``core``, ``pre`` and ``post``, and
    raises ``ActionNotRegisteredError`` for the first of them, in that order,
    that is declared and has no registered flow.
    """
    declared = await uow.actions.list_by_driver_version(driver_version.id)
    if not _declared_action_names(declared, HookKind.UPGRADE, "core"):
        return None
    core, pre, post = await _resolve_pairs(
        driver_version,
        application_name,
        [
            (HookKind.UPGRADE, "core"),
            (HookKind.UPGRADE, "pre"),
            (HookKind.UPGRADE, "post"),
        ],
        declared=declared,
        prefect_manager=prefect_manager,
    )
    # ``core`` is declared, so ``_resolve_pairs`` raised when it found no flow.
    assert core is not None
    return UpgradeHookFlows(core=core, pre=pre, post=post)
