from typing import Literal
from uuid import UUID, uuid4

from loguru import logger
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from styrmin_backend.agent.service.kubernetes.primitives import patch_custom_resource
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.exceptions import InvalidDeploymentContextError
from styrmin_backend.context.validators import validate_deployment_config
from styrmin_backend.domain.models import (
    Component,
    Deployment,
    DeploymentState,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.domain.utils import (
    generate_deployment_name,
    validate_deployment_name,
)
from styrmin_backend.context.models.config import DedicatedIngressConfig
from styrmin_backend.db.models import ApplicationDriver, ApplicationDriverVersion
from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION
from styrmin_backend.services.container_overrides.exceptions import (
    UnknownComponentContainerOverrideError,
)
from styrmin_backend.services.container_overrides.validator import (
    validate_container_override,
)
from styrmin_backend.services.env_vars.exceptions import (
    ComponentContainerNotDeclaredError,
    UnknownComponentEnvVarError,
)
from styrmin_backend.services.env_vars.validator import validate_env_vars_dict
from styrmin_backend.services.image_overrides.reference import validate_reference
from styrmin_backend.services.image_overrides.validator import (
    prevalidate_image_overrides,
    validate_image_override_targets,
)
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    DeploymentNameConflictError,
    DeploymentNameValidationError,
    DeploymentNotFoundError,
    DeploymentRestoringError,
    DriverVersionNotFoundError,
    EnvironmentNotFoundError,
    IngressControllerNotHealthyError,
    InvalidContextError,
    InvalidVersionError,
)
from styrmin_backend.services.ingress_controller.driver import INTERNAL_DRIVER_NAME
from styrmin_backend.services.parameters import (
    parse_parameter_definitions,
    validate_parameter_values,
)
from styrmin_backend.services.reconciliation import (
    apply_state,
    generate_instance_from_deployment,
)
from deepdiff import DeepDiff

from styrmin_backend.domain.models import Instance
from styrmin_backend.services.services_discovery import (
    create_services_for_deployment,
    parse_service_definitions,
    reconcile_services_on_upgrade,
)
from styrmin_backend.services.unit_of_work import UnitOfWork


def _validate_component_env_var_targets(
    deployment_config: dict | None,
    known_component_names: list[str],
) -> None:
    """Reject ``config.components.<name>.env_vars`` targeting unknown components.

    Raised at the service-layer entry point ahead of Pydantic-driven
    ``DeploymentConfig`` validation so the typed
    :class:`UnknownComponentEnvVarError` surfaces directly to the GraphQL
    caller (mapped to ``extensions.code = "UNKNOWN_COMPONENT_ENV_VAR"``)
    instead of being collapsed into ``ValidationError`` and re-wrapped as the
    generic ``INVALID_CONTEXT`` error code (008-deployment-env-vars / FR-010).
    The known-components list is sourced from the deployment's current
    driver and surfaced in the error metadata so operators can fix the typo
    without a round-trip.

    Read-vs-write asymmetry (US5 / FR-029..FR-033): this validator runs on
    the **write** path only (``deploy``, ``update_deployment``,
    ``update_deployment_config``). The read path
    (``EnvVarsResolver.resolve_for_deployment`` consumed by
    ``Deployment.componentEnvVars``) does NOT raise on unknown components —
    it tolerates orphan state and exposes ``ComponentEnvVars.isOrphaned=true``
    for blocks whose target component the current driver no longer declares.
    This split lets a driver upgrade that renames or removes a component
    succeed (the existing block becomes visibly orphaned and stops being
    injected) while still blocking new typos at the boundary.
    """
    if not deployment_config:
        return
    components_block = deployment_config.get("components")
    if not isinstance(components_block, dict) or not components_block:
        return
    known = set(known_component_names)
    for name, block in components_block.items():
        if name in known:
            continue
        # Only fail when the offending block actually carries env vars (the
        # block could be empty in transient client payloads); other future
        # per-component slots will get their own typed errors.
        if isinstance(block, dict) and block.get("env_vars"):
            raise UnknownComponentEnvVarError(
                component_name=name,
                known_components=sorted(known),
            )


def _containers_by_component(
    driver_version: ApplicationDriverVersion,
) -> dict[str, str | None]:
    """Map each declared component to its component container (``None`` if undeclared)."""
    containers: dict[str, str | None] = {}
    for component_config in driver_version.component_configs or []:
        config = component_config.config
        container = config.get("container") if isinstance(config, dict) else None
        containers[component_config.name] = container
    return containers


ComponentContainerSlot = Literal["env_vars", "image"]


def _slot_adds_or_changes(
    slot: ComponentContainerSlot, submitted_block: object, stored_block: object
) -> bool:
    """Return whether ``submitted_block`` adds or changes ``slot`` relative to ``stored_block``."""
    submitted = submitted_block.get(slot) if isinstance(submitted_block, dict) else None
    stored = stored_block.get(slot) if isinstance(stored_block, dict) else None
    if slot == "image":
        return submitted is not None and submitted != stored
    if not isinstance(submitted, dict) or not submitted:
        return False
    if not isinstance(stored, dict):
        stored = {}
    return any(
        key not in stored or stored[key] != value for key, value in submitted.items()
    )


def _validate_component_container_targets(
    submitted_config: dict | None,
    stored_config: dict | None,
    containers_by_component: dict[str, str | None],
    slots: tuple[ComponentContainerSlot, ...] = ("env_vars", "image"),
) -> None:
    """Reject added or changed component-container overrides on containerless components.

    ``containers_by_component`` comes from the driver version the deployment is
    pinned to after the write. Removals and unchanged re-submissions pass so
    values stored before a driver upgrade can still be cleaned up (017 FR-003,
    018 FR-005). Unknown components are left to the per-slot target checks.
    """
    submitted_components = (submitted_config or {}).get("components")
    if not isinstance(submitted_components, dict):
        return
    stored_components = (stored_config or {}).get("components")
    if not isinstance(stored_components, dict):
        stored_components = {}
    for name, block in submitted_components.items():
        if name not in containers_by_component or containers_by_component[name]:
            continue
        for slot in slots:
            if _slot_adds_or_changes(slot, block, stored_components.get(name)):
                raise ComponentContainerNotDeclaredError(
                    component_name=name,
                    components_with_container=[
                        component
                        for component, container in containers_by_component.items()
                        if container
                    ],
                    override=slot,
                )


def _validate_image_overrides_for_version(
    stored_config: dict | None,
    containers_by_component: dict[str, str | None],
    version: str,
) -> None:
    """Re-validate stored image overrides that apply under ``containers_by_component``.

    Runs before a version change dispatches anything, so the driver's upgrade action never
    stops components for a reference that cannot render (018 FR-009). Containerless and
    orphaned components are skipped: their override is never rendered.
    """
    stored_components = (stored_config or {}).get("components")
    if not isinstance(stored_components, dict):
        return
    for name, container in containers_by_component.items():
        block = stored_components.get(name)
        image = block.get("image") if isinstance(block, dict) else None
        if container and image is not None:
            validate_reference(image, version=version, component_name=name)


