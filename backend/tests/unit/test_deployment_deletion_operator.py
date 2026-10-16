"""Unit tests for the operator-side deletion observer + janitor (spec 008).

Covers three orthogonal pieces:

1. The ``spec.deletionRequested`` field-update observer — runs the
   teardown and advances the CR to ``phase: Deleting`` /
   ``displayState: Deleting`` without blocking on the namespace
   finaliser.
2. The periodic timer — advances ``Deleting`` to ``Deleted`` once the
   namespace returns 404, and emits a ``Deleted`` condition with a
   ``lastTransitionTime`` the janitor can read.
3. The janitor's selection rule — only reaps CRs whose
   ``status.phase == "Deleted"`` AND whose ``Deleted`` condition is
   older than ``DELETED_CR_TTL_HOURS``; never reaps ``Deleting``-stuck
   CRs.
4. The teardown step that deletes the deployment's service aliases in
   all namespaces (#503).

Kubernetes / kopf interactions are mocked at the helper boundary so the
tests run in-process with no cluster.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import call
from uuid import UUID, uuid4

import kopf
import pytest
from kubernetes_asyncio.client import (
    V1Namespace,
    V1NamespaceStatus,
    V1ObjectMeta,
    V1Service,
    V1ServiceList,
    V1ServiceSpec,
)
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.operator.config import ANNOTATION_SKIP_TEARDOWN
from styrmin_backend.operator.crd.schema import (
    ConditionType,
    DeploymentPhase,
    DisplayState,
)
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module
from styrmin_backend.operator.handlers.styrmin_deployment import (
    _delete_service_aliases,
    _teardown_owned_resources,
    kopf_on_styrmin_deployment_delete,
    kopf_on_styrmin_deployment_deletion_requested,
    kopf_on_styrmin_deployment_update,
    kopf_styrmin_deployment_timer,
)
from styrmin_backend.operator.janitor import is_eligible_for_reap

_PRIMITIVES = "styrmin_backend.agent.service.kubernetes.primitives"


class _Patch:
    """Minimal stand-in for ``kopf.Patch``."""

    def __init__(self) -> None:
        self.status: dict[str, Any] = {}
        self.spec: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}


class _Logger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.exceptions: list[str] = []

    def info(self, msg: str, *args: Any, **__: Any) -> None:
        self.infos.append(msg % args)

    def warning(self, msg: str, *args: Any, **__: Any) -> None:
        self.warnings.append(msg % args)

    def debug(self, *_: Any, **__: Any) -> None: ...
    def error(self, *_: Any, **__: Any) -> None: ...

    def exception(self, msg: str, *args: Any, **__: Any) -> None:
        self.exceptions.append(msg % args)


class _Stopped:
    """Stand-in for kopf's ``stopped`` flag of a timer that kopf does not stop."""

    def __bool__(self) -> bool:
        return False

    async def wait(self, timeout: float) -> None: ...


def _make_body(creation_offset_seconds: int = 0) -> dict[str, Any]:
    created_at = datetime.now(tz=timezone.utc) - timedelta(
        seconds=creation_offset_seconds
    )
    return {"metadata": {"creationTimestamp": created_at.isoformat()}}


# ---------------------------------------------------------------------------
# 1. spec.deletionRequested observer
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deletion_requested_handler_runs_teardown_and_advances_to_deleting(
    mocker,
) -> None:
    """When ``spec.deletionRequested`` flips true, the operator must run
    teardown + request namespace deletion + set phase/displayState to
    ``Deleting`` (not ``Deleted`` — that requires the namespace to be
    actually gone, which is the timer's job)."""

    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    delete_ns_mock = mocker.patch.object(
        handlers_module, "_request_namespace_deletion", autospec=True
    )

    patch = _Patch()
    spec = {"releaseReference": "rel-1", "deletionRequested": True}
    status = {"phase": DeploymentPhase.READY.value}

    await kopf_on_styrmin_deployment_deletion_requested(
        spec=spec,
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
    )

    teardown_mock.assert_called_once()
    delete_ns_mock.assert_called_once()
    assert patch.status["phase"] == DeploymentPhase.DELETING.value
    assert patch.status["displayState"] == DisplayState.DELETING.value


