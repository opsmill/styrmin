"""Unit tests for the cross-target post-velero recovery path (research D2.4).

A cross-target restore rides Velero's ``namespaceMapping``: the data lands in
the counterpart's namespace, but every restored object — including the
``StyrminDeployment`` CR — keeps its *source* name and, for the CR, the
source's whole identity (``deploymentId``, ``instanceId``,
``releaseReference``, resolved context). ``reapply_with_counterpart_identity``
is what replaces that identity with the counterpart's own before finalizing.

The tests drive the real recovery functions against a fake
``CustomObjectsApi`` so the ordering (apply counterpart -> delete restored ->
run phases -> mark Ready) is asserted on recorded calls rather than mocked
away.
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.operator import restore_recovery
from styrmin_backend.operator.config import CRD_PLURAL
from styrmin_backend.operator.crd.schema import DeploymentPhase, DisplayState
from styrmin_backend.operator.pipeline import PhaseResult


KOPF_ANNOTATION = "kopf.zalando.org/last-handled-configuration"


class FakeApiException(Exception):
    """Stand-in for ``kubernetes_asyncio.client.ApiException``."""

    def __init__(self, status: int) -> None:
        super().__init__(f"api error status={status}")
        self.status = status


class FakeApiClient:
    """Holds the fake cluster's custom objects plus a call recorder."""

    def __init__(self, objects: dict[str, dict[str, Any]] | None = None) -> None:
        # keyed by (namespace, name)
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        for name, body in (objects or {}).items():
            namespace = body["metadata"]["namespace"]
            self.objects[(namespace, name)] = body
        self.calls: list[tuple[str, str]] = []


class FakeCustomObjectsApi:
    """Minimal ``CustomObjectsApi`` over :class:`FakeApiClient` state."""

    def __init__(self, api_client: FakeApiClient) -> None:
        self._client = api_client

    def _record(self, verb: str, name: str) -> None:
        self._client.calls.append((verb, name))

    async def get_namespaced_custom_object(
        self, *, group: str, version: str, namespace: str, plural: str, name: str
    ) -> dict[str, Any]:
        assert plural == CRD_PLURAL
        self._record("get", name)
        body = self._client.objects.get((namespace, name))
        if body is None:
            raise FakeApiException(404)
        return body

    async def create_namespaced_custom_object(
        self, *, group: str, version: str, namespace: str, plural: str, body: dict
    ) -> dict[str, Any]:
        name = body["metadata"]["name"]
        self._record("create", name)
        if (namespace, name) in self._client.objects:
            raise FakeApiException(409)
        self._client.objects[(namespace, name)] = body
        return body

    async def patch_namespaced_custom_object(
        self,
        *,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
        body: dict,
        _content_type: str | None = None,
    ) -> dict[str, Any]:
        self._record("patch", name)
        assert _content_type == "application/merge-patch+json"
        existing = self._client.objects.setdefault((namespace, name), {})
        existing.update(body)
        return existing

    async def delete_namespaced_custom_object(
        self, *, group: str, version: str, namespace: str, plural: str, name: str
    ) -> None:
        self._record("delete", name)
        if (namespace, name) not in self._client.objects:
            raise FakeApiException(404)
        del self._client.objects[(namespace, name)]

    async def patch_namespaced_custom_object_status(
        self,
        *,
        group: str,
        version: str,
        namespace: str,
        plural: str,
        name: str,
        body: dict,
        _content_type: str | None = None,
    ) -> dict[str, Any]:
        self._record("patch_status", name)
        assert _content_type == "application/merge-patch+json"
        existing = self._client.objects.get((namespace, name))
        if existing is None:
            raise FakeApiException(404)
        existing["status"] = body["status"]
        return existing


class FakeK8sClientModule:
    """Namespace object replacing ``restore_recovery.k8s_client``."""

    CustomObjectsApi = FakeCustomObjectsApi
    ApiException = FakeApiException