def _prevalidate_deployment_env_vars(deployment_config: dict | None) -> None:
    """Run typed env-var validation ahead of Pydantic model construction.

    Pydantic's ``DeploymentConfig.env_vars`` field validators raise the same
    typed :class:`ServiceError` subclasses (``InvalidEnvVarNameError``,
    ``EnvVarSizeLimitExceededError``, ``DuplicateEnvVarNameError``), but
    :class:`pydantic.ValidationError` wraps them on the way out and
    :func:`context.validators.validate_deployment_config` rewraps that into a
    generic ``InvalidDeploymentContextError`` — collapsing the precise
    ``extensions.code`` to ``INVALID_CONTEXT``. Calling
    :func:`validate_env_vars_dict` directly here lets the typed errors
    propagate to Strawberry untouched, restoring the operator-visible codes
    promised by FR-006/FR-007/FR-008/FR-009 and SC-003.
    """
    if not deployment_config:
        return
    deployment_env = deployment_config.get("env_vars")
    if isinstance(deployment_env, dict):
        validate_env_vars_dict("deployment", deployment_env)
    components_block = deployment_config.get("components")
    if isinstance(components_block, dict):
        for _name, block in components_block.items():
            if not isinstance(block, dict):
                continue
            comp_env = block.get("env_vars")
            if isinstance(comp_env, dict):
                validate_env_vars_dict("component", comp_env)


def _validate_component_container_overrides(
    deployment_config: dict | None,
    known_component_names: list[str],
) -> None:
    """Reject malformed / mis-targeted ``command``/``args`` overrides at the write boundary.

    Runs ahead of Pydantic-driven ``DeploymentConfig`` validation (like
    :func:`_validate_component_env_var_targets` /
    :func:`_prevalidate_deployment_env_vars`) so the typed
    :class:`UnknownComponentContainerOverrideError` /
    :class:`InvalidContainerCommandError` / :class:`InvalidContainerArgsError`
    reach the GraphQL caller intact instead of collapsing into
    ``INVALID_CONTEXT`` (014-component-container-overrides / FR-004, FR-006).

    For each ``components[<name>]`` block carrying a non-null ``command`` or
    ``args``:

    * if ``<name>`` is not declared by the deployment's current driver →
      :class:`UnknownComponentContainerOverrideError` (FR-004, US4 Sc.1) — no
      reconcile is planned on rejection;
    * each present ``command``/``args`` is shape-validated via
      :func:`validate_container_override` (non-empty list-of-string;
      empty-string elements accepted; ``[]`` rejected — FR-006, US4 Sc.2/Sc.3).

    Read-vs-write asymmetry (US5 / FR-005): this validator runs on the **write**
    path only. The read path (``Deployment.componentContainerOverrides``)
    tolerates orphaned blocks and exposes ``isOrphaned=true`` so a driver
    upgrade that renames/removes a component succeeds, while new typos are
    blocked at the boundary.
    """
    if not deployment_config:
        return
    components_block = deployment_config.get("components")
    if not isinstance(components_block, dict) or not components_block:
        return
    known = set(known_component_names)
    for name, block in components_block.items():
        if not isinstance(block, dict):
            continue
        command = block.get("command")
        args = block.get("args")
        has_command = command is not None
        has_args = args is not None
        if not has_command and not has_args:
            continue
        # Unknown-component rejection fires before shape validation so the
        # operator learns the component is undeclared rather than getting a
        # shape error for a block that could never apply (US4 Sc.1).
        if name not in known:
            raise UnknownComponentContainerOverrideError(
                component_name=name,
                known_components=sorted(known),
            )
        if has_command:
            validate_container_override("command", command, component_name=name)
        if has_args:
            validate_container_override("args", args, component_name=name)


# Volatile / per-generation instance fields that are never part of the desired
# state and must be ignored when deciding whether an update is a no-op:
# the instance's own ``id`` / generated ``name`` / runtime ``status``, plus the
# synthetic ``context.instance.id`` that ``generate_instance_from_deployment``
# stamps onto every freshly-built candidate.
_NOOP_EXCLUDE_PATHS = frozenset(
    {
        "root['id']",
        "root['name']",
        "root['status']",
        "root['context']['instance']['id']",
    }
)


def _update_is_noop(
    *,
    current_instance: Instance | None,
    new_instance: Instance,
) -> bool:
    """Return True when the freshly-generated candidate resolves to the current
    realised instance — i.e. the update changes nothing (spec 014, FR-001/002).

    This compares the **raw structural diff** of the two resolved instances
    (``DeepDiff`` emptiness after excluding the volatile fields above), NOT the
    remediation-oriented ``Comparator.compare().diff``. The latter is unsafe as
    a no-op signal: its serializer only renders the ``values_changed`` DeepDiff
    category, so config *additions* — a first env var, ip-whitelist, or
    scheduling block, which DeepDiff classifies as ``type_changes``
    (``None`` → value) or ``dictionary_item_added`` (``{}`` → ``{...}``) —
    produce empty serialized diffs and would be falsely reported as a no-op,
    silently dropping a real change. Raw-diff emptiness catches every category.

    A ``None`` current instance means there is no realised state to match
    against (e.g. a failed initial deploy left none) → treated as a change.
    """
    if current_instance is None:
        return False

    # ``mode="json"`` normalises representation on both sides (UUID/datetime/
    # enum → their JSON primitives) so that a value persisted+reloaded as a
    # string and the same value freshly built as a ``UUID`` object (e.g.
    # ``context.labels.environment_id`` / ``deployment_id``) compare equal
    # instead of surfacing a spurious ``type_changes`` diff.
    raw_diff = DeepDiff(
        t1=current_instance.model_dump(mode="json"),
        t2=new_instance.model_dump(mode="json"),
        ignore_order=True,
        exclude_paths=set(_NOOP_EXCLUDE_PATHS),
    ).to_dict()
    return not raw_diff


async def get_deployment(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> Deployment:
    """Get a deployment by its ID."""
    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )
        return deployment


async def get_deployment_by_name(
    *,
    name: str,
    environment_id: UUID,
    uow: UnitOfWork,
) -> Deployment | None:
    """Look up a deployment by its natural identity ``(name, environment_id)``.

    Returns the matching :class:`Deployment` if and only if it is non-internal
    and not soft-deleted. Returns ``None`` for not-found, internal-hidden, or
    tombstoned rows — no exceptions on miss. The repository call is bounded by
    the existing ``unique_deployment_name_per_environment`` index.
    """
    async with uow:
        deployment = await uow.deployments.find_one_by_name_and_environment(
            name=name, environment_id=environment_id
        )
        if (
            deployment is None
            or deployment.internal
            or deployment.deleted_at is not None
        ):
            return None
        return deployment


