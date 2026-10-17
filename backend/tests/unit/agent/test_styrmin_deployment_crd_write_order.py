"""Unit tests for the order of StyrminDeployment writes (#386).

Each update schedules its own ``apply_state`` flow, and the flows can write the
StyrminDeployment in any order. A fake API server holds the StyrminDeployment,
applies the agent's JSON Patch the way Kubernetes does (``test`` included), and
can run a write of another flow between the agent's read and its write.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.exceptions import (
    CustomResourceNotFound,
    CustomResourceWriteConflictError,
)
from styrmin_backend.agent.service.kubernetes import styrmin_deployment
from styrmin_backend.agent.tasks import orchestration
from styrmin_backend.agent.tasks.orchestration import KeptInstance
from styrmin_backend.operator.config import ANNOTATION_INSTANCE_SEQUENCE
from styrmin_backend.operator.crd.builder import build_styrmin_deployment_body

from tests.unit.counterpart_crd_fixtures import make_context

DEPLOYMENT_ID = uuid4()
RESOURCE_UID = "0b7f6c1e-uid"


def _body(sequence: int | None) -> dict:
    """The StyrminDeployment body of a new instance of the deployment."""
    context = make_context(
        deployment_id=DEPLOYMENT_ID,
        namespace="ns",
        release_reference="rel",
        instance_id=uuid4(),
    )
    return build_styrmin_deployment_body(
        context=context,
        release_reference="rel",
        namespace="ns",
        instance_sequence=sequence,
    )


def _with_annotation(body: dict, value: str) -> dict:
    body["metadata"]["annotations"] = {ANNOTATION_INSTANCE_SEQUENCE: value}
    return body


def _resolve(document: dict, path: str) -> tuple[dict, str]:
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in path.split("/")[1:]]
    *parents, leaf = tokens
    node = document
    for token in parents:
        node = node[token]
    return node, leaf


class FakeApiServer:
    """Holds one StyrminDeployment and answers the agent's read, create and JSON Patch calls."""

    def __init__(self, live: dict | None = None) -> None:
        self.version = 0
        self.live: dict | None = None
        self.patches: list[list[dict[str, Any]]] = []
        #: Runs once, after the next read, as the write of another flow.
        self.after_read: Callable[[], None] | None = None
        if live is not None:
            self.store(live)

    def store(self, body: dict) -> None:
        self.version += 1
        self.live = copy.deepcopy(body)
        self.live["metadata"]["resourceVersion"] = str(self.version)
        self.live["metadata"]["uid"] = RESOURCE_UID

    def touch(self) -> None:
        """A write that changes only the resourceVersion, like a status or kopf write."""
        self.version += 1
        assert self.live is not None
        self.live["metadata"]["resourceVersion"] = str(self.version)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(styrmin_deployment, "get_custom_resource", self.get)
        monkeypatch.setattr(orchestration, "upsert_custom_resource", self.create)
        monkeypatch.setattr(orchestration, "patch_custom_resource", self.patch)

    async def get(self, **_: Any) -> dict:
        live = copy.deepcopy(self.live)
        if self.after_read is not None:
            interleaved, self.after_read = self.after_read, None
            interleaved()
        if live is None:
            raise CustomResourceNotFound("not found")
        return live

    async def create(self, *, body: dict, update: bool, **_: Any) -> None:
        assert update is False
        if self.live is not None:
            raise ApiException(status=409)
        self.store(body)

    async def patch(self, *, patch: list[dict[str, Any]], **_: Any) -> None:
        assert self.live is not None
        self.patches.append(patch)
        result = copy.deepcopy(self.live)
        for op in patch:
            node, leaf = _resolve(result, op["path"])
            if op["op"] == "test":
                if node.get(leaf) != op["value"]:
                    raise ApiException(status=422, reason="test failed")
            elif op["op"] == "add":
                node[leaf] = op["value"]
            elif op["op"] == "remove":
                del node[leaf]
        result["metadata"].pop("resourceVersion")
        self.store(result)


def _instance_id(server: FakeApiServer) -> str:
    assert server.live is not None
    return server.live["spec"]["instanceId"]


def _annotations(server: FakeApiServer) -> dict[str, str]:
    assert server.live is not None
    return server.live["metadata"].get("annotations") or {}


async def _apply(body: dict) -> KeptInstance | None:
    return await orchestration._apply_styrmin_deployment_crd(body=body, namespace="ns")


@pytest.mark.asyncio
async def test_an_absent_resource_is_created_with_the_instance_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer()
    server.install(monkeypatch)
    body = _body(1)

    assert await _apply(body) is None

    assert server.live is not None
    assert server.live["spec"] == body["spec"]
    assert _annotations(server)[ANNOTATION_INSTANCE_SEQUENCE] == "1"


@pytest.mark.asyncio
async def test_a_higher_sequence_replaces_a_lower_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer(_body(6))
    server.install(monkeypatch)
    newer = _body(7)

    assert await _apply(newer) is None

    assert _instance_id(server) == newer["spec"]["instanceId"]
    assert _annotations(server)[ANNOTATION_INSTANCE_SEQUENCE] == "7"


