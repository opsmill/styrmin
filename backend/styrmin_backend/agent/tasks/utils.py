from typing import Any

from prefect.client.schemas.objects import FlowRun
from prefect.deployments.flow_runs import arun_deployment


async def run_deployment_or_fail(**kwargs: Any) -> FlowRun:
    """Run a Prefect deployment and raise if the flow run fails or crashes."""
    # Prefect's 5s default rounds every hook/remediation wait up to 5s.
    kwargs.setdefault("poll_interval", 1)
    flow_run: FlowRun = await arun_deployment(**kwargs)
    if flow_run.state and flow_run.state.is_failed():
        raise RuntimeError(
            f"Deployment flow run {flow_run.id} failed: {flow_run.state.message}"
        )
    if flow_run.state and flow_run.state.is_crashed():
        raise RuntimeError(
            f"Deployment flow run {flow_run.id} crashed: {flow_run.state.message}"
        )
    return flow_run
