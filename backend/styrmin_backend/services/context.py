from uuid import UUID

from loguru import logger
from pydantic import ValidationError

from styrmin_backend.agent.service.kubernetes.utils import (
    get_kubernetes_reference,
)
from styrmin_backend.context.models.components import (
    ResolvedComponentScheduling,
)
from styrmin_backend.context.models.config import SchedulingConfig
from styrmin_backend.context.models.contexts import (
    GlobalContext,
    UtilityContext,
    UtilityKind,
)
from styrmin_backend.context.models.input import (
    ContextInput,
    UtilityInput,
    UtilityKindInput,
)
from styrmin_backend.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_backend.context.models.services import ServiceReference
from styrmin_backend.context.resolvers import (
    _resolve_scheduling_config,
    resolve_global_context,
)
from styrmin_backend.domain.models import Deployment
from styrmin_backend.services.exceptions import (
    DeploymentNotFoundError,
    InvalidSchedulingConfigError,
)
from styrmin_backend.services.scheduling.validator import (
    expand_deployment_references,
)
from styrmin_backend.services.unit_of_work import UnitOfWork


async def generate_context_from_deployment_id(
    deployment_id: UUID, uow: UnitOfWork
) -> GlobalContext:
    async with uow:
        # Fetch the deployment
        deployment = await uow.deployments.find(deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError(
                f"Instance with id {deployment_id} not found."
            )

        return await generate_context_from_deployment(deployment, uow)


async def generate_context_from_deployment(
    deployment: Deployment, uow: UnitOfWork
) -> GlobalContext:
    # FIXME: Fix the context generation
    logger.debug("Generating context for deployment: {}", deployment.id)
    async with uow:
        # Fetch the application driver version
        application_driver_version = await uow.application_driver_versions.get(
            deployment.application_driver_version_id
        )
        assert application_driver_version is not None, "Application not found"

        # Fetch the application driver
        application_driver = await uow.application_drivers.get(
            application_driver_version.application_driver_id
        )
        assert application_driver is not None, "Application driver not found"

        # Fetch the environment
        environment = await uow.environments.get(deployment.environment_id)
        assert environment is not None, "Environment not found"

        # Fetch the cluster
        cluster = await uow.clusters.get(environment.cluster_id)
        assert cluster is not None, "Cluster not found"

        # Fetch the helm chart
        helm_chart = await uow.helm_charts.get(application_driver_version.helm_chart_id)
        assert helm_chart is not None, "Helm chart not found"

        # Fetch the helm repository
        helm_repository = await uow.helm_repositories.get(helm_chart.repository_id)
        assert helm_repository is not None, "Helm repository not found"

        # Prepare the utilities information to send to the workflow
        # Internal deployments (e.g. ingress controller) do not need utilities
        # such as NetworkPolicies or Middlewares, which would interfere with
        # their operation.
        utilities_input: list[UtilityInput] = []
        if not deployment.internal:
            utilities = await uow.utilities.get_all()
            for utility in utilities:
                utilities_input.append(
                    UtilityInput(
                        kind=UtilityKindInput(utility.kind),
                    )
                )

        namespace = get_kubernetes_reference(deployment.id)
        release_reference = get_kubernetes_reference(deployment.id)
        context_input = ContextInput.model_validate(
            {
                "config": {
                    "cluster": cluster.config or {},
                    "environment": environment.config or {},
                    "deployment": deployment.config or {},
                },
                "instance": {
                    "deployment_id": deployment.id,
                    "namespace": namespace,
                    "release_reference": release_reference,
                },
                "application": {
                    "name": application_driver.name,
                    "version": deployment.application_version,
                    "chart": {
                        "id": helm_chart.id,
                        "name": helm_chart.name,
                        "version": helm_chart.version,
                        "values_template": helm_chart.values_template,
                    },
                    "repository": {
                        "id": helm_repository.id,
                        "url": helm_repository.url,
                    },
                },
                "components": [
                    component.model_dump(exclude={"id", "deployment_id"})
                    for component in deployment.components or []
                ],
                "utilities": utilities_input,
                "environment_name": environment.name,
                "labels": {
                    "environment_id": environment.id,
                    "deployment_id": deployment.id,
                },
                "parameters": deployment.parameters,
            }
        )

        context = resolve_global_context(context_input=context_input)

        # Populate capabilities from persisted data
        context.cluster.capabilities = cluster.capabilities or {}
        context.environment.capabilities = environment.capabilities or {}

        # Build services context from deployed services in the environment
        fqdn_suffix = context.instance.config.fqdn_suffix
        app_name = application_driver.name
        env_name = environment.name

        deployed_services = await uow.deployed_services.get_by_environment_id(
            deployment.environment_id
        )
        services_dict: dict = {}
        deployed_services_list: list[dict] = []
        for svc in deployed_services:
            ref = ServiceReference(
                host=svc.resolved_name,
                port=svc.port,
                kind=svc.kind,
                primary_fqdn=compute_primary_fqdn(
                    app_name, str(deployment.id), fqdn_suffix
                ),
                human_readable_fqdn=compute_human_readable_fqdn(
                    svc.resolved_name, env_name, fqdn_suffix
                ),
            )
            services_dict[svc.driver_service_name] = ref.model_dump()
            deployed_services_list.append(
                {
                    "resolved_name": svc.resolved_name,
                    "port": svc.port,
                    "kind": svc.kind,
                    "deployment_id": str(svc.deployment_id),
                    "component": svc.component,
                }
            )
        context.services = services_dict
        context.deployed_services = deployed_services_list

        # Auto-add service-discovery utility when this deployment has services
        has_own_services = any(
            str(svc.deployment_id) == str(deployment.id) for svc in deployed_services
        )
        if has_own_services:
            context.utilities.append(UtilityContext(kind=UtilityKind.SERVICE_DISCOVERY))

        # Resolve scheduling configuration per component and expand any
        # affinity ``deployment_ref`` terms into concrete label selectors.
        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=deployment.environment_id,
            environment_config=environment.config,
            deployment_config=deployment.config,
            deployment_components=deployment.components or [],
        )

        return context