@pytest.mark.asyncio
async def test_a_lower_sequence_leaves_the_resource_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    newer = _body(7)
    server = FakeApiServer(newer)
    server.install(monkeypatch)

    kept = await _apply(_body(6))

    assert kept == KeptInstance(
        instance_id=newer["spec"]["instanceId"], sequence=7, resource_uid=RESOURCE_UID
    )
    assert server.patches == []
    assert _instance_id(server) == newer["spec"]["instanceId"]


@pytest.mark.asyncio
async def test_the_same_sequence_is_written_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flow that runs again for the same instance rewrites the resource."""
    server = FakeApiServer(_body(7))
    server.install(monkeypatch)
    body = _body(7)

    assert await _apply(body) is None

    assert _instance_id(server) == body["spec"]["instanceId"]


@pytest.mark.asyncio
async def test_a_newer_write_between_the_read_and_the_patch_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race of #386: both flows read the resource before either writes it."""
    server = FakeApiServer(_body(5))
    server.install(monkeypatch)
    older, newer = _body(6), _body(7)
    server.after_read = lambda: server.store(newer)

    kept = await _apply(older)

    assert kept is not None
    assert kept.sequence == 7
    assert len(server.patches) == 1, "the stale patch must have been refused"
    assert _instance_id(server) == newer["spec"]["instanceId"]


@pytest.mark.asyncio
async def test_a_newer_create_between_the_read_and_the_create_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer()
    server.install(monkeypatch)
    older, newer = _body(1), _body(2)
    server.after_read = lambda: server.store(newer)

    kept = await _apply(older)

    assert kept is not None
    assert kept.sequence == 2
    assert _instance_id(server) == newer["spec"]["instanceId"]


@pytest.mark.asyncio
async def test_an_unrelated_change_between_the_read_and_the_patch_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status or kopf write also changes the resourceVersion; the flow reads again."""
    server = FakeApiServer(_body(6))
    server.install(monkeypatch)
    server.after_read = server.touch
    newer = _body(7)

    assert await _apply(newer) is None

    assert len(server.patches) == 2
    assert _instance_id(server) == newer["spec"]["instanceId"]


@pytest.mark.asyncio
async def test_a_resource_without_annotations_gets_the_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer(_body(None))
    server.install(monkeypatch)

    assert await _apply(_body(3)) is None

    assert _annotations(server)[ANNOTATION_INSTANCE_SEQUENCE] == "3"


@pytest.mark.asyncio
async def test_a_body_without_a_sequence_is_written_and_drops_the_annotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The annotation of the previous instance would describe the wrong spec."""
    server = FakeApiServer(_body(7))
    server.install(monkeypatch)
    body = _body(None)

    assert await _apply(body) is None

    assert _instance_id(server) == body["spec"]["instanceId"]
    assert ANNOTATION_INSTANCE_SEQUENCE not in _annotations(server)


@pytest.mark.asyncio
async def test_a_malformed_annotation_is_overwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer(_with_annotation(_body(None), "not-a-number"))
    server.install(monkeypatch)
    body = _body(2)

    assert await _apply(body) is None

    assert _instance_id(server) == body["spec"]["instanceId"]
    assert _annotations(server)[ANNOTATION_INSTANCE_SEQUENCE] == "2"


@pytest.mark.asyncio
async def test_other_api_errors_are_raised_without_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer(_body(6))
    server.install(monkeypatch)
    calls: list[Any] = []

    async def failing_patch(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise ApiException(status=500)

    monkeypatch.setattr(orchestration, "patch_custom_resource", failing_patch)

    with pytest.raises(ApiException) as raised:
        await _apply(_body(7))

    assert raised.value.status == 500
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_rejected_patch_on_an_unchanged_resource_is_raised_without_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schema or CEL validation failure also returns 422, but the resource did not change."""
    server = FakeApiServer(_body(6))
    server.install(monkeypatch)
    calls: list[Any] = []

    async def invalid_patch(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise ApiException(status=422, reason="spec.values: Invalid value")

    monkeypatch.setattr(orchestration, "patch_custom_resource", invalid_patch)

    with pytest.raises(ApiException) as raised:
        await _apply(_body(7))

    assert raised.value.reason == "spec.values: Invalid value"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_resource_that_keeps_changing_fails_the_write_with_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = FakeApiServer(_body(6))
    server.install(monkeypatch)
    real_get = server.get

    async def get_then_change(**kwargs: Any) -> dict:
        server.after_read = server.touch
        return await real_get(**kwargs)

    monkeypatch.setattr(styrmin_deployment, "get_custom_resource", get_then_change)

    with pytest.raises(CustomResourceWriteConflictError) as raised:
        await _apply(_body(7))

    assert str(raised.value) == (
        "Could not write StyrminDeployment ns/ns: another write changed it between "
        "each read and write, 5 times in a row. The next change to the deployment "
        "writes it again."
    )
    assert len(server.patches) == orchestration._CRD_WRITE_ATTEMPTS
