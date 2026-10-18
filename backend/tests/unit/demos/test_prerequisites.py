"""The record command's prerequisites check: its messages and their order (FR-012), with a fake demo stack."""

from __future__ import annotations

import shutil
import socket
from types import SimpleNamespace

import pytest
from styrmin_sdk.exceptions import StyrminAuthenticationError

from tests.e2e.demos import prerequisites, stack
from tests.e2e.demos.prerequisites import FFMPEG_MISSING, check

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


@pytest.fixture
def ffmpeg_on_path(monkeypatch):
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
        "ffmpeg is not on the PATH. Install it (for example 'brew install ffmpeg' or "
        "'apt install ffmpeg') and run the command again."
    )


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


async def test_a_failed_admin_login_gives_the_same_message(
    ffmpeg_on_path, stack_client, versions_file
) -> None:
    stack_client(
        StyrminAuthenticationError("Invalid credentials", "INVALID_CREDENTIALS")
    )

    assert await check(STACK_URL, CREDENTIALS, versions_file) == [STACK_DOWN]


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
        "the 'local' backup storage location. Run 'uv run invoke start' again."
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
        "The demo stack is missing the 'infrahub' driver. Run 'uv run invoke start' again."
    ]


async def test_the_versions_file_comes_last_with_its_path(
    ffmpeg_on_path, stack_client, tmp_path
) -> None:
    stack_client(_complete_stack())
    path = tmp_path / "infrahub_versions.yml"

    assert await check(STACK_URL, CREDENTIALS, path) == [
        f"{path}: the file does not exist"
    ]