@pytest.mark.anyio
async def test_legacy_update_handler_defers_when_deletion_requested(
    mocker,
) -> None:
    """``spec.deletionRequested=true`` is a spec change too, so the
    field=spec update handler also fires. It MUST defer to the
    deletion-observer handler (skip the re-reconcile) rather than
    re-running the deploy pipeline mid-teardown."""

    prereq_mock = mocker.patch(
        "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_prerequisites",
        autospec=True,
    )
    helmrelease_mock = mocker.patch(
        "styrmin_backend.operator.handlers.styrmin_deployment.execute_phase_helmrelease",
        autospec=True,
    )

    patch = _Patch()
    spec = {
        "releaseReference": "rel-1",
        "deletionRequested": True,
    }

    await kopf_on_styrmin_deployment_update(
        spec=spec,
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        diff=(),
    )

    prereq_mock.assert_not_called()
    helmrelease_mock.assert_not_called()
    # Critically, displayState must NOT be set to Deploying — that would
    # mid-teardown flicker to Deploying in the UI.
    assert patch.status == {}


@pytest.mark.anyio
async def test_deletion_requested_handler_short_circuits_when_already_deleted(
    mocker,
) -> None:
    """If the CR is already in phase: Deleted (defensive — the CEL rule
    prevents un-flipping the spec, but the handler may fire on resume),
    we must not run teardown again or rewind the phase."""

    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    delete_ns_mock = mocker.patch.object(
        handlers_module, "_request_namespace_deletion", autospec=True
    )

    patch = _Patch()
    spec = {"releaseReference": "rel-1", "deletionRequested": True}
    status = {"phase": DeploymentPhase.DELETED.value}

    await kopf_on_styrmin_deployment_deletion_requested(
        spec=spec,
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
    )

    teardown_mock.assert_not_called()
    delete_ns_mock.assert_not_called()
    assert patch.status == {}


@pytest.mark.anyio
async def test_delete_handler_runs_teardown(mocker) -> None:
    """A manual ``kubectl delete`` tears down the resources the CR names."""
    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    patch = _Patch()

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1"},
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace="styrmin-abc",
        annotations={},
        patch=patch,
        memo=kopf.Memo(),
        logger=_Logger(),
    )

    teardown_mock.assert_called_once()
    assert patch.status["phase"] == DeploymentPhase.DELETING.value


@pytest.mark.anyio
@pytest.mark.parametrize("annotations", [{}, {ANNOTATION_SKIP_TEARDOWN: "true"}])
async def test_delete_handler_rerun_leaves_the_patch_empty(
    mocker, annotations: dict[str, str]
) -> None:
    """#446, #461: kopf runs the handler again while a timer run has not ended.

    A patch that only repeats ``phase: Deleting`` changes nothing, so it makes no
    event, and kopf waits for that event and keeps the finalizer. With an empty
    patch, kopf checks the timer run again after its polling delay.
    """
    mocker.patch.object(handlers_module, "_teardown_owned_resources", autospec=True)
    status = {
        "phase": DeploymentPhase.DELETING.value,
        "message": "Cleaning up resources",
    }
    patch = _Patch()

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1"},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        annotations=annotations,
        patch=patch,
        memo=kopf.Memo(),
        logger=_Logger(),
    )

    assert patch.status == {}


@pytest.mark.anyio
async def test_delete_handler_logs_once_when_kopf_runs_it_again(mocker) -> None:
    """#461: the agent log shows when kopf kept the finalizer for a timer run."""
    mocker.patch.object(handlers_module, "_teardown_owned_resources", autospec=True)
    memo = kopf.Memo()
    logger = _Logger()
    expected = "StyrminDeployment styrmin-abc/dep-1 keeps its finalizer until its timer run ends"

    for _ in range(3):
        await kopf_on_styrmin_deployment_delete(
            spec={"releaseReference": "rel-1"},
            status={"phase": DeploymentPhase.DELETING.value},
            name="dep-1",
            namespace="styrmin-abc",
            annotations={},
            patch=_Patch(),
            memo=memo,
            logger=logger,
        )

    assert logger.infos.count(expected) == 1


