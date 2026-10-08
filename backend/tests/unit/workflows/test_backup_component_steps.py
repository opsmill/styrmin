"""Backup component steps from Velero's PodVolumeBackup objects (spec 019, research D13).

The USER flow ``execute_velero_backup`` records one ``backup:component:<name>``
step per component; the INTERNAL flow ``execute_backup_workflow`` gives it an
action token and the backup id, and fails its open steps when it dies.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from loguru import logger
from prefect.client.schemas.objects import StateType

from styrmin_backend import config
from styrmin_backend.agent.steps import backup_components
from styrmin_backend.agent.steps.backup_components import (
    FINISH_ATTEMPTS,
    BackupComponentSteps,
    ComponentProgress,
    PodComponents,
    component_progress,
)
from styrmin_backend.agent.steps.reporter import StepReporter
from styrmin_backend.agent.tasks.utils import (
    API_TOKEN_ENV,
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from styrmin_backend.domain.models import StepParent
from styrmin_backend.workflows.templates.backup import (
    execute_backup_workflow,
    execute_velero_backup_flow,
)
from tests.helpers.step_api import FakeStepApi
from tests.helpers.unit_of_work import yield_unit_of_work

MODULE = "styrmin_backend.workflows.templates.backup"
NAMESPACE = "styrmin-app"
T0 = "2026-10-06T10:00:00Z"
T1 = "2026-10-06T10:00:05Z"
T2 = "2026-10-06T10:00:09Z"
T3 = "2026-10-06T10:00:20Z"
BACKUP_START = "2026-10-06T09:59:58Z"
BACKUP_END = "2026-10-06T10:00:30Z"


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _pvb(
    pod: str,
    phase: str,
    *,
    start: str | None = None,
    end: str | None = None,
    message: str | None = None,
    volume: str = "data",
) -> dict[str, Any]:
    """A PodVolumeBackup as Velero stores it."""
    status: dict[str, Any] = {"phase": phase}
    if start is not None:
        status["startTimestamp"] = start
    if end is not None:
        status["completionTimestamp"] = end
    if message is not None:
        status["message"] = message
    return {
        "metadata": {"name": f"styrmin-backup-1-{pod}-{volume}"},
        "spec": {
            "pod": {"kind": "Pod", "name": pod, "namespace": NAMESPACE},
            "volume": volume,
        },
        "status": status,
    }


def _backup(phase: str, **status: Any) -> dict[str, Any]:
    return {
        "metadata": {"name": "styrmin-backup-1"},
        "status": {
            "phase": phase,
            "startTimestamp": BACKUP_START,
            "completionTimestamp": BACKUP_END,
            **status,
        },
    }


# component_progress ---------------------------------------------------------


def test_a_component_without_items_has_not_started() -> None:
    assert component_progress([]) == ComponentProgress()


def test_a_component_whose_items_have_not_started_has_not_started() -> None:
    assert component_progress([_pvb("db-0", "New")]) == ComponentProgress()


def test_a_component_starts_at_its_earliest_item() -> None:
    progress = component_progress(
        [
            _pvb("db-0", "InProgress", start=T1),
            _pvb("db-1", "Completed", start=T0, end=T2),
        ]
    )

    assert progress == ComponentProgress(started_at=_at(T0))


def test_a_component_ends_at_its_latest_item_once_all_items_ended() -> None:
    progress = component_progress(
        [
            _pvb("db-0", "Completed", start=T1, end=T3),
            _pvb("db-1", "Completed", start=T0, end=T2),
        ]
    )

    assert progress == ComponentProgress(started_at=_at(T0), ended_at=_at(T3))


def test_a_failed_item_fails_its_component_with_veleros_message() -> None:
    progress = component_progress(
        [
            _pvb("db-0", "Completed", start=T0, end=T1),
            _pvb("db-1", "Failed", start=T0, end=T2, message="disk full"),
            _pvb("db-2", "Failed", start=T1, end=T2, volume="logs"),
        ]
    )

    assert progress == ComponentProgress(
        started_at=_at(T0),
        ended_at=_at(T2),
        error="Pod volume db-1/data: disk full; Pod volume db-2/logs: phase Failed",
    )


# BackupComponentSteps ---------------------------------------------------------


Event = tuple[Any, ...]


@pytest.fixture
def events() -> list[Event]:
    return []


@pytest.fixture
def backup_id(monkeypatch: pytest.MonkeyPatch) -> UUID:
    for name in (TASK_ID_ENV, RESTORE_ID_ENV, STEP_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    backup_id = uuid4()
    monkeypatch.setenv(API_TOKEN_ENV, "action-token")
    monkeypatch.setenv(BACKUP_ID_ENV, str(backup_id))
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    return backup_id


@pytest.fixture
def api(
    monkeypatch: pytest.MonkeyPatch, events: list[Event], backup_id: UUID
) -> FakeStepApi:
    del backup_id
    fake = FakeStepApi(events)
    fake.install(monkeypatch)
    return fake


class Items:
    """The PodVolumeBackups Velero lists, changed by the test between polls."""

    def __init__(self) -> None:
        self.current: list[dict[str, Any]] = []
        self.calls = 0

    async def __call__(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.current


async def _component_of_pod(namespace: str, pod: str) -> str | None:
    assert namespace == NAMESPACE
    return {"db-0": "db", "db-1": "db", "web-0": "web"}.get(pod)


def _steps(components: list[str], items: Items) -> BackupComponentSteps:
    return BackupComponentSteps(
        StepReporter.from_env(),
        components,
        list_items=items,
        component_of_pod=_component_of_pod,
    )


async def test_component_steps_follow_the_pod_volume_backups_on_each_poll(
    api: FakeStepApi, events: list[Event], backup_id: UUID
) -> None:
    items = Items()
    steps = _steps(["db", "web"], items)

    items.current = [_pvb("db-0", "New")]
    await steps.on_poll(_backup("InProgress"))
    assert events == []

    items.current = [_pvb("db-0", "InProgress", start=T0)]
    await steps.on_poll(_backup("InProgress"))
    items.current = [_pvb("db-0", "InProgress", start=T0)]
    await steps.on_poll(_backup("InProgress"))
    items.current = [
        _pvb("db-0", "Completed", start=T0, end=T2),
        _pvb("web-0", "InProgress", start=T1),
    ]
    await steps.on_poll(_backup("InProgress"))
    items.current = [
        _pvb("db-0", "Completed", start=T0, end=T2),
        _pvb("web-0", "Completed", start=T1, end=T3),
    ]
    await steps.on_poll(_backup("Completed"))
    await steps.finish(_backup("Completed"))

    # db's items ended while the backup was InProgress: it ends with web, at its own time.
    assert events == [
        ("STARTED", "backup:component:db"),
        ("STARTED", "backup:component:web"),
        ("SUCCEEDED", "backup:component:db"),
        ("SUCCEEDED", "backup:component:web"),
    ]
    started = api.record("STARTED", "backup:component:db")
    assert (started["backupId"], started["name"], started["kind"]) == (
        str(backup_id),
        "Back up db",
        "BACKUP_COMPONENT",
    )
    assert _at(started["occurredAt"]) == _at(T0)
    assert _at(api.record("SUCCEEDED", "backup:component:db")["occurredAt"]) == _at(T2)
    assert _at(api.record("STARTED", "backup:component:web")["occurredAt"]) == _at(T1)
    assert _at(api.record("SUCCEEDED", "backup:component:web")["occurredAt"]) == _at(T3)


async def test_a_component_stays_running_while_velero_can_still_create_its_items(
    api: FakeStepApi, events: list[Event]
) -> None:
    items = Items()
    steps = _steps(["db"], items)

    items.current = [_pvb("db-0", "Completed", start=T0, end=T1)]
    await steps.on_poll(_backup("InProgress"))
    assert events == [("STARTED", "backup:component:db")]

    # Velero creates the PodVolumeBackup of the second pod later, and it fails.
    items.current = [
        _pvb("db-0", "Completed", start=T0, end=T1),
        _pvb("db-1", "InProgress", start=T2),
    ]
    await steps.on_poll(_backup("InProgress"))
    items.current = [
        _pvb("db-0", "Completed", start=T0, end=T1),
        _pvb("db-1", "Failed", start=T2, end=T3, message="disk full"),
    ]
    await steps.on_poll(_backup("FinalizingPartiallyFailed"))

    assert events == [
        ("STARTED", "backup:component:db"),
        ("FAILED", "backup:component:db"),
    ]
    failed = api.record("FAILED", "backup:component:db")
    assert failed["error"] == "Pod volume db-1/data: disk full"
    assert _at(failed["occurredAt"]) == _at(T3)


@pytest.mark.parametrize(
    "phase", ["WaitingForPluginOperations", "Finalizing", "Completed"]
)
async def test_a_component_ends_once_the_backup_has_left_in_progress(
    api: FakeStepApi, events: list[Event], phase: str
) -> None:
    items = Items()
    steps = _steps(["db"], items)
    items.current = [_pvb("db-0", "Completed", start=T0, end=T1)]

    await steps.on_poll(_backup(phase))

    assert events == [
        ("STARTED", "backup:component:db"),
        ("SUCCEEDED", "backup:component:db"),
    ]
    assert _at(api.record("SUCCEEDED", "backup:component:db")["occurredAt"]) == _at(T1)


async def test_a_component_whose_items_ended_during_in_progress_gets_the_backups_result(
    api: FakeStepApi, events: list[Event]
) -> None:
    """When the last poll could not list the items, the backup's result ends the component."""
    items = Items()
    steps = _steps(["db"], items)
    items.current = [_pvb("db-0", "Completed", start=T0, end=T1)]
    await steps.on_poll(_backup("InProgress"))

    await steps.finish(_backup("PartiallyFailed", errors=1))

    assert events == [
        ("STARTED", "backup:component:db"),
        ("FAILED", "backup:component:db"),
    ]
    failed = api.record("FAILED", "backup:component:db")
    assert failed["error"] == "Velero backup phase: PartiallyFailed (1 errors)"
    assert _at(failed["occurredAt"]) == _at(BACKUP_END)


