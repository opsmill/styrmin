from uuid import UUID

from fast_depends import Depends, inject
from loguru import logger
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from styrmin_backend.context.exceptions import InvalidDeploymentContextError
from styrmin_backend.context.validators import validate_deployment_config
from styrmin_backend.domain.models import (
    BackupDisposition,
    Component,
    Deployment,
    DeploymentState,
    Task,
    TaskType,
)
from styrmin_backend.domain.utils import (
    generate_deployment_name,
    validate_deployment_name,
)
from styrmin_backend.context.models.config import DedicatedIngressConfig
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    DeploymentAlreadyDeletedError,
    DeploymentMutationInProgressError,
    DeploymentNameConflictError,
    DeploymentNameValidationError,
    DeploymentNotFoundError,
    EnvironmentNotFoundError,
    IngressControllerNotHealthyError,
    InvalidContextError,
    InvalidVersionError,
)
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.manager import PrefectManager
from styrmin_backend.workflows.models import PrefectAction
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
            environment_id=deployment.environment_id, uow=uow
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

    if deployment_config is not None:
        try:
            validate_deployment_config(context=deployment_config)
        except InvalidDeploymentContextError as e:
            raise InvalidContextError() from e

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

        # Update deployment name if provided
        if deployment_name is not None:
            try:
                validated_name = validate_deployment_name(deployment_name)
            except ValueError as e:
                raise DeploymentNameValidationError(str(e)) from e

            # Allow same-name no-op
            if validated_name != deployment.name:
                existing = await uow.deployments.get_by_name(validated_name)
                if existing is not None:
                    raise DeploymentNameConflictError(
                        f"A deployment named '{validated_name}' already exists"
                    )
                deployment.name = validated_name

        # Update the deployment config if provided
        if deployment_config is not None:
            deployment.config = deployment_config
        # Ensure dedicated ingress controller is healthy if configured
        await _ensure_ingress_controller(
            environment_id=deployment.environment_id, uow=uow
        )

        # Update the deployment config
        deployment.config = deployment_config

        # Merge and validate parameters if provided
        if deployment_parameters is not None:
            application_driver_version = await uow.application_driver_versions.get(
                id=deployment.application_driver_version_id
            )
            assert application_driver_version is not None, (
                "Application driver version not found"
            )

            # Merge: existing values as base, new values override
            merged_parameters = {
                **deployment.parameters,
                **deployment_parameters,
            }

            definitions = parse_parameter_definitions(
                application_driver_version.parameters
            )
            resolved_parameters = validate_parameter_values(
                definitions=definitions,
                values=merged_parameters,
            )
            deployment.parameters = resolved_parameters

        # Get the current instance
        current_instance = deployment.active_instance

        # Generate the instance from the updated deployment
        logger.info("Generating new instance from updated deployment config")
        new_instance = await generate_instance_from_deployment(
            deployment=deployment,
            uow=uow,
        )

        # Set the new instance as the active one
        deployment.set_active_instance(instance=new_instance)
        deployment.set_status(DeploymentState.PENDING)
        logger.info("New instance set as active: instance_id={}", new_instance.id)

        # Get the task from the reconciliation workflow
        task = await apply_state(
            deployment=deployment, current_instance=current_instance, uow=uow
        )

        await uow.deployments.save(deployment=deployment)

        # Reconcile deployed services if overrides changed
        if service_name_overrides is not None:
            application_driver_version_for_services = (
                await uow.application_driver_versions.get(
                    id=deployment.application_driver_version_id
                )
            )
            assert application_driver_version_for_services is not None
            service_defs = parse_service_definitions(
                application_driver_version_for_services.services
            )
            if service_defs:
                await reconcile_services_on_upgrade(
                    deployment_id=deployment.id,
                    environment_id=deployment.environment_id,
                    new_service_definitions=service_defs,
                    uow=uow,
                    service_name_overrides=service_name_overrides,
                )

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
            environment_id=deployment.environment_id, uow=uow
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
) -> None:
    """Ensure a dedicated ingress controller is deployed for the environment.

    If dedicated_ingress is configured and no internal deployment exists,
    creates one. If one exists but is not healthy, raises an error.
    If dedicated_ingress is not configured, does nothing.
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

    existing_names = await uow.deployments.find_names_with_prefix(INTERNAL_DRIVER_NAME)
    ingress_name = generate_deployment_name(INTERNAL_DRIVER_NAME, existing_names)

    ingress_deployment = Deployment.create(
        application_version=ingress_driver_version.version,
        application_driver_version_id=ingress_driver_version.id,
        environment_id=environment_id,
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

    try:
        validate_deployment_config(context=deployment_config)
    except InvalidDeploymentContextError as e:
        raise InvalidContextError(str(e)) from e

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

        # Get the environment
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment {environment_id} could not be found"
            )

        # Ensure dedicated ingress controller is deployed if configured (FR-009)
        await _ensure_ingress_controller(environment_id=environment_id, uow=uow)

        # Validate and resolve parameter values against driver definitions
        definitions = parse_parameter_definitions(application_driver_version.parameters)
        resolved_parameters = validate_parameter_values(
            definitions=definitions,
            values=deployment_parameters,
        )

        # Resolve deployment name
        resolved_name: str
        if deployment_name and deployment_name.strip():
            # User provided a custom name — validate and check uniqueness
            try:
                resolved_name = validate_deployment_name(deployment_name)
            except ValueError as e:
                raise DeploymentNameValidationError(str(e)) from e

            existing = await uow.deployments.get_by_name(resolved_name)
            if existing is not None:
                raise DeploymentNameConflictError(
                    f"A deployment named '{resolved_name}' already exists"
                )
        else:
            # Auto-generate name from driver name
            existing_names = await uow.deployments.find_names_with_prefix(driver_name)
            resolved_name = generate_deployment_name(driver_name, existing_names)

        # Create the deployment
        deployment = Deployment.create(
            application_version=version,
            application_driver_version_id=application_driver_version.id,
            environment_id=environment_id,
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


_DELETION_LIFECYCLE_STATES = (
    DeploymentState.DELETION_REQUESTED,
    DeploymentState.DELETION_IN_PROGRESS,
    DeploymentState.DELETED,
)


@inject(cast_result=False)  # type: ignore[arg-type]
async def delete_deployment(
    deployment_id: UUID,
    uow: UnitOfWork,
    backup_disposition: BackupDisposition,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task:
    """Request deletion of a deployment.

    Soft-deletes (tombstones) the deployment: the record is kept with
    its full history, transitions to DELETION_REQUESTED, and a
    DELETE_INSTANCE task is launched to drive teardown asynchronously.

    Raises:
        DeploymentNotFoundError: If no deployment matches the id.
        DeploymentAlreadyDeletedError: If the deployment is already in a
            deletion lifecycle state or tombstoned.
        DeploymentMutationInProgressError: If another workflow is in
            flight for this deployment.

    Returns:
        The DELETE_INSTANCE task created for the deletion request.
    """
    logger.info(
        "Requesting deployment deletion: deployment_id={} backup_disposition={}",
        deployment_id,
        backup_disposition.value,
    )

    async with uow:
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Deployment with ID {deployment_id} not found"
            )

        if deployment.status in _DELETION_LIFECYCLE_STATES:
            raise DeploymentAlreadyDeletedError(
                f"Deployment {deployment_id} is already in state {deployment.status.value}"
            )

        active_tasks = await uow.deployments.list_active_tasks(deployment_id)
        if active_tasks:
            raise DeploymentMutationInProgressError(
                active_task_ids=[str(task.id) for task in active_tasks],
            )

        # Resolve cluster-side teardown targets from the active instance's
        # context. If the deployment never produced an instance (e.g.,
        # it was deleted while still PENDING) these stay None and the
        # flow skips the K8s work.
        release_reference: str | None = None
        namespace: str | None = None
        active_instance = deployment.active_instance
        if active_instance is not None:
            release_reference = active_instance.context.instance.release_reference
            namespace = active_instance.context.instance.namespace

        # REMOVE disposition: drop every backup (and its restores)
        # attached to any of this deployment's historical instances,
        # inside the same UoW so failures roll the whole thing back.
        # Backup rows carry metadata only; the underlying Velero /
        # object-store artefacts are cleaned up by the existing
        # backup-service semantics that the row represents.
        removed_backup_count = 0
        if backup_disposition == BackupDisposition.REMOVE:
            instances = await uow.application_instances.find_by_deployment(
                deployment_id=deployment.id,
            )
            for instance in instances:
                backups = await uow.backups.get_by_instance_id(
                    instance_id=instance.id,
                )
                for backup in backups:
                    restores = await uow.restores.get_by_backup_id(backup.id)
                    for restore in restores:
                        await uow.restores.delete(restore)
                    await uow.backups.delete(backup)
                    removed_backup_count += 1
            logger.info(
                "Removed {} backup(s) across {} instance(s) for deployment_id={}",
                removed_backup_count,
                len(instances),
                deployment_id,
            )

        deployment.set_status(DeploymentState.DELETION_REQUESTED)

        task = Task.create(
            type=TaskType.DELETE_INSTANCE,
            deployment_id=deployment.id,
            parameters={"backup_disposition": backup_disposition.value},
        )

        flow_info = await prefect_manager.run_action(
            action=PrefectAction.DELETE_INSTANCE,
            parameters={
                "task_id": task.id,
                "deployment_id": deployment.id,
                "release_reference": release_reference,
                "namespace": namespace,
                "backup_disposition": backup_disposition.value,
            },
        )
        task.prefect_flow_run_id = flow_info.id

        await uow.deployments.save(deployment=deployment)
        await uow.tasks.save(task=task)
        await uow.commit()

        logger.info(
            "Deletion request accepted: deployment_id={} task_id={} flow_run_id={}",
            deployment.id,
            task.id,
            flow_info.id,
        )

        result = await uow.tasks.find(id=task.id)
        assert result is not None, "Task not found"
        return result
