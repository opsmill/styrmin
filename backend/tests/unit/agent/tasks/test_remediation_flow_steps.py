"""Steps of the remediation flows (spec 019, contracts/flow-step-reporter.md).

The real ``StepReporter`` runs against a fake ``recordStep`` API; the
Kubernetes writes and the driver actions are mocks that log into the same
event list, so each test pins the order of step events and cluster work.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from styrmin_backend import config
from styrmin_backend.agent.tasks import orchestration
from styrmin_backend.agent.tasks.orchestration import (
    create_instance_crd,
    update_instance_crd,
    upgrade_instance_crd,
)
from styrmin_backend.agent.tasks.utils import (
    BACKUP_ID_ENV,
    RESTORE_ID_ENV,
    STEP_ID_ENV,
    TASK_ID_ENV,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.domain.models import Instance, InstanceStatus
from tests.helpers.step_api import FakeStepApi

Event = tuple[Any, ...]

STEP_NAMES = {
    "hook:setup:pre": ("Run the setup pre-hook", "HOOK"),
    "hook:setup:post": ("Run the setup post-hook", "HOOK"),
    "hook:upgrade:pre": ("Run the upgrade pre-hook", "HOOK"),
    "hook:upgrade:core": ("Run the upgrade hook", "HOOK"),
    "hook:upgrade:post": ("Run the upgrade post-hook", "HOOK"),
    "resource:styrmindeployment": (
        "Write the StyrminDeployment resource",
        "RESOURCE_WRITE",
    ),
    "resource:service-aliases": ("Create service aliases", "RESOURCE_WRITE"),
}


class Cluster:
    """Mocks of the flow's Kubernetes writes and driver actions."""

    def __init__(self, events: list[Event]) -> None:
        self.events = events
        self.failing_action: UUID | None = None
        self.action_step_ids: dict[UUID, UUID | None] = {}

    async def namespace(self, **_: Any) -> None:
        self.events.append(("namespace",))

    async def crd(self, **_: Any) -> None:
        self.events.append(("crd",))

    async def status_reset(self, **_: Any) -> None:
        self.events.append(("status reset",))

    async def aliases(self, **_: Any) -> None:
        self.events.append(("aliases",))

    async def action(self, *, name: UUID, step_id: UUID | None = None, **_: Any):
        self.events.append(("action", name))
        self.action_step_ids[name] = step_id
        if name == self.failing_action:
            raise RuntimeError(f"Deployment flow run {uuid4()} failed: hook broke")


@pytest.fixture(autouse=True)
def step_env(monkeypatch: pytest.MonkeyPatch) -> UUID:
    for name in (BACKUP_ID_ENV, RESTORE_ID_ENV, STEP_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    task_id = uuid4()
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", SecretStr("action-token"))
    monkeypatch.setenv(TASK_ID_ENV, str(task_id))
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    return task_id


@pytest.fixture
def events() -> list[Event]:
    return []


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, events: list[Event]) -> FakeStepApi:
    fake = FakeStepApi(events)
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def cluster(monkeypatch: pytest.MonkeyPatch, events: list[Event]) -> Cluster:
    fake = Cluster(events)
    for name, mock in (
        ("apply_kubernetes_namespace", fake.namespace),
        ("upsert_custom_resource", fake.crd),
        ("patch_custom_resource_status", fake.status_reset),
        ("apply_service_aliases", fake.aliases),
        ("run_driver_action_or_fail", fake.action),
    ):
        monkeypatch.setattr(orchestration, name, AsyncMock(side_effect=mock))
    monkeypatch.setattr(
        orchestration, "build_styrmin_deployment_body", lambda **_: {"spec": {}}
    )
    return fake


@pytest.fixture
def with_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestration, "compute_service_aliases", lambda _context: ["alias"]
    )


@pytest.fixture
def without_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestration, "compute_service_aliases", lambda _context: [])


def _instance() -> Instance:
    deployment_id = uuid4()
    context = GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="env", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=f"styrmin-{deployment_id}",
            release_reference=f"styrmin-{deployment_id}",
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(), name="chart", version="0.1.0", values_template=""
                ),
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
    )
    return Instance(
        id=uuid4(),
        name="instance",
        application_version="1.0.0",
        status=InstanceStatus.PENDING,
        deployment_id=deployment_id,
        application_driver_version_id=uuid4(),
        context=context,
    )


def _step(key: str, *work: Event) -> list[Event]:
    return [("STARTED", key), *work, ("SUCCEEDED", key)]


def _assert_started_records(api: FakeStepApi, task_id: UUID) -> None:
    for key in api.ids:
        record = api.started(key)
        name, kind = STEP_NAMES[key]
        assert (record["taskId"], record["name"], record["kind"]) == (
            str(task_id),
            name,
            kind,
        )


