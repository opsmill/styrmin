import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID

import httpx
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client.api_client import ApiException
from prefect import flow
from prefect.client.schemas.objects import FlowRun
from prefect.logging import get_run_logger

from prefect.states import Completed, format_exception
from prefect.client.schemas.objects import State

from styrmin_backend.agent.service.kubernetes.exceptions import (
    CustomResourceNotFound,
    CustomResourceWriteConflictError,
    JobFailedError,
)
from styrmin_backend.agent.service.kubernetes.primitives import (
    create_event,
    get_custom_resource,
    json_pointer_token,
    patch_custom_resource,
    replace_spec_keys_json_patch,
    run_kubernetes_job,
)
from styrmin_backend.agent.steps.reporter import ReportedStep, StepReporter
from styrmin_backend.agent.tasks.utils import (
    action_job_variables,
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
from styrmin_backend.domain import steps
from styrmin_backend.domain.models import Instance
from styrmin_backend.domain.models import Instance as InstanceEntity
from styrmin_backend.domain.models import InstanceStatus as InstanceStatusEntity
from styrmin_backend.domain.models import StepParent
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator
from styrmin_backend.services.reconciliation.remediation import (
    Remediation,
    Remediator,
)
from styrmin_backend.services.auth.action_token import action_api_token
from styrmin_backend.services.steps.internal_flows import (
    end_step,
    fail_open_steps,
    open_task_step,
)
from styrmin_backend.services.unit_of_work import get_unit_of_work
from styrmin_backend.agent.service.kubernetes.primitives import (
    patch_custom_resource_status,
    apply_kubernetes_namespace,
    upsert_custom_resource,
)
from styrmin_backend import config
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_IN_PROGRESS,
    ANNOTATION_INSTANCE_SEQUENCE,
    CRD_GROUP,
    CRD_KIND,
    CRD_PLURAL,
    CRD_VERSION,
    EVENT_NEWER_INSTANCE_KEPT,
    HELMRELEASE_GROUP,
    HELMRELEASE_PLURAL,
    HELMRELEASE_VERSION,
)
from styrmin_backend.operator.crd.builder import build_styrmin_deployment_body

#: The USER flow that runs a job's command; must match its catalogue entry.
RUN_JOB_COMMAND_DEPLOYMENT = "run_job_command/run_job_command"

#: Attempts at a StyrminDeployment write while other writes keep changing it.
_CRD_WRITE_ATTEMPTS = 5
_EVENT_COMPONENT = "styrmin-agent"
_SEQUENCE_ANNOTATION_PATH = (
    f"/metadata/annotations/{json_pointer_token(ANNOTATION_INSTANCE_SEQUENCE)}"
)


@dataclass(frozen=True)
class KeptInstance:
    """A newer instance that a flow found on the StyrminDeployment and left in place."""

    instance_id: str | None
    sequence: int
    resource_uid: str | None


def _build_namespace_labels(
    context: GlobalContext, label_prefix: str = "styrmin"
) -> dict[str, str]:
    """Build Kubernetes namespace labels from context labels."""
    return {
        f"{label_prefix}/{key}": str(value) for key, value in context.labels.items()
    }