async def refresh_deployment(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> Task:
    """Refresh a deployment by its ID.

    Args:
        deployment_id (UUID): The ID of the deployment to refresh.
        uow (UnitOfWork): The unit of work to use.

    Raises:
        DeploymentNotFoundError: If the deployment is not found.

    Returns:
        Task: The task created for the deployment refresh.
    """
    async with uow:
        # Get the deployment
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        # Ensure dedicated ingress controller is healthy if configured
        await _ensure_ingress_controller(
            environment_id=deployment.environment_id,
            uow=uow,
            created_by_user_id=deployment.created_by_user_id,
        )

        # Get the current instance
        current_instance = deployment.active_instance

        # Generate the instance from the deployment
        new_instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
        )

        # Set the new instance as the active one
        deployment.set_active_instance(instance=new_instance)
        deployment.set_status(DeploymentState.PENDING)

        # Get the task from the reconciliation workflow
        task = await apply_state(
            deployment=deployment, current_instance=current_instance, uow=uow
        )

        await uow.deployments.save(deployment=deployment)
        await uow.tasks.save(task=task)
        await uow.commit()

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


async def update_deployment(
    deployment_id: UUID,
    uow: UnitOfWork,
    deployment_config: dict | None = None,
    deployment_parameters: dict | None = None,
    deployment_name: str | None = None,
    service_name_overrides: dict[str, str] | None = None,
) -> Task | None:
    """Update a deployment with the given configuration and/or name.

    Args:
        deployment_id: The ID of the deployment to update.
        uow: The unit of work to use.
        deployment_config: The new configuration for the deployment (optional).
        deployment_parameters: Parameter values to merge with existing parameters.
        deployment_name: New name for the deployment (optional).
        service_name_overrides: Optional mapping of driver service name → desired
            resolved name. Renames the corresponding DeployedService rows before
            instance generation so the new instance context carries the updated names.

    Raises:
        InvalidContextError: If the context is invalid.
        DeploymentNameValidationError: If the provided name is invalid.
        DeploymentNameConflictError: If the provided name is already in use.

    Returns:
        Task | None: The task created for the deployment update, or ``None``
            when the submitted desired state resolves to the current realised
            instance (a no-op — no instance persisted, no reconcile dispatched).
    """
    logger.info("Updating deployment for deployment_id={}", deployment_id)

    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        logger.info(
            "Deployment found: id={} current_version={}",
            deployment.id,
            deployment.application_version,
        )

        # ---- Phase 1: validate + write user intent to the DB ----
        # Everything that affects the *desired-state context* must land here
        # so that `generate_instance_from_deployment` in phase 2 reads
        # already-committed rows. This is the #237 fix: the previous ordering
        # ran reconcile_services_on_upgrade AFTER instance generation, so the
        # context carried the old service name.

        if deployment_config is not None:
            # Reject component-level env var blocks targeting components the
            # deployment's current driver does not declare (FR-010). Run this
            # ahead of Pydantic validation so the typed error reaches the
            # GraphQL caller intact.
            adv = await uow.application_driver_versions.get(
                id=deployment.application_driver_version_id
            )
            assert adv is not None, "Application driver version not found"
            known_names = [cc.name for cc in (adv.component_configs or [])]
            _validate_component_env_var_targets(deployment_config, known_names)

            # Reject component-level container command/args overrides that
            # target an unknown component or carry a malformed list, before
            # any reconcile (014 / FR-004, FR-006).
            _validate_component_container_overrides(deployment_config, known_names)

            # Image overrides: unknown component, then grammar and substitution at
            # the stored application version, so the error names the component (018).
            # Unchanged references skip the grammar check; unknown components are
            # rejected regardless, as for env vars and container overrides.
            validate_image_override_targets(deployment_config, known_names)
            prevalidate_image_overrides(
                deployment_config,
                version=deployment.application_version,
                stored_config=deployment.config,
            )

            # Pre-validate env-var bundles so the typed error codes
            # (INVALID_ENV_VAR_NAME / ENV_VAR_SIZE_LIMIT_EXCEEDED /
            # DUPLICATE_ENV_VAR_NAME) survive the GraphQL boundary instead of
            # being collapsed into INVALID_CONTEXT (FR-006/FR-007/FR-008/
            # FR-009 / SC-003).
            _prevalidate_deployment_env_vars(deployment_config)

            try:
                validate_deployment_config(context=deployment_config)
            except InvalidDeploymentContextError as e:
                raise InvalidContextError(str(e)) from e

            # updateDeployment never switches driver versions, so the pinned
            # version is the one the deployment keeps after this write (FR-003).
            _validate_component_container_targets(
                deployment_config, deployment.config, _containers_by_component(adv)
            )

        if deployment_name is not None:
            try:
                validated_name = validate_deployment_name(deployment_name)
            except ValueError as e:
                raise DeploymentNameValidationError(str(e)) from e

            if validated_name != deployment.name:
                existing = await uow.deployments.get_by_name(
                    validated_name, deployment.environment_id
                )
                if existing is not None:
                    raise DeploymentNameConflictError(
                        f"A deployment named '{validated_name}' already exists "
                        "in this environment"
                    )
                deployment.name = validated_name

        if deployment_config is not None:
            deployment.config = deployment_config

        await _ensure_ingress_controller(
            environment_id=deployment.environment_id,
            uow=uow,
            created_by_user_id=deployment.created_by_user_id,
        )

        if deployment_parameters is not None:
            application_driver_version = await uow.application_driver_versions.get(
                id=deployment.application_driver_version_id
            )
            assert application_driver_version is not None, (
                "Application driver version not found"
            )
            merged_parameters = {
                **deployment.parameters,
                **deployment_parameters,
            }
            definitions = parse_parameter_definitions(
                application_driver_version.parameters
            )
            deployment.parameters = validate_parameter_values(
                definitions=definitions,
                values=merged_parameters,
            )

        if service_name_overrides is not None:
            adv_for_services = await uow.application_driver_versions.get(
                id=deployment.application_driver_version_id
            )
            assert adv_for_services is not None
            service_defs = parse_service_definitions(adv_for_services.services)
            if service_defs:
                await reconcile_services_on_upgrade(
                    deployment_id=deployment.id,
                    environment_id=deployment.environment_id,
                    new_service_definitions=service_defs,
                    uow=uow,
                    service_name_overrides=service_name_overrides,
                )

        await uow.deployments.save(deployment=deployment)
        await uow.commit()
        logger.info(
            "Phase 1 committed: deployment_id={} (intent written to DB)",
            deployment.id,
        )

    # ---- Phase 2: regenerate instance against the freshly-committed DB ----
    # Re-entry is a logical boundary, NOT a new session. SqlModelUnitOfWork is
    # not nest-safe — __aenter__ rebuilds repository handles on the same
    # underlying AsyncSession. The phase separation is enforced by the
    # commit() above, which finalises phase 1's writes so that the find()
    # below performs a real DB round-trip and reads the post-commit state.

    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)
        assert deployment is not None, (
            "Deployment vanished between phase 1 commit and phase 2 load"
        )

        current_instance = deployment.active_instance
        new_instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
        )

        # No-op detection (spec 014 / FR-001): if the freshly-generated
        # candidate instance resolves to the current realised state, short
        # circuit before any side effect. The candidate is in-memory only
        # (generate_instance_from_deployment does not session.add), so
        # returning here leaves no orphan instance, dispatches no reconcile,
        # and leaves status + the active-instance pointer untouched.
        if _update_is_noop(
            current_instance=current_instance, new_instance=new_instance
        ):
            logger.info(
                "Update is a no-op for deployment_id={}; no instance persisted, "
                "no reconcile dispatched",
                deployment.id,
            )
            return None

        deployment.set_active_instance(instance=new_instance)
        deployment.set_status(DeploymentState.PENDING)
        logger.info("New instance set as active: instance_id={}", new_instance.id)

        task = await apply_state(
            deployment=deployment, current_instance=current_instance, uow=uow
        )

        await uow.deployments.save(deployment=deployment)
        await uow.tasks.save(task=task)
        await uow.commit()

        logger.info("Deployment config update committed, task_id={}", task.id)

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


