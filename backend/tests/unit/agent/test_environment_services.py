"""The alias step's read of an environment's services from the server (#503)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from styrmin_backend import config
from styrmin_backend.agent.tasks.environment_services import (
    EnvironmentServicesReadError,
    read_environment_services,
)

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", SecretStr("action-token"))
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    return []


def _serve(
    monkeypatch: pytest.MonkeyPatch, requests: list[httpx.Request], handler: Handler
) -> None:
    real_client = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(record), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.asyncio
async def test_returns_the_name_and_owner_of_each_service(
    monkeypatch: pytest.MonkeyPatch, requests: list[httpx.Request]
) -> None:
    services = [
        {
            "resolvedName": "intent",
            "deploymentId": "6f1e1b8a-0000-4000-8000-000000000001",
        },
        {
            "resolvedName": "executor",
            "deploymentId": "6f1e1b8a-0000-4000-8000-000000000002",
        },
    ]
    _serve(
        monkeypatch,
        requests,
        lambda _: httpx.Response(200, json={"data": {"environmentServices": services}}),
    )

    result = await read_environment_services("env-1")

    assert result == [
        {"resolved_name": "intent", "deployment_id": services[0]["deploymentId"]},
        {"resolved_name": "executor", "deployment_id": services[1]["deploymentId"]},
    ]
    (request,) = requests
    assert str(request.url) == config.SETTINGS.url.graphql
    assert request.headers["Authorization"] == "Bearer action-token"
    body = json.loads(request.content)
    assert body["variables"] == {"environmentId": "env-1"}
    assert "query ListEnvironmentServices" in body["query"]


@pytest.mark.asyncio
async def test_raises_without_an_action_token(
    monkeypatch: pytest.MonkeyPatch, requests: list[httpx.Request]
) -> None:
    monkeypatch.setattr(config.SETTINGS.agent, "api_token", None)
    _serve(monkeypatch, requests, lambda _: httpx.Response(200))

    with pytest.raises(EnvironmentServicesReadError, match="no action token"):
        await read_environment_services("env-1")

    assert requests == []


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        pytest.param(
            lambda _: httpx.Response(
                200, json={"errors": [{"message": "Authentication is required"}]}
            ),
            "GraphQL error: Authentication is required",
            id="graphql-error",
        ),
        pytest.param(
            lambda _: httpx.Response(502, text="Bad Gateway"),
            "the request failed",
            id="http-error",
        ),
        pytest.param(
            lambda _: httpx.Response(200, text="not json"),
            "the request failed",
            id="not-json",
        ),
        pytest.param(
            lambda _: httpx.Response(200, json={"data": None}),
            "unexpected response",
            id="no-data",
        ),
    ],
)
@pytest.mark.asyncio
async def test_raises_when_the_server_answers_without_the_services(
    monkeypatch: pytest.MonkeyPatch,
    requests: list[httpx.Request],
    handler: Handler,
    message: str,
) -> None:
    _serve(monkeypatch, requests, handler)

    with pytest.raises(EnvironmentServicesReadError, match=message):
        await read_environment_services("env-1")


@pytest.mark.asyncio
async def test_raises_when_the_server_cannot_be_reached(
    monkeypatch: pytest.MonkeyPatch, requests: list[httpx.Request]
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _serve(monkeypatch, requests, refuse)

    with pytest.raises(EnvironmentServicesReadError, match="connection refused"):
        await read_environment_services("env-1")
