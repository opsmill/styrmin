import asyncio
from uuid import UUID

import httpx
from prefect import flow
from prefect.client.schemas.objects import FlowRun
from prefect.logging import get_run_logger

from prefect.states import Completed
from prefect.client.schemas.objects import State

from styrmin_backend.agent.service.kubernetes.primitives import (
    patch_custom_resource,
    run_kubernetes_job,
)
from styrmin_backend.agent.tasks.utils import (
    run_deployment_or_fail,
    run_driver_action_or_fail,
)
from styrmin_backend.agent.tasks.core import (
    render_application_helm_release_specifications,
)
from styrmin_backend.agent.tasks.extra import (
    install_utility,
    update_utility,
)
from styrmin_backend.agent.tasks.service_aliases import (
    apply_service_aliases,
    compute_service_aliases,
)
from styrmin_backend.agent.tasks.shared import (
    render_helm_chart_specifications,
    render_helm_repository_specifications,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.db.models import ApplicationInstance as ApplicationInstanceModel
from styrmin_backend.domain.models import Instance
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator
from styrmin_backend.services.reconciliation.remediation import Remediator
from styrmin_backend.services.auth.action_token import action_api_token
from styrmin_backend.services.unit_of_work import get_unit_of_work
from styrmin_backend.agent.service.kubernetes.primitives import (
    patch_custom_resource_status,
    apply_kubernetes_namespace,
    upsert_custom_resource,
)
from styrmin_backend import config
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_IN_PROGRESS,
    CRD_GROUP,
    CRD_PLURAL,
    CRD_VERSION,
    HELMRELEASE_GROUP,
    HELMRELEASE_PLURAL,
    HELMRELEASE_VERSION,
)
from styrmin_backend.operator.crd.builder import build_styrmin_deployment_body


def _build_namespace_labels(
    context: GlobalContext, label_prefix: str = "styrmin"
) -> dict[str, str]:
    """Build Kubernetes namespace labels from context labels."""
    return {
        f"{label_prefix}/{key}": str(value) for key, value in context.labels.items()
    }


async def _apply_styrmin_deployment_crd(*, body: dict, namespace: str) -> None:
    """Create or update the StyrminDeployment CR, replacing each spec key it
    writes so keys dropped from the context do not linger (017 FR-011); the
    server-owned ``spec.deletionRequested`` is left alone."""
    await upsert_custom_resource(
        plurals=CRD_PLURAL,
        body=body,
        group=CRD_GROUP,
        version=CRD_VERSION,
        namespace=namespace,
        replace_spec_keys_on_update=True,
    )


async def _set_deployment_in_progress(namespace: str, release_reference: str) -> None:
    """Set the deployment-in-progress annotation on the HelmRelease.

    This signals the kopf operator to defer reconciliation while a
    Prefect flow is modifying resources.
    """
    try:
        await patch_custom_resource(
            plural=HELMRELEASE_PLURAL,
            reference=release_reference,
            group=HELMRELEASE_GROUP,
            version=HELMRELEASE_VERSION,
            namespace=namespace,
            patch=[
                {
                    "op": "add",
                    "path": f"/metadata/annotations/{ANNOTATION_DEPLOYMENT_IN_PROGRESS.replace('/', '~1')}",
                    "value": "true",
                }
            ],
        )
    except Exception:
        pass  # Best-effort; don't block deployment if annotation fails


async def _clear_deployment_in_progress(namespace: str, release_reference: str) -> None:
    """Remove the deployment-in-progress annotation from the HelmRelease."""
    try:
        await patch_custom_resource(
            plural=HELMRELEASE_PLURAL,
            reference=release_reference,
            group=HELMRELEASE_GROUP,
            version=HELMRELEASE_VERSION,
            namespace=namespace,
            patch=[
                {
                    "op": "remove",
                    "path": f"/metadata/annotations/{ANNOTATION_DEPLOYMENT_IN_PROGRESS.replace('/', '~1')}",
                }
            ],
        )
    except Exception:
        pass  # Best-effort