async def _populate_component_scheduling(
    *,
    context: GlobalContext,
    uow: UnitOfWork,
    environment_id: UUID,
    environment_config: dict | None,
    deployment_config: dict | None,
    deployment_components: list,
) -> None:
    """Populate ``ComponentContext.scheduling`` for each component.

    Reads ``scheduling`` from each level's raw JSON config, merges them via
    :func:`_resolve_scheduling_config`, expands affinity ``deployment_ref``
    terms, and stores the resulting :class:`ResolvedComponentScheduling` on
    the matching :class:`ComponentContext`. Deployment-level ``runtime_class``
    values are passed through without cluster-side validation — an unknown
    name surfaces later as a Pending pod with a scheduler error rather than
    a pre-rollout rejection.
    """
    if context.components is None:
        return

    env_scheduling = _extract_scheduling(
        environment_config, path="environment.config.scheduling"
    )
    dep_scheduling = _extract_scheduling(
        deployment_config, path="deployment.config.scheduling"
    )

    component_scheduling_by_name: dict[str, SchedulingConfig | None] = {}
    for component in deployment_components:
        component_scheduling_by_name[component.name] = _extract_scheduling(
            component.config,
            path=f"component[{component.name}].config.scheduling",
        )

    for name, component_ctx in context.components.root.items():
        comp_scheduling = component_scheduling_by_name.get(name)
        if (
            env_scheduling is None
            and dep_scheduling is None
            and comp_scheduling is None
        ):
            continue
        resolved, provenance = _resolve_scheduling_config(
            env=env_scheduling,
            dep=dep_scheduling,
            comp=comp_scheduling,
        )
        resolved = await expand_deployment_references(
            uow=uow,
            environment_id=environment_id,
            config=resolved,
        )
        component_ctx.scheduling = ResolvedComponentScheduling(
            config=resolved, provenance=provenance
        )


def _extract_scheduling(
    raw_config: dict | None, *, path: str
) -> SchedulingConfig | None:
    if not raw_config:
        return None
    payload = raw_config.get("scheduling") if isinstance(raw_config, dict) else None
    if payload is None:
        return None
    try:
        return SchedulingConfig.model_validate(payload)
    except ValidationError as e:
        raise InvalidSchedulingConfigError(
            message=f"Invalid scheduling configuration at {path}: {e!s}",
            path=path,
        ) from e
