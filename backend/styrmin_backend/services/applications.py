"""Provides the application service."""

import asyncio
from dataclasses import dataclass

from fast_depends import Depends, inject
from loguru import logger
from sqlalchemy.exc import IntegrityError

from styrmin_backend import config as styrmin_config
from styrmin_backend.db.models import (
    Action,
    ApplicationDriverVersion,
    HelmChart,
    HelmRepository,
)
from styrmin_backend.db.models import (
    ApplicationDriver as ApplicationDriverModel,
)
from styrmin_backend.db.models import (
    ApplicationDriverVersion as ApplicationDriverVersionModel,
)
from styrmin_backend.domain.models import ComponentConfig
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.driver_directory import quoted
from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.hooks import ActionRegistrationKey
from styrmin_backend.services.driver.loaders import (
    get_git_driver_loader,
    get_local_driver_loader,
)
from styrmin_backend.services.driver.models.resources.driver import Info
from styrmin_backend.services.driver.models.structure.source import (
    GitSource,
    LocalSource,
)
from styrmin_backend.services.exceptions import (
    ServiceError,
)
from styrmin_backend.services.unit_of_work import UnitOfWork
from styrmin_backend.services.user import ActionsWorkflowBuilder
from styrmin_backend.services.utils import (
    get_chart_name_from_chart_url,
    get_chart_repository_from_chart_url,
)
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager


@dataclass(frozen=True)
class LoadedDriverVersion:
    """A stored driver version and the warnings its specification file produced."""

    version: ApplicationDriverVersionModel
    # Values of ``spec.info`` that were left out, and why (spec 020).
    warnings: list[str]


async def _store_loaded_driver(
    driver_object: ApplicationDriver, uow: UnitOfWork
) -> LoadedDriverVersion:
    warnings = driver_object.driver_spec.spec.info.warnings
    for warning in warnings:
        logger.warning(
            "Driver {}: {}", driver_object.driver_spec.metadata.name, warning
        )
    version = await load_application_driver_from_object(
        driver_object=driver_object, uow=uow
    )
    return LoadedDriverVersion(version=version, warnings=warnings)


def _driver_info_columns(info: Info) -> dict[str, object]:
    """Map ``spec.info`` to the driver version's info columns; empty values become NULL."""
    return {
        "icon": str(info.icon) if info.icon else None,
        "description": info.description or None,
        "links": [link.model_dump(mode="json") for link in info.links or []] or None,
    }


def _refuse_two_actions_for_one_hook_and_mode(driver_object: ApplicationDriver) -> None:
    """Refuse a driver that declares more than one action for one hook and mode.

    The actions of a hook and mode are registered under one key, so a second
    action would replace the first, or would be skipped when the first is
    registered already.
    """
    by_pair: dict[tuple[str, str], list[str]] = {}
    for action in driver_object.driver_spec.spec.actions:
        by_pair.setdefault((action.hook.value, action.mode), []).append(action.name)
    for (hook, mode), names in by_pair.items():
        if len(names) > 1:
            raise DriverLoadingError(
                f"Driver {driver_object.driver_spec.metadata.name} declares "
                f"{len(names)} actions for the {hook} hook, mode {mode}: "
                f"{', '.join(names)}. Styrmin runs one action for each hook and mode. "
                "Keep one of them, or call the others from it, then load the driver "
                "again."
            )