@pytest.fixture
def fake_k8s(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(restore_recovery, "k8s_client", FakeK8sClientModule)


@pytest.fixture
def phase_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the ``crd_spec`` each pipeline phase is invoked with."""
    seen: list[dict[str, Any]] = []

    async def _phase(*, crd_spec: dict[str, Any], namespace: str) -> PhaseResult:
        seen.append(crd_spec)
        return PhaseResult(success=True)

    monkeypatch.setattr(restore_recovery, "execute_phase_prerequisites", _phase)
    monkeypatch.setattr(restore_recovery, "execute_phase_services", _phase)
    return seen


NAMESPACE = "styrmin-counterpart-id"
RESTORED_NAME = "styrmin-source-id"
COUNTERPART_NAME = "styrmin-counterpart-id"


def restored_crd() -> dict[str, Any]:
    """The source-named CR Velero recreated inside the counterpart namespace."""
    return {
        "apiVersion": "styrmin.io/v1alpha1",
        "kind": "StyrminDeployment",
        "metadata": {
            "name": RESTORED_NAME,
            "namespace": NAMESPACE,
            "annotations": {
                KOPF_ANNOTATION: '{"spec":{"deploymentId":"source-id"}}',
                "unrelated.io/keep": "yes",
            },
        },
        "spec": {
            "deploymentId": "source-id",
            "releaseReference": RESTORED_NAME,
        },
    }


def counterpart_body() -> dict[str, Any]:
    return {
        "apiVersion": "styrmin.io/v1alpha1",
        "kind": "StyrminDeployment",
        "metadata": {"name": COUNTERPART_NAME, "namespace": NAMESPACE},
        "spec": {
            "deploymentId": "counterpart-id",
            "releaseReference": COUNTERPART_NAME,
        },
    }


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_counterpart_identity_replaces_the_restored_source_named_crd(
    phase_spy: list[dict[str, Any]],
) -> None:
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        counterpart_body(),
    )

    # The counterpart CR now owns the namespace ...
    assert (NAMESPACE, COUNTERPART_NAME) in api_client.objects
    applied = api_client.objects[(NAMESPACE, COUNTERPART_NAME)]
    assert applied["spec"]["deploymentId"] == "counterpart-id"
    assert applied["spec"]["releaseReference"] == COUNTERPART_NAME
    # ... and the restored source-named CR is gone.
    assert (NAMESPACE, RESTORED_NAME) not in api_client.objects

    # Both pipeline phases ran against the counterpart's spec, never the
    # restored source spec.
    assert len(phase_spy) == 2
    assert all(spec["deploymentId"] == "counterpart-id" for spec in phase_spy)

    # The counterpart CR is the one finalized to Ready/Running.
    status = applied["status"]
    assert status["phase"] == DeploymentPhase.READY.value
    assert status["displayState"] == DisplayState.RUNNING.value


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_kopf_state_annotations_are_carried_over(
    phase_spy: list[dict[str, Any]],
) -> None:
    """A CR without ``last-handled-configuration`` makes kopf fire on.create.

    ``reapply_and_finalize`` documents why that must not happen (it undoes the
    finalize and the deployment oscillates); the counterpart CR inherits the
    annotation from the restored CR for the same reason.
    """
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        counterpart_body(),
    )

    annotations = api_client.objects[(NAMESPACE, COUNTERPART_NAME)]["metadata"][
        "annotations"
    ]
    assert annotations[KOPF_ANNOTATION] == '{"spec":{"deploymentId":"source-id"}}'
    # Only kopf state annotations are inherited — nothing else from the source.
    assert "unrelated.io/keep" not in annotations


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_ordering_applies_before_deleting(
    phase_spy: list[dict[str, Any]],
) -> None:
    """The counterpart CR exists before the restored one is removed.

    Deleting first would leave the namespace with no ``StyrminDeployment`` if
    the apply then failed, and the operator's janitor treats an orphaned
    namespace as garbage.
    """
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        counterpart_body(),
    )

    verbs = [verb for verb, _ in api_client.calls]
    assert verbs.index("create") < verbs.index("delete")
    assert api_client.calls[-1] == ("patch_status", COUNTERPART_NAME)


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_existing_counterpart_crd_is_patched_not_duplicated(
    phase_spy: list[dict[str, Any]],
) -> None:
    """Recovery is idempotent: a retried restore must not 409-crash."""
    stale_counterpart = counterpart_body()
    stale_counterpart["spec"] = {"deploymentId": "counterpart-id", "stale": True}
    api_client = FakeApiClient(
        {RESTORED_NAME: restored_crd(), COUNTERPART_NAME: stale_counterpart}
    )

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        counterpart_body(),
    )

    applied = api_client.objects[(NAMESPACE, COUNTERPART_NAME)]
    assert applied["spec"] == {
        "deploymentId": "counterpart-id",
        "releaseReference": COUNTERPART_NAME,
    }
    assert ("patch", COUNTERPART_NAME) in api_client.calls


@pytest.mark.anyio
async def test_already_deleted_restored_crd_is_tolerated(
    monkeypatch: pytest.MonkeyPatch,
    phase_spy: list[dict[str, Any]],
) -> None:
    """A 404 on the delete is a retry, not a failure."""
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    class DeletingApi(FakeCustomObjectsApi):
        async def delete_namespaced_custom_object(
            self, *, group: str, version: str, namespace: str, plural: str, name: str
        ) -> None:
            self._record("delete", name)
            raise FakeApiException(404)

    class Module(FakeK8sClientModule):
        CustomObjectsApi = DeletingApi

    monkeypatch.setattr(restore_recovery, "k8s_client", Module)

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        counterpart_body(),
    )

    assert (NAMESPACE, COUNTERPART_NAME) in api_client.objects


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_unnamed_counterpart_body_is_rejected(
    phase_spy: list[dict[str, Any]],
) -> None:
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})
    body = counterpart_body()
    body["metadata"] = {"namespace": NAMESPACE}

    with pytest.raises(RuntimeError, match="named counterpart CR body"):
        await restore_recovery.reapply_with_counterpart_identity(
            api_client,  # type: ignore[arg-type]
            NAMESPACE,
            RESTORED_NAME,
            body,
        )

    assert phase_spy == []


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_phase_failure_propagates_and_does_not_mark_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller (the USER flow) owns the failure translation."""
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    async def _failing(*, crd_spec: dict[str, Any], namespace: str) -> PhaseResult:
        result = PhaseResult()
        result.add_error("boom")
        return result

    monkeypatch.setattr(restore_recovery, "execute_phase_prerequisites", _failing)

    with pytest.raises(RuntimeError, match="Failed to re-apply prerequisites"):
        await restore_recovery.reapply_with_counterpart_identity(
            api_client,  # type: ignore[arg-type]
            NAMESPACE,
            RESTORED_NAME,
            counterpart_body(),
        )

    assert "status" not in api_client.objects[(NAMESPACE, COUNTERPART_NAME)]


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_in_place_reapply_and_finalize_is_unchanged(
    phase_spy: list[dict[str, Any]],
) -> None:
    """Regression: the shared helper must not alter the in-place contract.

    In-place recovery still reads the restored CR, runs both phases against
    *its* spec, and marks that same CR Ready — no CR is created or deleted.
    """
    in_place = restored_crd()
    api_client = FakeApiClient({RESTORED_NAME: in_place})

    await restore_recovery.reapply_and_finalize(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
    )

    assert [spec["deploymentId"] for spec in phase_spy] == ["source-id", "source-id"]
    status = api_client.objects[(NAMESPACE, RESTORED_NAME)]["status"]
    assert status["phase"] == DeploymentPhase.READY.value
    assert status["displayState"] == DisplayState.RUNNING.value
    assert [verb for verb, _ in api_client.calls] == ["get", "patch_status"]
