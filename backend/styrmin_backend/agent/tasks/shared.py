import os
from uuid import UUID

import httpx
from prefect import State, get_run_logger, task
from prefect.states import Completed, Failed

from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.agent.service.kubernetes.primitives import (
    apply_kubernetes_namespace,
    get_custom_resource,
    get_deployments,
    get_stateful_sets,
    patch_custom_resource,
    upsert_custom_resource,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.context.models.helm import HelmInfo
from styrmin_backend.services.helm.renderer import (
    render_helm_chart_spec,
    render_helm_repository_spec,
)
from styrmin_backend.services.utils import get_helm_repository_type
from styrmin_backend import config

POLL_RETRIES = int(os.environ.get("STYRMIN_AGENT_POLL_RETRIES", "60"))
POLL_RETRY_DELAY_SECONDS = int(os.environ.get("STYRMIN_AGENT_POLL_RETRY_DELAY_SECONDS", "10"))
POLL_INTERVAL = int(os.environ.get("STYRMIN_AGENT_POLL_INTERVAL", "10"))


@task
async def get_context(instance_id: UUID) -> GlobalContext:
    styrmin_api_url = os.environ.get("STYRMIN_URL_API", "http://localhost:8000")

    logger = get_run_logger()
    async with httpx.AsyncClient() as client:
        logger.info(f"Fetching context for deployment {instance_id}")
        response = await client.get(
            f"{styrmin_api_url}/deployments/{instance_id}/context",
        )
        if response.status_code == 404:
            raise Exception(f"Deployment not found: {instance_id}")
        if response.status_code != 200:
            raise Exception(f"Failed to fetch context: HTTP {response.status_code}")
        return GlobalContext.model_validate(response.json())


@task
async def render_helm_chart_specifications(helm: HelmInfo) -> dict:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    return render_helm_chart_spec(
        helm_chart_id=helm.chart.id,
        name=helm.chart.name,
        version=helm.chart.version,
        repository_id=helm.repository.id,
    )


@task(task_run_name="Render helm repository specifications")
async def render_helm_repository_specifications(helm: HelmInfo) -> dict:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    return render_helm_repository_spec(
        repository_id=helm.repository.id,
        repository_url=helm.repository.url,
        repository_type=get_helm_repository_type(helm.repository.url),
    )


@task(task_run_name="apply namespace: {namespace}")
async def apply_namespace(namespace: str, labels: dict[str, str] | None = None) -> None:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()
    logger.info(f"Creating namespace {namespace}")
    await apply_kubernetes_namespace(namespace=namespace, labels=labels)


@task(task_run_name="apply helm repositories")
async def apply_helm_repositories(helm_repositories: list[dict]) -> None:
    logger = get_run_logger()
    logger.info("Applying Helm repositories...")
    for repository in helm_repositories:
        logger.info(f"Creating Helm repository {repository['metadata']['name']}")
        await upsert_custom_resource(
            plurals="helmrepositories",
            body=repository,
            group="source.toolkit.fluxcd.io",
            version="v1",
            namespace="styrmin",
        )


@task(task_run_name="apply helm charts")
async def apply_helm_charts(charts: list[dict]) -> None:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()
    logger = get_run_logger()
    logger.info("Applying Helm charts...")
    for chart in charts:
        logger.info(f"Applying Helm chart {chart['metadata']['name']}")
        await upsert_custom_resource(
            namespace="styrmin",
            plurals="helmcharts",
            body=chart,
            group="source.toolkit.fluxcd.io",
            version="v1",
        )


@task(task_run_name="patch helm release: {namespace}")
async def patch_helm_release(namespace: str, patch: list, reference: str) -> None:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()
    logger.info(f"Patching custom resource {namespace}")
    await patch_custom_resource(
        plural="helmreleases",
        reference=reference,
        group="helm.toolkit.fluxcd.io",
        version="v2",
        namespace=namespace,
        patch=patch,
    )


@task(task_run_name="apply helm release: {namespace}")
async def apply_helm_release(
    namespace: str,
    release_spec: dict,
) -> None:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()
    logger.info(f"Updating Helm release {namespace}")
    await upsert_custom_resource(
        plurals="helmreleases",
        body=release_spec,
        group="helm.toolkit.fluxcd.io",
        version="v2",
        namespace=namespace,
        update=True,
    )


@task(retries=POLL_RETRIES, retry_delay_seconds=POLL_RETRY_DELAY_SECONDS)
async def poll_helm_release_status(namespace: str, reference: str) -> State:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()
    logger.info(f"Polling Helm release status for {namespace}")
    try:
        custom_resource = await get_custom_resource(
            plural="helmreleases",
            name=reference,
            group="helm.toolkit.fluxcd.io",
            version="v2",
            namespace=namespace,
        )
    except CustomResourceNotFound:
        return Failed(message="Instance does not exist")

    logger.info(f"Fetched helm release status for {namespace}: {custom_resource}")

    metadata = custom_resource.get("metadata", {})  # type: ignore[attr-defined]
    generation = metadata.get("generation")

    if status := custom_resource.get("status"):  # type: ignore[attr-defined]
        observed_generation = status.get("observedGeneration")

        # Ensure Flux has processed the latest spec change before checking conditions
        if generation is not None and observed_generation is not None:
            if observed_generation < generation:
                raise Exception(
                    f"HelmRelease {reference}: not yet reconciled by controller "
                    f"(observed={observed_generation}, current={generation})"
                )

        if conditions := status.get("conditions"):
            for condition in conditions:
                if condition["type"] == "Ready":
                    if condition["status"] == "True":
                        return Completed(message="Deployment succeeded")
                    if condition["status"] == "False":
                        logger.error("Deployment failed: %s", condition["message"])
                        return Failed(message="Deployment failed")
    logger.info("No status available yet. Instance creation in progress...")
    raise Exception("Instance create in progress...")


@task(
    task_run_name="Poll Kubernetes deployments status: {namespace}",
    retries=POLL_RETRIES,
    retry_delay_seconds=POLL_RETRY_DELAY_SECONDS,
)
async def poll_kubernetes_deployments_status(namespace: str) -> None:
    """Check the status of all deployments in the instance namespace.

    Verifies that the controller has observed the latest spec, all replicas
    run the updated pod template, and they are ready and available.
    When this task is successful, the rollout is complete.
    """
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()
    logger.info(f"Polling Kubernetes deployments status for {namespace}")
    deployments = await get_deployments(namespace=namespace)
    for deployment in deployments.items:
        name = deployment.metadata.name
        generation = deployment.metadata.generation or 0
        spec_replicas = (
            deployment.spec.replicas if deployment.spec.replicas is not None else 1
        )

        observed_generation = deployment.status.observed_generation or 0
        updated_replicas = deployment.status.updated_replicas or 0
        ready_replicas = deployment.status.ready_replicas or 0
        available_replicas = deployment.status.available_replicas or 0

        if observed_generation < generation:
            raise Exception(
                f"Deployment {name}: rollout not yet observed by controller "
                f"(observed={observed_generation}, current={generation})"
            )
        if updated_replicas < spec_replicas:
            raise Exception(
                f"Deployment {name}: waiting for updated replicas ({updated_replicas}/{spec_replicas})"
            )
        if ready_replicas < spec_replicas:
            raise Exception(
                f"Deployment {name}: waiting for ready replicas ({ready_replicas}/{spec_replicas})"
            )
        if available_replicas < spec_replicas:
            raise Exception(
                f"Deployment {name}: waiting for available replicas ({available_replicas}/{spec_replicas})"
            )


@task(
    task_run_name="Poll Kubernetes statefulsets status: {namespace}",
    retries=POLL_RETRIES,
    retry_delay_seconds=POLL_RETRY_DELAY_SECONDS,
)
async def poll_kubernetes_stateful_sets_status(namespace: str) -> None:
    """Check the status of all statefulsets in the instance namespace.

    Verifies that the controller has observed the latest spec, all replicas
    run the updated pod template, and they are ready.
    When this task is successful, the rollout is complete.
    """
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    logger = get_run_logger()
    logger.info(f"Polling Kubernetes statefulsets status for {namespace}")
    stateful_sets = await get_stateful_sets(namespace=namespace)
    for stateful_set in stateful_sets.items:
        name = stateful_set.metadata.name
        generation = stateful_set.metadata.generation or 0
        spec_replicas = (
            stateful_set.spec.replicas if stateful_set.spec.replicas is not None else 1
        )

        observed_generation = stateful_set.status.observed_generation or 0
        updated_replicas = stateful_set.status.updated_replicas or 0
        ready_replicas = stateful_set.status.ready_replicas or 0

        if observed_generation < generation:
            raise Exception(
                f"StatefulSet {name}: rollout not yet observed by controller "
                f"(observed={observed_generation}, current={generation})"
            )
        if updated_replicas < spec_replicas:
            raise Exception(
                f"StatefulSet {name}: waiting for updated replicas ({updated_replicas}/{spec_replicas})"
            )
        if ready_replicas < spec_replicas:
            raise Exception(
                f"StatefulSet {name}: waiting for ready replicas ({ready_replicas}/{spec_replicas})"
            )