def _refuse_local_actions_that_the_check_cannot_cover(
    driver_object: ApplicationDriver, source: LocalSource
) -> None:
    """Refuse a local driver with actions whose path or action locations the check cannot cover (spec 029)."""
    if "{" in source.path or "}" in source.path:
        raise DriverLoadingError(
            f"Driver path {quoted(source.path)} is refused: it contains '{{' or '}}', "
            "and the driver declares actions. Prefect fills in '{{ ... }}' templates "
            "in the path before the action checks the driver files. Load the driver "
            "from a path without '{' or '}'."
        )
    if not source.path.startswith("/"):
        raise DriverLoadingError(
            f"Driver path {quoted(source.path)} is refused: it is a relative path, "
            "and the driver declares actions. The Styrmin agent runs each action from "
            "a temporary working folder, where a relative path does not lead to the "
            "driver. Load the driver from an absolute path, such as "
            f"/styrmin/drivers/{driver_object.driver_spec.metadata.name}."
        )
    actions_file = styrmin_config.SETTINGS.driver.actions_code_file
    for action in driver_object.driver_spec.spec.actions:
        module, function = action.location.split("::")
        if module != actions_file:
            raise DriverLoadingError(
                f"Action {action.name} of the driver loaded from {quoted(source.path)} "
                f"is refused: its location {action.location} is not in "
                f"{actions_file}. Before an action of a driver loaded from a local "
                f"directory runs, Styrmin checks only the driver specification, the "
                f"values template and {actions_file}, so the code of another file "
                f"could change without the check noticing. Move the function to "
                f"{actions_file}, set the location to {actions_file}::{function}, and "
                "load the driver again."
            )


async def ensure_action_registrations(
    driver_object: ApplicationDriver,
    prefect_manager: PrefectManager,
) -> int:
    """Register the declared actions whose hook and mode have no registered flow.

    Spec 029 (FR-001, FR-002, FR-006). The actions of a driver version loaded
    from git or from a local directory are registered under the key that hook
    resolution looks them up with (:class:`ActionRegistrationKey`): the driver,
    the supported versions, the short provenance fingerprint and the driver
    directory (the path of a local driver version). Each hook and mode that the
    driver declares is looked up first, and only the actions of the pairs
    without a registered flow are registered, so a load with nothing to
    register makes no Prefect write.

    Returns:
        int: The number of actions registered.

    Raises:
        DriverLoadingError: The driver declares more than one action for one
            hook and mode: they share one registration key, so only one of
            them would run. Or the driver declares actions and was loaded from
            a local path that:

            - contains ``{`` or ``}``. Prefect fills in ``{{ ... }}`` templates
              in the inputs of the step that checks the driver files, so the
              path could make the check write a secret, such as the action
              token, into its error (research R-005);
            - is relative. The agent runs each action from a temporary working
              folder, where a relative path does not lead to the driver.

            Or an action of a local driver has a location outside the actions
            file, which the check before each action does not cover.
    """
    actions = driver_object.driver_spec.spec.actions
    if not actions:
        return 0
    _refuse_two_actions_for_one_hook_and_mode(driver_object)
    source = driver_object.source
    if isinstance(source, LocalSource):
        _refuse_local_actions_that_the_check_cannot_cover(driver_object, source)

    key = ActionRegistrationKey.key_for_driver_object(driver_object)
    pairs = list(dict.fromkeys((action.hook, action.mode) for action in actions))
    flows = await asyncio.gather(
        *(
            prefect_manager.get_user_action_deployment_id(
                application=key.application,
                version=key.version,
                hook=hook,
                mode=mode,
                fingerprint=key.fingerprint,
                driver_directory=key.directory,
            )
            for hook, mode in pairs
        )
    )
    missing_pairs = {
        pair for pair, flow in zip(pairs, flows, strict=True) if flow is None
    }
    missing = [
        action for action in actions if (action.hook, action.mode) in missing_pairs
    ]
    if not missing:
        return 0

    if isinstance(source, GitSource):
        await prefect_manager.register_token(namespace="user", token=source.token)
    builder = ActionsWorkflowBuilder(
        source=source,
        commit_sha=driver_object.source_commit_sha,
        content_hash=driver_object.content_hash,
    )
    for action in missing:
        workflow = builder.build_user_action_workflow_definition(action=action)
        logger.info(
            "Registering action {} of driver {} ({}): hook={} mode={} "
            "fingerprint={} driver_directory={}",
            action.name,
            key.application,
            key.version,
            action.hook.value,
            action.mode,
            key.fingerprint,
            key.directory,
        )
        await prefect_manager.register_user_action(
            workflow=workflow,
            application=key.application,
            version=key.version,
            hook=action.hook,
            mode=action.mode,
            fingerprint=key.fingerprint,
            driver_directory=key.directory,
        )
    return len(missing)


