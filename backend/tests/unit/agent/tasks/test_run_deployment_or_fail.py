"""Pin what ``run_deployment_or_fail`` and its driver-action variant hand to Prefect."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from prefect.workers.base import BaseJobConfiguration

from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    api_token_job_variables,
    run_deployment_or_fail,
    run_driver_action_or_fail,
)
from styrmin_backend.services.reconciliation.remediation import (
    Remediation,
    RemediationType,
)

MODULE = "styrmin_backend.agent.tasks.utils"
REMEDIATION_MODULE = "styrmin_backend.services.reconciliation.remediation"


def _completed_flow_run() -> MagicMock:
    flow_run = MagicMock()
    flow_run.state.is_failed.return_value = False
    flow_run.state.is_crashed.return_value = False
    return flow_run


@pytest.mark.asyncio
async def test_defaults_poll_interval_to_one_second() -> None:
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_deployment_or_fail(name="flow/deployment", parameters={})

    assert run.await_args is not None
    assert run.await_args.kwargs["poll_interval"] == 1


@pytest.mark.asyncio
async def test_explicit_poll_interval_is_kept() -> None:
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_deployment_or_fail(name="flow/deployment", poll_interval=10)

    assert run.await_args is not None
    assert run.await_args.kwargs["poll_interval"] == 10


# Driver action token forwarding (issue #381, ADR-059).


@pytest.mark.asyncio
async def test_driver_action_receives_this_jobs_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_TOKEN_ENV, "action-token")
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_driver_action_or_fail(name="flow/deployment", parameters={})

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token"}
    }


@pytest.mark.asyncio
async def test_driver_action_without_token_gets_no_job_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_TOKEN_ENV, raising=False)
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_driver_action_or_fail(name="flow/deployment", parameters={})

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {}


@pytest.mark.asyncio
async def test_remediation_passes_token_to_its_flow_run() -> None:
    remediation = Remediation.model_construct(
        instance=MagicMock(id=uuid4()),
        flow_id=uuid4(),
        parameters={},
        type=RemediationType.UPGRADE_INSTANCE,
    )
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{REMEDIATION_MODULE}.run_deployment_or_fail", run):
        await remediation.apply(api_token="action-token")

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token"}
    }


@pytest.mark.asyncio
async def test_token_env_merges_with_work_pool_env_defaults() -> None:
    """Prefect adds a flow run's ``env`` to the pool's default env instead of replacing it."""
    base_job_template = {
        "job_configuration": {"env": "{{ env }}", "command": "{{ command }}"},
        "variables": {
            "properties": {
                "env": {
                    "type": "object",
                    "default": {"STYRMIN_URL_API": "http://styrmin:8000"},
                },
                "command": {"type": "string"},
            }
        },
    }
    configuration = await BaseJobConfiguration.from_template_and_values(
        base_job_template=base_job_template,
        values=api_token_job_variables("action-token"),
    )

    assert configuration.env["STYRMIN_URL_API"] == "http://styrmin:8000"
    assert configuration.env[API_TOKEN_ENV] == "action-token"
