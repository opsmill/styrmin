"""Restore steps (spec 019, research D13).

The USER flow ``execute_velero_restore`` records "Delete the namespace", "Run
the Velero restore" and "Run the recovery". The INTERNAL flow
``execute_restore_workflow`` gives it an action token and the restore id, and
fails its open steps when it dies. A cross-target restore also runs the alias
step after the recovery, and a refused alias write fails the restore (#530).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from kubernetes_asyncio.client import ApiException
from prefect.client.schemas.actions import DeploymentFlowRunCreate
from prefect.client.schemas.objects import StateType

from styrmin_backend import config
from styrmin_backend.agent.service.kubernetes.velero.client import VeleroClientError
from styrmin_backend.agent.steps.reporter import StepReporter
from styrmin_backend.agent.tasks import service_aliases
from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.db.models import RestoreStatus
from styrmin_backend.domain.models import Deployment, StepParent
from styrmin_backend.workflows.templates.backup import (
    execute_restore_workflow,
    execute_velero_restore_flow,
)
from tests.helpers.step_api import FakeStepApi
from tests.helpers.unit_of_work import yield_unit_of_work
from tests.unit.counterpart_crd_fixtures import (
    COUNTERPART_NAMESPACE,
    SOURCE_RELEASE_REFERENCE,
    counterpart_context,
    counterpart_deployment,
)

MODULE = "styrmin_backend.workflows.templates.backup"
SERVICE_MODULE = "styrmin_backend.services.backup.service"
RECOVERY_MODULE = "styrmin_backend.operator.restore_recovery"
TARGET_NAMESPACE = "styrmin-app"

Event = tuple[Any, ...]

ALL_STEPS_SUCCEEDED = [
    ("STARTED", "restore:namespace"),
    ("SUCCEEDED", "restore:namespace"),
    ("STARTED", "restore:velero"),
    ("SUCCEEDED", "restore:velero"),
    ("STARTED", "restore:recovery"),
    ("SUCCEEDED", "restore:recovery"),
]


@pytest.fixture
def events() -> list[Event]:
    return []


@pytest.fixture
def restore_id(monkeypatch: pytest.MonkeyPatch) -> UUID:
    for name in (TASK_ID_ENV, BACKUP_ID_ENV, STEP_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    restore_id = uuid4()
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", SecretStr("action-token"))
    monkeypatch.setenv(RESTORE_ID_ENV, str(restore_id))
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    return restore_id


@pytest.fixture
def api(
    monkeypatch: pytest.MonkeyPatch, events: list[Event], restore_id: UUID
) -> FakeStepApi:
    del restore_id
    fake = FakeStepApi(events)
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def alias_step(events: list[Event]) -> Iterator[AsyncMock]:
    """Stand in for the alias step, which records ``("alias step", context)``."""

    async def _record(reporter: StepReporter, context: GlobalContext) -> None:
        assert isinstance(reporter, StepReporter)
        events.append(("alias step", context))

    step = AsyncMock(side_effect=_record)
    with patch(f"{MODULE}.apply_service_aliases_step", step):
        yield step


def _alias_write_error() -> ApiException:
    return ApiException(status=500, reason="Internal Server Error")


#: The recovery error that a refused alias write stores for the INTERNAL flow.
ALIAS_ERROR = f"Service alias step failed: {_alias_write_error()}"


@pytest.fixture
def refused_alias_write(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Run the real alias step with one alias to write, which the API refuses."""
    monkeypatch.setattr(
        service_aliases,
        "with_current_peer_services",
        AsyncMock(side_effect=lambda context: context),
    )
    monkeypatch.setattr(
        service_aliases,
        "compute_service_aliases",
        lambda _context: [{"metadata": {"name": "db"}}],
    )
    monkeypatch.setattr(
        service_aliases, "find_stale_service_aliases", AsyncMock(return_value=[])
    )
    write = AsyncMock(side_effect=_alias_write_error())
    monkeypatch.setattr(service_aliases, "apply_service_aliases", write)
    return write


def _velero_restore(phase: str, **status: Any) -> dict[str, Any]:
    return {
        "metadata": {"name": "styrmin-restore-1"},
        "status": {"phase": phase, **status},
    }


