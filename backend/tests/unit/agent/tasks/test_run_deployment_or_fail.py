"""Pin the poll interval ``run_deployment_or_fail`` hands to Prefect."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrmin_backend.agent.tasks.utils import run_deployment_or_fail

MODULE = "styrmin_backend.agent.tasks.utils"


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