async def _apply_styrmin_deployment_crd(
    *, body: dict, namespace: str
) -> KeptInstance | None:
    """Create or update the StyrminDeployment unless it holds a higher instance sequence.

    Returns the newer instance it left in place, or None when it wrote ``body`` (#386).
    """
    name = body["metadata"]["name"]
    for _ in range(_CRD_WRITE_ATTEMPTS):
        live = await _read_styrmin_deployment(name=name, namespace=namespace)
        if live is None:
            try:
                await upsert_custom_resource(
                    plurals=CRD_PLURAL,
                    body=body,
                    group=CRD_GROUP,
                    version=CRD_VERSION,
                    namespace=namespace,
                    update=False,
                )
            except ApiException as exc:
                if exc.status != HTTPStatus.CONFLICT:  # Created by another flow.
                    raise
                continue
            return None
        kept = _kept_instance(live, body)
        if kept is not None:
            return kept
        read_version = live["metadata"]["resourceVersion"]
        try:
            await patch_custom_resource(
                plural=CRD_PLURAL,
                reference=name,
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=namespace,
                patch=_conditional_patch(live, body),
            )
        except ApiException as exc:
            # A failed resourceVersion test and a schema violation both return 422.
            if exc.status != HTTPStatus.CONFLICT and not (
                exc.status == HTTPStatus.UNPROCESSABLE_CONTENT
                and await _changed_since(read_version, name=name, namespace=namespace)
            ):
                raise
            continue
        return None
    raise CustomResourceWriteConflictError(
        f"Could not write StyrminDeployment {namespace}/{name}: another write "
        f"changed it between each read and write, {_CRD_WRITE_ATTEMPTS} times in a "
        "row. The next change to the deployment writes it again."
    )


async def _read_styrmin_deployment(*, name: str, namespace: str) -> dict | None:
    try:
        live = await get_custom_resource(
            plural=CRD_PLURAL,
            name=name,
            group=CRD_GROUP,
            version=CRD_VERSION,
            namespace=namespace,
        )
    except CustomResourceNotFound:
        return None
    assert isinstance(live, dict)
    return live


async def _changed_since(read_version: str, *, name: str, namespace: str) -> bool:
    live = await _read_styrmin_deployment(name=name, namespace=namespace)
    return live is None or live["metadata"]["resourceVersion"] != read_version


def _kept_instance(live: dict, body: dict) -> KeptInstance | None:
    live_sequence = _instance_sequence(live)
    sequence = _instance_sequence(body)
    if live_sequence is None or sequence is None or live_sequence <= sequence:
        return None
    return KeptInstance(
        instance_id=live["spec"].get("instanceId"),
        sequence=live_sequence,
        resource_uid=live["metadata"].get("uid"),
    )


def _conditional_patch(live: dict, body: dict) -> list[dict]:
    """The patch that writes ``body`` only over the version of the resource that was read."""
    live_metadata = live["metadata"]
    live_annotations = live_metadata.get("annotations") or {}
    annotations = body["metadata"].get("annotations") or {}
    patch: list[dict] = [
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": live_metadata["resourceVersion"],
        }
    ]
    # A per-key annotation ``add`` needs the map to exist.
    if annotations and not live_annotations:
        patch.append({"op": "add", "path": "/metadata/annotations", "value": {}})
    # A sequence left in place would describe the previous spec.
    if (
        ANNOTATION_INSTANCE_SEQUENCE in live_annotations
        and ANNOTATION_INSTANCE_SEQUENCE not in annotations
    ):
        patch.append({"op": "remove", "path": _SEQUENCE_ANNOTATION_PATH})
    return patch + replace_spec_keys_json_patch(body)


def _instance_sequence(resource: dict) -> int | None:
    """The sequence of the resource's instance, from its annotation; None when unknown."""
    annotations = resource["metadata"].get("annotations") or {}
    try:
        return int(annotations[ANNOTATION_INSTANCE_SEQUENCE])
    except KeyError, ValueError:
        return None


