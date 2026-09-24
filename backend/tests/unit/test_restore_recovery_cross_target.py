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

import base64
import gzip
import json
from types import SimpleNamespace
from typing import Any

import pytest

from styrmin_backend.operator import restore_recovery
from styrmin_backend.operator.config import CRD_PLURAL
from styrmin_backend.operator.crd.schema import DeploymentPhase, DisplayState
from styrmin_backend.operator.pipeline import PhaseResult

from tests.unit.counterpart_crd_fixtures import (
    COUNTERPART_DEPLOYMENT_ID,
    COUNTERPART_NAMESPACE,
    SOURCE_DEPLOYMENT_ID,
    SOURCE_RELEASE_REFERENCE,
    build_counterpart_body,
)


KOPF_ANNOTATION = "kopf.zalando.org/last-handled-configuration"


def _merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> None:
    """Apply an RFC 7386 merge patch in place (one real behaviour that matters).

    A shallow ``dict.update`` would let ``{"metadata": {"finalizers": []}}``
    wipe the object's name and namespace, which is exactly the kind of thing the
    finalizer-clearing test must not accidentally rely on.
    """
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_patch(target[key], value)
        else:
            target[key] = value


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
        # Secrets keyed by (namespace, name), as the API returns them.
        self.secrets: dict[tuple[str, str], SimpleNamespace] = {}
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
        _merge_patch(existing, body)
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


class FakeCoreV1Api:
    """The two Secret calls Helm-storage retargeting makes."""

    def __init__(self, api_client: FakeApiClient) -> None:
        self._client = api_client

    async def list_namespaced_secret(
        self, *, namespace: str, label_selector: str
    ) -> SimpleNamespace:
        key, _, value = label_selector.partition("=")
        items = [
            secret
            for (ns, _name), secret in self._client.secrets.items()
            if ns == namespace and secret.metadata.labels.get(key) == value
        ]
        return SimpleNamespace(items=items)

    async def patch_namespaced_secret(
        self, *, name: str, namespace: str, body: dict[str, Any]
    ) -> None:
        self._client.calls.append(("patch_secret", name))
        self._client.secrets[(namespace, name)].data.update(body["data"])


class FakeK8sClientModule:
    """Namespace object replacing ``restore_recovery.k8s_client``."""

    CustomObjectsApi = FakeCustomObjectsApi
    CoreV1Api = FakeCoreV1Api
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
    monkeypatch.setattr(restore_recovery, "execute_phase_helmrelease", _phase)
    monkeypatch.setattr(restore_recovery, "execute_phase_services", _phase)
    return seen


