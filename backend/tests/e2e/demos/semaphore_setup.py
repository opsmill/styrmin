"""Create the Semaphore project and the task template that read the devices from Infrahub (research R-010)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# The admin account that the `semaphore` driver's values.j2.yml creates. Never print the password.
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin-password"  # noqa: S105
PROJECT_NAME = "Network lab"
TEMPLATE_NAME = "List network devices"
# Paths inside the demo Semaphore image (demos/semaphore/Dockerfile).
REPOSITORY_PATH = "/opt/demo/ansible"
INVENTORY_PATH = "inventory/infrahub.yml"
PLAYBOOK = "list_hosts.yml"
TOKEN_VARIABLE = "INFRAHUB_API_TOKEN"  # noqa: S105
POLL_INTERVAL = 3.0


class SemaphoreSetupError(RuntimeError):
    """Semaphore refused a request of the setup, or created something other than what the setup asked for."""


@dataclass(frozen=True)
class SemaphoreProject:
    project_id: int
    template_id: int
    environment_id: int


def repository_body(project_id: int, key_id: int) -> dict[str, Any]:
    # A path that starts with "/" is a local repository: Semaphore runs the playbook in it without cloning.
    return {
        "name": "Demo playbooks",
        "project_id": project_id,
        "git_url": REPOSITORY_PATH,
        "git_branch": "",
        "ssh_key_id": key_id,
    }


def inventory_body(project_id: int, key_id: int, repository_id: int) -> dict[str, Any]:
    return {
        "name": "Infrahub devices",
        "project_id": project_id,
        "type": "file",
        "inventory": INVENTORY_PATH,
        "repository_id": repository_id,
        "ssh_key_id": key_id,
    }


def environment_body(project_id: int, infrahub_token: str) -> dict[str, Any]:
    # `json` and `env` are strings that hold JSON.
    return {
        "name": "Infrahub token",
        "project_id": project_id,
        "json": "{}",
        "env": "{}",
        "secrets": [
            {
                "type": "env",
                "name": TOKEN_VARIABLE,
                "secret": infrahub_token,
                "operation": "create",
            }
        ],
    }


def template_body(
    project_id: int, *, repository_id: int, inventory_id: int, environment_id: int
) -> dict[str, Any]:
    return {
        "name": TEMPLATE_NAME,
        "project_id": project_id,
        "app": "ansible",
        "playbook": PLAYBOOK,
        "repository_id": repository_id,
        "inventory_id": inventory_id,
        "environment_id": environment_id,
    }


def created_object(
    response: httpx.Response,
    what: str,
    expected: Mapping[str, object],
    *,
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Return the object of a 201 answer whose fields match ``expected``; raise on anything else.

    Some endpoints create the record and still answer 400, so a 400 never counts as created.
    """
    if response.status_code != httpx.codes.CREATED:
        raise SemaphoreSetupError(
            f"Semaphore answered HTTP {response.status_code} when the setup created {what} "
            f"(it may have created it anyway): {_describe(response, secrets)}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise SemaphoreSetupError(
            f"Semaphore created {what} but its answer is not JSON: {_describe(response, secrets)}"
        ) from exc
    if not isinstance(body, dict) or not isinstance(body.get("id"), int):
        raise SemaphoreSetupError(
            f"Semaphore's answer for {what} has no id: {_describe(response, secrets)}"
        )
    wrong = {
        key: body.get(key) for key, value in expected.items() if body.get(key) != value
    }
    if wrong:
        raise SemaphoreSetupError(
            f"Semaphore created {what} with other values than the setup sent: "
            + ", ".join(f"{key}={value!r}" for key, value in wrong.items())
        )
    return body


def _describe(response: httpx.Response, secrets: Iterable[str]) -> str:
    text = response.text.strip()[:500] or "(empty body)"
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


def _ok(response: httpx.Response, what: str) -> Any:
    if not response.is_success:
        raise SemaphoreSetupError(
            f"Semaphore answered HTTP {response.status_code} to {what}: {_describe(response, ())}"
        )
    return response.json() if response.content else None


async def configure(
    url: str,
    *,
    infrahub_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SemaphoreProject:
    """Create the project, the inventory that reads Infrahub and the template in the Semaphore at ``url``."""
    async with httpx.AsyncClient(
        base_url=url, timeout=30.0, transport=transport
    ) as http:
        login = await http.post(
            "/api/auth/login", json={"auth": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        _ok(login, f"the login of {ADMIN_USERNAME!r}")

        name = {"name": PROJECT_NAME}
        project = created_object(
            await http.post("/api/projects", json=name),
            f"project {PROJECT_NAME!r}",
            name,
        )
        project_id = project["id"]
        base = f"/api/project/{project_id}"

        keys = _ok(await http.get(f"{base}/keys"), "the list of keys")
        key = next((item for item in keys if item.get("name") == "None"), None)
        if key is None:
            raise SemaphoreSetupError(
                f"Project {PROJECT_NAME!r} has no key named 'None'; Semaphore creates it with each project"
            )

        async def create(path: str, what: str, body: dict[str, Any]) -> int:
            expected = {k: v for k, v in body.items() if k != "secrets"}
            response = await http.post(f"{base}/{path}", json=body)
            created = created_object(response, what, expected, secrets=[infrahub_token])
            return created["id"]

        repository_id = await create(
            "repositories", "the repository", repository_body(project_id, key["id"])
        )
        inventory_id = await create(
            "inventory",
            "the inventory",
            inventory_body(project_id, key["id"], repository_id),
        )
        environment_id = await create(
            "environment",
            "the environment",
            environment_body(project_id, infrahub_token),
        )
        environment = _ok(
            await http.get(f"{base}/environment/{environment_id}"),
            "reading the environment",
        )
        check_token_secret(environment)
        template_id = await create(
            "templates",
            f"template {TEMPLATE_NAME!r}",
            template_body(
                project_id,
                repository_id=repository_id,
                inventory_id=inventory_id,
                environment_id=environment_id,
            ),
        )
    return SemaphoreProject(
        project_id=project_id, template_id=template_id, environment_id=environment_id
    )


def check_token_secret(environment: Mapping[str, Any]) -> None:
    """Raise unless the environment holds the token as an environment-variable secret."""
    secrets = environment.get("secrets") or []
    if not any(
        item.get("type") == "env" and item.get("name") == TOKEN_VARIABLE
        for item in secrets
    ):
        found = ", ".join(str(item.get("name")) for item in secrets) or "none"
        raise SemaphoreSetupError(
            f"Semaphore created the environment without the secret {TOKEN_VARIABLE}; "
            f"its secrets: {found}"
        )


async def wait_until_ready(
    url: str,
    timeout: float,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    poll_interval: float = POLL_INTERVAL,
) -> None:
    """Wait until the Semaphore at ``url`` answers ``GET /api/ping`` with 200."""
    deadline = time.monotonic() + timeout
    last = "no answer"
    async with httpx.AsyncClient(
        base_url=url, timeout=10.0, transport=transport
    ) as http:
        while True:
            try:
                response = await http.get("/api/ping")
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                if response.status_code == httpx.codes.OK:
                    return
                last = f"HTTP {response.status_code}"
            if time.monotonic() >= deadline:
                raise SemaphoreSetupError(
                    f"Semaphore at {url} did not answer within {timeout:.0f} s (last answer: {last})"
                )
            await asyncio.sleep(poll_interval)