def _driver_version_sort_key(
    driver_version: ApplicationDriverVersion,
) -> tuple[int, Version, float, UUID]:
    """Total "latest-wins" ordering key for application driver versions.

    Sorted descending (``max`` wins), the latest driver version is:

    1. the one with the highest *parseable* ``version`` string
       (:class:`packaging.version.Version`); unparseable version strings sort
       below all parseable ones;
    2. ties broken by ``created_on`` descending — most recently loaded wins
       (``None`` sorts oldest);
    3. final tie-break on ``id`` for a stable, total order.
    """
    try:
        parsed = Version(driver_version.version)
        parseable = 1
    except InvalidVersion:
        # Placeholder keeps the tuple comparable across rows; the
        # ``parseable`` flag guarantees unparseable rows never outrank
        # parseable ones.
        parsed = Version("0")
        parseable = 0
    created_ts = (
        driver_version.created_on.timestamp()
        if driver_version.created_on is not None
        else float("-inf")
    )
    return (parseable, parsed, created_ts, driver_version.id)


def _resolve_latest_matching_version(
    application_driver: ApplicationDriver,
    app_version: str,
) -> ApplicationDriverVersion | None:
    """Return the latest driver version supporting ``app_version``, if any.

    Among the driver's versions whose ``application_supported_versions``
    specifier matches the requested application version, pick the latest by
    :func:`_driver_version_sort_key` — never the implicit DB insertion order.
    """
    target = Version(app_version)
    candidates = [
        driver_version
        for driver_version in application_driver.versions
        if target in SpecifierSet(driver_version.application_supported_versions)
    ]
    if not candidates:
        return None
    return max(candidates, key=_driver_version_sort_key)


async def _load_pinned_driver_version(
    driver_version_id: UUID,
    application_driver: ApplicationDriver,
    uow: UnitOfWork,
) -> ApplicationDriverVersion:
    """Load an explicitly pinned driver version and check driver ownership."""
    pinned = await uow.application_driver_versions.get(id=driver_version_id)
    if pinned is None:
        raise DriverVersionNotFoundError(
            f"Application driver version {driver_version_id} not found"
        )
    if pinned.application_driver_id != application_driver.id:
        raise InvalidVersionError(
            f"Driver version {driver_version_id} does not belong to application "
            f"driver {application_driver.name}; cross-driver moves are not supported"
        )
    return pinned


def _ensure_pin_supports_version(
    pinned: ApplicationDriverVersion, version: str
) -> None:
    """Reject a pin whose specifier does not cover the requested version."""
    if Version(version) not in SpecifierSet(pinned.application_supported_versions):
        raise InvalidVersionError(
            f"Version {version} is not supported by driver version {pinned.id} "
            f"(supports {pinned.application_supported_versions})"
        )