# create_instance_crd


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_create_with_hooks_and_aliases_records_each_step_in_order(
    api: FakeStepApi, cluster: Cluster, events: list[Event], step_env: UUID
) -> None:
    prehook, posthook = uuid4(), uuid4()

    await create_instance_crd(instance=_instance(), prehook=prehook, posthook=posthook)

    assert events == [
        *_step("hook:setup:pre", ("action", prehook)),
        *_step("resource:styrmindeployment", ("namespace",), ("crd",)),
        *_step("resource:service-aliases", ("aliases",)),
        *_step("hook:setup:post", ("action", posthook)),
    ]
    assert cluster.action_step_ids == {
        prehook: api.ids["hook:setup:pre"],
        posthook: api.ids["hook:setup:post"],
    }
    _assert_started_records(api, step_env)


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_create_without_hooks_and_aliases_records_the_resource_write(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    await create_instance_crd(instance=_instance(), prehook=None, posthook=None)

    assert events == _step("resource:styrmindeployment", ("namespace",), ("crd",))
    assert cluster.action_step_ids == {}


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_create_failing_pre_hook_records_failed_and_stops(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    prehook = uuid4()
    cluster.failing_action = prehook

    with pytest.raises(RuntimeError, match="hook broke"):
        await create_instance_crd(
            instance=_instance(), prehook=prehook, posthook=uuid4()
        )

    assert events == [
        ("STARTED", "hook:setup:pre"),
        ("action", prehook),
        ("FAILED", "hook:setup:pre"),
    ]
    assert api.failed("hook:setup:pre")["error"].startswith("RuntimeError: ")
    assert "hook broke" in api.failed("hook:setup:pre")["error"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_create_failing_resource_write_records_failed(
    api: FakeStepApi,
    cluster: Cluster,
    events: list[Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orchestration,
        "upsert_custom_resource",
        AsyncMock(side_effect=ValueError("admission webhook denied")),
    )

    with pytest.raises(ValueError, match="admission webhook denied"):
        await create_instance_crd(instance=_instance(), prehook=None, posthook=None)

    assert events == [
        ("STARTED", "resource:styrmindeployment"),
        ("namespace",),
        ("FAILED", "resource:styrmindeployment"),
    ]
    assert api.failed("resource:styrmindeployment")["error"] == (
        "ValueError: admission webhook denied"
    )


# update_instance_crd


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_update_with_aliases_records_each_step_in_order(
    api: FakeStepApi, cluster: Cluster, events: list[Event], step_env: UUID
) -> None:
    await update_instance_crd(instance=_instance())

    assert events == [
        *_step("resource:styrmindeployment", ("crd",)),
        *_step("resource:service-aliases", ("aliases",)),
    ]
    _assert_started_records(api, step_env)


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_update_without_aliases_records_the_resource_write(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    await update_instance_crd(instance=_instance())

    assert events == _step("resource:styrmindeployment", ("crd",))


# upgrade_instance_crd


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_upgrade_with_hooks_and_aliases_records_each_step_in_order(
    api: FakeStepApi, cluster: Cluster, events: list[Event], step_env: UUID
) -> None:
    prehook, core, posthook = uuid4(), uuid4(), uuid4()

    await upgrade_instance_crd(
        instance=_instance(),
        upgrade_hook=core,
        target_version="2.0.0",
        prehook=prehook,
        posthook=posthook,
    )

    assert events == [
        *_step("resource:styrmindeployment", ("crd",), ("status reset",)),
        *_step("hook:upgrade:pre", ("action", prehook)),
        *_step("hook:upgrade:core", ("action", core)),
        *_step("resource:service-aliases", ("aliases",)),
        *_step("hook:upgrade:post", ("action", posthook)),
    ]
    assert cluster.action_step_ids == {
        prehook: api.ids["hook:upgrade:pre"],
        core: api.ids["hook:upgrade:core"],
        posthook: api.ids["hook:upgrade:post"],
    }
    _assert_started_records(api, step_env)


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_upgrade_without_optional_hooks_and_aliases(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    core = uuid4()

    await upgrade_instance_crd(
        instance=_instance(), upgrade_hook=core, target_version="2.0.0"
    )

    assert events == [
        *_step("resource:styrmindeployment", ("crd",), ("status reset",)),
        *_step("hook:upgrade:core", ("action", core)),
    ]
    assert cluster.action_step_ids == {core: api.ids["hook:upgrade:core"]}


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_upgrade_failing_core_hook_records_failed_and_stops(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    prehook, core, posthook = uuid4(), uuid4(), uuid4()
    cluster.failing_action = core

    with pytest.raises(RuntimeError, match="hook broke"):
        await upgrade_instance_crd(
            instance=_instance(),
            upgrade_hook=core,
            target_version="2.0.0",
            prehook=prehook,
            posthook=posthook,
        )

    assert events == [
        *_step("resource:styrmindeployment", ("crd",), ("status reset",)),
        *_step("hook:upgrade:pre", ("action", prehook)),
        ("STARTED", "hook:upgrade:core"),
        ("action", core),
        ("FAILED", "hook:upgrade:core"),
    ]
    assert "hook broke" in api.failed("hook:upgrade:core")["error"]


# Reporting off


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_without_token_flows_run_unchanged_and_actions_get_no_step(
    api: FakeStepApi,
    cluster: Cluster,
    events: list[Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", None)
    core = uuid4()

    await upgrade_instance_crd(
        instance=_instance(), upgrade_hook=core, target_version="2.0.0"
    )

    assert events == [
        ("crd",),
        ("status reset",),
        ("action", core),
        ("aliases",),
    ]
    assert cluster.action_step_ids == {core: None}