async def test_a_failed_pod_volume_backup_fails_its_component(
    api: FakeStepApi, events: list[Event]
) -> None:
    items = Items()
    steps = _steps(["db"], items)
    items.current = [_pvb("db-0", "Failed", start=T0, end=T1, message="disk full")]

    await steps.on_poll(_backup("PartiallyFailed"))
    await steps.finish(_backup("PartiallyFailed"))

    assert events == [
        ("STARTED", "backup:component:db"),
        ("FAILED", "backup:component:db"),
    ]
    failed = api.record("FAILED", "backup:component:db")
    assert failed["error"] == "Pod volume db-0/data: disk full"
    assert _at(failed["occurredAt"]) == _at(T1)


async def test_a_component_without_items_gets_the_backups_result_and_times(
    api: FakeStepApi, events: list[Event]
) -> None:
    items = Items()
    steps = _steps(["config"], items)

    await steps.on_poll(_backup("Completed"))
    await steps.finish(_backup("Completed"))

    assert events == [
        ("STARTED", "backup:component:config"),
        ("SUCCEEDED", "backup:component:config"),
    ]
    started = api.record("STARTED", "backup:component:config")
    assert started["name"] == "Back up config"
    assert _at(started["occurredAt"]) == _at(BACKUP_START)
    succeeded = api.record("SUCCEEDED", "backup:component:config")
    assert _at(succeeded["occurredAt"]) == _at(BACKUP_END)


