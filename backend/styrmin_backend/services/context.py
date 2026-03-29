from uuid import UUID

from loguru import logger

from styrmin_backend.agent.service.kubernetes.utils import (
    get_kubernetes_reference,
)
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
from styrmin_backend.context.resolvers import resolve_global_context
from styrmin_backend.domain.models import Deployment
from styrmin_backend.services.exceptions import DeploymentNotFoundError
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
                "labels": {"environment_id": environment.id},
                "parameters": deployment.parameters,
            }
        )

        context = resolve_global_context(context_input=context_input)

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

        return context