@pytest.fixture
def phase_order(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which pipeline phases ran, in order."""
    order: list[str] = []

    def _spy(label: str):
        async def _phase(*, crd_spec: dict[str, Any], namespace: str) -> PhaseResult:
            order.append(label)
            return PhaseResult(success=True)

        return _phase

    monkeypatch.setattr(
        restore_recovery, "execute_phase_prerequisites", _spy("prerequisites")
    )
    monkeypatch.setattr(
        restore_recovery, "execute_phase_helmrelease", _spy("helmrelease")
    )
    monkeypatch.setattr(restore_recovery, "execute_phase_services", _spy("services"))
    return order


#: Both names are derived from the shared counterpart fixture rather than spelled
#: out here, so the body this module feeds the consumer and the body the producer
#: renders can never disagree.
NAMESPACE = COUNTERPART_NAMESPACE
RESTORED_NAME = SOURCE_RELEASE_REFERENCE
COUNTERPART_NAME = COUNTERPART_NAMESPACE
SOURCE_ID = str(SOURCE_DEPLOYMENT_ID)
COUNTERPART_ID = str(COUNTERPART_DEPLOYMENT_ID)
KOPF_STATE = json.dumps({"spec": {"deploymentId": SOURCE_ID}})


def restored_crd() -> dict[str, Any]:
    """The source-named CR Velero recreated inside the counterpart namespace."""
    return {
        "apiVersion": "styrmin.io/v1alpha1",
        "kind": "StyrminDeployment",
        "metadata": {
            "name": RESTORED_NAME,
            "namespace": NAMESPACE,
            # Velero restores finalizers along with the rest of the metadata,
            # so the restored CR arrives still holding kopf's.
            "finalizers": ["kopf.zalando.org/KopfFinalizerMarker"],
            "annotations": {
                KOPF_ANNOTATION: KOPF_STATE,
                "unrelated.io/keep": "yes",
            },
        },
        "spec": {
            "deploymentId": SOURCE_ID,
            "releaseReference": RESTORED_NAME,
        },
    }


async def counterpart_body() -> dict[str, Any]:
    """The counterpart's own CR body, as ``_build_counterpart_crd_body`` renders it.

    Literally as it renders it: this calls the real producer through
    :func:`build_counterpart_body` instead of hand-writing a look-alike. A
    hand-written fixture is how the producer's most important decision — the CR
    is named after the **namespace**, the Helm release name goes to
    ``spec.releaseReference`` only (010 research D2) — stayed asserted on both
    sides of a contract that nothing actually joined, so a revert on the
    producer would have failed only the 20-minute E2E.

    Note the deliberate split the body carries: the CR is named after the
    counterpart's namespace, while ``releaseReference`` is the **source's** —
    the counterpart adopts the restored Helm release rather than installing a
    second one over objects Helm already owns.
    """
    body = await build_counterpart_body()
    assert body["metadata"]["name"] == COUNTERPART_NAME, (
        "the producer no longer names the counterpart CR after its namespace; "
        f"got {body['metadata']['name']!r}"
    )
    assert body["spec"]["releaseReference"] == RESTORED_NAME, (
        "the producer no longer has the counterpart adopt the source's Helm "
        f"release name; got {body['spec']['releaseReference']!r}"
    )
    return body


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
        await counterpart_body(),
    )

    # The counterpart CR now owns the namespace ...
    assert (NAMESPACE, COUNTERPART_NAME) in api_client.objects
    applied = api_client.objects[(NAMESPACE, COUNTERPART_NAME)]
    assert applied["spec"]["deploymentId"] == COUNTERPART_ID
    # The adopted Helm release keeps the source's name — that is the point.
    assert applied["spec"]["releaseReference"] == RESTORED_NAME
    # ... and the restored source-named CR is gone.
    assert (NAMESPACE, RESTORED_NAME) not in api_client.objects

    # All three pipeline phases ran against the counterpart's spec, never the
    # restored source spec.
    assert len(phase_spy) == 3
    assert all(spec["deploymentId"] == COUNTERPART_ID for spec in phase_spy)

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
        await counterpart_body(),
    )

    annotations = api_client.objects[(NAMESPACE, COUNTERPART_NAME)]["metadata"][
        "annotations"
    ]
    assert annotations[KOPF_ANNOTATION] == KOPF_STATE
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
        await counterpart_body(),
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
    stale_counterpart = await counterpart_body()
    stale_counterpart["spec"] = {"deploymentId": COUNTERPART_ID, "stale": True}
    api_client = FakeApiClient(
        {RESTORED_NAME: restored_crd(), COUNTERPART_NAME: stale_counterpart}
    )

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        await counterpart_body(),
    )

    applied = api_client.objects[(NAMESPACE, COUNTERPART_NAME)]
    # A merge patch overwrites the fields the counterpart body carries; a
    # leftover key it does not mention survives here and is pruned server-side
    # by the CRD's structural schema in a real cluster.
    assert applied["spec"]["deploymentId"] == COUNTERPART_ID
    assert applied["spec"]["releaseReference"] == RESTORED_NAME
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
        await counterpart_body(),
    )

    assert (NAMESPACE, COUNTERPART_NAME) in api_client.objects


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_unnamed_counterpart_body_is_rejected(
    phase_spy: list[dict[str, Any]],
) -> None:
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})
    body = await counterpart_body()
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
            await counterpart_body(),
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

    assert [spec["deploymentId"] for spec in phase_spy] == [SOURCE_ID, SOURCE_ID]
    status = api_client.objects[(NAMESPACE, RESTORED_NAME)]["status"]
    assert status["phase"] == DeploymentPhase.READY.value
    assert status["displayState"] == DisplayState.RUNNING.value
    assert [verb for verb, _ in api_client.calls] == ["get", "patch_status"]


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_cross_target_reruns_the_helmrelease_phase_in_pipeline_order(
    phase_order: list[str],
) -> None:
    """The counterpart's HelmRelease is re-rendered, between the other phases.

    The restored HelmRelease was rendered from the *source's* context (source
    FQDNs, source ingress hosts). Skipping phase 2 would leave the cloned
    namespace serving the source's identity forever (010 research D2.4), and
    running it out of order would upsert a HelmRelease before its Secrets and
    NetworkPolicies exist.
    """
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        await counterpart_body(),
    )

    assert phase_order == ["prerequisites", "helmrelease", "services"]


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_in_place_recovery_does_not_touch_the_helmrelease(
    phase_order: list[str],
) -> None:
    """The in-place contract is unchanged: no phase 2, as before."""
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    await restore_recovery.reapply_and_finalize(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
    )

    assert phase_order == ["prerequisites", "services"]


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_restored_crd_finalizers_are_cleared_before_it_is_deleted(
    phase_spy: list[dict[str, Any]],
) -> None:
    """Deleting the restored CR with kopf's finalizer would destroy the data.

    kopf's ``on.delete`` handler for a ``StyrminDeployment`` runs
    ``_teardown_owned_resources``, which deletes the HelmRelease named by
    ``spec.releaseReference`` — for a cross-target restore that is the release
    keeping the counterpart's chart (and its just-restored volumes) alive. The
    finalizer must be gone before the delete so the handler never runs.
    """
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        await counterpart_body(),
    )

    restored_patches = [
        index
        for index, (verb, name) in enumerate(api_client.calls)
        if verb == "patch" and name == RESTORED_NAME
    ]
    delete_index = api_client.calls.index(("delete", RESTORED_NAME))
    assert restored_patches, "the restored CR's finalizers were never cleared"
    assert max(restored_patches) < delete_index
    assert (NAMESPACE, RESTORED_NAME) not in api_client.objects


@pytest.mark.anyio
async def test_restored_crd_is_not_deleted_while_finalizers_remain(
    monkeypatch: pytest.MonkeyPatch,
    phase_spy: list[dict[str, Any]],
) -> None:
    """A finalizer that survives the clear aborts the recovery instead of deleting.

    Failing the restore is recoverable (discard the cloned environment and
    re-clone); letting kopf's teardown run is not.
    """
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})

    class StubbornApi(FakeCustomObjectsApi):
        async def patch_namespaced_custom_object(self, **kwargs: Any) -> dict[str, Any]:
            # Accept the patch, then put the finalizer straight back — the
            # observable shape of another controller re-adding it.
            result = await super().patch_namespaced_custom_object(**kwargs)
            if kwargs["name"] == RESTORED_NAME:
                result["metadata"]["finalizers"] = [
                    "kopf.zalando.org/KopfFinalizerMarker"
                ]
            return result

    class Module(FakeK8sClientModule):
        CustomObjectsApi = StubbornApi

    monkeypatch.setattr(restore_recovery, "k8s_client", Module)

    with pytest.raises(RuntimeError, match="Refusing to delete"):
        await restore_recovery.reapply_with_counterpart_identity(
            api_client,  # type: ignore[arg-type]
            NAMESPACE,
            RESTORED_NAME,
            await counterpart_body(),
        )

    assert ("delete", RESTORED_NAME) not in api_client.calls
    assert (NAMESPACE, RESTORED_NAME) in api_client.objects


SOURCE_NAMESPACE = RESTORED_NAME
HELM_SECRET_NAME = f"sh.helm.release.v1.{RESTORED_NAME}.v3"

#: A Bitnami-style object pinned to the source namespace next to one that is not.
SOURCE_MANIFEST = f"""---
# Source: simple-app/charts/postgresql/templates/primary/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: styrmin-postgresql
  namespace: "{SOURCE_NAMESPACE}"
