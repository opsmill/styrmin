"""Provides the application service."""

import asyncio
from uuid import UUID

from fast_depends import Depends, inject
from loguru import logger
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from styrmin_backend import config as styrmin_config
from styrmin_backend.context.exceptions import InvalidDeploymentContextError
from styrmin_backend.context.validators import validate_deployment_config
from styrmin_backend.db.models import (
    Action,
    ApplicationDriverVersion,
    ApplicationInstance,
    HelmChart,
    HelmRepository,
    InstanceStatus,
    Task,
    TaskStatus,
    TaskType,
)
from styrmin_backend.db.models import (
    ApplicationDriver as ApplicationDriverModel,
)
from styrmin_backend.db.models import (
    ApplicationDriverVersion as ApplicationDriverVersionModel,
)
from styrmin_backend.domain.models import ComponentConfig
from styrmin_backend.domain.payloads import (
    HookDeploymentsPayload,
)
from styrmin_backend.services.driver import ApplicationDriver
from styrmin_backend.services.driver.loaders import (
    get_git_driver_loader,
    get_local_driver_loader,
)
from styrmin_backend.services.driver.models.resources.actions import HookKind
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.exceptions import (
    ApplicationDriverNotFoundError,
    ApplicationDriverVersionAlreadyExistsError,
    EnvironmentNotFoundError,
    InvalidContextError,
    InvalidVersionError,
    InvalidVersionSyntaxError,
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
from styrmin_backend.workflows.models import PrefectAction


@inject(cast_result=False)  # type: ignore[arg-type]
async def load_application_driver_from_object(
    driver_object: ApplicationDriver,
    uow: UnitOfWork,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> ApplicationDriverVersionModel:
    """Load an application driver from an object.

    Args:
        driver_object (ApplicationDriver): The object representing the application driver.

    Returns:
        Application: The loaded application driver.
    """

    async with uow:
        name = driver_object.driver_spec.metadata.name

        supported_versions = driver_object.driver_spec.spec.supported_versions

        application_driver = await uow.application_drivers.get_by_name(name=name)
        if application_driver is None:
            application_driver = await uow.application_drivers.create(
                ApplicationDriverModel(name=name)
            )

        application_driver_version = (
            await uow.application_driver_versions.get_by_supported_versions(
                application_driver_id=application_driver.id,
                versions=driver_object.driver_spec.spec.supported_versions,
            )
        )

        if application_driver_version is not None:
            raise ApplicationDriverVersionAlreadyExistsError(
                f"An application with the name {name} and supported versions {supported_versions} already exists."
            )

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

        # Register token and action workflows only for git-sourced drivers
        if isinstance(driver_object.source, GitSource):
            await prefect_manager.register_token(
                namespace="user",
                token=driver_object.source.token,
            )

            builder = ActionsWorkflowBuilder(source=driver_object.source)
            if driver_object.driver_spec.spec.actions:
                for action in driver_object.driver_spec.spec.actions:
                    workflow = builder.build_user_action_workflow_definition(
                        action=action
                    )
                    logger.info(
                        f"Registering user action {action.name}: {workflow.name}, {supported_versions}, {action.hook}, {action.mode}"
                    )
                    await prefect_manager.register_user_action(
                        workflow=workflow,
                        application=name,
                        version=supported_versions,
                        hook=action.hook,
                        mode=action.mode,
                    )

        # Build source fields for DB record
        if isinstance(driver_object.source, GitSource):
            source_type = "git"
            source_repository = driver_object.source.repository
            source_branch: str | None = driver_object.source.branch
            source_path: str | None = None
        else:
            source_type = "local"
            source_repository = ""
            source_branch = None
            source_path = driver_object.source.path

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
                helm_chart_id=helm_chart.id,
                source_type=source_type,
                source_repository=source_repository,
                source_branch=source_branch,
                source_path=source_path,
            )
        )

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
    repository_url: str, branch: str, uow: UnitOfWork
) -> ApplicationDriverVersion:
    """Load an application driver from a git repository.

    Args:
        repository_url (str): The URL of the git repository.
        branch (str): The branch to clone.

    Returns:
        Application: The loaded application driver.
    """

    # TODO: Token setup
    token = styrmin_config.SETTINGS.driver.token
    if token is None:
        raise ServiceError(
            "No Git token where provided for loading the driver from a remote code storage."
        )

    # Load the driver from the remote repository
    driver_loader = get_git_driver_loader(
        repository=repository_url, branch=branch, token=token
    )
    application_driver = driver_loader.load_driver()

    # Create the application driver objects in database
    return await load_application_driver_from_object(
        driver_object=application_driver, uow=uow
    )


