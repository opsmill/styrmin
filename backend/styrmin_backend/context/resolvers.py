from uuid import UUID

from pydantic import ValidationError

from styrmin_backend.context.exceptions import ContextError
from styrmin_backend.context.models.components import (
    ComponentContext,
    ComponentsContext,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
    UtilityContext,
    UtilityKind,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.context.models.input import (
    ApplicationInput,
    ContextInput,
    UtilityInput,
)


def _resolve_cluster_context(cluster_config: ClusterConfig) -> ClusterContext:
    return ClusterContext(config=cluster_config)


def _resolve_environment_context(
    environment_config: EnvironmentConfig,
    name: str,
) -> EnvironmentContext:
    return EnvironmentContext(name=name, config=environment_config)


def _resolve_deployment_context(
    deployment_config: DeploymentConfig,
) -> DeploymentContext:
    return DeploymentContext(
        config=deployment_config,
    )


def _resolve_instance_config(
    cluster: ClusterConfig, environment: EnvironmentConfig, deployment: DeploymentConfig
) -> ResolvedConfig:
    # Merge the cluster, environment and deployment contexts
    resolved_context = {
        **cluster.model_dump(exclude_none=True),
        **environment.model_dump(exclude_none=True),
        **deployment.model_dump(exclude_none=True),
    }

    return ResolvedConfig(**resolved_context)


def _resolve_application_context(
    application: ApplicationInput,
) -> ApplicationContext:
    chart = ChartInfo(**application.chart.model_dump(exclude_none=True))
    repository = RepositoryInfo(**application.repository.model_dump(exclude_none=True))

    helm = HelmInfo(chart=chart, repository=repository)

    return ApplicationContext(
        name=application.name,
        version=application.version,
        helm=helm,
    )


def _resolve_instance_context(
    cluster_config: ClusterConfig,
    environment_config: EnvironmentConfig,
    deployment_config: DeploymentConfig,
    namespace: str,
    release_reference: str,
    deployment_id: UUID,
) -> InstanceContext:
    # Resolve the context between cluster, environment and instance
    resolved_config = _resolve_instance_config(
        cluster=cluster_config,
        environment=environment_config,
        deployment=deployment_config,
    )

    instance_context = InstanceContext(
        deployment_id=deployment_id,
        namespace=namespace,
        release_reference=release_reference,
        config=resolved_config,
    )

    return instance_context


def _resolve_utilities_context(
    utilities: list[UtilityInput],
) -> list[UtilityContext]:
    utilities_context = []
    for utility in utilities:
        utility_context = UtilityContext(
            kind=UtilityKind(utility.kind.value),
        )
        utilities_context.append(utility_context)

    return utilities_context


def resolve_global_context(context_input: ContextInput) -> GlobalContext:
    # Create the components context
    if context_input.components:
        try:
            components_context = ComponentsContext.model_validate(
                {
                    component.name: ComponentContext.model_validate(
                        component.model_dump()
                    )
                    for component in context_input.components
                }
            )
        except ValidationError as e:
            raise ContextError(
                f"The components context validation failed. {e!s}"
            ) from e
    else:
        components_context = None

    # Create the cluster context
    cluster_context: ClusterContext = _resolve_cluster_context(
        context_input.config.cluster
    )

    # Create the environment context
    environment_context: EnvironmentContext = _resolve_environment_context(
        context_input.config.environment,
        name=context_input.environment_name,
    )

    # Create the deployment context
    deployment_context: DeploymentContext = _resolve_deployment_context(
        context_input.config.deployment
    )

    # Create the instance context
    instance_context = _resolve_instance_context(
        cluster_config=context_input.config.cluster,
        environment_config=context_input.config.environment,
        deployment_config=context_input.config.deployment,
        namespace=context_input.instance.namespace,
        release_reference=context_input.instance.release_reference,
        deployment_id=context_input.instance.deployment_id,
    )

    # Create the application context
    application_context = _resolve_application_context(context_input.application)

    # Create the utilities context
    utilities_context = _resolve_utilities_context(context_input.utilities)

    # Create the global context object with original contexts and resolved context
    global_context = GlobalContext(
        app=application_context,
        cluster=cluster_context,
        environment=environment_context,
        deployment=deployment_context,
        instance=instance_context,
        components=components_context,
        labels=context_input.labels,
        utilities=utilities_context,
        parameters=context_input.parameters,
    )

    return global_context