@pytest.mark.anyio
async def test_delete_handler_skips_teardown_when_annotated(mocker) -> None:
    """A cross-target restore discards its restored copy of the source's CR.

    That copy names the counterpart's own HelmRelease and resources, so tearing
    them down would uninstall the counterpart's release and remove the
    resources the restore is re-applying. kopf can still run this handler for
    it, because kopf puts back the finalizer the restore clears.
    """
    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    patch = _Patch()

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1"},
        status={"phase": DeploymentPhase.RESTORING.value},
        name="dep-1",
        namespace="styrmin-abc",
        annotations={ANNOTATION_SKIP_TEARDOWN: "true"},
        patch=patch,
        memo=kopf.Memo(),
        logger=_Logger(),
    )

    teardown_mock.assert_not_called()
    assert patch.status == {}


# ---------------------------------------------------------------------------
# 1b. Service aliases of the deleted deployment (#503)
# ---------------------------------------------------------------------------


def _alias(
    name: str, namespace: str, target_namespace: str, owner: UUID | None
) -> V1Service:
    """A live alias, built as ``_live_alias`` in ``agent/test_service_aliases.py``."""
    labels = {"styrmin.io/service-alias": "true"}
    if owner is not None:
        labels["styrmin.io/deployment-id"] = str(owner)
    return V1Service(
        metadata=V1ObjectMeta(name=name, namespace=namespace, labels=labels),
        spec=V1ServiceSpec(
            type="ExternalName",
            external_name=f"{name}.{target_namespace}.svc.cluster.local",
        ),
    )


def _patch_alias_primitives(mocker, aliases: list[V1Service]) -> tuple[Any, Any, Any]:
    """Patch the primitives where ``_delete_service_aliases`` imports them."""
    list_mock = mocker.patch(
        f"{_PRIMITIVES}.list_services_in_all_namespaces",
        new_callable=mocker.AsyncMock,
        return_value=V1ServiceList(items=aliases),
    )
    delete_mock = mocker.patch(
        f"{_PRIMITIVES}.delete_service",
        new_callable=mocker.AsyncMock,
        return_value=True,
    )
    get_namespace_mock = mocker.patch(
        f"{_PRIMITIVES}.get_namespace", new_callable=mocker.AsyncMock
    )
    return list_mock, delete_mock, get_namespace_mock


@pytest.mark.anyio
async def test_delete_service_aliases_deletes_only_the_aliases_of_the_deployment(
    mocker,
) -> None:
    """FR-001 to FR-003: labelled aliases by id, unlabelled ones by their target namespace."""
    deployment_id, peer, other_env_deployment, other_env_peer = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    namespace = get_kubernetes_reference(deployment_id)
    peer_namespace = get_kubernetes_reference(peer)
    other_env_namespace = get_kubernetes_reference(other_env_deployment)
    other_env_peer_namespace = get_kubernetes_reference(other_env_peer)
    _, delete_mock, _ = _patch_alias_primitives(
        mocker,
        [
            _alias("intent", peer_namespace, namespace, deployment_id),
            _alias("legacy", peer_namespace, namespace, owner=None),
            _alias("executor", namespace, peer_namespace, peer),
            _alias("old-executor", namespace, peer_namespace, owner=None),
            _alias(
                "intent",
                other_env_peer_namespace,
                other_env_namespace,
                other_env_deployment,
            ),
        ],
    )
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=True,
        logger=logger,
    )

    assert delete_mock.await_args_list == [
        call(name="intent", namespace=peer_namespace),
        call(name="legacy", namespace=peer_namespace),
    ]
    assert f"Deleted 2 service aliases of {deployment_id}" in logger.infos


