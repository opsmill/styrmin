"""The record command's prerequisites check: its messages and their order (FR-012), with a fake demo stack."""

from __future__ import annotations

import shutil
import socket
from types import SimpleNamespace

import pytest
from styrmin_sdk.exceptions import StyrminAuthenticationError

from tests.e2e.demos import prerequisites, stack
from tests.e2e.demos.prerequisites import (
    DOCKER_MISSING,
    FFMPEG_MISSING,
    chromium_missing,
    kube_context_unreachable,
    login_rejected,
)

STACK_URL = "http://styrmin.local.styrmin.io:8080"
CREDENTIALS = ("admin", "not-a-secret")
STACK_DOWN = (
    f"The demo stack does not respond at {STACK_URL}. Run 'uv run invoke start' first."
)


def _named(*names: str, versions: bool = True):
    return [
        SimpleNamespace(name=name, versions=["1"] if versions else []) for name in names
    ]


class FakeClient:
    def __init__(self, *, drivers, clusters, locations) -> None:
        self.closed = False
        self.drivers = SimpleNamespace(list=self._returns(drivers))
        self.clusters = SimpleNamespace(list=self._returns(clusters))
        self.backup_storage_locations = SimpleNamespace(list=self._returns(locations))

    @staticmethod
    def _returns(value):
        async def call():
            return value

        return call

    async def close(self) -> None:
        self.closed = True


def _complete_stack() -> FakeClient:
    return FakeClient(
        drivers=_named("infrahub", "semaphore", "infrahub-enterprise"),
        clusters=_named("local"),
        locations=_named("local"),
    )


@pytest.fixture
def versions_file(tmp_path):
    path = tmp_path / "infrahub_versions.yml"
    path.write_text('previous: "1.10.11"\nlatest: "1.11.7"\n')
    return path


async def check(
    api_url, credentials, versions_path, *, needs_docker=True, empty_stack=False
):
    return await prerequisites.check(
        api_url,
        credentials,
        versions_path,
        needs_docker=needs_docker,
        empty_stack=empty_stack,
    )


@pytest.fixture
def chromium(tmp_path, monkeypatch):
    """Chromium is installed at a path that exists; a test deletes the file to remove it."""
    path = tmp_path / "chrome-linux" / "chrome"
    path.parent.mkdir()
    path.write_text("")

    async def chromium_path():
        return path

    monkeypatch.setattr(prerequisites, "chromium_path", chromium_path)
    return path


@pytest.fixture
def kube_context(monkeypatch):
    """The kube context answers unless a test sets ``problem``."""
    state = SimpleNamespace(problem=None, checked=[])

    async def check_kube_context(context):
        state.checked.append(context)
        return state.problem

    monkeypatch.setattr(stack, "check_kube_context", check_kube_context)
    return state


@pytest.fixture
def ffmpeg_on_path(monkeypatch, chromium, kube_context):
    """Every tool is on the PATH, Chromium is installed and the kube context answers."""
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.fixture
def stack_client(monkeypatch):
    calls: list[tuple] = []

    def install(client: FakeClient | Exception) -> list[tuple]:
        async def connect(api_url, username, password, *, timeout):
            calls.append((api_url, username, timeout))
            if isinstance(client, Exception):
                raise client
            return client

        monkeypatch.setattr(stack, "connect", connect)
        return calls

    return install


async def test_a_complete_stack_and_a_valid_versions_file_give_no_message(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    client = _complete_stack()
    calls = stack_client(client)

    assert await check(STACK_URL, CREDENTIALS, versions_file) == []
    assert calls == [(STACK_URL, "admin", prerequisites.CONNECT_TIMEOUT)]
    assert client.closed


async def test_ffmpeg_comes_first_and_stops_the_check(
    monkeypatch, stack_client, tmp_path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    calls = stack_client(StyrminAuthenticationError("bad", "INVALID_CREDENTIALS"))

    assert await check(STACK_URL, CREDENTIALS, tmp_path / "missing.yml") == [
        FFMPEG_MISSING
    ]
    assert calls == []
    assert FFMPEG_MISSING == (
        "ffmpeg or ffprobe is not on the PATH. Install ffmpeg (for example 'brew install ffmpeg' or "
        "'apt install ffmpeg') and run the command again."
    )


async def test_ffprobe_is_needed_too(monkeypatch, stack_client, tmp_path) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "ffprobe" else f"/usr/bin/{name}"
    )
    calls = stack_client(_complete_stack())

    assert await check(STACK_URL, CREDENTIALS, tmp_path / "missing.yml") == [
        FFMPEG_MISSING
    ]
    assert calls == []


async def test_a_missing_chromium_build_is_named_before_the_stack_is_reached(
    ffmpeg_on_path, chromium, kube_context, stack_client, versions_file
) -> None:
    chromium.unlink()
    calls = stack_client(_complete_stack())

    assert await check(STACK_URL, CREDENTIALS, versions_file) == [
        chromium_missing(str(chromium))
    ]
    assert "uv run playwright install chromium" in chromium_missing(str(chromium))
    assert calls == []
    assert kube_context.checked == []


async def test_docker_is_needed_only_to_build_the_semaphore_image(
    monkeypatch, chromium, kube_context, stack_client, versions_file
) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "docker" else f"/usr/bin/{name}"
    )
    stack_client(_complete_stack())

    assert await check(STACK_URL, CREDENTIALS, versions_file) == [DOCKER_MISSING]
    assert await check(STACK_URL, CREDENTIALS, versions_file, needs_docker=False) == []