@asynccontextmanager
async def _user_flow(
    *,
    restore: dict[str, Any] | None = None,
    poll_error: Exception | None = None,
    namespace_stays: bool = False,
    recovery_error: Exception | None = None,
    counterpart_recovery_error: Exception | None = None,
) -> AsyncIterator[SimpleNamespace]:
    """Fake the cluster, Velero and the recovery around ``execute_velero_restore``."""
    api_client = MagicMock()
    api_client.close = AsyncMock()
    core_api = MagicMock()
    core_api.delete_namespace = AsyncMock()
    core_api.read_namespace = AsyncMock(
        side_effect=None if namespace_stays else ApiException(status=404)
    )
    velero = MagicMock()
    velero.create_restore_from_dict = AsyncMock()
    velero.poll_restore_status = AsyncMock(
        return_value=restore or _velero_restore("Completed"), side_effect=poll_error
    )
    recovery = SimpleNamespace(
        mark_restoring=AsyncMock(),
        reapply_and_finalize=AsyncMock(side_effect=recovery_error),
        reapply_with_counterpart_identity=AsyncMock(
            side_effect=counterpart_recovery_error
        ),
        mark_failed=AsyncMock(),
    )
    variable = MagicMock()
    variable.set = AsyncMock()
    with (
        patch(
            "styrmin_backend.agent.service.kubernetes.dependency.load_kubernetes_config",
            AsyncMock(),
        ),
        patch("kubernetes_asyncio.client.ApiClient", return_value=api_client),
        patch("kubernetes_asyncio.client.CoreV1Api", return_value=core_api),
        patch(
            "styrmin_backend.agent.service.kubernetes.velero.client.VeleroClient",
            return_value=velero,
        ),
        patch(f"{RECOVERY_MODULE}.mark_restoring", recovery.mark_restoring),
        patch(f"{RECOVERY_MODULE}.reapply_and_finalize", recovery.reapply_and_finalize),
        patch(
            f"{RECOVERY_MODULE}.reapply_with_counterpart_identity",
            recovery.reapply_with_counterpart_identity,
        ),
        patch(f"{RECOVERY_MODULE}.mark_failed", recovery.mark_failed),
        patch(f"{MODULE}.get_run_logger", return_value=MagicMock()),
        patch(f"{MODULE}.Variable", variable),
        patch(f"{MODULE}.flow_run_ctx", SimpleNamespace(id=uuid4())),
    ):
        yield SimpleNamespace(velero=velero, recovery=recovery, variable=variable)


async def _restore(**cross_target: Any) -> dict[str, Any]:
    return await execute_velero_restore_flow.fn(
        crd_body={"kind": "Restore"},
        velero_restore_name="styrmin-restore-1",
        velero_namespace="styrmin",
        target_namespace=TARGET_NAMESPACE,
        timeout=60,
        **cross_target,
    )


def _cross_target(context: GlobalContext) -> dict[str, Any]:
    """The parameters the INTERNAL flow adds for a cross-target restore."""
    return {
        "restored_crd_name": SOURCE_RELEASE_REFERENCE,
        "counterpart_crd_body": {"metadata": {"name": COUNTERPART_NAMESPACE}},
        "counterpart_context": context,
    }


def _stored_result(variable: MagicMock) -> dict[str, Any]:
    return variable.set.await_args.kwargs["value"]


# execute_velero_restore_flow (USER) ------------------------------------------


async def test_a_restore_records_its_three_steps_in_order(
    api: FakeStepApi, events: list[Event], restore_id: UUID
) -> None:
    async with _user_flow() as cluster:
        await _restore()

    assert events == ALL_STEPS_SUCCEEDED
    names = [
        (record["name"], record["kind"], record["restoreId"])
        for record in api.records
        if record["event"] == "STARTED"
    ]
    assert names == [
        ("Delete the namespace", "RESTORE", str(restore_id)),
        ("Run the Velero restore", "RESTORE", str(restore_id)),
        ("Run the recovery", "RESTORE", str(restore_id)),
    ]
    assert _stored_result(cluster.variable)["recovery"] == {
        "recovered": True,
        "error": None,
    }