async def orchestration_callback(flow, flow_run: FlowRun, state: State) -> None:  # type: ignore[no-untyped-def]
    styrmin_server_url = config.SETTINGS.url.graphql

    # Check state
    async with httpx.AsyncClient() as client:
        await client.post(
            styrmin_server_url,
            json={
                "variables": {
                    "taskId": str(flow_run.parameters["task_id"]),
                    "stateName": state.name,
                    "stateMessage": state.message,
                    "stateType": state.type,
                },
                "query": """
                    mutation Callback($taskId: UUID!, $stateName: String!, $stateMessage: String, $stateType: String!) {
                        callback(taskId: $taskId, stateName: $stateName, stateMessage: $stateMessage, stateType: $stateType) {
                            message
                            success
                        }
                    }
                """,
            },
        )


@flow(
    on_cancellation=[orchestration_callback],
    on_completion=[orchestration_callback],
    on_failure=[orchestration_callback],
    on_crashed=[orchestration_callback],
    on_running=[orchestration_callback],
)
async def apply_state(
    task_id: UUID,
    deployment_id: UUID,
    new_instance_id: UUID,
    current_instance_id: UUID | None,
) -> State | None:
    """Reconcile a deployment to its declared state.

    Post-#237 boundary: the flow loads the deployment + both instances
    fresh from the DB at run time, builds the diff, and generates the
    remediation here — not in the FastAPI request. This means a flow
    retry sees fresh state, and DB writes that landed between scheduling
    and run no longer produce a stale plan.
    """
    async with get_unit_of_work() as uow:
        deployment = await uow.deployments.find(id=deployment_id)
        if deployment is None:
            return Completed(
                message=f"Deployment {deployment_id} not found; nothing to apply",
            )

        new_instance_model = await uow.application_instances.get(id=new_instance_id)
        assert new_instance_model is not None, (
            f"new_instance {new_instance_id} not found"
        )
        new_instance = _build_instance_entity(new_instance_model)
        assert new_instance is not None

        current_instance = None
        if current_instance_id is not None:
            current_instance_model = await uow.application_instances.get(
                id=current_instance_id
            )
            current_instance = _build_instance_entity(current_instance_model)

        comparator = Comparator(
            current_instance=current_instance,
            new_instance=new_instance,
        )
        diff_report = comparator.compare()
        get_run_logger().info(f"Flow-side diff report: {diff_report}")

        remediator = Remediator(uow=uow)
        remediation = await remediator.generate_remediation(diff_report=diff_report)

        if remediation is None:
            return Completed(message="No remediation needed")

    # Applied after the unit of work closes, so its connection is not held
    # while the remediation flow runs or while the action token is written.
    async with action_api_token() as api_token:
        flow_info = await remediation.apply(api_token=api_token, task_id=task_id)
    return flow_info.state


@flow(
    on_cancellation=[orchestration_callback],
    on_completion=[orchestration_callback],
    on_failure=[orchestration_callback],
    on_crashed=[orchestration_callback],
    on_running=[orchestration_callback],
)
async def run_job(
    task_id: UUID,
    runtime_class: str,
    env: list[dict],
    namespace: str,
    commands: list[str],
    image: str,
) -> None:
    # Render job template file

    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "namespace": namespace,
            "generateName": f"job-run-{task_id}-",
        },
        "spec": {
            "template": {
                "spec": {
                    "parallelism": 1,
                    "completions": 1,
                    "restartPolicy": "Never",
                    "runtimeClassName": runtime_class if runtime_class else None,
                    "affinity": {
                        "podAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": [
                                {
                                    "labelSelector": {
                                        "matchLabels": {
                                            "helm.neo4j.com/pod_category": "neo4j-instance"
                                        }
                                    },
                                    "topologyKey": "kubernetes.io/hostname",
                                }
                            ]
                        }
                    },
                    "tolerations": [
                        {
                            "effect": "NoExecute",
                            "key": "node.kubernetes.io/not-ready",
                            "operator": "Exists",
                            "tolerationSeconds": 60,
                        },
                        {
                            "effect": "NoExecute",
                            "key": "node.kubernetes.io/unreachable",
                            "operator": "Exists",
                            "tolerationSeconds": 60,
                        },
                    ],
                    "containers": [
                        {
                            "name": "prefect-job",
                            "image": image,
                            "env": env,
                            "command": commands,
                        }
                    ],
                }
            }
        },
    }

    await run_kubernetes_job(manifest=manifest, namespace=namespace)