@pytest.mark.anyio
async def test_delete_service_aliases_does_not_read_the_namespace_when_deletion_requested(
    mocker,
) -> None:
    """With a deletion request the aliases go even while the namespace is being deleted."""
    deployment_id = uuid4()
    _, _, get_namespace_mock = _patch_alias_primitives(mocker, [])

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=get_kubernetes_reference(deployment_id),
        deletion_requested=True,
        logger=_Logger(),
    )

    get_namespace_mock.assert_not_called()


@pytest.mark.anyio
async def test_delete_service_aliases_lists_services_by_the_alias_label(
    mocker,
) -> None:
    deployment_id = uuid4()
    list_mock, _, _ = _patch_alias_primitives(mocker, [])

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=get_kubernetes_reference(deployment_id),
        deletion_requested=True,
        logger=_Logger(),
    )

    list_mock.assert_awaited_once_with(label_selector="styrmin.io/service-alias=true")


class _FakeKubernetesClient:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None: ...


def _patch_teardown_kubernetes(mocker) -> tuple[Any, Any]:
    """Patch steps 2 to 4 of the teardown; return the listing mock and the CustomObjectsApi."""
    list_mock = mocker.patch(
        "styrmin_backend.operator.reconciler.list_managed_resources",
        new_callable=mocker.AsyncMock,
        return_value=[],
    )
    mocker.patch(
        "styrmin_backend.operator.reconciler.delete_kubernetes_resource",
        new_callable=mocker.AsyncMock,
    )
    mocker.patch(
        "styrmin_backend.operator.kubernetes.get_kubernetes_client",
        return_value=_FakeKubernetesClient(),
    )
    custom_api = mocker.MagicMock()
    custom_api.delete_namespaced_custom_object = mocker.AsyncMock()
    mocker.patch("kubernetes_asyncio.client.CustomObjectsApi", return_value=custom_api)
    return list_mock, custom_api


@pytest.mark.anyio
async def test_teardown_deletes_service_aliases_before_the_deployment_services(
    mocker,
) -> None:
    """Step 1 of the teardown runs before the deployment's own Services are listed."""
    deployment_id = str(uuid4())
    namespace = get_kubernetes_reference(UUID(deployment_id))
    logger = _Logger()
    parent = mocker.Mock()
    aliases_mock = mocker.patch.object(
        handlers_module, "_delete_service_aliases", autospec=True
    )
    list_mock, custom_api = _patch_teardown_kubernetes(mocker)
    parent.attach_mock(aliases_mock, "delete_service_aliases")
    parent.attach_mock(list_mock, "list_managed_resources")

    await _teardown_owned_resources(
        namespace=namespace,
        release_reference="rel-1",
        deployment_id=deployment_id,
        deletion_requested=True,
        name="dep-1",
        logger=logger,
    )

    assert parent.mock_calls[:2] == [
        call.delete_service_aliases(
            deployment_id=deployment_id,
            namespace=namespace,
            deletion_requested=True,
            logger=logger,
        ),
        call.list_managed_resources(
            namespace=namespace, release_reference="rel-1", kind="Service"
        ),
    ]
    assert (
        f"Teardown step 1: service aliases of {deployment_id} in all namespaces"
        in logger.infos
    )
    custom_api.delete_namespaced_custom_object.assert_awaited_once()


@pytest.mark.anyio
async def test_deletion_requested_handler_tears_down_aliases_before_namespace_deletion(
    mocker,
) -> None:
    """The handler passes the CR's deployment id, and the teardown runs before the
    namespace deletion request."""
    deployment_id = str(uuid4())
    namespace = get_kubernetes_reference(UUID(deployment_id))
    logger = _Logger()
    parent = mocker.Mock()
    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )
    delete_ns_mock = mocker.patch.object(
        handlers_module, "_request_namespace_deletion", autospec=True
    )
    parent.attach_mock(teardown_mock, "teardown")
    parent.attach_mock(delete_ns_mock, "request_namespace_deletion")

    await kopf_on_styrmin_deployment_deletion_requested(
        spec={
            "releaseReference": "rel-1",
            "deletionRequested": True,
            "deploymentId": deployment_id,
        },
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace=namespace,
        patch=_Patch(),
        logger=logger,
    )

    assert parent.mock_calls == [
        call.teardown(
            namespace=namespace,
            release_reference="rel-1",
            deployment_id=deployment_id,
            deletion_requested=True,
            name="dep-1",
            logger=logger,
        ),
        call.request_namespace_deletion(namespace=namespace, logger=logger),
    ]


