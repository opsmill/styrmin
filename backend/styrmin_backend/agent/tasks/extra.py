from typing import Any
from uuid import UUID

from prefect import flow, task
from prefect.deployments.flow_runs import arun_deployment

from styrmin_backend.agent.service.kubernetes.resources.builders.utility import (
    UtilityResourceBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import Utility
from styrmin_backend.agent.service.kubernetes.resources.utilities.factory import (
    build_utility,
)
from styrmin_backend.context.models.contexts import GlobalContext, UtilityContext
from styrmin_backend import config


async def _apply_utility(
    utility: UtilityContext,
    release_reference: str,
    context: GlobalContext,
    namespace: str,
    apply_flow: UUID,
    action: str,
    namespace_labels: dict[str, str] | None = None,
) -> None:
    """Shared logic for install and update utility flows."""
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    utility_obj = build_utility(utility_kind=utility.kind.value)

    resources = await render_utility_resources(
        utility=utility_obj,
        release_reference=release_reference,
        namespace=namespace,
        context=context,
    )

    await arun_deployment(
        flow_run_name=f"{action} Utility Resources",
        name=apply_flow,
        parameters={
            "namespace": namespace,
            "resources": resources,
            "namespace_labels": namespace_labels,
        },
    )


@flow(flow_run_name="Install utility")
async def install_utility(
    utility: UtilityContext,
    release_reference: str,
    context: GlobalContext,
    namespace: str,
    apply_flow: UUID,
    namespace_labels: dict[str, str] | None = None,
) -> None:
    await _apply_utility(
        utility=utility,
        release_reference=release_reference,
        context=context,
        namespace=namespace,
        apply_flow=apply_flow,
        action="Install",
        namespace_labels=namespace_labels,
    )


@flow(flow_run_name="Update utility")
async def update_utility(
    utility: UtilityContext,
    release_reference: str,
    context: GlobalContext,
    namespace: str,
    apply_flow: UUID,
    namespace_labels: dict[str, str] | None = None,
) -> None:
    await _apply_utility(
        utility=utility,
        release_reference=release_reference,
        context=context,
        namespace=namespace,
        apply_flow=apply_flow,
        action="Update",
        namespace_labels=namespace_labels,
    )


@task(task_run_name="Render utility resources")
async def render_utility_resources(
    utility: Utility,
    release_reference: str,
    namespace: str,
    context: GlobalContext,
) -> list[dict[str, Any]]:
    if not config.SETTINGS.initialized:
        config.SETTINGS.initialize()

    builder = UtilityResourceBuilder(context=context)
    return builder.build(
        utility=utility,
        release_reference=release_reference,
        namespace=namespace,
    )
