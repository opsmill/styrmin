from typing import Any

from prefect import task

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.factory import (
    load_utilities,
)
from styrmin_backend.context.models.contexts import GlobalContext


@task(task_run_name="Render Helm Chart specifications")
async def render_application_helm_release_specifications(
    context: GlobalContext,
) -> dict[str, Any]:
    utility_objs = load_utilities([utility.kind for utility in context.utilities])

    helm_release_builder = ApplicationHelmReleaseBuilder(
        context=context,
        label_prefix="styrmin",
    )

    release = helm_release_builder.build(
        utilities=utility_objs,
    )
    return release.render()