@pytest.mark.anyio
async def test_delete_handler_passes_no_deletion_request_to_the_teardown(
    mocker,
) -> None:
    """``kubectl delete styrmindeployment``: the CR has no deletion request."""
    deployment_id = str(uuid4())
    namespace = get_kubernetes_reference(UUID(deployment_id))
    teardown_mock = mocker.patch.object(
        handlers_module, "_teardown_owned_resources", autospec=True
    )

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1", "deploymentId": deployment_id},
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace=namespace,
        annotations={},
        patch=_Patch(),
        memo=kopf.Memo(),
        logger=_Logger(),
    )

    teardown_mock.assert_awaited_once()
    assert teardown_mock.await_args.kwargs["deployment_id"] == deployment_id
    assert teardown_mock.await_args.kwargs["deletion_requested"] is False


# ---------------------------------------------------------------------------
# 1c. Failed alias deletions, and the guards that keep aliases (#503)
# ---------------------------------------------------------------------------


def _aliases_of(deployment_id: UUID) -> tuple[str, str, list[V1Service]]:
    """Return the deployment's namespace, a peer's namespace, and two aliases held there."""
    namespace = get_kubernetes_reference(deployment_id)
    peer_namespace = get_kubernetes_reference(uuid4())
    aliases = [
        _alias("first", peer_namespace, namespace, deployment_id),
        _alias("second", peer_namespace, namespace, deployment_id),
    ]
    return namespace, peer_namespace, aliases


@pytest.mark.anyio
async def test_delete_service_aliases_counts_an_alias_already_gone(mocker) -> None:
    """FR-004, US3 scenario 1: a 404 (``False``) counts as deleted; the next alias goes."""
    deployment_id = uuid4()
    namespace, peer_namespace, aliases = _aliases_of(deployment_id)
    _, delete_mock, _ = _patch_alias_primitives(mocker, aliases)
    delete_mock.side_effect = [False, True]
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=True,
        logger=logger,
    )

    assert delete_mock.await_args_list == [
        call(name="first", namespace=peer_namespace),
        call(name="second", namespace=peer_namespace),
    ]
    assert f"Deleted 2 service aliases of {deployment_id}" in logger.infos
    assert logger.exceptions == []


@pytest.mark.anyio
async def test_delete_service_aliases_logs_a_failed_delete_and_deletes_the_next(
    mocker,
) -> None:
    """FR-004, SC-003: the log names the alias's namespace and name; the loop continues."""
    deployment_id = uuid4()
    namespace, peer_namespace, aliases = _aliases_of(deployment_id)
    _, delete_mock, _ = _patch_alias_primitives(mocker, aliases)
    delete_mock.side_effect = [ApiException(status=500), True]
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=True,
        logger=logger,
    )

    assert delete_mock.await_args_list == [
        call(name="first", namespace=peer_namespace),
        call(name="second", namespace=peer_namespace),
    ]
    assert logger.exceptions == [
        f"Failed to delete service alias {peer_namespace}/first"
    ]
    assert f"Deleted 1 service aliases of {deployment_id}" in logger.infos


@pytest.mark.anyio
async def test_delete_service_aliases_logs_a_failed_listing_and_returns(mocker) -> None:
    """FR-004, US3 scenario 3: a listing error is logged, not raised."""
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    list_mock, delete_mock, _ = _patch_alias_primitives(mocker, [])
    list_mock.side_effect = ApiException(status=500)
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=True,
        logger=logger,
    )

    delete_mock.assert_not_called()
    assert logger.exceptions == [
        f"Failed to list the service aliases of {deployment_id}"
    ]