async def test_a_namespace_that_is_not_deleted_fails_the_namespace_step(
    api: FakeStepApi, events: list[Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config.SETTINGS.agent, "poll_retry_delay_seconds", 600)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    async with _user_flow(namespace_stays=True) as cluster:
        with pytest.raises(RuntimeError, match="was not deleted within 600s"):
            await _restore()

    assert events == [("STARTED", "restore:namespace"), ("FAILED", "restore:namespace")]
    assert api.record("FAILED", "restore:namespace")["error"] == (
        f"RuntimeError: Namespace {TARGET_NAMESPACE} was not deleted within 600s"
    )
    cluster.velero.create_restore_from_dict.assert_not_awaited()


@pytest.mark.parametrize(
    ("restore", "error"),
    [
        pytest.param(
            _velero_restore(
                "FailedValidation",
                validationErrors=[
                    'Error retrieving backup: backups.velero.io "styrmin-1" not found'
                ],
            ),
            "Velero restore failed validation: Error retrieving backup: "
            'backups.velero.io "styrmin-1" not found',
            id="failed-validation",
        ),
        pytest.param(
            _velero_restore(
                "Failed", failureReason="found a backup with status Failed"
            ),
            "found a backup with status Failed",
            id="failed",
        ),
    ],
)
async def test_a_failed_velero_restore_fails_the_velero_step_with_veleros_error(
    api: FakeStepApi, events: list[Event], restore: dict[str, Any], error: str
) -> None:
    async with _user_flow(restore=restore) as cluster:
        result = await _restore()

    assert result is restore
    assert events == [
        ("STARTED", "restore:namespace"),
        ("SUCCEEDED", "restore:namespace"),
        ("STARTED", "restore:velero"),
        ("FAILED", "restore:velero"),
    ]
    assert api.record("FAILED", "restore:velero")["error"] == error
    # The existing failure handling is unchanged: the CR is marked failed.
    cluster.recovery.mark_failed.assert_awaited_once()
    cluster.recovery.mark_restoring.assert_not_awaited()
    assert _stored_result(cluster.variable)["status"] == {
        "phase": restore["status"]["phase"],
        # The INTERNAL flow stores it as the restore's error message.
        "failureReason": error,
    }


async def test_a_completed_velero_restore_stores_no_failure_reason(
    api: FakeStepApi,
) -> None:
    del api
    async with _user_flow() as cluster:
        await _restore()

    assert _stored_result(cluster.variable)["status"] == {
        "phase": "Completed",
        "failureReason": "",
    }


async def test_a_velero_restore_that_cannot_be_polled_fails_the_velero_step(
    api: FakeStepApi, events: list[Event]
) -> None:
    timeout = VeleroClientError("Restore styrmin-restore-1 timed out after 60s")

    async with _user_flow(poll_error=timeout):
        with pytest.raises(VeleroClientError):
            await _restore()

    assert events[-2:] == [("STARTED", "restore:velero"), ("FAILED", "restore:velero")]
    assert api.record("FAILED", "restore:velero")["error"] == (
        "VeleroClientError: Restore styrmin-restore-1 timed out after 60s"
    )


async def test_a_failed_recovery_fails_the_recovery_step(
    api: FakeStepApi, events: list[Event]
) -> None:
    async with _user_flow(recovery_error=RuntimeError("CR is gone")) as cluster:
        await _restore()

    assert events == [
        *ALL_STEPS_SUCCEEDED[:4],
        ("STARTED", "restore:recovery"),
        ("FAILED", "restore:recovery"),
    ]
    assert api.record("FAILED", "restore:recovery")["error"] == (
        "Restore reapply failed: CR is gone"
    )
    assert _stored_result(cluster.variable)["recovery"] == {
        "recovered": False,
        "error": "Restore reapply failed: CR is gone",
    }


async def test_a_cross_target_restore_writes_the_aliases_after_the_recovery(
    api: FakeStepApi, events: list[Event], alias_step: AsyncMock
) -> None:
    del api
    context = counterpart_context()

    async with _user_flow() as cluster:
        await _restore(**_cross_target(context))

    assert events == [*ALL_STEPS_SUCCEEDED, ("alias step", context)]
    alias_step.assert_awaited_once()
    cluster.recovery.reapply_with_counterpart_identity.assert_awaited_once()
    assert _stored_result(cluster.variable)["recovery"] == {
        "recovered": True,
        "error": None,
    }


async def test_an_in_place_restore_writes_no_aliases(
    api: FakeStepApi, events: list[Event], alias_step: AsyncMock
) -> None:
    """Velero writes back the deployment's own aliases (FR-006)."""
    del api
    async with _user_flow():
        await _restore()

    assert events == ALL_STEPS_SUCCEEDED
    alias_step.assert_not_awaited()


@pytest.mark.parametrize(
    ("restore", "counterpart_recovery_error", "last_events"),
    [
        pytest.param(
            None,
            RuntimeError("CR is gone"),
            [("STARTED", "restore:recovery"), ("FAILED", "restore:recovery")],
            id="recovery-failed",
        ),
        pytest.param(
            _velero_restore(
                "Failed", failureReason="found a backup with status Failed"
            ),
            None,
            [("STARTED", "restore:velero"), ("FAILED", "restore:velero")],
            id="velero-failed",
        ),
    ],
)
async def test_a_cross_target_restore_that_fails_before_its_end_writes_no_aliases(
    api: FakeStepApi,
    events: list[Event],
    alias_step: AsyncMock,
    restore: dict[str, Any] | None,
    counterpart_recovery_error: Exception | None,
    last_events: list[Event],
) -> None:
    del api
    async with _user_flow(
        restore=restore, counterpart_recovery_error=counterpart_recovery_error
    ) as cluster:
        await _restore(**_cross_target(counterpart_context()))

    assert events[-2:] == last_events
    alias_step.assert_not_awaited()
    assert _stored_result(cluster.variable)["recovery"]["recovered"] is False


async def test_a_refused_alias_write_fails_the_alias_step_and_the_recovery(
    api: FakeStepApi,
    events: list[Event],
    restore_id: UUID,
    refused_alias_write: AsyncMock,
) -> None:
    """SC-004: the step and the stored result carry the error; no CR is marked failed."""
    async with _user_flow() as cluster:
        await _restore(**_cross_target(counterpart_context()))

    assert events == [
        *ALL_STEPS_SUCCEEDED,
        ("STARTED", "resource:service-aliases"),
        ("FAILED", "resource:service-aliases"),
    ]
    started = api.record("STARTED", "resource:service-aliases")
    assert (started["name"], started["restoreId"]) == (
        "Create and delete service aliases",
        str(restore_id),
    )
    assert api.record("FAILED", "resource:service-aliases")["error"] == (
        "ApiException: (500)\nReason: Internal Server Error\n"
    )
    refused_alias_write.assert_awaited_once_with(
        aliases=[{"metadata": {"name": "db"}}], stale_aliases=[]
    )
    assert _stored_result(cluster.variable)["recovery"] == {
        "recovered": False,
        "error": ALIAS_ERROR,
    }
    cluster.recovery.mark_failed.assert_not_awaited()


async def test_a_failed_alias_read_fails_the_alias_step_and_the_recovery(
    api: FakeStepApi,
    events: list[Event],
    refused_alias_write: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-004: a read that fails before the step opens is still a failed step."""
    monkeypatch.setattr(
        service_aliases,
        "find_stale_service_aliases",
        AsyncMock(side_effect=_alias_write_error()),
    )

    async with _user_flow() as cluster:
        await _restore(**_cross_target(counterpart_context()))

    assert events == [
        *ALL_STEPS_SUCCEEDED,
        ("STARTED", "resource:service-aliases"),
        ("FAILED", "resource:service-aliases"),
    ]
    assert api.record("STARTED", "resource:service-aliases")["name"] == (
        "Create and delete service aliases"
    )
    assert api.record("FAILED", "resource:service-aliases")["error"] == (
        "ApiException: (500)\nReason: Internal Server Error\n"
    )
    refused_alias_write.assert_not_awaited()
    assert _stored_result(cluster.variable)["recovery"] == {
        "recovered": False,
        "error": ALIAS_ERROR,
    }
    cluster.recovery.mark_failed.assert_not_awaited()


# execute_restore_workflow (INTERNAL) -----------------------------------------


@asynccontextmanager
async def _internal_restore_flow(
    events: list[Event],
    *,
    state_type: StateType = StateType.COMPLETED,
    state_message: str = "",
    token_error: Exception | None = None,
    velero_result: dict[str, Any] | None = None,
    counterpart: Deployment | None = None,
) -> AsyncIterator[SimpleNamespace]:
    backup = MagicMock()
    backup.name = "styrmin-backup-1"
    backup.instance_id = uuid4()
    backup.component_statuses = None
    restore = MagicMock()
    restore.name = "styrmin-restore-1"
    restore.metadata_ = {"timeout": 1800}
    restore.target_instance_id = None

    flow_run = MagicMock()
    flow_run.id = uuid4()
    flow_run.state = MagicMock()
    flow_run.state.type = state_type
    flow_run.state.message = state_message
    flow_run.state.is_failed.return_value = state_type == StateType.FAILED

    async def _dispatch(**kwargs: Any) -> MagicMock:
        events.append(("USER flow", kwargs["name"]))
        return flow_run

    @asynccontextmanager
    async def _action_api_token() -> AsyncIterator[str]:
        if token_error is not None:
            raise token_error
        events.append(("token created",))
        try:
            yield "action-token"
        finally:
            events.append(("token revoked",))

    async def _fail_open_steps(parent: StepParent, message: str) -> None:
        events.append(("open steps failed", parent, message))

    variable = MagicMock()
    variable.get = AsyncMock(
        return_value=velero_result
        or {"status": {"phase": "Completed"}, "recovery": {"recovered": True}}
    )
    variable.unset = AsyncMock()
    built = MagicMock()
    built.render.return_value = {"kind": "Restore"}
    uow = MagicMock()
    uow.deployments.find = AsyncMock(return_value=counterpart)

    dispatch = AsyncMock(side_effect=_dispatch)
    status = AsyncMock()
    fail_open = AsyncMock(side_effect=_fail_open_steps)
    deployment_running = AsyncMock()
    deployment_failed = AsyncMock()
    with (
        patch(f"{MODULE}.get_run_logger", return_value=MagicMock()),
        patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(uow)),
        patch(f"{MODULE}.get_backup", AsyncMock(return_value=backup)),
        patch(f"{SERVICE_MODULE}.get_restore", AsyncMock(return_value=restore)),
        patch(f"{MODULE}.update_restore_status", status),
        patch(f"{MODULE}.build_velero_restore", MagicMock(return_value=built)),
        patch(f"{MODULE}.arun_deployment", dispatch),
        patch(f"{MODULE}.Variable", variable),
        patch(f"{MODULE}._set_deployment_status_running", deployment_running),
        patch(f"{MODULE}._set_deployment_status_failed", deployment_failed),
        patch(f"{MODULE}.action_api_token", _action_api_token),
        patch(f"{MODULE}.fail_open_steps", fail_open),
    ):
        yield SimpleNamespace(
            dispatch=dispatch,
            status=status,
            fail_open=fail_open,
            deployment_running=deployment_running,
            deployment_failed=deployment_failed,
        )


async def _run_restore_workflow(
    restore_id: UUID,
    *,
    deployment_id: UUID | None = None,
    source_deployment_id: UUID | None = None,
) -> None:
    deployment_id = deployment_id or uuid4()
    await execute_restore_workflow.fn(
        restore_id=str(restore_id),
        backup_id=str(uuid4()),
        deployment_id=str(deployment_id),
        target_namespace=f"styrmin-{deployment_id}",
        source_deployment_id=(
            str(source_deployment_id) if source_deployment_id is not None else None
        ),
    )


async def test_restore_workflow_gives_the_user_flow_a_token_and_the_restore(
    events: list[Event],
) -> None:
    restore_id = uuid4()

    async with _internal_restore_flow(events) as flow:
        await _run_restore_workflow(restore_id)

    assert flow.dispatch.await_args.kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token", RESTORE_ID_ENV: str(restore_id)}
    }
    assert events == [
        ("token created",),
        ("USER flow", "execute_velero_restore/execute_velero_restore"),
        ("token revoked",),
    ]
    flow.fail_open.assert_not_awaited()


@pytest.mark.parametrize(
    ("state_type", "state_message", "message"),
    [
        pytest.param(
            StateType.FAILED,
            "RuntimeError: Namespace styrmin-app was not deleted within 600s",
            "Velero restore flow failed: RuntimeError: Namespace styrmin-app was "
            "not deleted within 600s",
            id="failed",
        ),
        pytest.param(StateType.CRASHED, "pod evicted", "pod evicted", id="crashed"),
    ],
)
async def test_restore_workflow_fails_open_steps_when_the_user_flow_dies(
    events: list[Event], state_type: StateType, state_message: str, message: str
) -> None:
    restore_id = uuid4()

    async with _internal_restore_flow(
        events, state_type=state_type, state_message=state_message
    ) as flow:
        with pytest.raises(RuntimeError):
            await _run_restore_workflow(restore_id)

    flow.fail_open.assert_awaited_once_with(StepParent.of_restore(restore_id), message)
    # The restore is still marked FAILED with the same message.
    assert flow.status.await_args.kwargs["error_message"] == message


@pytest.mark.parametrize(
    ("failure_reason", "message"),
    [
        pytest.param(
            "Velero restore failed validation: backup not found",
            "Velero restore failed validation: backup not found",
            id="reason",
        ),
        # A result without a reason still gives the restore an error message.
        pytest.param("", "Velero restore phase: FailedValidation", id="empty"),
    ],
)
async def test_failed_velero_restore_gives_the_restore_an_error_message(
    events: list[Event], failure_reason: str, message: str
) -> None:
    velero_result = {
        "status": {"phase": "FailedValidation", "failureReason": failure_reason},
        "recovery": {"recovered": False, "error": None},
    }

    async with _internal_restore_flow(events, velero_result=velero_result) as flow:
        await _run_restore_workflow(uuid4())

    kwargs = flow.status.await_args.kwargs
    assert (kwargs["status"].name, kwargs["error_message"]) == ("FAILED", message)


async def test_a_refused_alias_write_fails_the_restore_and_the_counterpart(
    events: list[Event],
) -> None:
    """Critique E4: the restore's error is the alias error that the clone entry shows."""
    counterpart = counterpart_deployment()
    velero_result = {
        "status": {"phase": "Completed", "failureReason": ""},
        "recovery": {"recovered": False, "error": ALIAS_ERROR},
    }

    async with _internal_restore_flow(
        events, velero_result=velero_result, counterpart=counterpart
    ) as flow:
        await _run_restore_workflow(
            uuid4(), deployment_id=counterpart.id, source_deployment_id=uuid4()
        )

    kwargs = flow.status.await_args.kwargs
    assert (kwargs["status"], kwargs["error_message"]) == (
        RestoreStatus.FAILED,
        ALIAS_ERROR,
    )
    flow.deployment_failed.assert_awaited_once()
    failed = flow.deployment_failed.await_args.kwargs
    assert (failed["deployment_id"], failed["error_message"]) == (
        counterpart.id,
        ALIAS_ERROR,
    )
    flow.deployment_running.assert_not_awaited()
    flow.fail_open.assert_not_awaited()


async def test_restore_runs_without_steps_when_no_token_can_be_created(
    events: list[Event],
) -> None:
    restore_id = uuid4()

    async with _internal_restore_flow(
        events, token_error=RuntimeError("database unavailable")
    ) as flow:
        await _run_restore_workflow(restore_id)

    assert flow.dispatch.await_args.kwargs["job_variables"] == {
        "env": {RESTORE_ID_ENV: str(restore_id)}
    }
    assert flow.status.await_args.kwargs["status"].name == "COMPLETED"


async def test_restore_workflow_gives_a_cross_target_restore_the_counterpart_context(
    events: list[Event],
) -> None:
    counterpart = counterpart_deployment()
    assert counterpart.active_instance is not None

    async with _internal_restore_flow(events, counterpart=counterpart) as flow:
        await _run_restore_workflow(
            uuid4(), deployment_id=counterpart.id, source_deployment_id=uuid4()
        )

    parameters = flow.dispatch.await_args.kwargs["parameters"]
    assert parameters["counterpart_context"] == counterpart.active_instance.context
    assert parameters["counterpart_crd_body"]["metadata"]["name"] == (
        COUNTERPART_NAMESPACE
    )


async def test_restore_workflow_gives_an_in_place_restore_no_counterpart_context(
    events: list[Event],
) -> None:
    async with _internal_restore_flow(events) as flow:
        await _run_restore_workflow(uuid4())

    parameters = flow.dispatch.await_args.kwargs["parameters"]
    assert parameters["counterpart_context"] is None
    assert parameters["counterpart_crd_body"] is None


async def test_the_counterpart_context_reaches_the_user_flow_as_a_context(
    events: list[Event],
) -> None:
    """Prefect sends the parameters as JSON; the USER flow validates them back."""
    counterpart = counterpart_deployment()
    assert counterpart.active_instance is not None

    async with _internal_restore_flow(events, counterpart=counterpart) as flow:
        await _run_restore_workflow(
            uuid4(), deployment_id=counterpart.id, source_deployment_id=uuid4()
        )

    sent = DeploymentFlowRunCreate(
        parameters=flow.dispatch.await_args.kwargs["parameters"]
    ).model_dump(mode="json", exclude_unset=True)["parameters"]
    received = execute_velero_restore_flow.validate_parameters(sent)
    assert isinstance(received["counterpart_context"], GlobalContext)
    assert received["counterpart_context"] == counterpart.active_instance.context
