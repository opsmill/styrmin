"""The task-starting action primitives link their task to the hook step (spec 019, research D12).

``stop_components``, ``start_components`` and ``upgrade_deployment_version``
send ``STYRMIN_STEP_ID`` as ``startedByStepId``; the request goes to a fake
API that records it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from styrmin_backend import config
from styrmin_backend.actions import primitives
from styrmin_backend.agent.tasks.utils import API_TOKEN_ENV, STEP_ID_ENV

DEPLOYMENT_ID = uuid4()

Primitive = Callable[[Any], Awaitable[None]]

PRIMITIVES: dict[str, tuple[Primitive, str]] = {
    "stop_components": (
        lambda context: primitives.stop_components.fn(["server"], context),
        "stopComponents",
    ),
    "start_components": (
        lambda context: primitives.start_components.fn(["server"], context),
        "startComponents",
    ),
    "upgrade_deployment_version": (
        lambda context: primitives.upgrade_deployment_version.fn("2.0.0", context),
        "updateDeploymentVersion",
    ),
}


@pytest.fixture
def sent_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The GraphQL requests the primitives send; each answers with a new task."""
    sent: list[dict[str, Any]] = []

    def _answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        field = next(
            field for _, field in PRIMITIVES.values() if field in body["query"]
        )
        return httpx.Response(200, json={"data": {field: {"id": str(uuid4())}}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        primitives,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda **kwargs: real_client(
                transport=httpx.MockTransport(_answer), **kwargs
            )
        ),
    )
    monkeypatch.setattr(primitives, "_wait_for_task", AsyncMock())
    monkeypatch.setattr(config.SETTINGS.url, "api", "http://styrmin.test")
    monkeypatch.setenv(API_TOKEN_ENV, "action-token")
    return sent


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        components={"server": object()},
        instance=SimpleNamespace(deployment_id=DEPLOYMENT_ID),
    )


@pytest.mark.parametrize("primitive", sorted(PRIMITIVES))
async def test_primitive_sends_the_hook_step_as_started_by_step_id(
    sent_requests: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, primitive: str
) -> None:
    step_id = uuid4()
    monkeypatch.setenv(STEP_ID_ENV, str(step_id))
    call, field = PRIMITIVES[primitive]

    await call(_context())

    (request,) = sent_requests
    assert f"{field}(" in request["query"]
    assert "startedByStepId: $startedByStepId" in request["query"]
    assert request["variables"]["startedByStepId"] == str(step_id)
    assert request["variables"]["deploymentId"] == str(DEPLOYMENT_ID)


@pytest.mark.parametrize("primitive", sorted(PRIMITIVES))
@pytest.mark.parametrize("step_id", [None, "not-a-uuid"], ids=["unset", "invalid"])
async def test_primitive_without_a_valid_hook_step_sends_null(
    sent_requests: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    primitive: str,
    step_id: str | None,
) -> None:
    if step_id is None:
        monkeypatch.delenv(STEP_ID_ENV, raising=False)
    else:
        monkeypatch.setenv(STEP_ID_ENV, step_id)
    call, _field = PRIMITIVES[primitive]

    await call(_context())

    (request,) = sent_requests
    assert request["variables"]["startedByStepId"] is None