@flow(flow_run_name="Upgrade instance")
async def upgrade_instance(
    instance: Instance,
    upgrade_hook: UUID,
    update_flow: UUID,
    target_version: str,
    apply_utility_flow: UUID | None = None,
    prehook: UUID | None = None,
    posthook: UUID | None = None,
) -> None:
    """Orchestrate the upgrade of an application instance.

    Args:
        instance: The new instance with the target version context.
        upgrade_hook: Prefect deployment ID for the driver's core upgrade action.
        update_flow: Prefect deployment ID for UPDATE_HELM_RELEASE.
        target_version: The application version being upgraded to.
        prehook: Optional Prefect deployment ID for the driver's pre-upgrade action.
        posthook: Optional Prefect deployment ID for the driver's post-upgrade action.
    """

    logger = get_run_logger()
    context = instance.context

    # Format the release reference
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace
    namespace_labels = _build_namespace_labels(context)

    logger.info(
        f"Starting upgrade: application={context.app.name} target_version={target_version} "
        f"namespace={namespace} release={release_reference}"
    )

    await _set_deployment_in_progress(namespace, release_reference)

    try:
        # Run pre-hook
        if prehook:
            logger.info(f"Running upgrade pre-hook for {context.app.name}")
            await run_deployment_or_fail(
                flow_run_name=f"Run {context.app.name} upgrade pre-hook",
                name=prehook,
                parameters={"context": context, "target_version": target_version},
            )
            logger.info(f"Upgrade pre-hook completed for {context.app.name}")
        else:
            logger.info("No upgrade pre-hook defined, skipping")

        # Run core upgrade hook (driver's upgrade function)
        logger.info(
            f"Running core upgrade hook for {context.app.name} -> {target_version} (hook={upgrade_hook})"
        )
        await run_deployment_or_fail(
            flow_run_name=f"Upgrade {context.app.name} to {target_version}",
            name=upgrade_hook,
            parameters={"context": context, "target_version": target_version},
        )
        logger.info(f"Core upgrade hook completed for {context.app.name}")

        # Update utilities
        if context.utilities and apply_utility_flow:
            logger.info(
                f"Updating {len(context.utilities)} utilities for {context.app.name}"
            )
            await asyncio.gather(
                *[
                    update_utility(
                        utility=utility,
                        release_reference=release_reference,
                        context=context,
                        namespace=namespace,
                        apply_flow=apply_utility_flow,
                        namespace_labels=namespace_labels,
                    )
                    for utility in context.utilities
                ]
            )
            logger.info("Utilities update completed")
        else:
            logger.info("No utilities to update")

        # Apply cross-namespace ExternalName service aliases for service discovery
        aliases = compute_service_aliases(context)
        if aliases:
            await apply_service_aliases(
                aliases=aliases,
                namespace_labels=namespace_labels,
            )

        # Update Helm release to sync chart values with the new version
        logger.info(
            f"Updating Helm release for {context.app.name}:{target_version} (release={release_reference})"
        )
        release_spec = await render_application_helm_release_specifications(
            context=context,
        )

        await run_deployment_or_fail(
            flow_run_name=f"Update Helm release for {context.app.name}:{target_version}",
            name=update_flow,
            parameters={
                "namespace": namespace,
                "release_spec": release_spec,
                "reference": release_reference,
                "namespace_labels": namespace_labels,
            },
        )
        logger.info(f"Helm release updated for {context.app.name}:{target_version}")

        # Run post-hook
        if posthook:
            logger.info(f"Running upgrade post-hook for {context.app.name}")
            await run_deployment_or_fail(
                flow_run_name=f"Run {context.app.name} upgrade post-hook",
                name=posthook,
                parameters={"context": context, "target_version": target_version},
            )
            logger.info(f"Upgrade post-hook completed for {context.app.name}")
        else:
            logger.info("No upgrade post-hook defined, skipping")

        logger.info(
            f"Upgrade completed: application={context.app.name} version={target_version}"
        )
    finally:
        await _clear_deployment_in_progress(namespace, release_reference)