async def test_an_unreachable_kube_context_is_named_before_the_stack_is_reached(
    ffmpeg_on_path, kube_context, stack_client, versions_file
) -> None:
    kube_context.problem = "ValueError: No such context vcluster-docker_styrmin"
    calls = stack_client(_complete_stack())

    assert await check(STACK_URL, CREDENTIALS, versions_file) == [
        kube_context_unreachable("vcluster-docker_styrmin", kube_context.problem)
    ]
    assert kube_context.checked == ["vcluster-docker_styrmin"]
    assert calls == []
    assert "uv run invoke start" in kube_context_unreachable("c", "r")


async def test_a_stack_that_refuses_connections_does_not_respond(
    ffmpeg_on_path, tmp_path
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"

    assert await check(url, CREDENTIALS, tmp_path / "missing.yml") == [
        f"The demo stack does not respond at {url}. Run 'uv run invoke start' first."
    ]


async def test_a_rejected_admin_login_is_named_as_such(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    stack_client(
        StyrminAuthenticationError("Invalid credentials", "INVALID_CREDENTIALS")
    )

    [message] = await check(STACK_URL, CREDENTIALS, versions_file)

    assert message == login_rejected(STACK_URL, "admin")
    assert message.startswith(
        f"The demo stack at {STACK_URL} rejected the login of 'admin'."
    )
    assert "dev/local/demo-values.yaml" in message
    assert message != STACK_DOWN


async def test_the_missing_items_are_named_in_one_message_before_the_versions_file(
    ffmpeg_on_path, stack_client, tmp_path
) -> None:
    client = FakeClient(
        drivers=[*_named("infrahub"), *_named("semaphore", versions=False)],
        clusters=_named("other"),
        locations=[],
    )
    stack_client(client)

    assert await check(STACK_URL, CREDENTIALS, tmp_path / "missing.yml") == [
        "The demo stack is missing the 'semaphore' driver, the 'local' cluster and "
        "the 'local' backup storage location. Run 'uv run invoke start' again, "
        "or record the setup demo before the others."
    ]
    assert client.closed


async def test_one_missing_item_is_named_alone(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    stack_client(
        FakeClient(
            drivers=_named("semaphore"),
            clusters=_named("local"),
            locations=_named("local"),
        )
    )

    assert await check(STACK_URL, CREDENTIALS, versions_file) == [
        "The demo stack is missing the 'infrahub' driver. Run 'uv run invoke start' again, "
        "or record the setup demo before the others."
    ]


async def test_the_setup_demo_accepts_an_empty_stack(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    # A stack started with --no-bootstrap has no driver, cluster or backup storage location.
    client = FakeClient(drivers=[], clusters=[], locations=_named("offsite"))
    stack_client(client)

    assert await check(STACK_URL, CREDENTIALS, versions_file, empty_stack=True) == []
    assert client.closed


async def test_the_setup_demo_names_what_the_stack_already_has(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    stack_client(_complete_stack())

    assert await check(STACK_URL, CREDENTIALS, versions_file, empty_stack=True) == [
        "The setup demo creates the cluster and the backup storage location in the Styrmin UI, so it needs "
        "a demo stack without them, and this demo stack has the cluster 'local' and the backup storage "
        "location 'local'. Run 'uv run invoke reset --no-bootstrap', which creates the demo stack without "
        "them, or record the other demos only with "
        "'uv run invoke record --demo deploy-upgrade,component-overrides,backup-restore,clone'."
    ]


async def test_the_setup_demo_refuses_a_cluster_of_any_name(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    stack_client(FakeClient(drivers=[], clusters=_named("other"), locations=[]))

    [message] = await check(STACK_URL, CREDENTIALS, versions_file, empty_stack=True)

    assert "this demo stack has the cluster 'other'. Run" in message


async def test_the_versions_file_comes_last_with_its_path(
    ffmpeg_on_path, stack_client, tmp_path
) -> None:
    stack_client(_complete_stack())
    path = tmp_path / "infrahub_versions.yml"

    assert await check(STACK_URL, CREDENTIALS, path) == [
        f"{path}: the file does not exist"
    ]