async def update_deployment_version(
    deployment_id: UUID,
    version: str,
    uow: UnitOfWork,
    deployment_parameters: dict | None = None,
    driver_version_id: UUID | None = None,
) -> Task | None:
    """Update a deployment's application version and driver-version binding.

    The driver binding is always re-resolved: without an explicit pin the
    latest driver version (per :func:`_driver_version_sort_key`) whose
    specifier matches ``version`` is bound — so calling with the deployment's
    current application version moves it onto a newly loaded overlapping
    driver build.

    Returns ``None`` without dispatching a Task when the requested state
    already matches the persisted deployment (no-op detection, FR-002 /
    FR-006).

    Args:
        deployment_id (UUID): The ID of the deployment to update.
        version (str): The target application version.
        uow (UnitOfWork): The unit of work to use.
        deployment_parameters (dict | None): Parameter values to validate and
            persist; falls back to the deployment's current parameters.
        driver_version_id (UUID | None): Pin a specific driver version instead
            of latest-wins resolution. Must belong to the deployment's driver
            and support ``version``.

    Raises:
        InvalidContextError: If the context is invalid.
        DriverVersionNotFoundError: If the pinned driver version does not exist.
        InvalidVersionError: If no driver version (or the pinned one) supports
            ``version``, or the pin belongs to a different driver.
        InvalidImageReferenceError: If a stored image override applicable in the
            target driver version is invalid at ``version``.

    Returns:
        Task | None: The task created for the deployment update, or ``None``
            when the requested state matches the persisted deployment (no-op).
    """

    logger.info(
        "Upgrading deployment version: deployment_id={} target_version={}",
        deployment_id,
        version,
    )

    async with uow:
        # Get the deployment
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        logger.info(
            "Deployment found: id={} current_version={}",
            deployment.id,
            deployment.application_version,
        )

        # Get the application driver version
        application_driver_version = await uow.application_driver_versions.get(
            id=deployment.application_driver_version_id
        )
        assert application_driver_version is not None, "Version not found"

        # Resolve the target driver version. With an explicit pin, validate
        # it; otherwise always re-resolve to the latest driver version (per
        # _driver_version_sort_key) whose specifier matches the requested
        # application version — even when the currently bound version still
        # matches, so a newly loaded overlapping driver build is picked up.
        application_driver = await uow.application_drivers.get(
            id=application_driver_version.application_driver_id
        )
        assert application_driver is not None, "Application driver not found"

        if driver_version_id is not None:
            target_driver_version = await _load_pinned_driver_version(
                driver_version_id=driver_version_id,
                application_driver=application_driver,
                uow=uow,
            )
            _ensure_pin_supports_version(target_driver_version, version)
            logger.info(
                "Pinned driver version: id={} supports={}",
                target_driver_version.id,
                target_driver_version.application_supported_versions,
            )
        else:
            target_driver_version = _resolve_latest_matching_version(
                application_driver=application_driver,
                app_version=version,
            )
            if target_driver_version is None:
                raise InvalidVersionError(
                    f"Version {version} is not supported by the application driver {application_driver.name}"
                )
            logger.info(
                "Resolved latest matching driver version: id={} supports={}",
                target_driver_version.id,
                target_driver_version.application_supported_versions,
            )

        # Overrides applicable in the target driver version must still resolve at the
        # target application version (018 FR-009); reject before any task is dispatched.
        _validate_image_overrides_for_version(
            deployment.config, _containers_by_component(target_driver_version), version
        )

        # After validation: creating the ingress deployment dispatches its flow run immediately.
        await _ensure_ingress_controller(
            environment_id=deployment.environment_id,
            uow=uow,
            created_by_user_id=deployment.created_by_user_id,
        )

        if target_driver_version.id != deployment.application_driver_version_id:
            # Store components state
            components_state = {}
            for component in deployment.components:
                components_state[component.name] = component.enabled

            # Recreate the components from the target driver version,
            # preserving the enabled state of same-named components.
            deployment.set_components(
                [
                    Component.create(
                        name=component_config.name,
                        config=component_config.config,
                        enabled=components_state.get(component_config.name, True),
                    )
                    for component_config in target_driver_version.component_configs
                ]
            )

            # Bind the new version to the deployment
            deployment.application_driver_version_id = target_driver_version.id
            logger.info(
                "Switched driver version: old={} new={} ({} components recreated with preserved state)",
                application_driver_version.id,
                target_driver_version.id,
                len(target_driver_version.component_configs),
            )
        else:
            logger.info(
                "Driver version binding unchanged: id={}",
                target_driver_version.id,
            )

        # The driver version used for parameter validation and the new instance
        effective_driver_version = target_driver_version

        # Validate parameters against the new driver version's definitions
        # User-provided parameters take priority, then existing, then None
        definitions = parse_parameter_definitions(effective_driver_version.parameters)
        values_to_validate = (
            deployment_parameters
            if deployment_parameters is not None
            else deployment.parameters
        )
        resolved_parameters = validate_parameter_values(
            definitions=definitions,
            values=values_to_validate,
        )
        # Snapshot the pre-mutation desired-state fields so the no-op path can
        # leave the deployment exactly as it found it (FR-002 / FR-006). The
        # no-op return happens before save/commit, so the DB row is never
        # written; restoring the in-memory object too keeps the entity
        # consistent for any caller that retains the reference.
        status_before = deployment.status
        version_before = deployment.application_version
        parameters_before = deployment.parameters

        deployment.parameters = resolved_parameters

        # Update the deployment version
        deployment.application_version = version
        deployment.set_status(DeploymentState.DEPLOYING)

        # Get the current instance
        current_instance = deployment.active_instance

        # Generate the instance from the updated deployment
        logger.info(
            "Generating new instance for version upgrade: {} -> {}",
            current_instance.application_version if current_instance else "None",
            version,
        )
        new_instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
        )

        # No-op detection (spec 014 / FR-002): requesting the deployment's
        # current version (with no other change) resolves to the current
        # realised instance. Short circuit before any side effect — no new
        # instance persisted, no reconcile dispatched. The in-memory mutations
        # above (status -> DEPLOYING, version, parameters) are never saved or
        # committed on this path, so the persisted deployment is untouched.
        if _update_is_noop(
            current_instance=current_instance, new_instance=new_instance
        ):
            # Roll back the in-memory desired-state mutations so the entity is
            # left untouched (status/version/parameters), mirroring the fact
            # that nothing is saved or committed on this path.
            deployment.application_version = version_before
            deployment.parameters = parameters_before
            deployment.set_status(status_before)
            logger.info(
                "Version update is a no-op for deployment_id={} version={}; "
                "no instance persisted, no reconcile dispatched",
                deployment.id,
                version,
            )
            return None

        # Set the new instance as the active one
        deployment.set_active_instance(instance=new_instance)
        logger.info("New instance set as active: instance_id={}", new_instance.id)

        # Get the task from the reconciliation workflow
        task = await apply_state(
            deployment=deployment, current_instance=current_instance, uow=uow
        )

        await uow.deployments.save(deployment=deployment)

        # Reconcile deployed services for the new driver version. Preserve
        # the existing ``service_name_overrides`` — ``upgrade_deployment_version``
        # doesn't accept an ``overrides`` parameter (unlike
        # ``update_deployment``), so the intent is "keep whatever was in
        # effect for the deployment". Without this, an upgrade silently
        # renames the service back to the driver's default name, which
        # collides with any sibling deployment relying on that name.
        existing_services = await uow.deployed_services.get_by_deployment_id(
            deployment.id
        )
        existing_overrides = {
            svc.driver_service_name: svc.resolved_name
            for svc in existing_services
            if svc.resolved_name != svc.driver_service_name
        }
        new_service_defs = parse_service_definitions(effective_driver_version.services)
        if new_service_defs:
            await reconcile_services_on_upgrade(
                deployment_id=deployment.id,
                environment_id=deployment.environment_id,
                new_service_definitions=new_service_defs,
                uow=uow,
                service_name_overrides=existing_overrides or None,
            )
        else:
            # New driver version has no services — remove any existing ones
            from styrmin_backend.services.services_discovery import (
                delete_services_for_deployment,
            )

            await delete_services_for_deployment(deployment_id=deployment.id, uow=uow)

        await uow.tasks.save(task=task)
        await uow.commit()

        logger.info(
            "Version upgrade committed: deployment_id={} version={} task_id={}",
            deployment.id,
            version,
            task.id,
        )

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