@flow(flow_run_name="Update instance")
async def update_instance(
    instance: Instance,
    update_flow: UUID,
    apply_utility_flow: UUID | None = None,
) -> None:
    logger = get_run_logger()
    context = instance.context

    # Format the release reference
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace

    namespace_labels = _build_namespace_labels(context)

    logger.info(
        f"Starting instance update: application={context.app.name} version={context.app.version} "
        f"namespace={namespace} release={release_reference}"
    )

    await _set_deployment_in_progress(namespace, release_reference)

    try:
        # Update utilities releases
        if context.utilities and apply_utility_flow:
            logger.info(
                f"Updating {len(context.utilities)} utilities for {context.app.name}"
            )
            await asyncio.gather(
                *[
                    update_utility(
                        utility=utility,
                        release_reference=release_reference,
                        context=context,
                        namespace=namespace,
                        apply_flow=apply_utility_flow,
                        namespace_labels=namespace_labels,
                    )
                    for utility in context.utilities
                ]
            )
            logger.info("Utilities update completed")
        else:
            logger.info("No utilities to update")

        # Apply cross-namespace ExternalName service aliases for service discovery
        aliases = compute_service_aliases(context)
        if aliases:
            await apply_service_aliases(
                aliases=aliases,
                namespace_labels=namespace_labels,
            )

        # Render the helm release specifications
        logger.info(f"Rendering Helm release specifications for {context.app.name}")
        release_spec = await render_application_helm_release_specifications(
            context=context,
        )

        logger.info(
            f"Updating Helm release for {context.app.name} (release={release_reference})"
        )
        await run_deployment_or_fail(
            name=update_flow,
            parameters={
                "namespace": namespace,
                "release_spec": release_spec,
                "reference": release_reference,
                "namespace_labels": namespace_labels,
            },
        )

        logger.info(
            f"Instance update completed: application={context.app.name} version={context.app.version}"
        )
    finally:
        await _clear_deployment_in_progress(namespace, release_reference)


@flow(flow_run_name="Create instance")
async def create_instance(
    instance: Instance,
    corehook: UUID,
    prehook: UUID | None,
    posthook: UUID | None,
    apply_utility_flow: UUID | None = None,
) -> None:
    """
    Orchestrate the setup of an application instance.

    Args:
        context_input (ContextPayload): The context payload containing all required information for computing the context.
        application_payload (ApplicationPayload): The application payload containing all required information for the application.
        labels (dict): The labels to be tagged on the resulting kubernetes resources.
        utilities (list[UtilityPayload]): The utilities to be installed.
        hook_deployments_payload (HookDeploymentsPayload): The hook deployments payload containing the pre, core and post hook deployment IDs.
    """

    context = instance.context

    # Format the release reference
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace
    namespace_labels = _build_namespace_labels(context)

    # Render helm chart and repository specs
    helm = context.app.helm
    chart_spec, helm_repo_spec, release_spec = await asyncio.gather(
        render_helm_chart_specifications(helm=helm),
        render_helm_repository_specifications(helm=helm),
        render_application_helm_release_specifications(
            context=context,
        ),
    )

    # Signal the operator to defer reconciliation during deployment
    await _set_deployment_in_progress(namespace, release_reference)

    try:
        # Install utilities first (network policies, secrets) so they are in place
        # before the application pods start
        if context.utilities and apply_utility_flow:
            await asyncio.gather(
                *[
                    install_utility(
                        utility=utility,
                        release_reference=release_reference,
                        context=context,
                        namespace=namespace,
                        apply_flow=apply_utility_flow,
                        namespace_labels=namespace_labels,
                    )
                    for utility in context.utilities
                ]
            )

        # Apply cross-namespace ExternalName service aliases for service discovery
        aliases = compute_service_aliases(context)
        if aliases:
            await apply_service_aliases(
                aliases=aliases,
                namespace_labels=namespace_labels,
            )

        if prehook:
            await run_deployment_or_fail(
                flow_run_name=f"Run {context.app.name} pre-hook",
                name=prehook,
                parameters={"context": context},
            )

        await run_deployment_or_fail(
            flow_run_name=f"Create instance for application {context.app.name}:{context.app.version}",
            name=corehook,
            parameters={
                "namespace": namespace,
                "reference": release_reference,
                "release_spec": release_spec,
                "helm_repositories": [helm_repo_spec],
                "charts": [chart_spec],
                "namespace_labels": namespace_labels,
            },
        )

        if posthook:
            await run_deployment_or_fail(
                flow_run_name=f"Run {context.app.name} post-hook",
                name=posthook,
                parameters={"context": context},
            )
    finally:
        await _clear_deployment_in_progress(namespace, release_reference)