@pytest.mark.anyio
async def test_deletion_requested_handler_finishes_the_teardown_when_listing_aliases_fails(
    mocker,
) -> None:
    """FR-004: the HelmRelease is still deleted and the namespace deletion still requested."""
    deployment_id = str(uuid4())
    namespace = get_kubernetes_reference(UUID(deployment_id))
    list_aliases_mock, _, _ = _patch_alias_primitives(mocker, [])
    list_aliases_mock.side_effect = ApiException(status=500)
    _, custom_api = _patch_teardown_kubernetes(mocker)
    delete_ns_mock = mocker.patch.object(
        handlers_module, "_request_namespace_deletion", autospec=True
    )
    logger = _Logger()

    await kopf_on_styrmin_deployment_deletion_requested(
        spec={
            "releaseReference": "rel-1",
            "deletionRequested": True,
            "deploymentId": deployment_id,
        },
        status={"phase": DeploymentPhase.READY.value},
        name="dep-1",
        namespace=namespace,
        patch=_Patch(),
        logger=logger,
    )

    list_aliases_mock.assert_awaited_once()
    assert logger.exceptions == [
        f"Failed to list the service aliases of {deployment_id}"
    ]
    custom_api.delete_namespaced_custom_object.assert_awaited_once_with(
        group="helm.toolkit.fluxcd.io",
        version="v2",
        namespace=namespace,
        plural="helmreleases",
        name="rel-1",
    )
    delete_ns_mock.assert_awaited_once_with(namespace=namespace, logger=logger)


@pytest.mark.anyio
async def test_delete_handler_with_skip_teardown_makes_no_alias_call(mocker) -> None:
    """FR-006, US3 scenario 4: the restored copy of a source's CR keeps every alias."""
    deployment_id = uuid4()
    namespace, _, aliases = _aliases_of(deployment_id)
    list_mock, delete_mock, get_namespace_mock = _patch_alias_primitives(
        mocker, aliases
    )
    _patch_teardown_kubernetes(mocker)

    await kopf_on_styrmin_deployment_delete(
        spec={"releaseReference": "rel-1", "deploymentId": str(deployment_id)},
        status={"phase": DeploymentPhase.RESTORING.value},
        name="dep-1",
        namespace=namespace,
        annotations={ANNOTATION_SKIP_TEARDOWN: "true"},
        patch=_Patch(),
        memo=kopf.Memo(),
        logger=_Logger(),
    )

    get_namespace_mock.assert_not_called()
    list_mock.assert_not_called()
    delete_mock.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "namespace_object",
    [V1Namespace(status=V1NamespaceStatus(phase="Terminating")), None],
    ids=["terminating", "gone"],
)
async def test_delete_service_aliases_keeps_aliases_when_the_namespace_goes_without_a_request(
    mocker, namespace_object: V1Namespace | None
) -> None:
    """FR-017, SC-006: a restore deletes the namespace, and with it the CR, without a
    deletion request; the restored deployment keeps running, so its aliases stay."""
    deployment_id = uuid4()
    namespace, _, aliases = _aliases_of(deployment_id)
    list_mock, delete_mock, get_namespace_mock = _patch_alias_primitives(
        mocker, aliases
    )
    get_namespace_mock.return_value = namespace_object
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=False,
        logger=logger,
    )

    get_namespace_mock.assert_awaited_once_with(name=namespace)
    list_mock.assert_not_called()
    delete_mock.assert_not_called()
    assert (
        f"Namespace {namespace} is being deleted without a deletion request; "
        "keeping its service aliases"
    ) in logger.infos


