"""The Semaphore setup's requests and answer checks, with a fake Semaphore API and no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from tests.e2e.demos import semaphore_setup
from tests.e2e.demos.semaphore_setup import (
    SemaphoreProject,
    SemaphoreSetupError,
    check_token_secret,
    configure,
    created_object,
)

TOKEN = "token-for-the-test"  # noqa: S105
URL = "http://semaphore-lab.local.styrmin.io:8080"
IMAGE_DIRECTORY = Path(semaphore_setup.__file__).parent / "semaphore"


class FakeSemaphore:
    """Answers the endpoints the setup calls as Semaphore v2.16.47 does, and records each request."""

    def __init__(self, *, answers: dict[str, httpx.Response] | None = None) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.answers = answers or {}
        self.next_id = 10

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        key = f"{request.method} {request.url.path}"
        self.requests.append((request.method, request.url.path, body))
        if key in self.answers:
            return self.answers[key]
        if key == "POST /api/auth/login":
            return httpx.Response(
                204, headers={"set-cookie": "semaphore=session; Path=/"}
            )
        if key == "GET /api/project/10/keys":
            return httpx.Response(200, json=[{"id": 3, "name": "None", "type": "none"}])
        if key == "GET /api/project/10/environment/13":
            return httpx.Response(
                200,
                json={
                    **body_of(self, "/api/project/10/environment"),
                    "id": 13,
                    "secrets": [
                        {
                            "id": 4,
                            "type": "env",
                            "name": "INFRAHUB_API_TOKEN",
                            "secret": "",
                        }
                    ],
                },
            )
        if request.method == "POST":
            created = {key: value for key, value in body.items() if key != "secrets"}
            created["id"] = self.next_id
            self.next_id += 1
            return httpx.Response(201, json=created)
        return httpx.Response(404, json={"error": "not found"})


def body_of(fake: FakeSemaphore, path: str) -> dict:
    return next(
        body
        for method, request_path, body in fake.requests
        if method == "POST" and request_path == path
    )


async def run(fake: FakeSemaphore) -> SemaphoreProject:
    return await configure(
        URL, infrahub_token=TOKEN, transport=httpx.MockTransport(fake.handler)
    )


async def test_configure_creates_the_project_objects_in_order_and_returns_their_ids() -> (
    None
):
    fake = FakeSemaphore()

    project = await run(fake)

    assert project == SemaphoreProject(project_id=10, template_id=14, environment_id=13)
    assert [(method, path) for method, path, _ in fake.requests] == [
        ("POST", "/api/auth/login"),
        ("POST", "/api/projects"),
        ("GET", "/api/project/10/keys"),
        ("POST", "/api/project/10/repositories"),
        ("POST", "/api/project/10/inventory"),
        ("POST", "/api/project/10/environment"),
        ("GET", "/api/project/10/environment/13"),
        ("POST", "/api/project/10/templates"),
    ]


async def test_configure_logs_in_with_the_driver_admin_and_names_the_project() -> None:
    fake = FakeSemaphore()

    await run(fake)

    assert body_of(fake, "/api/auth/login") == {
        "auth": "admin",
        "password": "admin-password",
    }
    assert body_of(fake, "/api/projects") == {"name": "Network lab"}


async def test_every_body_after_the_project_carries_the_project_id_and_the_none_key() -> (
    None
):
    fake = FakeSemaphore()

    await run(fake)

    for path in ("repositories", "inventory", "environment", "templates"):
        assert body_of(fake, f"/api/project/10/{path}")["project_id"] == 10
    assert body_of(fake, "/api/project/10/repositories")["ssh_key_id"] == 3
    assert body_of(fake, "/api/project/10/inventory")["ssh_key_id"] == 3


async def test_the_bodies_point_to_the_files_of_the_demo_image() -> None:
    fake = FakeSemaphore()

    await run(fake)

    repository = body_of(fake, "/api/project/10/repositories")
    inventory = body_of(fake, "/api/project/10/inventory")
    template = body_of(fake, "/api/project/10/templates")
    assert (repository["git_url"], repository["git_branch"]) == (
        "/opt/demo/ansible",
        "",
    )
    assert inventory["repository_id"] == 11
    assert (inventory["type"], inventory["inventory"]) == (
        "file",
        "inventory/infrahub.yml",
    )
    assert template == {
        "name": "List network devices",
        "project_id": 10,
        "app": "ansible",
        "playbook": "list_hosts.yml",
        "repository_id": 11,
        "inventory_id": 12,
        "environment_id": 13,
    }
    assert (IMAGE_DIRECTORY / "ansible" / template["playbook"]).is_file()
    assert (IMAGE_DIRECTORY / "ansible" / inventory["inventory"]).is_file()


async def test_the_environment_holds_the_token_as_a_secret_and_json_strings() -> None:
    fake = FakeSemaphore()

    await run(fake)

    environment = body_of(fake, "/api/project/10/environment")
    assert (environment["json"], environment["env"]) == ("{}", "{}")
    assert environment["secrets"] == [
        {
            "type": "env",
            "name": "INFRAHUB_API_TOKEN",
            "secret": TOKEN,
            "operation": "create",
        }
    ]


async def test_a_400_that_created_the_template_still_fails_and_hides_the_token() -> (
    None
):
    # AddTemplate creates the record before it checks the app, then answers 400.
    answer = httpx.Response(400, text=f'{{"error":"Invalid app id: {TOKEN}"}}\n')
    fake = FakeSemaphore(answers={"POST /api/project/10/templates": answer})

    with pytest.raises(SemaphoreSetupError, match="HTTP 400.*template") as raised:
        await run(fake)

    assert "may have created it anyway" in str(raised.value)
    assert TOKEN not in str(raised.value)


async def test_a_failed_login_stops_the_setup() -> None:
    fake = FakeSemaphore(answers={"POST /api/auth/login": httpx.Response(401, text="")})

    with pytest.raises(SemaphoreSetupError, match="HTTP 401"):
        await run(fake)
    assert len(fake.requests) == 1


async def test_a_project_without_the_none_key_stops_the_setup() -> None:
    fake = FakeSemaphore(
        answers={"GET /api/project/10/keys": httpx.Response(200, json=[])}
    )

    with pytest.raises(SemaphoreSetupError, match="no key named 'None'"):
        await run(fake)


def test_created_object_accepts_a_201_whose_fields_match() -> None:
    response = httpx.Response(
        201, json={"id": 7, "name": "Demo", "project_id": 2, "extra": None}
    )

    assert (
        created_object(response, "the repository", {"name": "Demo", "project_id": 2})[
            "id"
        ]
        == 7
    )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, json={"id": 7}), "HTTP 200"),
        (httpx.Response(201, text='{"error":"x"}\n{"id":7}\n'), "not JSON"),
        (httpx.Response(201, json={"name": "Demo"}), "has no id"),
        (httpx.Response(201, json={"id": 7, "name": "Other"}), "name='Other'"),
    ],
)
def test_created_object_rejects_other_answers(
    response: httpx.Response, message: str
) -> None:
    with pytest.raises(SemaphoreSetupError, match=message):
        created_object(response, "the repository", {"name": "Demo"})


def test_check_token_secret_raises_when_the_environment_lost_the_secret() -> None:
    with pytest.raises(
        SemaphoreSetupError,
        match="without the secret INFRAHUB_API_TOKEN; its secrets: none",
    ):
        check_token_secret({"id": 3, "secrets": []})


def test_the_inventory_file_reads_devices_from_the_infrahub_of_the_same_environment() -> (
    None
):
    inventory = yaml.safe_load(
        (IMAGE_DIRECTORY / "ansible" / "inventory" / "infrahub.yml").read_text()
    )

    assert inventory == {
        "plugin": "opsmill.infrahub.inventory",
        "api_endpoint": "http://infrahub:8000",
        "hostnames": ["name"],
        "nodes": {"InfraDevice": {"include": ["name"]}},
    }


def test_the_playbook_prints_the_device_count_once_without_connecting() -> None:
    (play,) = yaml.safe_load(
        (IMAGE_DIRECTORY / "ansible" / "list_hosts.yml").read_text()
    )

    assert (play["hosts"], play["gather_facts"], play["connection"]) == (
        "all",
        False,
        "local",
    )
    (task,) = play["tasks"]
    assert task["run_once"] is True
    assert task["ansible.builtin.debug"]["msg"][0] == (
        "Devices in the inventory: {{ groups['all'] | length }}"
    )
