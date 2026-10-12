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
from kubernetes_asyncio.client.api_client import ApiException
from pydantic import SecretStr

from styrmin_backend import config
from styrmin_backend.agent.tasks import orchestration
from styrmin_backend.agent.tasks.orchestration import (
    KeptInstance,
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
from styrmin_backend.operator.config import ANNOTATION_INSTANCE_SEQUENCE
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
        #: Set when the StyrminDeployment holds a newer instance that the write keeps.
        self.kept: KeptInstance | None = None
        self.crd_bodies: list[dict[str, Any]] = []
        self.namespaces: list[dict[str, Any]] = []
        self.k8s_events: list[dict[str, Any]] = []
        self.action_step_ids: dict[UUID, UUID | None] = {}

    async def namespace(self, **kwargs: Any) -> None:
        self.events.append(("namespace",))
        self.namespaces.append(kwargs)

    async def crd(self, **_: Any) -> KeptInstance | None:
        self.events.append(("crd",))
        return self.kept

    async def k8s_event(self, **kwargs: Any) -> None:
        self.events.append(("k8s event",))
        self.k8s_events.append(kwargs)

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
        ("_apply_styrmin_deployment_crd", fake.crd),
        ("create_event", fake.k8s_event),
        ("patch_custom_resource_status", fake.status_reset),
        ("apply_service_aliases", fake.aliases),
        ("run_driver_action_or_fail", fake.action),
    ):
        monkeypatch.setattr(orchestration, name, AsyncMock(side_effect=mock))

    def build_body(**kwargs: Any) -> dict[str, Any]:
        fake.crd_bodies.append(kwargs)
        sequence = kwargs.get("instance_sequence")
        annotations = {ANNOTATION_INSTANCE_SEQUENCE: str(sequence)} if sequence else {}
        return {
            "metadata": {"name": kwargs["namespace"], "annotations": annotations},
            "spec": {"instanceId": "older-instance"},
        }

    monkeypatch.setattr(orchestration, "build_styrmin_deployment_body", build_body)
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
        "_apply_styrmin_deployment_crd",
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
        *_step("resource:styrmindeployment", ("namespace",), ("crd",)),
        *_step("resource:service-aliases", ("aliases",)),
    ]
    _assert_started_records(api, step_env)


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_update_without_aliases_records_the_resource_write(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    await update_instance_crd(instance=_instance())

    assert events == _step("resource:styrmindeployment", ("namespace",), ("crd",))


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_update_and_upgrade_create_a_missing_namespace_with_its_labels(
    api: FakeStepApi, cluster: Cluster
) -> None:
    """An instance whose create flow stopped before the namespace existed (#313)."""
    instance = _instance()
    instance.context.labels = {"environment": "env", "deployment": "app"}
    namespace = instance.context.instance.namespace

    await update_instance_crd(instance=instance)
    await upgrade_instance_crd(
        instance=instance, upgrade_hook=uuid4(), target_version="2.0.0"
    )

    labels = {"styrmin/environment": "env", "styrmin/deployment": "app"}
    assert cluster.namespaces == [{"namespace": namespace, "labels": labels}] * 2


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
        *_step(
            "resource:styrmindeployment", ("namespace",), ("crd",), ("status reset",)
        ),
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
        *_step(
            "resource:styrmindeployment", ("namespace",), ("crd",), ("status reset",)
        ),
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
        *_step(
            "resource:styrmindeployment", ("namespace",), ("crd",), ("status reset",)
        ),
        *_step("hook:upgrade:pre", ("action", prehook)),
        ("STARTED", "hook:upgrade:core"),
        ("action", core),
        ("FAILED", "hook:upgrade:core"),
    ]
    assert "hook broke" in api.failed("hook:upgrade:core")["error"]


# A StyrminDeployment that already holds a newer instance (#386)

NEWER = KeptInstance(instance_id="newer-instance", sequence=8, resource_uid="uid-1")


def _older_instance() -> Instance:
    return _instance().model_copy(update={"sequence": 7})


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_flows_record_the_instance_sequence_on_the_resource(
    api: FakeStepApi, cluster: Cluster
) -> None:
    instance = _instance().model_copy(update={"sequence": 7})

    await create_instance_crd(instance=instance, prehook=None, posthook=None)
    await update_instance_crd(instance=instance)
    await upgrade_instance_crd(
        instance=instance, upgrade_hook=uuid4(), target_version="2.0.0"
    )

    assert [body["instance_sequence"] for body in cluster.crd_bodies] == [7] * 3


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_create_that_keeps_a_newer_instance_runs_its_hooks_without_aliases(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    cluster.kept = NEWER
    prehook, posthook = uuid4(), uuid4()

    await create_instance_crd(
        instance=_older_instance(), prehook=prehook, posthook=posthook
    )

    assert events == [
        *_step("hook:setup:pre", ("action", prehook)),
        *_step(
            "resource:styrmindeployment",
            ("namespace",),
            ("crd",),
            ("OUTPUT", "resource:styrmindeployment"),
            ("k8s event",),
        ),
        *_step("hook:setup:post", ("action", posthook)),
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_update_that_keeps_a_newer_instance_records_why_on_its_step(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    cluster.kept = NEWER
    instance = _older_instance()
    namespace = instance.context.instance.namespace

    await update_instance_crd(instance=instance)

    assert events == _step(
        "resource:styrmindeployment",
        ("namespace",),
        ("crd",),
        ("OUTPUT", "resource:styrmindeployment"),
        ("k8s event",),
    )
    message = (
        f"Left StyrminDeployment {namespace}/{namespace} unchanged: it holds instance "
        "newer-instance (sequence 8) of a later change. This task's instance is "
        "older-instance (sequence 7)."
    )
    output = api.record("OUTPUT", "resource:styrmindeployment")
    assert (output["output"], output["outputTruncated"]) == (message, False)
    [k8s_event] = cluster.k8s_events
    involved = k8s_event["involved_object"]
    assert (involved.kind, involved.name, involved.namespace, involved.uid) == (
        "StyrminDeployment",
        namespace,
        namespace,
        "uid-1",
    )
    assert (k8s_event["reason"], k8s_event["message"]) == ("NewerInstanceKept", message)


@pytest.mark.asyncio
@pytest.mark.usefixtures("with_aliases")
async def test_upgrade_that_keeps_a_newer_instance_keeps_its_status(
    api: FakeStepApi, cluster: Cluster, events: list[Event]
) -> None:
    cluster.kept = NEWER
    core = uuid4()

    await upgrade_instance_crd(
        instance=_instance(), upgrade_hook=core, target_version="2.0.0"
    )

    assert events == [
        *_step(
            "resource:styrmindeployment",
            ("namespace",),
            ("crd",),
            ("OUTPUT", "resource:styrmindeployment"),
            ("k8s event",),
        ),
        *_step("hook:upgrade:core", ("action", core)),
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("without_aliases")
async def test_a_failed_event_write_does_not_fail_the_step(
    api: FakeStepApi,
    cluster: Cluster,
    events: list[Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster.kept = NEWER
    monkeypatch.setattr(
        orchestration,
        "create_event",
        AsyncMock(side_effect=ApiException(status=403, reason="Forbidden")),
    )

    await update_instance_crd(instance=_instance())

    assert events == _step(
        "resource:styrmindeployment",
        ("namespace",),
        ("crd",),
        ("OUTPUT", "resource:styrmindeployment"),
    )


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
        ("namespace",),
        ("crd",),
        ("status reset",),
        ("action", core),
        ("aliases",),
    ]
    assert cluster.action_step_ids == {core: None}