async def load_application_driver_from_local_directory(
    path: str, uow: UnitOfWork
) -> ApplicationDriverVersionModel:
    """Load an application driver from a local filesystem directory.

    Args:
        path (str): The absolute path to the local driver directory.
        uow (UnitOfWork): The unit of work to use.

    Returns:
        ApplicationDriverVersion: The loaded application driver version.
    """
    driver_loader = get_local_driver_loader(path=path)
    application_driver = driver_loader.load_driver()

    async with uow:
        name = application_driver.driver_spec.metadata.name

        application_driver_obj = await uow.application_drivers.get_by_name(name=name)
        if application_driver_obj is None:
            application_driver_obj = await uow.application_drivers.create(
                ApplicationDriverModel(name=name)
            )

        # Upsert: if a version with the same source_path and version string exists, delete it
        existing = await uow.application_driver_versions.get_by_source_path_and_version(
            application_driver_id=application_driver_obj.id,
            source_path=path,
            version=application_driver.driver_spec.spec.version,
        )
        if existing is not None:
            await uow.application_driver_versions.delete(existing)

    # Create the application driver objects in database
    return await load_application_driver_from_object(
        driver_object=application_driver, uow=uow
    )


@inject(cast_result=False)  # type: ignore[arg-type]
async def instantiate_application(
    name: str,
    version: str,
    application_id: UUID,
    environment_id: UUID,
    uow: UnitOfWork,
    instance_config: dict | None = None,
    prefect_manager: PrefectManager = Depends(get_manager),
) -> Task:
    """Instantiate an application in the given environment.

    Args:
        name (str): The name of the application instance.
        application_id (UUID): The id of the application to instantiate.
        environment_id (UUID): The id of the environment to instantiate the application in.
        uow (UnitOfWork): The unit of work to use.
        config (dict | None): The runtime configuration of the application instance.
        workflow_executor (StyrminWorkflowExecutor): The workflow executor to use.

    Raises:
        InvalidContextError: If the context is invalid.

    Returns:
        Task: the task created for the application instantiation.
    """

    if instance_config is None:
        instance_config = {}

    try:
        validate_deployment_config(context=instance_config)
    except InvalidDeploymentContextError as e:
        raise InvalidContextError() from e

    async with uow:
        # Get the application
        application = await uow.application_driver_versions.get(application_id)
        if application is None:
            raise ApplicationDriverNotFoundError(
                f"Application {application_id} could not be found"
            )

        # Check if the required version match the driver requirement specifier
        try:
            if Version(version) not in SpecifierSet(
                application.application_supported_versions
            ):
                raise InvalidVersionError(
                    f"Version {version} does not match the required version specifier {application.application_supported_versions}"
                )
        except InvalidVersion as e:
            raise InvalidVersionSyntaxError(
                f"Version {version} is not a valid version string"
            ) from e

        # Get the environment
        environment = await uow.environments.get(environment_id)
        if environment is None:
            raise EnvironmentNotFoundError(
                f"Environment {environment_id} could not be found"
            )

        # Create instance on db
        application_instance = await uow.instances.create(  # type: ignore[attr-defined]
            ApplicationInstance(
                name=name,
                status=InstanceStatus.PENDING,
                application_version=version,
                environment_id=environment.id,
                application_id=application.id,
                config=instance_config,
            )
        )

        prehook, posthook, corehook = await asyncio.gather(
            prefect_manager.get_user_action_deployment_id(
                application=application.name,  # type: ignore[attr-defined]
                hook=HookKind.SETUP,
                mode="pre",
                version=application.application_supported_versions,
            ),
            prefect_manager.get_user_action_deployment_id(
                application=application.name,  # type: ignore[attr-defined]
                hook=HookKind.SETUP,
                mode="post",
                version=application.application_supported_versions,
            ),
            prefect_manager.get_action_deployment_id(
                action=PrefectAction.CREATE_HELM_RELEASE
            ),
        )
        assert corehook is not None, "Core hook deployment not found"

        hook_deployments_payload = HookDeploymentsPayload(
            core_hook=corehook,
            pre_hook=prehook,
            post_hook=posthook,
        )

        task = await uow.tasks.create(
            Task(
                status=TaskStatus.PENDING,
                type=TaskType.CREATE_INSTANCE,
                application_instance_id=application_instance.id,
            )
        )

        logger.debug("Run the orchestration workflow...")
        kwargs = {
            "task_id": task.id,
            "instance_id": application_instance.id,
            "hook_deployments_payload": hook_deployments_payload,
        }

        # Run the orchestration workflow
        flow_info = await prefect_manager.run_action(
            action=PrefectAction.CREATE_INSTANCE,
            parameters=kwargs,
        )

        task.prefect_flow_run_id = flow_info.info.id
        await uow.tasks.update(task)  # type: ignore[attr-defined]

        await uow.commit()

        result = await uow.tasks.get(task.id)
        assert result is not None, "Task not found"
        return result
