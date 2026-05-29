from uuid import UUID, uuid4

from loguru import logger
from packaging.specifiers import SpecifierSet
from packaging.version import Version

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
from styrmin_backend.operator.config import CRD_GROUP, CRD_PLURAL, CRD_VERSION
from styrmin_backend.services.container_overrides.exceptions import (
    UnknownComponentContainerOverrideError,
)
from styrmin_backend.services.container_overrides.validator import (
    validate_container_override,
)
from styrmin_backend.services.env_vars.exceptions import (
    UnknownComponentEnvVarError,
)
from styrmin_backend.services.env_vars.validator import validate_env_vars_dict
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    DeploymentNameConflictError,
    DeploymentNameValidationError,
    DeploymentNotFoundError,
    DeploymentRestoringError,
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
) -> Task:
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
        Task: The task created for the deployment update.
    """
    logger.info("Updating deployment for deployment_id={}", deployment_id)

    if (
        deployment_config is None
        and deployment_name is None
        and deployment_parameters is None
        and service_name_overrides is None
    ):
        raise InvalidContextError(
            "At least one of config, parameters, name, or serviceNameOverrides must be provided"
        )

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

            # Pre-validate env-var bundles so the typed error codes
            # (INVALID_ENV_VAR_NAME / ENV_VAR_SIZE_LIMIT_EXCEEDED /
            # DUPLICATE_ENV_VAR_NAME) survive the GraphQL boundary instead of
            # being collapsed into INVALID_CONTEXT (FR-006/FR-007/FR-008/
            # FR-009 / SC-003).
            _prevalidate_deployment_env_vars(deployment_config)

            try:
                validate_deployment_config(context=deployment_config)
            except InvalidDeploymentContextError as e:
                raise InvalidContextError() from e

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


async def update_deployment_version(
    deployment_id: UUID,
    version: str,
    uow: UnitOfWork,
    deployment_parameters: dict | None = None,
) -> Task:
    """Update a deployment with the given configuration.

    Args:
        deployment_id (UUID): The ID of the deployment to update.
        deployment_config (dict): The new configuration for the deployment.
        uow (UnitOfWork): The unit of work to use.

    Raises:
        InvalidContextError: If the context is invalid.

    Returns:
        Task: The task created for the deployment update.
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

        # Ensure dedicated ingress controller is healthy if configured
        await _ensure_ingress_controller(
            environment_id=deployment.environment_id,
            uow=uow,
            created_by_user_id=deployment.created_by_user_id,
        )

        # Get the application driver version
        application_driver_version = await uow.application_driver_versions.get(
            id=deployment.application_driver_version_id
        )
        assert application_driver_version is not None, "Version not found"

        # Check if the version is supported by the application driver
        new_application_driver_version = None
        if Version(version) not in SpecifierSet(
            application_driver_version.application_supported_versions
        ):
            logger.info(
                "Version {} not supported by current driver version (supports {}), searching for compatible driver version",
                version,
                application_driver_version.application_supported_versions,
            )
            # Check if the version is supported by another application driver version
            application_driver = await uow.application_drivers.get(
                id=application_driver_version.application_driver_id
            )
            assert application_driver is not None, "Application driver not found"
            for driver_version in application_driver.versions:
                if Version(version) in SpecifierSet(
                    driver_version.application_supported_versions
                ):
                    new_application_driver_version = driver_version
                    break

            # If the version is not supported by any application driver version, raise an error
            if new_application_driver_version is None:
                raise InvalidVersionError(
                    f"Version {version} is not supported by the application driver {application_driver.name}"
                )

            logger.info(
                "Found compatible driver version: id={} supports={}",
                new_application_driver_version.id,
                new_application_driver_version.application_supported_versions,
            )

            # Store components state
            components_state = {}
            for component in deployment.components:
                components_state[component.name] = component.enabled

            # Bind the new version to the deployment
            deployment.application_driver_version_id = new_application_driver_version.id
            logger.info(
                "Switched driver version: old={} new={}",
                application_driver_version.id,
                new_application_driver_version.id,
            )

            # Recreate the components
            for component_config in new_application_driver_version.component_configs:
                deployment.add_component(
                    component=Component.create(
                        name=component_config.name,
                        config=component_config.config,
                        enabled=components_state.get(component_config.name, True),
                    ),
                )
            logger.info(
                "Recreated {} components with preserved state",
                len(new_application_driver_version.component_configs),
            )
        else:
            logger.info(
                "Version {} supported by current driver version (supports {})",
                version,
                application_driver_version.application_supported_versions,
            )

        # Determine the effective driver version for parameter validation
        effective_driver_version = (
            new_application_driver_version
            if new_application_driver_version is not None
            else application_driver_version
        )

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
) -> Task:
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
    """
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

    # Find the driver version
    ingress_driver_version = None
    for dv in ingress_driver.versions:
        ingress_driver_version = dv
        break

    if ingress_driver_version is None:
        raise ApplicationDriverNotFoundError(
            f"No version found for internal driver '{INTERNAL_DRIVER_NAME}'"
        )

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
) -> Task:
    """Instantiate an application in the given environment.

    Args:
        driver_name: The name of the application driver.
        version: The version of the application. If None or empty, the driver's
            default_version is used.
        environment_id: The id of the environment to instantiate the application in.
        uow: The unit of work to use.
        created_by_user_id: The id of the user creating the deployment. Used for
            audit attribution exposed via ``Deployment.createdBy`` in the API.
        deployment_config: Optional deployment configuration.
        deployment_parameters: Optional parameter values.
        deployment_name: Optional custom name for the deployment. If not provided,
            a name is auto-generated as <driver_name>-<N>.

    Raises:
        InvalidContextError: If the context is invalid.
        DeploymentNameValidationError: If the provided name is invalid.
        DeploymentNameConflictError: If the provided name is already in use.

    Returns:
        Task: the task created for the application instantiation.
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

        # If no version provided, resolve from driver's default_version
        if version is None:
            for driver_version in application.versions:
                if driver_version.default_version:
                    version = driver_version.default_version
                    break
            if version is None:
                raise InvalidVersionError(
                    f"No version specified and no default version found for driver {driver_name}"
                )

        # Get the application driver version
        application_driver_version = None
        for driver_version in application.versions:
            if Version(version) in SpecifierSet(
                driver_version.application_supported_versions
            ):
                application_driver_version = driver_version
                break

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
        )
        # Set the new instance as the active one
        deployment.set_active_instance(instance=instance)

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