async def _write_styrmin_deployment(
    reporter: StepReporter,
    step: ReportedStep,
    *,
    body: dict,
    namespace: str,
    namespace_labels: dict[str, str],
) -> bool:
    """Write the StyrminDeployment; False, recorded on the step, when it holds a newer instance."""
    # The namespace is missing when the create flow stopped before it (#313).
    await apply_kubernetes_namespace(namespace=namespace, labels=namespace_labels)
    kept = await _apply_styrmin_deployment_crd(body=body, namespace=namespace)
    if kept is None:
        return True
    name = body["metadata"]["name"]
    message = (
        f"Left StyrminDeployment {namespace}/{name} unchanged: it holds instance "
        f"{kept.instance_id} (sequence {kept.sequence}) of a later change. This "
        f"task's instance is {body['spec'].get('instanceId')} (sequence "
        f"{_instance_sequence(body)})."
    )
    run_logger = get_run_logger()
    run_logger.info(message)
    await reporter.record_output(step.id, message, truncated=False)
    try:
        await create_event(
            involved_object=kubeclient.V1ObjectReference(
                api_version=f"{CRD_GROUP}/{CRD_VERSION}",
                kind=CRD_KIND,
                name=name,
                namespace=namespace,
                uid=kept.resource_uid,
            ),
            reason=EVENT_NEWER_INSTANCE_KEPT,
            message=message,
            component=_EVENT_COMPONENT,
        )
    except ApiException as exc:
        run_logger.warning(
            "Could not record the %s event on StyrminDeployment %s/%s: %s",
            EVENT_NEWER_INSTANCE_KEPT,
            namespace,
            name,
            exc.reason,
        )
    return False


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
    plan_step_id = await open_task_step(task_id, steps.PLAN)
    try:
        remediation = await _plan_remediation(
            deployment_id=deployment_id,
            new_instance_id=new_instance_id,
            current_instance_id=current_instance_id,
        )
    except Exception as exc:
        await end_step(plan_step_id, error=format_exception(exc))
        raise
    await end_step(plan_step_id)
    if isinstance(remediation, State):
        return remediation

    # Applied after the unit of work closes, so its connection is not held
    # while the remediation flow runs or while the action token is written.
    async with action_api_token() as api_token:
        try:
            flow_info = await remediation.apply(api_token=api_token, task_id=task_id)
        except Exception as exc:
            # A crashed remediation Job cannot end the step it was running.
            await fail_open_steps(StepParent.of_task(task_id), str(exc))
            raise
    return flow_info.state


async def _plan_remediation(
    *,
    deployment_id: UUID,
    new_instance_id: UUID,
    current_instance_id: UUID | None,
) -> Remediation | State:
    """Build the remediation, or the ``Completed`` state when there is nothing to apply."""
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
        return remediation


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
    """Run the job's command in the USER flow ``run_job_command`` with an action token (019 research D11)."""
    async with action_api_token() as api_token:
        try:
            await run_deployment_or_fail(
                name=RUN_JOB_COMMAND_DEPLOYMENT,
                parameters={
                    "task_id": task_id,
                    "runtime_class": runtime_class,
                    "env": env,
                    "namespace": namespace,
                    "commands": commands,
                    "image": image,
                },
                job_variables=action_job_variables(api_token, task_id=task_id),
            )
        except Exception as exc:
            # A crashed command Job cannot end the step it was running.
            await fail_open_steps(StepParent.of_task(task_id), str(exc))
            raise


@flow(flow_run_name="Run job command")
async def run_job_command(
    task_id: UUID,
    runtime_class: str,
    env: list[dict],
    namespace: str,
    commands: list[str],
    image: str,
) -> None:
    """Run the job's command as a Kubernetes Job and record it as the ``command`` step."""
    manifest = _build_job_manifest(
        task_id=task_id,
        runtime_class=runtime_class,
        env=env,
        namespace=namespace,
        commands=commands,
        image=image,
    )
    reporter = StepReporter.from_env()
    async with reporter.step(*steps.COMMAND) as step:
        try:
            await run_kubernetes_job(manifest=manifest, namespace=namespace)
        except JobFailedError as exc:
            if exc.output is not None:
                await reporter.record_output(step.id, exc.output, exc.truncated)
            raise