async def redeploy_for_environment_update(
    deployment: Deployment,
    uow: UnitOfWork,
) -> Task | None:
    """Redeploy a deployment in response to an environment-config change.

    Generates a new :class:`ApplicationInstance` from the deployment (which
    now resolves against the just-updated environment config flowing through
    :func:`_resolve_instance_context`), sets it as the active instance,
    transitions the deployment into ``DEPLOYING``, dispatches the
    reconciliation Task via :func:`apply_state`, and persists the deployment.
    Returns the dispatched Task so the caller (the env-config fanout in
    :func:`services.environments.update_environment`) can collect it.

    The helper does NOT change the deployment's ``application_version``,
    ``parameters``, or service overrides — it only regenerates the active
    instance against the deployment's current bound driver. This is the
    "redeploy at the current version" primitive that the env-config fanout
    needs (data-model.md §2.3 / FR-006/FR-010).

    Mirrors the post-version-decision portion of
    :func:`update_deployment_version` (the steps that run after the version
    is decided and the new driver/components are bound). Kept as a separate
    function rather than refactoring ``update_deployment_version`` to call
    it: ``update_deployment_version`` carries extra version-specific
    bookkeeping (service-overrides preservation, services-discovery
    reconcile on driver change) that is not relevant to a same-version
    redeploy. The duplication is intentional and bounded — see the comment
    inside ``update_deployment_version`` for the cross-reference.

    Returns ``None`` without touching the deployment when it is ``RESTORING``:
    a restore is about to delete and recreate that namespace wholesale, so a
    concurrent ``apply_state`` races Velero for the same objects with an
    undefined outcome. ``restore_environment_backup`` already excludes the
    deployments it is restoring by construction; this guard closes the gap
    ADR-055 flagged for restores started outside the current fan-out — and it
    is what protects a clone's counterparts, which sit in ``RESTORING`` until
    their cross-target restore lands (research D8).
    """
    if deployment.status == DeploymentState.RESTORING:
        logger.info(
            "redeploy_skipped_restoring deployment_id={} environment_id={}",
            deployment.id,
            deployment.environment_id,
        )
        return None

    current_instance = deployment.active_instance

    new_instance = await generate_instance_from_deployment(
        deployment=deployment,
        uow=uow,
    )
    deployment.set_active_instance(instance=new_instance)
    deployment.set_status(DeploymentState.DEPLOYING)

    task = await apply_state(
        deployment=deployment,
        current_instance=current_instance,
        uow=uow,
    )

    await uow.deployments.save(deployment=deployment)
    await uow.tasks.save(task=task)

    return task


async def _resolve_dedicated_ingress(
    environment_id: UUID,
    uow: UnitOfWork,
) -> DedicatedIngressConfig | None:
    """Resolve the effective dedicated_ingress config for an environment.

    Checks environment config first, falls back to cluster config.
    """
    environment = await uow.environments.get(environment_id)
    if environment is None:
        return None

    env_config = environment.config or {}
    if env_config.get("dedicated_ingress"):
        return DedicatedIngressConfig.model_validate(env_config["dedicated_ingress"])

    cluster = await uow.clusters.get(environment.cluster_id)
    if cluster is None:
        return None

    cluster_config = cluster.config or {}
    if cluster_config.get("dedicated_ingress"):
        return DedicatedIngressConfig.model_validate(
            cluster_config["dedicated_ingress"]
        )

    return None


async def _ensure_ingress_controller(
    environment_id: UUID,
    uow: UnitOfWork,
    created_by_user_id: UUID,
) -> None:
    """Ensure a dedicated ingress controller is deployed for the environment.

    If dedicated_ingress is configured and no internal deployment exists,
    creates one. If one exists but is not healthy, raises an error.
    If dedicated_ingress is not configured, does nothing.

    Args:
        created_by_user_id: Attribution for the system-managed internal
            deployment when it must be created. Threaded through from the
            outer mutation so the FK to ``user`` is satisfied.
    """
    dedicated_ingress = await _resolve_dedicated_ingress(environment_id, uow)
    if dedicated_ingress is None:
        return

    # Check for existing internal ingress deployment
    existing = await uow.deployments.find_internal_by_environment(environment_id)
    if existing is not None:
        if existing.status == DeploymentState.RUNNING:
            return
        if existing.status == DeploymentState.FAILED:
            raise IngressControllerNotHealthyError(
                "The dedicated ingress controller has failed. "
                "Resolve the ingress controller issue before deploying applications."
            )
        # PENDING — still deploying, let it proceed
        return

    # Create the internal ingress controller deployment
    ingress_driver = await uow.application_drivers.get_by_name(
        name=INTERNAL_DRIVER_NAME
    )
    if ingress_driver is None:
        raise ApplicationDriverNotFoundError(
            f"Internal driver '{INTERNAL_DRIVER_NAME}' not found. "
            "Ensure Styrmin startup completed successfully."
        )

    # Find the driver version (latest by the canonical ordering)
    if not ingress_driver.versions:
        raise ApplicationDriverNotFoundError(
            f"No version found for internal driver '{INTERNAL_DRIVER_NAME}'"
        )
    ingress_driver_version = max(ingress_driver.versions, key=_driver_version_sort_key)

    logger.info(
        "Creating internal ingress controller deployment for environment={}",
        environment_id,
    )

    existing_names = await uow.deployments.find_names_with_prefix(
        INTERNAL_DRIVER_NAME, environment_id
    )
    ingress_name = generate_deployment_name(INTERNAL_DRIVER_NAME, existing_names)

    ingress_deployment = Deployment.create(
        application_version=ingress_driver_version.version,
        application_driver_version_id=ingress_driver_version.id,
        environment_id=environment_id,
        created_by_user_id=created_by_user_id,
        internal=True,
        name=ingress_name,
    )

    current_instance = ingress_deployment.active_instance
    instance = await generate_instance_from_deployment(
        deployment=ingress_deployment,
        uow=uow,
    )
    ingress_deployment.set_active_instance(instance=instance)

    ingress_task = await apply_state(
        deployment=ingress_deployment,
        current_instance=current_instance,
        uow=uow,
    )

    await uow.deployments.save(ingress_deployment)
    await uow.tasks.save(ingress_task)