@inject(cast_result=False)  # type: ignore[arg-type]
async def load_application_driver_from_object(
    driver_object: ApplicationDriver,
    uow: UnitOfWork,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> ApplicationDriverVersionModel:
    """Load an application driver from an object.

    The driver version's identity includes ``source_path``: the absolute path
    of a local load, the driver directory of a git load from one, or None for
    a git load from the repository root.

    A new driver version's actions, from git or from a local directory, are
    registered with :func:`ensure_action_registrations` before the version is
    stored. Loading a stored driver version again registers the declared
    actions that have no registered flow, and returns the stored version.

    Args:
        driver_object (ApplicationDriver): The object representing the application driver.

    Returns:
        Application: The loaded application driver.

    Raises:
        DriverLoadingError: A local driver with actions was loaded from a path
            that contains ``{`` or ``}``.
    """

    async with uow:
        name = driver_object.driver_spec.metadata.name

        supported_versions = driver_object.driver_spec.spec.supported_versions

        application_driver = await uow.application_drivers.get_by_name(name=name)
        if application_driver is None:
            application_driver = await uow.application_drivers.create(
                ApplicationDriverModel(name=name)
            )

        # Build the source-identity tuple ahead of the duplicate check so
        # spec 013 (provenance fingerprint) can disambiguate two rows that
        # share the same ``application_supported_versions`` range but differ
        # on ``content_hash`` (local) or ``source_commit_sha`` (git).
        if isinstance(driver_object.source, GitSource):
            source_type = "git"
            source_repository = driver_object.source.repository
            source_branch: str | None = driver_object.source.branch
            # The driver directory, or None for a load from the repository root (spec 028).
            source_path: str | None = driver_object.source.driver_directory
        else:
            source_type = "local"
            source_repository = ""
            source_branch = None
            source_path = driver_object.source.path

        # Spec 013 / T024 — idempotency check on the full identity tuple.
        # A row that matches every identity column (incl. the new fingerprint
        # columns) means this exact driver byte-content is already loaded;
        # return it instead of either raising or creating a duplicate.
        existing_identity = await uow.application_driver_versions.get_by_identity(
            application_driver_id=application_driver.id,
            source_type=source_type,
            source_repository=source_repository,
            source_branch=source_branch,
            source_path=source_path,
            version=driver_object.driver_spec.spec.version,
            content_hash=driver_object.content_hash,
            source_commit_sha=driver_object.source_commit_sha,
        )
        if existing_identity is not None:
            # Spec 029 (FR-006) — loading a driver version again registers the
            # declared actions whose hook and mode have no registered flow, for
            # example after their Prefect deployments were deleted. Before both
            # returns below, and before the info refresh commits, so a load
            # that this refuses writes nothing.
            await ensure_action_registrations(driver_object, prefect_manager)
            # The identity tuple pins the file content, so this only fills
            # rows stored before the info columns existed (spec 020, R5).
            info = _driver_info_columns(driver_object.driver_spec.spec.info)
            if any(getattr(existing_identity, k) != v for k, v in info.items()):
                for key, value in info.items():
                    setattr(existing_identity, key, value)
                await uow.commit()
                refreshed = await uow.application_driver_versions.get(
                    existing_identity.id
                )
                assert refreshed is not None, "Application driver version not found"
                return refreshed
            return existing_identity

        # Get or create Helm repository
        helm_chart_repository = get_chart_repository_from_chart_url(
            driver_object.driver_spec.spec.helm.main.location
        )
        helm_repository: HelmRepository | None = await uow.helm_repositories.get_by_url(
            url=helm_chart_repository
        )
        if not helm_repository:
            helm_repository = await uow.helm_repositories.create(
                HelmRepository(url=helm_chart_repository)
            )

        # Get or create Helm chart
        helm_chart_version = driver_object.driver_spec.spec.helm.main.version
        value_template = driver_object.values_template
        chart_name = get_chart_name_from_chart_url(
            driver_object.driver_spec.spec.helm.main.location
        )
        helm_chart: HelmChart | None = await uow.helm_charts.get_by_name_version(
            name=name, version=supported_versions
        )
        if not helm_chart:
            helm_chart = await uow.helm_charts.create(
                HelmChart(
                    name=chart_name,
                    version=helm_chart_version,
                    values_template=value_template,
                    repository_id=helm_repository.id,
                )
            )

        # Create application
        components = (
            driver_object.driver_spec.spec.components.model_dump()
            if driver_object.driver_spec.spec.components
            else None
        )
        parameters = (
            [p.model_dump() for p in driver_object.driver_spec.spec.parameters]
            if driver_object.driver_spec.spec.parameters
            else None
        )
        services = None
        if driver_object.driver_spec.spec.services:
            # Validate that each service's component references a declared component
            component_names = set(components.keys()) if components else set()
            for svc in driver_object.driver_spec.spec.services:
                if svc.component not in component_names:
                    raise ServiceError(
                        f"Service '{svc.name}' references undeclared component "
                        f"'{svc.component}'. Available components: "
                        f"{sorted(component_names)}"
                    )
            services = [s.model_dump() for s in driver_object.driver_spec.spec.services]
        # 008 / US4: persist doc-only env var declarations, mode="json"
        # so the enum serialises to its string value (matches the JSON
        # column shape and the GraphQL resolver's expectations).
        env_vars_payload = (
            [
                doc.model_dump(mode="json")
                for doc in driver_object.driver_spec.spec.env_vars
            ]
            if driver_object.driver_spec.spec.env_vars
            else None
        )
        # Spec 029 — register the actions of the new driver version, from git
        # or from a local directory, after the checks above and before the
        # insert: a load that the checks refuse leaves no deployment in
        # Prefect, and a load whose registration fails stores no driver
        # version (critique E3). The registration key includes the short
        # provenance fingerprint (spec 013) and the driver directory, so two
        # driver versions of one driver keep their own deployments, and hook
        # resolution looks them up with the same key.
        await ensure_action_registrations(driver_object, prefect_manager)
        # Spec 013 — the ``get_by_identity`` fast-path above resolves the
        # common case where the row already exists. Two concurrent loads
        # of the same content can still both miss the lookup and race
        # to the INSERT; the UNIQUE index ``uq_application_driver_version_identity``
        # guarantees exactly one wins. The loser surfaces an
        # ``IntegrityError``; we rollback the poisoned transaction and
        # re-run the identity lookup to return the winner's row instead
        # of leaking a 500 to the caller.
        try:
            application_driver_version = await uow.application_driver_versions.create(
                ApplicationDriverVersion(
                    version=driver_object.driver_spec.spec.version,
                    application_driver_id=application_driver.id,
                    application_supported_versions=supported_versions,
                    default_version=driver_object.driver_spec.spec.default_version,
                    components=components,
                    parameters=parameters,
                    services=services,
                    env_vars=env_vars_payload,
                    **_driver_info_columns(driver_object.driver_spec.spec.info),
                    helm_chart_id=helm_chart.id,
                    source_type=source_type,
                    source_repository=source_repository,
                    source_branch=source_branch,
                    source_path=source_path,
                    # Spec 013 / T025 — persist the provenance fingerprint
                    # captured by the driver loader. ``content_hash`` is
                    # set for local-sourced drivers; ``source_commit_sha``
                    # is set for git-sourced drivers (US2, C9). Both
                    # nullable.
                    content_hash=driver_object.content_hash,
                    source_commit_sha=driver_object.source_commit_sha,
                )
            )
        except IntegrityError:
            # A concurrent loader landed first. Rollback the poisoned
            # transaction (the failed flush leaves the session in an
            # unusable state until we do) and re-fetch the winner's row
            # via the same identity tuple. The UNIQUE index ensures the
            # second lookup resolves to exactly one row; anything else
            # would be a genuine bug in the identity definition rather
            # than a race, so we let the original IntegrityError surface
            # by re-raising.
            logger.info(
                "IntegrityError on application_driver_versions insert; "
                "treating as concurrent-load race and re-fetching identity "
                "row (application={}, version={}, source_type={}).",
                name,
                driver_object.driver_spec.spec.version,
                source_type,
            )
            await uow.rollback()
            # Rollback undoes any ancillary inserts we performed in this
            # transaction (e.g. the ``application_driver`` row created at
            # the top), so re-resolve the parent driver in the fresh
            # transaction. The winning concurrent loader is guaranteed to
            # have committed an ``ApplicationDriver`` row with this name
            # before its identity-tuple INSERT (same code path).
            parent = await uow.application_drivers.get_by_name(name=name)
            if parent is None:
                raise
            winner = await uow.application_driver_versions.get_by_identity(
                application_driver_id=parent.id,
                source_type=source_type,
                source_repository=source_repository,
                source_branch=source_branch,
                source_path=source_path,
                version=driver_object.driver_spec.spec.version,
                content_hash=driver_object.content_hash,
                source_commit_sha=driver_object.source_commit_sha,
            )
            if winner is None:
                # The UNIQUE-index violation wasn't our identity tuple
                # after all — surface the original error.
                raise
            return winner

        # Create component configs
        if components:
            for component_name, component_def in components.items():
                await uow.component_configs.save(
                    application_driver_version_id=application_driver_version.id,
                    component_config=ComponentConfig.create(
                        name=component_name,
                        config=component_def,
                    ),
                )

        # Create actions
        if driver_object.driver_spec.spec.actions:
            for action in driver_object.driver_spec.spec.actions:
                await uow.actions.create(
                    Action(
                        application_driver_version_id=application_driver_version.id,
                        name=action.name,
                        description=action.description,
                        location=action.location,
                        hook=action.hook.value if action.hook else None,
                        mode=action.mode,
                        image=action.image,
                    )
                )

        await uow.commit()
        result = await uow.application_driver_versions.get(
            application_driver_version.id
        )
        assert result is not None, "Application driver version not found"
        return result


async def load_application_driver_from_git_repository(
    repository_url: str,
    branch: str,
    uow: UnitOfWork,
    driver_directory: str | None = None,
) -> LoadedDriverVersion:
    """Load an application driver from a git repository.

    Args:
        repository_url (str): The URL of the git repository.
        branch (str): The branch to clone.
        uow (UnitOfWork): The unit of work to use.
        driver_directory (str | None): The folder of the repository that holds the
            driver, relative to the repository root; None for the repository root.
            Stored in normalised form in ``source_path``.

    Returns:
        LoadedDriverVersion: The stored driver version and the load warnings.

    Raises:
        DriverLoadingError: The driver directory is refused (before any clone),
            the clone fails, or the driver directory or a driver file cannot be
            followed or leads outside the repository or the driver directory.
        MissingDriverSpecificationError: The driver directory holds no
            driver specification file.
    """

    # TODO: Token setup
    token = styrmin_config.SETTINGS.driver.token
    if token is None:
        raise ServiceError(
            "No Git token where provided for loading the driver from a remote code storage."
        )

    # Load the driver from the remote repository
    driver_loader = get_git_driver_loader(
        repository=repository_url,
        branch=branch,
        token=token,
        driver_directory=driver_directory,
    )
    # The clone blocks, so it runs off the event loop.
    application_driver = await asyncio.to_thread(driver_loader.load_driver)

    # Create the application driver objects in database
    return await _store_loaded_driver(application_driver, uow)


async def load_application_driver_from_local_directory(
    path: str, uow: UnitOfWork
) -> LoadedDriverVersion:
    """Load an application driver from a local filesystem directory.

    Args:
        path (str): The absolute path to the local driver directory.
        uow (UnitOfWork): The unit of work to use.

    Returns:
        LoadedDriverVersion: The stored driver version and the load warnings.

    Notes:
        Spec 013 / T024 — the previous ``get_by_source_path_and_version`` +
        ``delete(existing)`` block has been removed. Idempotency now lives
        inside :func:`load_application_driver_from_object`, which uses
        :meth:`ApplicationDriverVersionRepository.get_by_identity` to look
        up the full identity tuple (including the new ``content_hash``
        column). Two reloads of the same content return the same row; a
        reload with edited content creates a new row (no delete of the
        prior one) so historical deployments stay reproducible.
    """
    driver_loader = get_local_driver_loader(path=path)
    application_driver = driver_loader.load_driver()

    # Create the application driver objects in database (idempotent on
    # identity-tuple via ``get_by_identity`` inside).
    return await _store_loaded_driver(application_driver, uow)