async def test_a_component_without_items_gets_the_failed_backups_error(
    api: FakeStepApi, events: list[Event]
) -> None:
    items = Items()
    steps = _steps(["config"], items)
    backup = _backup("Failed", failureReason="BackupStorageLocation unavailable")

    await steps.finish(backup)

    assert events == [
        ("STARTED", "backup:component:config"),
        ("FAILED", "backup:component:config"),
    ]
    failed = api.record("FAILED", "backup:component:config")
    assert failed["error"] == "BackupStorageLocation unavailable"
    assert _at(failed["occurredAt"]) == _at(BACKUP_END)


async def test_a_component_still_running_when_the_backup_fails_gets_its_error(
    api: FakeStepApi, events: list[Event]
) -> None:
    items = Items()
    steps = _steps(["db"], items)
    items.current = [_pvb("db-0", "InProgress", start=T0)]

    await steps.on_poll(_backup("Failed", failureReason="node agent gone"))
    await steps.finish(_backup("Failed", failureReason="node agent gone"))

    assert events == [
        ("STARTED", "backup:component:db"),
        ("FAILED", "backup:component:db"),
    ]
    assert _at(api.record("STARTED", "backup:component:db")["occurredAt"]) == _at(T0)
    failed = api.record("FAILED", "backup:component:db")
    assert failed["error"] == "node agent gone"
    assert _at(failed["occurredAt"]) == _at(BACKUP_END)