def _build_job_manifest(
    *,
    task_id: UUID,
    runtime_class: str,
    env: list[dict],
    namespace: str,
    commands: list[str],
    image: str,
) -> dict:
    return {
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
    reporter = StepReporter.from_env()
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
        async with reporter.step(*steps.SETUP_PRE_HOOK) as step:
            await run_driver_action_or_fail(
                step_id=step.id,
                flow_run_name=f"Run {context.app.name} pre-hook",
                name=prehook,
                parameters={"context": context},
            )

    async with reporter.step(*steps.STYRMIN_DEPLOYMENT_WRITE) as step:
        # Build and create the StyrminDeployment CRD
        crd_body = build_styrmin_deployment_body(
            context=context,
            release_reference=release_reference,
            namespace=namespace,
            internal=internal,
            instance_sequence=instance.sequence,
        )

        written = await _write_styrmin_deployment(
            reporter,
            step,
            body=crd_body,
            namespace=namespace,
            namespace_labels=_build_namespace_labels(context),
        )

    # A later change wrote its own StyrminDeployment and service aliases.
    if written:
        logger.info(
            "StyrminDeployment CRD created: %s/%s",
            namespace,
            release_reference,
        )
        await _apply_service_aliases_step(reporter, context)

    # Run post-hook after CRD creation (imperative action)
    if posthook:
        async with reporter.step(*steps.SETUP_POST_HOOK) as step:
            await run_driver_action_or_fail(
                step_id=step.id,
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
    reporter = StepReporter.from_env()
    context = instance.context
    release_reference = context.instance.release_reference
    namespace = context.instance.namespace

    async with reporter.step(*steps.STYRMIN_DEPLOYMENT_WRITE) as step:
        crd_body = build_styrmin_deployment_body(
            context=context,
            release_reference=release_reference,
            namespace=namespace,
            instance_sequence=instance.sequence,
        )

        written = await _write_styrmin_deployment(
            reporter,
            step,
            body=crd_body,
            namespace=namespace,
            namespace_labels=_build_namespace_labels(context),
        )

    if written:
        await _apply_service_aliases_step(reporter, context)
        logger.info(
            "StyrminDeployment CRD updated: %s/%s", namespace, release_reference
        )


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
    reporter = StepReporter.from_env()
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
    async with reporter.step(*steps.STYRMIN_DEPLOYMENT_WRITE) as step:
        crd_body = build_styrmin_deployment_body(
            context=context,
            release_reference=release_reference,
            namespace=namespace,
            instance_sequence=instance.sequence,
        )
        written = await _write_styrmin_deployment(
            reporter,
            step,
            body=crd_body,
            namespace=namespace,
            namespace_labels=_build_namespace_labels(context),
        )

        # Reset the status with the spec, so the previous rollout's Running cannot
        # set the deployment RUNNING. A newer instance keeps its rollout's status.
        if written:
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
        async with reporter.step(*steps.UPGRADE_PRE_HOOK) as step:
            await run_driver_action_or_fail(
                step_id=step.id,
                flow_run_name=f"Run {context.app.name} upgrade pre-hook",
                name=prehook,
                parameters={"context": context, "target_version": target_version},
            )

    async with reporter.step(*steps.UPGRADE_CORE_HOOK) as step:
        await run_driver_action_or_fail(
            step_id=step.id,
            flow_run_name=f"Upgrade {context.app.name} to {target_version}",
            name=upgrade_hook,
            parameters={"context": context, "target_version": target_version},
        )

    if written:
        await _apply_service_aliases_step(reporter, context)

    if posthook:
        async with reporter.step(*steps.UPGRADE_POST_HOOK) as step:
            await run_driver_action_or_fail(
                step_id=step.id,
                flow_run_name=f"Run {context.app.name} upgrade post-hook",
                name=posthook,
                parameters={"context": context, "target_version": target_version},
            )

    logger.info(
        "Upgrade CRD updated: %s:%s in %s", context.app.name, target_version, namespace
    )


async def _apply_service_aliases_step(
    reporter: StepReporter, context: GlobalContext
) -> None:
    """Apply cross-namespace ExternalName service aliases for service discovery, if any."""
    aliases = compute_service_aliases(context)
    if not aliases:
        return
    async with reporter.step(*steps.SERVICE_ALIASES):
        await apply_service_aliases(
            aliases=aliases,
            namespace_labels=_build_namespace_labels(context),
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
        sequence=model.sequence,
    )
