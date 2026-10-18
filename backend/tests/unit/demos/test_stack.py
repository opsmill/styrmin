"""The demo stack helpers' logic, with a fake Styrmin client and no cluster."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from styrmin_sdk.exceptions import ResourceNotFoundError
from styrmin_sdk.graphql._generated.get_deployment import (
    GetDeploymentDeployment,
    GetDeploymentDeploymentDeployedServices,
)

from tests.e2e.demos import stack
from tests.e2e.demos.stack import (
    StackError,
    create_environment,
    delete_environments,
    deploy,
    existing_environments,
    load_enterprise_driver,
    service_url,
)


def _deployment(services: list[dict]) -> GetDeploymentDeployment:
    # Only the fields service_url reads; the services themselves are validated.
    return GetDeploymentDeployment.model_construct(
        name="infrahub",
        deployed_services=[
            GetDeploymentDeploymentDeployedServices.model_validate(item)
            for item in services
        ],
    )


def _service(name: str, url: str | None) -> dict:
    return {
        "id": "5f1d3f5e-0000-4000-8000-000000000003",
        "driverServiceName": name,
        "resolvedName": name,
        "kind": "http",
        "scope": "external",
        "port": 8000,
        "component": "server",
        "primaryFqdn": None,
        "humanReadableFqdn": None,
        "primaryUrl": None,
        "humanReadableUrl": url,
    }


def test_service_url_returns_the_human_readable_url_of_the_named_service() -> None:
    deployment = _deployment(
        [
            _service("task-manager", "http://task-manager-lab.local.styrmin.io:8080"),
            _service("infrahub", "http://infrahub-lab.local.styrmin.io:8080"),
        ]
    )

    assert (
        service_url(deployment, "infrahub")
        == "http://infrahub-lab.local.styrmin.io:8080"
    )


def test_service_url_names_the_services_when_the_service_is_missing() -> None:
    deployment = _deployment(
        [_service("task-manager", "http://task-manager-lab.local.styrmin.io:8080")]
    )

    with pytest.raises(
        StackError, match="has no service 'infrahub'; it has: task-manager"
    ):
        service_url(deployment, "infrahub")


def test_service_url_raises_when_the_service_has_no_url() -> None:
    deployment = _deployment([_service("infrahub", None)])

    with pytest.raises(StackError, match="has no human-readable URL"):
        service_url(deployment, "infrahub")


class FakeEnvironments:
    def __init__(self, calls: list[tuple], existing: dict[str, str]) -> None:
        self.calls = calls
        self.existing = existing

    async def get(self, *, environment_name: str, cluster_name: str):
        self.calls.append(("get", environment_name, cluster_name))
        if environment_name not in self.existing:
            raise ResourceNotFoundError(
                f"Environment not found: {environment_name!r}", "NOT_FOUND"
            )
        return SimpleNamespace(
            id=self.existing[environment_name], name=environment_name
        )

    async def delete(self, *, environment_id: str) -> None:
        self.calls.append(("delete", environment_id))

    async def create(self, *, name: str, cluster_name: str, config: dict):
        self.calls.append(("create", name, cluster_name, config))
        return SimpleNamespace(id=f"env-{name}", name=name)


# The fakes below define a `list` method, which hides the builtin inside their class bodies.
type Calls = list[tuple]
type Names = list[str]


class FakeDeployments:
    def __init__(
        self,
        calls: Calls,
        by_environment: dict[str, Names],
        statuses: Names,
    ) -> None:
        self.calls = calls
        self.by_environment = by_environment
        self.statuses = statuses

    async def list(
        self, environment_id: str, *, include_deleted: bool, include_internal: bool
    ):
        self.calls.append(("list", environment_id, include_deleted, include_internal))
        return [
            SimpleNamespace(id=deployment_id)
            for deployment_id in self.by_environment.get(environment_id, [])
        ]

    async def create(self, **kwargs):
        self.calls.append(("deploy", kwargs))
        return SimpleNamespace(
            id="task-1", deployment_id="dep-1", message=None, status="pending"
        )

    async def get(self, deployment_id: str):
        status = self.statuses.pop(0)
        self.calls.append(("get_deployment", deployment_id, status))
        return SimpleNamespace(id=deployment_id, status=status)


class FakeLocations:
    def __init__(self, calls: Calls, names: Names) -> None:
        self.calls = calls
        self.names = names

    async def list(self):
        return [SimpleNamespace(id=f"bsl-{name}", name=name) for name in self.names]

    async def assign(self, environment_id: str, bsl_id: str) -> None:
        self.calls.append(("assign", environment_id, bsl_id))


class FakeDrivers:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    async def load_local_version(self, path: str):
        self.calls.append(("load_local_version", path))
        return SimpleNamespace(id="driver-version-1")


class FakeTasks:
    async def failed_step(self, task_id: str):
        return SimpleNamespace(
            name="Install or upgrade the HelmRelease",
            task_id=task_id,
            error="timed out",
        )


def _client(
    calls: list[tuple],
    *,
    environments: dict[str, str] | None = None,
    deployments: dict[str, list[str]] | None = None,
    statuses: list[str] | None = None,
    locations: list[str] | None = None,
):
    return SimpleNamespace(
        environments=FakeEnvironments(calls, environments or {}),
        deployments=FakeDeployments(calls, deployments or {}, statuses or []),
        backup_storage_locations=FakeLocations(
            calls, locations if locations is not None else ["local"]
        ),
        drivers=FakeDrivers(calls),
        tasks=FakeTasks(),
    )


@pytest.fixture
def waited(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    waits: list[tuple] = []

    async def fake_wait(namespaces, *, timeout, kube_context):
        waits.append((list(namespaces), timeout, kube_context))

    monkeypatch.setattr(stack, "wait_for_namespaces_gone", fake_wait)
    return waits


async def test_delete_environments_deletes_existing_ones_in_order_then_waits_for_every_namespace(
    waited: list[tuple],
) -> None:
    calls: list[tuple] = []
    client = _client(
        calls,
        environments={"network-lab": "env-source", "network-lab-clone": "env-clone"},
        deployments={"env-clone": ["c1", "c2"], "env-source": ["s1"]},
    )

    await delete_environments(
        client, ["network-lab-clone", "network-lab", "never-created"]
    )

    assert [call for call in calls if call[0] in {"list", "delete"}] == [
        ("list", "env-clone", True, True),
        ("delete", "env-clone"),
        ("list", "env-source", True, True),
        ("delete", "env-source"),
    ]
    assert ("get", "never-created", "local") in calls
    assert waited == [
        (["styrmin-c1", "styrmin-c2", "styrmin-s1"], 600.0, "vcluster-docker_styrmin")
    ]


async def test_existing_environments_keeps_the_given_order_and_skips_missing_ones() -> (
    None
):
    calls: list[tuple] = []
    client = _client(
        calls,
        environments={"network-lab": "env-source", "network-lab-clone": "env-clone"},
    )

    assert await existing_environments(
        client, ["network-lab-clone", "never-created", "network-lab"]
    ) == ["network-lab-clone", "network-lab"]
    assert ("get", "never-created", "local") in calls


async def test_wait_for_namespaces_gone_returns_once_each_namespace_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    present = {"styrmin-a": 2, "styrmin-b": 1}

    async def fake_api(*, context):
        assert context == "vcluster-docker_styrmin"
        return object()

    async def fake_exists(_api, namespace):
        present[namespace] -= 1
        return present[namespace] >= 0

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(stack.kr8s.asyncio, "api", fake_api)
    monkeypatch.setattr(stack, "_namespace_exists", fake_exists)
    monkeypatch.setattr(stack.asyncio, "sleep", no_sleep)

    await stack.wait_for_namespaces_gone(["styrmin-a", "styrmin-b"], timeout=600.0)

    assert present == {"styrmin-a": -1, "styrmin-b": -1}


async def test_wait_for_namespaces_gone_names_the_namespaces_left_after_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_api(*, context):
        return object()

    async def fake_exists(_api, namespace):
        return namespace == "styrmin-stuck"

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(stack.kr8s.asyncio, "api", fake_api)
    monkeypatch.setattr(stack, "_namespace_exists", fake_exists)
    monkeypatch.setattr(stack.asyncio, "sleep", no_sleep)

    with pytest.raises(StackError, match="still exist after 0 s: styrmin-stuck"):
        await stack.wait_for_namespaces_gone(
            ["styrmin-gone", "styrmin-stuck"], timeout=0.0
        )


async def test_create_environment_assigns_the_local_backup_storage_location() -> None:
    calls: list[tuple] = []
    client = _client(calls, locations=["offsite", "local"])

    environment_id = await create_environment(client, "network-lab-backup")

    assert environment_id == "env-network-lab-backup"
    assert calls == [
        ("create", "network-lab-backup", "local", {}),
        ("assign", "env-network-lab-backup", "bsl-local"),
    ]


async def test_create_environment_creates_nothing_without_the_local_backup_storage_location() -> (
    None
):
    calls: list[tuple] = []
    client = _client(calls, locations=["offsite"])

    with pytest.raises(StackError, match="no backup storage location named 'local'"):
        await create_environment(client, "network-lab-backup")
    assert calls == []


async def test_load_enterprise_driver_loads_the_bundled_local_driver() -> None:
    calls: list[tuple] = []

    await load_enterprise_driver(_client(calls))

    assert calls == [("load_local_version", "/styrmin/drivers/infrahub-enterprise")]


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(stack.asyncio, "sleep", fake_sleep)


async def test_deploy_passes_parameters_and_returns_the_running_deployment(
    no_sleep: None,
) -> None:
    calls: list[tuple] = []
    client = _client(calls, statuses=["pending", "deploying", "running"])

    deployment = await deploy(
        client,
        environment_id="env-1",
        driver="semaphore",
        version="2.16.47",
        name="semaphore",
        parameters={"docker_image": "styrmin-demo/semaphore"},
    )

    assert deployment.status == "running"
    created = calls[0][1]
    assert created["environment_id"] == "env-1"
    assert [(item.name, item.value) for item in created["parameters"]] == [
        ("docker_image", "styrmin-demo/semaphore")
    ]
    assert [call[2] for call in calls if call[0] == "get_deployment"] == [
        "pending",
        "deploying",
        "running",
    ]


async def test_deploy_names_the_failed_step_when_the_deployment_fails(
    no_sleep: None,
) -> None:
    client = _client([], statuses=["deploying", "failed"])

    with pytest.raises(
        StackError, match='step "Install or upgrade the HelmRelease" failed: timed out'
    ):
        await deploy(
            client,
            environment_id="env-1",
            driver="infrahub",
            version="1.11.7",
            name="infrahub",
        )


async def test_deploy_without_parameters_sends_none(no_sleep: None) -> None:
    calls: list[tuple] = []
    client = _client(calls, statuses=["running"])

    await deploy(
        client,
        environment_id="env-1",
        driver="infrahub",
        version="1.11.7",
        name="infrahub",
    )

    assert calls[0][1]["parameters"] is None