class FlakyStepApi(FakeStepApi):
    """Answers the first ``failures`` writes of ``event`` with a GraphQL error."""

    def __init__(self, events: list[Event], event: str, failures: int) -> None:
        super().__init__(events)
        self.event = event
        self.failures = failures
        self.rejected = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        record = json.loads(request.content)["variables"]["input"]
        if record["event"] == self.event and self.rejected < self.failures:
            self.rejected += 1
            return httpx.Response(200, json={"errors": [{"message": "unavailable"}]})
        return super().handle(request)


def _flaky_api(
    monkeypatch: pytest.MonkeyPatch, events: list[Event], event: str, failures: int
) -> FlakyStepApi:
    monkeypatch.setattr(backup_components, "FINISH_RETRY_DELAY_SECONDS", 0)
    fake = FlakyStepApi(events, event, failures)
    fake.install(monkeypatch)
    return fake


@pytest.mark.parametrize("event", ["STARTED", "SUCCEEDED"])
async def test_finish_sends_a_write_that_was_not_recorded_again(
    monkeypatch: pytest.MonkeyPatch, events: list[Event], backup_id: UUID, event: str
) -> None:
    del backup_id
    api = _flaky_api(monkeypatch, events, event, failures=FINISH_ATTEMPTS - 1)
    steps = _steps(["config"], Items())

    await steps.finish(_backup("Completed"))

    assert api.rejected == FINISH_ATTEMPTS - 1
    assert events == [
        ("STARTED", "backup:component:config"),
        ("SUCCEEDED", "backup:component:config"),
    ]


async def test_finish_stops_after_its_last_attempt(
    monkeypatch: pytest.MonkeyPatch, events: list[Event], backup_id: UUID
) -> None:
    del backup_id
    api = _flaky_api(monkeypatch, events, "SUCCEEDED", failures=FINISH_ATTEMPTS + 1)
    steps = _steps(["config"], Items())
    warnings: list[str] = []
    sink = logger.add(warnings.append, level="WARNING", format="{message}")
    try:
        await steps.finish(_backup("Completed"))
    finally:
        logger.remove(sink)

    assert api.rejected == FINISH_ATTEMPTS
    assert events == [("STARTED", "backup:component:config")]
    assert any(
        f"components config after {FINISH_ATTEMPTS} attempts" in line
        for line in warnings
    )


async def test_listing_errors_do_not_fail_the_backup(
    api: FakeStepApi, events: list[Event]
) -> None:
    async def _forbidden() -> list[dict[str, Any]]:
        raise RuntimeError("podvolumebackups is forbidden")

    steps = BackupComponentSteps(
        StepReporter.from_env(),
        ["db"],
        list_items=_forbidden,
        component_of_pod=_component_of_pod,
    )
    warnings: list[str] = []
    sink = logger.add(warnings.append, level="WARNING", format="{message}")
    try:
        await steps.on_poll(_backup("InProgress"))
        await steps.finish(_backup("Completed"))
    finally:
        logger.remove(sink)

    assert any("podvolumebackups is forbidden" in line for line in warnings)
    # The component still ends with the backup's result.
    assert events == [
        ("STARTED", "backup:component:db"),
        ("SUCCEEDED", "backup:component:db"),
    ]