# ─── CRD-Based Orchestration Flows ───────────────────────────────────
#
# These flows create/update/delete StyrminDeployment CRDs instead of
# managing HelmReleases and utility resources directly. The operator
# handles all Kubernetes resource lifecycle from the CRD.
#
# Driver pre/post hooks are retained — they are imperative actions
# that remain Prefect-managed.


@flow(flow_run_name="Create instance (CRD)")
async def create_instance_crd(
    instance: Instance,
    prehook: UUID | None,
    posthook: UUID | None,
    internal: bool = False,
) -> None:
    """Create a StyrminDeployment CRD for the operator to process.

    The operator handles all resource creation in guaranteed order:
    NetworkPolicies/Secrets -> HelmRelease -> Services/Middlewares.

    Driver pre/post hooks remain Prefect-managed.
    """
    logger = get_run_logger()
    context = instance.context
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace

    logger.info(
        "Creating StyrminDeployment CRD for %s:%s in %s",
        context.app.name,
        context.app.version,
        namespace,
    )

    # Run pre-hook before CRD creation (imperative action)
    if prehook:
        await run_driver_action_or_fail(
            flow_run_name=f"Run {context.app.name} pre-hook",
            name=prehook,
            parameters={"context": context},
        )

    # Build and create the StyrminDeployment CRD
    crd_body = build_styrmin_deployment_body(
        context=context,
        release_reference=release_reference,
        namespace=namespace,
        internal=internal,
    )

    namespace_labels = _build_namespace_labels(context)
    await apply_kubernetes_namespace(namespace=namespace, labels=namespace_labels)

    await _apply_styrmin_deployment_crd(body=crd_body, namespace=namespace)

    logger.info(
        "StyrminDeployment CRD created: %s/%s",
        namespace,
        release_reference,
    )

    # Apply cross-namespace ExternalName service aliases for service discovery
    aliases = compute_service_aliases(context)
    if aliases:
        namespace_labels = _build_namespace_labels(context)
        await apply_service_aliases(
            aliases=aliases,
            namespace_labels=namespace_labels,
        )

    # Run post-hook after CRD creation (imperative action)
    if posthook:
        await run_driver_action_or_fail(
            flow_run_name=f"Run {context.app.name} post-hook",
            name=posthook,
            parameters={"context": context},
        )


