import os
from typing import Any

from prefect.client.schemas.objects import FlowRun
from prefect.deployments.flow_runs import arun_deployment

#: Carries a reconcile's API token into the jobs it starts (ADR-059). The SDK
#: reads the same variable, so a driver action using it is authenticated too.
API_TOKEN_ENV = "STYRMIN_TOKEN"


def api_token_job_variables(token: str | None) -> dict[str, Any]:
    """Prefect job variables that set ``API_TOKEN_ENV`` in the flow run's job."""
    return {"env": {API_TOKEN_ENV: token}} if token else {}


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


async def run_driver_action_or_fail(**kwargs: Any) -> FlowRun:
    """``run_deployment_or_fail`` for a driver action: forwards this job's API token."""
    return await run_deployment_or_fail(
        job_variables=api_token_job_variables(os.environ.get(API_TOKEN_ENV)),
        **kwargs,
    )