async def test_nothing_is_listed_without_an_action_token(
    monkeypatch: pytest.MonkeyPatch, backup_id: UUID
) -> None:
    del backup_id
    monkeypatch.delenv(API_TOKEN_ENV)
    items = Items()
    steps = _steps(["db"], items)

    await steps.on_poll(_backup("Completed"))
    await steps.finish(_backup("Completed"))

    assert items.calls == 0


# PodComponents ----------------------------------------------------------------


def _pod(name: str, labels: dict[str, str] | None) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name, labels=labels))


async def test_pods_are_mapped_to_components_by_their_label() -> None:
    core_api = MagicMock()
    core_api.list_namespaced_pod = AsyncMock(
        return_value=SimpleNamespace(
            items=[
                _pod("db-0", {"styrmin/component": "db"}),
                _pod("web-0", {"styrmin/component": "web", "app": "web"}),
            ]
        )
    )
    pods = PodComponents(core_api)

    assert await pods.component_of(NAMESPACE, "db-0") == "db"
    assert await pods.component_of(NAMESPACE, "web-0") == "web"
    assert await pods.component_of(NAMESPACE, "sidecar-0") is None
    assert await pods.component_of(NAMESPACE, "sidecar-0") is None

    # Listed once for the known pods, once more for the pod it had not seen.
    assert core_api.list_namespaced_pod.await_count == 2
    core_api.list_namespaced_pod.assert_awaited_with(
        namespace=NAMESPACE, label_selector="styrmin/component"
    )


# execute_velero_backup_flow (USER) -------------------------------------------


class FakeVelero:
    """A Velero client that returns one backup and PodVolumeBackup list per poll."""

    def __init__(self, polls: list[tuple[dict[str, Any], list[dict[str, Any]]]]):
        self.polls = polls
        self.items: list[dict[str, Any]] = []
        self.listed: list[tuple[str, str]] = []
        self.created: dict[str, Any] | None = None

    async def create_backup_from_dict(self, body: dict[str, Any]) -> dict[str, Any]:
        self.created = body
        return body

    async def poll_backup_status(
        self,
        name: str,
        namespace: str,
        timeout: int,
        interval: int,
        on_poll: Any = None,
    ) -> dict[str, Any]:
        del name, namespace, timeout, interval
        for backup, items in self.polls:
            self.items = items
            if on_poll is not None:
                await on_poll(backup)
        return self.polls[-1][0]

    async def list_pod_volume_backups(
        self, namespace: str, backup_name: str
    ) -> list[dict[str, Any]]:
        self.listed.append((namespace, backup_name))
        return self.items


@asynccontextmanager
async def _kubernetes(velero: FakeVelero) -> AsyncIterator[SimpleNamespace]:
    api_client = MagicMock()
    api_client.close = AsyncMock()
    core_api = MagicMock()
    core_api.list_namespaced_pod = AsyncMock(
        return_value=SimpleNamespace(
            items=[
                _pod("db-0", {"styrmin/component": "db"}),
                _pod("web-0", {"styrmin/component": "web"}),
            ]
        )
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
        patch(f"{MODULE}.get_run_logger", return_value=MagicMock()),
        patch(f"{MODULE}.Variable", variable),
        patch(f"{MODULE}.flow_run_ctx", SimpleNamespace(id=uuid4())),
    ):
        yield SimpleNamespace(api_client=api_client, variable=variable)