@flow(flow_run_name="Update instance (CRD)")
async def update_instance_crd(
    instance: Instance,
) -> None:
    """Update the StyrminDeployment CRD spec for the operator to reconcile."""
    logger = get_run_logger()
    context = instance.context
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace

    crd_body = build_styrmin_deployment_body(
        context=context,
        release_reference=release_reference,
        namespace=namespace,
    )

    await _apply_styrmin_deployment_crd(body=crd_body, namespace=namespace)

    # Apply cross-namespace ExternalName service aliases for service discovery
    aliases = compute_service_aliases(context)
    if aliases:
        namespace_labels = _build_namespace_labels(context)
        await apply_service_aliases(
            aliases=aliases,
            namespace_labels=namespace_labels,
        )

    logger.info("StyrminDeployment CRD updated: %s/%s", namespace, release_reference)


@flow(flow_run_name="Upgrade instance (CRD)")
async def upgrade_instance_crd(
    instance: Instance,
    upgrade_hook: UUID,
    target_version: str,
    prehook: UUID | None = None,
    posthook: UUID | None = None,
) -> None:
    """Upgrade via StyrminDeployment CRD. Driver hooks remain Prefect-managed."""
    logger = get_run_logger()
    context = instance.context
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace

    # Write the new CRD spec and reset its status BEFORE running hooks.
    # The driver's upgrade hook typically calls back into the server (e.g.
    # stop_components / start_components / upgrade_deployment_version), each
    # of which spawns a nested update_instance_crd flow that advances the
    # CRD to a fresh instance. Writing the CRD at the end of this flow
    # would stomp those hook-driven updates with this flow's (older)
    # instance. Writing here first lets hook updates layer correctly on top.
    crd_body = build_styrmin_deployment_body(
        context=context,
        release_reference=release_reference,
        namespace=namespace,
    )
    await _apply_styrmin_deployment_crd(body=crd_body, namespace=namespace)

    # Reset status.displayState + phase atomically with the spec change.
    # Without this there is a window where the CRD carries the new
    # instanceId / appVersion but the previous rollout's "Running"
    # displayState, letting a stale agent report race the server into
    # prematurely flipping Deployment.status to RUNNING.
    await patch_custom_resource_status(
        plural=CRD_PLURAL,
        # The CR is named after its namespace, not after the release reference
        # (``build_styrmin_deployment_body``). The two are the same string for an
        # ordinary deployment and differ for a clone counterpart, which adopts
        # the source's Helm release name (010 research D2).
        reference=namespace,
        group=CRD_GROUP,
        version=CRD_VERSION,
        namespace=namespace,
        status_patch={"displayState": "Deploying", "phase": "Pending"},
    )

    if prehook:
        await run_driver_action_or_fail(
            flow_run_name=f"Run {context.app.name} upgrade pre-hook",
            name=prehook,
            parameters={"context": context, "target_version": target_version},
        )

    await run_driver_action_or_fail(
        flow_run_name=f"Upgrade {context.app.name} to {target_version}",
        name=upgrade_hook,
        parameters={"context": context, "target_version": target_version},
    )

    # Apply cross-namespace ExternalName service aliases for service discovery
    aliases = compute_service_aliases(context)
    if aliases:
        namespace_labels = _build_namespace_labels(context)
        await apply_service_aliases(
            aliases=aliases,
            namespace_labels=namespace_labels,
        )

    if posthook:
        await run_driver_action_or_fail(
            flow_run_name=f"Run {context.app.name} upgrade post-hook",
            name=posthook,
            parameters={"context": context, "target_version": target_version},
        )

    logger.info(
        "Upgrade CRD updated: %s:%s in %s", context.app.name, target_version, namespace
    )


# ─── Helpers ─────────────────────────────────────────────────────────


def _build_instance_entity(
    model: ApplicationInstanceModel | None,
) -> InstanceEntity | None:
    """Convert a DB ApplicationInstance row to a domain Instance entity.

    Returns None when *model* is None so callers can pass optional
    ``current_instance`` rows without a separate null-check.
    """
    if model is None:
        return None
    return InstanceEntity(
        id=model.id,
        name=model.name,
        application_version=model.application_version,
        status=InstanceStatusEntity(model.status.value),
        context=GlobalContext.model_validate(model.context),
        application_driver_version_id=model.application_driver_version_id,
        deployment_id=model.deployment_id,
    )