async def deploy_application(
    driver_name: str,
    version: str | None,
    environment_id: UUID,
    uow: UnitOfWork,
    created_by_user_id: UUID,
    deployment_config: dict | None = None,
    deployment_parameters: dict | None = None,
    deployment_name: str | None = None,
    service_name_overrides: dict[str, str] | None = None,
    driver_version_id: UUID | None = None,
    skip_initial_reconcile: bool = False,
    release_reference: str | None = None,
) -> Task | None:
    """Instantiate an application in the given environment.

    Args:
        driver_name: The name of the application driver.
        version: The version of the application. If None or empty, the driver's
            default_version is used (from the pinned driver version when one is
            given, otherwise from the latest driver version declaring one).
        environment_id: The id of the environment to instantiate the application in.
        uow: The unit of work to use.
        created_by_user_id: The id of the user creating the deployment. Used for
            audit attribution exposed via ``Deployment.createdBy`` in the API.
        deployment_config: Optional deployment configuration.
        deployment_parameters: Optional parameter values.
        deployment_name: Optional custom name for the deployment. If not provided,
            a name is auto-generated as <driver_name>-<N>.
        driver_version_id: Pin a specific driver version instead of latest-wins
            resolution. Must belong to ``driver_name`` and support the resolved
            application version.
        skip_initial_reconcile: Create the deployment without dispatching the
            initial ``apply_state`` reconciliation, and start it in the
            ``RESTORING`` state instead of ``PENDING``. Used for an
            environment clone's counterpart deployments (research D5): the
            cross-target restore rebuilds their namespace from the capture and
            deletes whatever is in it first, so reconciling here would only
            create resources the restore immediately destroys. Everything
            else still runs — ``_ensure_ingress_controller`` (whose internal
            ingress deployment is never part of a capture),
            ``create_services_for_deployment`` and
            ``generate_instance_from_deployment`` — because the counterpart's
            service rows and instance context are what the restore's recovery
            step builds its CR body from. Returns ``None`` in this mode, since
            no Task is dispatched. The ``RESTORING`` state also makes the
            existing restoring-deployment mutation guards protect the
            counterpart until its restore lands (research D8).
        release_reference: Pin the deployment's Helm release name instead of
            deriving ``styrmin-<deployment id>``. Only the clone flow passes
            it: a counterpart **adopts the source's release name** so the
            restored Helm release, its storage record and the
            ``meta.helm.sh/release-*`` ownership annotations on the restored
            chart objects all agree, and Flux performs an *upgrade* rather
            than an install that would fail Helm's ownership check (research
            D2). The value sticks for the deployment's whole life — see
            ``services.context._resolve_release_reference``.

    Raises:
        InvalidContextError: If the context is invalid.
        DeploymentNameValidationError: If the provided name is invalid.
        DeploymentNameConflictError: If the provided name is already in use.
        DriverVersionNotFoundError: If the pinned driver version does not exist.
        InvalidVersionError: If no driver version (or the pinned one) supports
            the resolved version, or the pin belongs to a different driver.

    Returns:
        Task: the task created for the application instantiation, or ``None``
        when ``skip_initial_reconcile`` is set (no reconciliation dispatched).
    """

    if deployment_config is None:
        deployment_config = {}

    # Pydantic validation runs after driver lookup so we can surface the
    # typed ``UnknownComponentEnvVarError`` (FR-010) ahead of the generic
    # context-validation error.

    # Treat empty string as no version provided
    if version is not None and version.strip() == "":
        version = None

    async with uow:
        # Get the application
        application = await uow.application_drivers.get_by_name(name=driver_name)
        if application is None:
            raise ApplicationDriverNotFoundError(
                f"Application driver {driver_name} not found in the database"
            )

        # Explicit pin: validate ownership, derive the version from the pin's
        # default when none was provided, then check the pin's specifier.
        pinned_driver_version = None
        if driver_version_id is not None:
            pinned_driver_version = await _load_pinned_driver_version(
                driver_version_id=driver_version_id,
                application_driver=application,
                uow=uow,
            )
            if version is None:
                version = pinned_driver_version.default_version
                if version is None:
                    raise InvalidVersionError(
                        f"No version specified and pinned driver version "
                        f"{pinned_driver_version.id} declares no default version"
                    )
            _ensure_pin_supports_version(pinned_driver_version, version)

        # If no version provided, resolve the default_version declared by the
        # latest driver version (per _driver_version_sort_key) that has one.
        if version is None:
            version = next(
                (
                    driver_version.default_version
                    for driver_version in sorted(
                        application.versions,
                        key=_driver_version_sort_key,
                        reverse=True,
                    )
                    if driver_version.default_version
                ),
                None,
            )
            if version is None:
                raise InvalidVersionError(
                    f"No version specified and no default version found for driver {driver_name}"
                )

        # Get the application driver version: the pin when given, otherwise
        # the latest driver version whose specifier matches the version.
        application_driver_version = (
            pinned_driver_version
            if pinned_driver_version is not None
            else _resolve_latest_matching_version(
                application_driver=application, app_version=version
            )
        )

        if application_driver_version is None:
            raise InvalidVersionError(
                f"Version {version} is not supported by the application driver {driver_name}"
            )

        # Reject component-level env var blocks targeting components the
        # selected driver does not declare (FR-010). Surface
        # ``UnknownComponentEnvVarError`` with ``UNKNOWN_COMPONENT_ENV_VAR``
        # ahead of Pydantic-driven config validation so the typed error
        # reaches the GraphQL caller.
        known_names = [
            cc.name for cc in (application_driver_version.component_configs or [])
        ]
        _validate_component_env_var_targets(deployment_config, known_names)

        # Reject component-level container command/args overrides submitted at
        # create time (via the deploy mutation's config JSON) that target an
        # unknown component or carry a malformed list, before any reconcile
        # (014 / FR-002 covers both deploy and update flows; FR-004, FR-006).
        _validate_component_container_overrides(deployment_config, known_names)

        # Image overrides: unknown component, then grammar and substitution at
        # the requested application version, so the error names the component (018).
        validate_image_override_targets(deployment_config, known_names)
        prevalidate_image_overrides(deployment_config, version=version)

        # Pre-validate env-var bundles so the typed error codes
        # (INVALID_ENV_VAR_NAME / ENV_VAR_SIZE_LIMIT_EXCEEDED /
        # DUPLICATE_ENV_VAR_NAME) survive the GraphQL boundary instead of
        # being collapsed into INVALID_CONTEXT (FR-006/FR-007/FR-008/FR-009 /
        # SC-003).
        _prevalidate_deployment_env_vars(deployment_config)

        try:
            validate_deployment_config(context=deployment_config)
        except InvalidDeploymentContextError as e:
            raise InvalidContextError(str(e)) from e

        # A new deployment has no stored values: every block is an addition.
        _validate_component_container_targets(
            deployment_config,
            None,
            _containers_by_component(application_driver_version),
        )

        # Get the environment
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment {environment_id} could not be found"
            )

        # Ensure dedicated ingress controller is deployed if configured (FR-009).
        # The internal ingress deployment is system-managed; we attribute it to
        # the user who triggered the first deploy in the environment so the FK
        # to ``user`` is satisfied and the audit trail still resolves.
        await _ensure_ingress_controller(
            environment_id=environment_id,
            uow=uow,
            created_by_user_id=created_by_user_id,
        )

        # Validate and resolve parameter values against driver definitions
        definitions = parse_parameter_definitions(application_driver_version.parameters)
        resolved_parameters = validate_parameter_values(
            definitions=definitions,
            values=deployment_parameters,
        )

        # Resolve deployment name. Uniqueness scope is per-environment
        # and ignores tombstoned deployments (so operators can reuse
        # the name of a previously-deleted deployment in the same env).
        resolved_name: str
        if deployment_name and deployment_name.strip():
            try:
                resolved_name = validate_deployment_name(deployment_name)
            except ValueError as e:
                raise DeploymentNameValidationError(str(e)) from e

            existing = await uow.deployments.get_by_name(resolved_name, environment_id)
            if existing is not None:
                raise DeploymentNameConflictError(
                    f"A deployment named '{resolved_name}' already exists "
                    "in this environment"
                )
        else:
            # Auto-generate name from driver name. Tombstoned names are
            # excluded from the prefix search so the auto-generator can
            # reclaim the lowest free suffix.
            existing_names = await uow.deployments.find_names_with_prefix(
                driver_name, environment_id
            )
            resolved_name = generate_deployment_name(driver_name, existing_names)

        # Create the deployment
        deployment = Deployment.create(
            application_version=version,
            application_driver_version_id=application_driver_version.id,
            environment_id=environment_id,
            created_by_user_id=created_by_user_id,
            config=deployment_config,
            parameters=resolved_parameters,
            name=resolved_name,
        )

        if skip_initial_reconcile:
            # A counterpart is not "pending deployment" — it is waiting on its
            # cross-target restore, and the existing restoring-deployment
            # guards keep ordinary mutations off it until then (research D8).
            deployment.set_status(DeploymentState.RESTORING)

        for component in application_driver_version.component_configs:
            deployment.add_component(
                component=Component.create(
                    name=component.name, config=component.config, enabled=True
                ),
            )

        # Save deployment early so deployed-service FK constraint is satisfied
        await uow.deployments.save(deployment=deployment)

        # Create deployed service records if driver declares services.
        # Must happen before context generation so the context query
        # finds this deployment's own services (has_own_services).
        service_definitions = parse_service_definitions(
            application_driver_version.services
        )
        if service_definitions:
            await create_services_for_deployment(
                deployment_id=deployment.id,
                environment_id=environment_id,
                service_definitions=service_definitions,
                uow=uow,
                service_name_overrides=service_name_overrides,
            )

        current_instance = deployment.active_instance
        # Generate the instance from the deployment
        instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
            release_reference=release_reference,
        )
        # Set the new instance as the active one
        deployment.set_active_instance(instance=instance)

        if skip_initial_reconcile:
            # No apply_state: the deployment row, its services and its active
            # instance are persisted, but nothing is reconciled into the
            # cluster. The caller (the clone flow) drives convergence through
            # the cross-target restore instead.
            await uow.deployments.save(deployment=deployment)
            await uow.commit()
            logger.info(
                "deploy_application_reconcile_skipped deployment_id={} "
                "environment_id={} instance_id={}",
                deployment.id,
                environment_id,
                instance.id,
            )
            return None

        # Get the task from the reconciliation workflow
        task = await apply_state(
            deployment=deployment, current_instance=current_instance, uow=uow
        )

        # Save again to persist active_application_instance_id
        await uow.deployments.save(deployment=deployment)

        await uow.tasks.save(task=task)

        await uow.commit()

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