---
# Source: simple-app/templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: styrmin-simple-app
"""


def _helm_payload(release: dict[str, Any]) -> str:
    """Encode a release the way Helm's Secret driver stores it, as the API returns it."""
    helm_encoded = base64.b64encode(gzip.compress(json.dumps(release).encode()))
    return base64.b64encode(helm_encoded).decode()


def _helm_release(data: str) -> dict[str, Any]:
    return json.loads(gzip.decompress(base64.b64decode(base64.b64decode(data))))


def _seed_secret(
    api_client: FakeApiClient,
    name: str,
    *,
    secret_type: str = "helm.sh/release.v1",
    release: dict[str, Any] | None = None,
) -> None:
    release = release or {
        "name": RESTORED_NAME,
        "namespace": SOURCE_NAMESPACE,
        "version": 3,
        "manifest": SOURCE_MANIFEST,
        "hooks": [{"name": "hook", "manifest": f"namespace: {SOURCE_NAMESPACE}"}],
    }
    api_client.secrets[(NAMESPACE, name)] = SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels={"owner": "helm"}),
        type=secret_type,
        data={"release": _helm_payload(release)},
    )


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_restored_helm_release_is_retargeted_before_the_helmrelease_phase(
    monkeypatch: pytest.MonkeyPatch,
    phase_spy: list[dict[str, Any]],
) -> None:
    """An upgrade from the source's manifest would delete the source's pinned objects.

    The StatefulSet above carries an explicit source namespace, so Helm would
    see it as dropped from the chart and delete it *in the source namespace* —
    which is how a clone used to take its source's database down.
    """
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})
    _seed_secret(api_client, HELM_SECRET_NAME)
    seen_at_helmrelease: list[dict[str, Any]] = []

    async def _helmrelease(*, crd_spec: dict[str, Any], namespace: str) -> PhaseResult:
        secret = api_client.secrets[(NAMESPACE, HELM_SECRET_NAME)]
        seen_at_helmrelease.append(_helm_release(secret.data["release"]))
        return PhaseResult(success=True)

    monkeypatch.setattr(restore_recovery, "execute_phase_helmrelease", _helmrelease)

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        await counterpart_body(),
    )

    assert len(seen_at_helmrelease) == 1, "the HelmRelease phase must run once"
    release = seen_at_helmrelease[0]
    assert release["namespace"] == NAMESPACE
    assert SOURCE_NAMESPACE not in release["manifest"]
    assert f'namespace: "{NAMESPACE}"' in release["manifest"]
    assert release["hooks"][0]["manifest"] == f"namespace: {NAMESPACE}"
    # Everything Helm keys the release on is left alone.
    assert (release["name"], release["version"]) == (RESTORED_NAME, 3)


@pytest.mark.anyio
@pytest.mark.usefixtures("fake_k8s")
async def test_only_helm_release_secrets_are_rewritten(
    phase_spy: list[dict[str, Any]],
) -> None:
    api_client = FakeApiClient({RESTORED_NAME: restored_crd()})
    _seed_secret(api_client, HELM_SECRET_NAME)
    _seed_secret(api_client, "not-helm-storage", secret_type="Opaque")

    await restore_recovery.reapply_with_counterpart_identity(
        api_client,  # type: ignore[arg-type]
        NAMESPACE,
        RESTORED_NAME,
        await counterpart_body(),
    )

    patched = [name for verb, name in api_client.calls if verb == "patch_secret"]
    assert patched == [HELM_SECRET_NAME]