@pytest.mark.anyio
async def test_delete_service_aliases_keeps_aliases_when_the_namespace_cannot_be_read(
    mocker,
) -> None:
    """FR-017: without a deletion request, an unreadable namespace keeps the aliases."""
    deployment_id = uuid4()
    namespace, _, aliases = _aliases_of(deployment_id)
    list_mock, delete_mock, get_namespace_mock = _patch_alias_primitives(
        mocker, aliases
    )
    get_namespace_mock.side_effect = ApiException(status=500)
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=False,
        logger=logger,
    )

    list_mock.assert_not_called()
    delete_mock.assert_not_called()
    assert logger.exceptions == [
        f"Failed to read namespace {namespace}; keeping its service aliases"
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("deletion_requested", "phase"),
    [(False, "Active"), (True, "Terminating")],
    ids=["kubectl-delete-active-namespace", "deletion-requested-terminating-namespace"],
)
async def test_delete_service_aliases_deletes_the_aliases(
    mocker, deletion_requested: bool, phase: str
) -> None:
    """FR-005: ``kubectl delete styrmindeployment`` leaves the namespace ``Active``; with
    a deletion request the namespace phase does not matter."""
    deployment_id = uuid4()
    namespace, peer_namespace, aliases = _aliases_of(deployment_id)
    _, delete_mock, get_namespace_mock = _patch_alias_primitives(mocker, aliases)
    get_namespace_mock.return_value = V1Namespace(status=V1NamespaceStatus(phase=phase))

    await _delete_service_aliases(
        deployment_id=str(deployment_id),
        namespace=namespace,
        deletion_requested=deletion_requested,
        logger=_Logger(),
    )

    assert delete_mock.await_args_list == [
        call(name="first", namespace=peer_namespace),
        call(name="second", namespace=peer_namespace),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("deletion_requested", [True, False])
@pytest.mark.parametrize(
    "has_deployment_id", [True, False], ids=["source-id", "no-deployment-id"]
)
async def test_delete_service_aliases_makes_no_api_call_outside_the_deployment_namespace(
    mocker, deletion_requested: bool, has_deployment_id: bool
) -> None:
    """Research R-001: a restored copy of a source's CR is in the counterpart's
    namespace but carries the source's id, and the source keeps running."""
    source_id = uuid4()
    counterpart_namespace = get_kubernetes_reference(uuid4())
    deployment_id = str(source_id) if has_deployment_id else ""
    _, _, aliases = _aliases_of(source_id)
    list_mock, delete_mock, get_namespace_mock = _patch_alias_primitives(
        mocker, aliases
    )
    logger = _Logger()

    await _delete_service_aliases(
        deployment_id=deployment_id,
        namespace=counterpart_namespace,
        deletion_requested=deletion_requested,
        logger=logger,
    )

    get_namespace_mock.assert_not_called()
    list_mock.assert_not_called()
    delete_mock.assert_not_called()
    assert logger.warnings == [
        f"Namespace {counterpart_namespace} is not the namespace of deployment "
        f"{deployment_id!r}; keeping its service aliases"
    ]


# ---------------------------------------------------------------------------
# 2. Timer advancement to phase: Deleted
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_timer_advances_to_deleted_once_namespace_is_gone(mocker) -> None:
    """The timer must flip the phase to Deleted (with a Deleted
    condition the janitor can read) only after the namespace is gone."""

    mocker.patch.object(
        handlers_module, "_namespace_is_gone", return_value=True, autospec=True
    )

    patch = _Patch()
    body = _make_body(creation_offset_seconds=60)
    status = {
        "phase": DeploymentPhase.DELETING.value,
        "displayState": DisplayState.DELETING.value,
        "conditions": [],
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={"releaseReference": "rel-1", "deletionRequested": True},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )

    assert patch.status["phase"] == DeploymentPhase.DELETED.value
    assert patch.status["displayState"] == DisplayState.DELETED.value

    deleted_conds = [
        c
        for c in patch.status["conditions"]
        if c["type"] == ConditionType.DELETED.value
    ]
    assert len(deleted_conds) == 1
    assert deleted_conds[0]["status"] == "True"
    assert deleted_conds[0]["reason"] == "NamespaceGone"
    assert deleted_conds[0]["lastTransitionTime"]  # non-empty timestamp


@pytest.mark.anyio
async def test_timer_keeps_deleting_when_namespace_still_present(mocker) -> None:
    """If the namespace finaliser hasn't completed yet, the timer must
    leave the CR in ``Deleting`` and try again next tick."""

    mocker.patch.object(
        handlers_module, "_namespace_is_gone", return_value=False, autospec=True
    )

    patch = _Patch()
    body = _make_body(creation_offset_seconds=60)
    status = {
        "phase": DeploymentPhase.DELETING.value,
        "conditions": [],
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={"releaseReference": "rel-1", "deletionRequested": True},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )

    assert "phase" not in patch.status
    assert "displayState" not in patch.status


@pytest.mark.anyio
async def test_timer_noop_for_terminal_deleted_phase(mocker) -> None:
    """A CR already at ``phase: Deleted`` is the janitor's responsibility
    — the timer must not re-emit conditions or otherwise touch it."""

    ns_gone_mock = mocker.patch.object(
        handlers_module, "_namespace_is_gone", return_value=True, autospec=True
    )

    patch = _Patch()
    body = _make_body(creation_offset_seconds=60)
    status = {
        "phase": DeploymentPhase.DELETED.value,
        "conditions": [
            {
                "type": ConditionType.DELETED.value,
                "status": "True",
                "reason": "NamespaceGone",
                "message": "...",
                "lastTransitionTime": datetime.now(tz=timezone.utc).isoformat(),
            }
        ],
    }

    await kopf_styrmin_deployment_timer(
        body=body,
        spec={"releaseReference": "rel-1", "deletionRequested": True},
        status=status,
        name="dep-1",
        namespace="styrmin-abc",
        patch=patch,
        logger=_Logger(),
        stopped=_Stopped(),
    )

    # _advance_to_phase_deleted will be entered (because the gating
    # condition includes deletionRequested), but the early return for
    # phase == DELETED below it ensures nothing is written; alternatively
    # the handler may flip the same state idempotently. Either way, no
    # spurious phase regression.
    assert patch.status.get("phase") in (None, DeploymentPhase.DELETED.value)
    # Sanity: the namespace-gone helper was queried at most once.
    assert ns_gone_mock.call_count <= 1


# ---------------------------------------------------------------------------
# 3. Janitor selection rule
# ---------------------------------------------------------------------------


def _deleted_status(*, transitioned_at: datetime, phase: str = "Deleted") -> dict:
    return {
        "phase": phase,
        "conditions": [
            {
                "type": ConditionType.DELETED.value,
                "status": "True",
                "reason": "NamespaceGone",
                "message": "...",
                "lastTransitionTime": transitioned_at.isoformat(),
            }
        ],
    }


def test_janitor_reaps_when_phase_deleted_and_ttl_elapsed() -> None:
    now = datetime.now(tz=timezone.utc)
    status = _deleted_status(transitioned_at=now - timedelta(hours=7))
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is True


def test_janitor_does_not_reap_when_ttl_not_elapsed() -> None:
    now = datetime.now(tz=timezone.utc)
    status = _deleted_status(transitioned_at=now - timedelta(hours=2))
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is False


def test_janitor_never_reaps_phase_deleting() -> None:
    """CRs stuck in Deleting are never auto-reaped — visibility for
    human investigation is more important than tidiness (spec FR-015)."""

    now = datetime.now(tz=timezone.utc)
    status = _deleted_status(
        transitioned_at=now - timedelta(hours=24),
        phase=DeploymentPhase.DELETING.value,
    )
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is False


def test_janitor_does_not_reap_when_deleted_condition_missing() -> None:
    """Defensive: cannot date the transition, so we leave the CR alone
    rather than reap something we cannot prove is past TTL."""

    now = datetime.now(tz=timezone.utc)
    status = {"phase": DeploymentPhase.DELETED.value, "conditions": []}
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is False


def test_janitor_handles_z_suffix_iso_timestamp() -> None:
    """Kubernetes serialises timestamps with a ``Z`` suffix; verify
    parsing handles both forms."""

    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    status = {
        "phase": DeploymentPhase.DELETED.value,
        "conditions": [
            {
                "type": ConditionType.DELETED.value,
                "status": "True",
                "lastTransitionTime": (now - timedelta(hours=12))
                .isoformat()
                .replace("+00:00", "Z"),
            }
        ],
    }
    assert is_eligible_for_reap(status, now=now, ttl_hours=6) is True