_DELETE_ALLOWED_STATES = {
    DeploymentState.PENDING,
    DeploymentState.DEPLOYING,
    DeploymentState.RUNNING,
    DeploymentState.FAILED,
}


async def delete_deployment(
    deployment_id: UUID,
    uow: UnitOfWork,
) -> Task:
    """Request deletion of a deployment.

    Patches ``spec.deletionRequested = true`` on the cluster-side
    StyrminDeployment CRD and creates a born-complete ``DELETE_DEPLOYMENT``
    task as the audit record. The operator drives teardown asynchronously;
    callers observe ``Deployment.status`` transition through ``DELETING``
    to ``DELETED`` via the existing reconciliation status reporter.

    Idempotent: a second call while the deployment is already ``DELETING``
    returns the most recent existing ``DELETE_DEPLOYMENT`` task without
    re-issuing the patch. A call against a deployment in ``DELETED`` raises
    ``DeploymentNotFoundError`` (intentional conflation with unknown id).

    Raises:
        DeploymentNotFoundError: id is unknown OR the deployment is already
            tombstoned (status DELETED / deleted_at set).
        DeploymentRestoringError: the deployment is currently restoring;
            deletion is refused for data-integrity reasons.
    """
    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None or deployment.deleted_at is not None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        if deployment.status == DeploymentState.DELETED:
            # Defence in depth: deleted_at IS NULL was the primary guard
            # above; this branch covers the (impossible-but-cheap) case
            # where status is DELETED with deleted_at unset.
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        if deployment.status == DeploymentState.RESTORING:
            raise DeploymentRestoringError()

        if deployment.status == DeploymentState.DELETING:
            # Idempotent: return the most recent existing DELETE_DEPLOYMENT
            # task without issuing a new patch. find_by_deployment is
            # ordered newest-first (see repository/tasks.py).
            existing_tasks = await uow.tasks.find_by_deployment(deployment_id)
            for prior in existing_tasks:
                if prior.type == TaskType.DELETE_DEPLOYMENT:
                    return prior
            # Fall through if no prior task exists (e.g. legacy migrated row).

        if deployment.status not in _DELETE_ALLOWED_STATES and (
            deployment.status != DeploymentState.DELETING
        ):
            # This should not happen given the enum is closed, but keep an
            # explicit guard so future state additions surface a clear error.
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} cannot be deleted from "
                f"state {deployment.status.value}"
            )

        # Patch the CRD spec. The CR name and namespace both follow the
        # `styrmin-{deployment_id}` convention (CR name == namespace for
        # platform-managed deployments).
        crd_name = get_kubernetes_reference(deployment_id)
        await patch_custom_resource(
            plural=CRD_PLURAL,
            reference=crd_name,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=crd_name,
            patch=[{"op": "add", "path": "/spec/deletionRequested", "value": True}],
        )

        # Create a born-complete DELETE_DEPLOYMENT task. This is the audit
        # record on the deployment timeline, not a progress channel — the
        # mutation acks immediately; cluster-side teardown is observed via
        # the status reporter (see services/deployment_status.py).
        task = Task(
            id=uuid4(),
            type=TaskType.DELETE_DEPLOYMENT,
            deployment_id=deployment_id,
            status=TaskStatus.SUCCESS,
            prefect_flow_run_id=None,
        )
        await uow.tasks.save(task=task)
        await uow.commit()

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result


async def request_cluster_teardown(deployment_id: UUID) -> bool:
    """Ask the operator to tear a deployment's cluster resources down.

    Flips ``spec.deletionRequested`` on the ``StyrminDeployment`` CR — the same
    single signal :func:`delete_deployment` uses. The operator's
    ``deletionRequested`` handler removes the Services, the HelmRelease (so Flux
    uninstalls the chart), the NetworkPolicies and Secrets, and finally the
    namespace itself.

    Unlike :func:`delete_deployment` this writes nothing to the database and
    enforces no state guard, because its caller —
    :func:`~styrmin_backend.services.environments.delete_environment` — removes
    the deployment *rows* wholesale and must work from any state, including the
    ``RESTORING`` counterparts of an in-flight clone (spec SC-005: discarding a
    clone is always allowed).

    Best-effort by design: a deployment whose CR was never created (a clone
    counterpart that never reconciled) or that is already torn down has nothing
    to patch, and an unreachable cluster must not strand the database rows that
    keep the environment undeletable.

    Returns:
        ``True`` when the CR was patched, ``False`` when it could not be.
    """
    crd_name = get_kubernetes_reference(deployment_id)
    try:
        await patch_custom_resource(
            plural=CRD_PLURAL,
            reference=crd_name,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=crd_name,
            patch=[{"op": "add", "path": "/spec/deletionRequested", "value": True}],
        )
    except Exception as exc:
        logger.warning(
            "deployment_teardown_request_failed deployment_id={} error={}",
            deployment_id,
            exc,
        )
        return False
    return True