async def test_velero_backup_flow_records_a_step_per_component(
    api: FakeStepApi, events: list[Event]
) -> None:
    final = _backup("Completed", expiration="2026-11-05T10:00:30Z")
    velero = FakeVelero(
        [
            (_backup("InProgress"), [_pvb("db-0", "InProgress", start=T0)]),
            (final, [_pvb("db-0", "Completed", start=T0, end=T2)]),
        ]
    )

    async with _kubernetes(velero) as kubernetes:
        result = await execute_velero_backup_flow.fn(
            crd_body={"kind": "Backup"},
            velero_backup_name="styrmin-backup-1",
            velero_namespace="styrmin",
            timeout=60,
            components=["db", "config"],
        )

    assert result is final
    assert velero.listed == [("styrmin", "styrmin-backup-1")] * 2
    assert events == [
        ("STARTED", "backup:component:db"),
        ("SUCCEEDED", "backup:component:db"),
        ("STARTED", "backup:component:config"),
        ("SUCCEEDED", "backup:component:config"),
    ]
    # The result the INTERNAL flow reads is unchanged.
    kubernetes.variable.set.assert_awaited_once()
    assert kubernetes.variable.set.await_args.kwargs["value"]["status"]["phase"] == (
        "Completed"
    )
    kubernetes.api_client.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("final", "error"),
    [
        pytest.param(
            _backup("FailedValidation", validationErrors=["no storage location"]),
            "Velero backup failed validation: no storage location",
            id="failed-validation",
        ),
        pytest.param(
            _backup("PartiallyFailed", errors=2),
            "Velero backup phase: PartiallyFailed (2 errors)",
            id="partially-failed",
        ),
        pytest.param(
            _backup("Failed", failureReason="BackupStorageLocation unavailable"),
            "BackupStorageLocation unavailable",
            id="failed",
        ),
    ],
)
async def test_velero_backup_flow_stores_the_step_error_as_the_failure_reason(
    api: FakeStepApi, final: dict[str, Any], error: str
) -> None:
    velero = FakeVelero([(final, [])])

    async with _kubernetes(velero) as kubernetes:
        await execute_velero_backup_flow.fn(
            crd_body={"kind": "Backup"},
            velero_backup_name="styrmin-backup-1",
            velero_namespace="styrmin",
            timeout=60,
            components=["config"],
        )

    assert api.record("FAILED", "backup:component:config")["error"] == error
    # The INTERNAL flow stores it as the backup's error message.
    stored = kubernetes.variable.set.await_args.kwargs["value"]["status"]
    assert stored["failureReason"] == error


async def test_velero_backup_flow_without_components_records_no_steps(
    api: FakeStepApi, events: list[Event]
) -> None:
    del api
    velero = FakeVelero([(_backup("Completed"), [])])

    async with _kubernetes(velero):
        await execute_velero_backup_flow.fn(
            crd_body={"kind": "Backup"},
            velero_backup_name="styrmin-backup-1",
            velero_namespace="styrmin",
            timeout=60,
        )

    assert events == []
    assert velero.listed == []


# execute_backup_workflow (INTERNAL) ------------------------------------------


@asynccontextmanager
async def _internal_backup_flow(
    events: list[Event],
    *,
    state_type: StateType = StateType.COMPLETED,
    state_message: str = "",
    token_error: Exception | None = None,
    velero_result: dict[str, Any] | None = None,
) -> AsyncIterator[SimpleNamespace]:
    backup = MagicMock()
    backup.name = "styrmin-backup-1"
    backup.instance_id = uuid4()
    backup.component_statuses = {
        "db": {"status": "pending", "kind": "postgres"},
        "web": {"status": "pending", "kind": "disk"},
        "legacy": "not a configuration",
    }
    backup.metadata_ = {"timeout": 1800}

    uow = MagicMock()
    uow.deployments.find = AsyncMock(return_value=None)

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
        or {"status": {"phase": "Completed", "expiration": None}}
    )
    variable.unset = AsyncMock()
    built = MagicMock()
    built.render.return_value = {"kind": "Backup"}

    dispatch = AsyncMock(side_effect=_dispatch)
    status = AsyncMock()
    fail_open = AsyncMock(side_effect=_fail_open_steps)
    with (
        patch(f"{MODULE}.get_run_logger", return_value=MagicMock()),
        patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(uow)),
        patch(f"{MODULE}.get_backup", AsyncMock(return_value=backup)),
        patch(f"{MODULE}.update_backup_status", status),
        patch(f"{MODULE}.build_component_hooks", MagicMock(return_value=[])),
        patch(f"{MODULE}.build_velero_backup", MagicMock(return_value=built)),
        patch(f"{MODULE}.arun_deployment", dispatch),
        patch(f"{MODULE}.Variable", variable),
        patch(f"{MODULE}.action_api_token", _action_api_token),
        patch(f"{MODULE}.fail_open_steps", fail_open),
    ):
        yield SimpleNamespace(dispatch=dispatch, status=status, fail_open=fail_open)


