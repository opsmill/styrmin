"""Pin what ``run_deployment_or_fail`` and its driver-action variant hand to Prefect."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from prefect.workers.base import BaseJobConfiguration

from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
    action_job_variables,
    run_deployment_or_fail,
    run_driver_action_or_fail,
)
from styrmin_backend.services.reconciliation.remediation import (
    Remediation,
    RemediationType,
)

MODULE = "styrmin_backend.agent.tasks.utils"
REMEDIATION_MODULE = "styrmin_backend.services.reconciliation.remediation"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        API_TOKEN_ENV,
        TASK_ID_ENV,
        BACKUP_ID_ENV,
        RESTORE_ID_ENV,
        STEP_ID_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


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
async def test_driver_action_forwards_token_and_task_and_adds_hook_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id, step_id = uuid4(), uuid4()
    monkeypatch.setenv(API_TOKEN_ENV, "action-token")
    monkeypatch.setenv(TASK_ID_ENV, str(task_id))
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{MODULE}.arun_deployment", run):
        await run_driver_action_or_fail(
            name="flow/deployment", parameters={}, step_id=step_id
        )

    assert run.await_args is not None
    assert "step_id" not in run.await_args.kwargs
    assert run.await_args.kwargs["job_variables"] == {
        "env": {
            API_TOKEN_ENV: "action-token",
            TASK_ID_ENV: str(task_id),
            STEP_ID_ENV: str(step_id),
        }
    }


def test_action_job_variables_sets_each_given_variable() -> None:
    ids = {name: uuid4() for name in ("task", "backup", "restore", "step")}

    variables = action_job_variables(
        "action-token",
        task_id=ids["task"],
        backup_id=ids["backup"],
        restore_id=ids["restore"],
        step_id=ids["step"],
    )

    assert variables == {
        "env": {
            API_TOKEN_ENV: "action-token",
            TASK_ID_ENV: str(ids["task"]),
            BACKUP_ID_ENV: str(ids["backup"]),
            RESTORE_ID_ENV: str(ids["restore"]),
            STEP_ID_ENV: str(ids["step"]),
        }
    }
    assert action_job_variables(None) == {}


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
async def test_remediation_passes_task_id_to_its_flow_run() -> None:
    remediation = Remediation.model_construct(
        instance=MagicMock(id=uuid4()),
        flow_id=uuid4(),
        parameters={},
        type=RemediationType.CREATE_INSTANCE,
    )
    task_id = uuid4()
    run = AsyncMock(return_value=_completed_flow_run())
    with patch(f"{REMEDIATION_MODULE}.run_deployment_or_fail", run):
        await remediation.apply(api_token="action-token", task_id=task_id)

    assert run.await_args is not None
    assert run.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token", TASK_ID_ENV: str(task_id)}
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
        values=action_job_variables("action-token", task_id="task-1"),
    )

    assert configuration.env["STYRMIN_URL_API"] == "http://styrmin:8000"
    assert configuration.env[API_TOKEN_ENV] == "action-token"
    assert configuration.env[TASK_ID_ENV] == "task-1"