async def test_backup_workflow_gives_the_user_flow_a_token_and_the_backup(
    events: list[Event],
) -> None:
    backup_id = uuid4()

    async with _internal_backup_flow(events) as flow:
        await execute_backup_workflow.fn(
            backup_id=str(backup_id), deployment_id=str(uuid4())
        )

    kwargs = flow.dispatch.await_args.kwargs
    assert kwargs["job_variables"] == {
        "env": {API_TOKEN_ENV: "action-token", BACKUP_ID_ENV: str(backup_id)}
    }
    assert kwargs["parameters"]["components"] == ["db", "web"]
    assert events == [
        ("token created",),
        ("USER flow", "execute_velero_backup/execute_velero_backup"),
        ("token revoked",),
    ]
    flow.fail_open.assert_not_awaited()


@pytest.mark.parametrize(
    ("state_type", "state_message", "message"),
    [
        pytest.param(
            StateType.FAILED,
            "VeleroClientError: timed out",
            "Velero backup flow failed: VeleroClientError: timed out",
            id="failed",
        ),
        pytest.param(StateType.CRASHED, "pod evicted", "pod evicted", id="crashed"),
    ],
)
async def test_backup_workflow_fails_open_steps_when_the_user_flow_dies(
    events: list[Event], state_type: StateType, state_message: str, message: str
) -> None:
    backup_id = uuid4()

    async with _internal_backup_flow(
        events, state_type=state_type, state_message=state_message
    ) as flow:
        with pytest.raises(RuntimeError):
            await execute_backup_workflow.fn(
                backup_id=str(backup_id), deployment_id=str(uuid4())
            )

    flow.fail_open.assert_awaited_once_with(StepParent.of_backup(backup_id), message)
    # The backup is still marked FAILED with the same message.
    assert flow.status.await_args.kwargs["error_message"] == message


@pytest.mark.parametrize(
    ("failure_reason", "message"),
    [
        pytest.param(
            "Velero backup phase: PartiallyFailed (2 errors)",
            "Velero backup phase: PartiallyFailed (2 errors)",
            id="reason",
        ),
        # A result without a reason still gives the backup an error message.
        pytest.param("", "Velero backup phase: PartiallyFailed", id="empty"),
    ],
)
async def test_failed_velero_backup_gives_the_backup_an_error_message(
    events: list[Event], failure_reason: str, message: str
) -> None:
    velero_result = {
        "status": {"phase": "PartiallyFailed", "failureReason": failure_reason}
    }

    async with _internal_backup_flow(events, velero_result=velero_result) as flow:
        await execute_backup_workflow.fn(
            backup_id=str(uuid4()), deployment_id=str(uuid4())
        )

    kwargs = flow.status.await_args.kwargs
    assert (kwargs["status"].name, kwargs["error_message"]) == ("FAILED", message)


async def test_backup_runs_without_steps_when_no_token_can_be_created(
    events: list[Event],
) -> None:
    backup_id = uuid4()

    async with _internal_backup_flow(
        events, token_error=RuntimeError("database unavailable")
    ) as flow:
        await execute_backup_workflow.fn(
            backup_id=str(backup_id), deployment_id=str(uuid4())
        )

    assert flow.dispatch.await_args.kwargs["job_variables"] == {
        "env": {BACKUP_ID_ENV: str(backup_id)}
    }
    assert flow.status.await_args.kwargs["status"].name == "COMPLETED"
