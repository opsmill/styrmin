"""The operator lists, deletes and reconciles the ``Ingress`` kind (#598, T010).

Written before the implementation (Constitution V). Source: ``specs/033-service-ingress-override/``
``research.md`` D-002 and FR-001: the Ingress that Styrmin builds for an external service is created,
updated and deleted with the deployment's other utility resources, and the operator restores it after
drift and deletes it when it is no longer desired.

Before this change ``list_managed_resources`` lists only NetworkPolicy, Service and Secret,
``delete_kubernetes_resource`` has no ``Ingress`` branch (an ``Ingress`` falls into the custom-object
branch with the plural ``ingresss``), and the reconcile loops iterate over other kinds.

``compute_diff`` works on any kind, so its tests describe behaviour that must stay true.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from kubernetes_asyncio import client as kubeclient
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.operator import reconciler as reconciler_module
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_ID,
    LABEL_RELEASE_REFERENCE,
)
from styrmin_backend.operator.crd.schema import DeploymentPhase
from styrmin_backend.operator.handlers import helmrelease as helmrelease_module
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module
from styrmin_backend.operator.reconciler import (
    ReconcileResult,
    compute_diff,
    delete_kubernetes_resource,
    list_managed_resources,
)

NAMESPACE = "styrmin-deadbeef"
RELEASE_REF = "styrmin-deadbeef"


def _ingress(
    name: str = "styrmin-svc-web", host: str = "web-test.example.com"
) -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": {
                "app.kubernetes.io/managed-by": "styrmin",
                "styrmin.io/release-reference": RELEASE_REF,
                "styrmin.io/service-name": name.removeprefix("styrmin-svc-"),
            },
        },
        "spec": {
            "ingressClassName": "traefik",
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {"name": "web", "port": {"number": 8080}}
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


class _Logger:
    def info(self, *_: Any, **__: Any) -> None: ...
    def warning(self, *_: Any, **__: Any) -> None: ...
    def debug(self, *_: Any, **__: Any) -> None: ...
    def error(self, *_: Any, **__: Any) -> None: ...
    def exception(self, *_: Any, **__: Any) -> None: ...


@pytest.fixture
def fake_client(mocker: Any) -> Any:
    """Replace the Kubernetes client of the operator with a stand-in that needs no cluster."""
    client = mocker.MagicMock()
    client.sanitize_for_serialization.side_effect = lambda item: dict(item)

    @asynccontextmanager
    async def _client() -> Any:
        yield client

    mocker.patch("styrmin_backend.operator.kubernetes.get_kubernetes_client", _client)
    return client


def _api(mocker: Any, api_class: type, patched_name: str, **async_methods: Any) -> Any:
    """A stand-in for one Kubernetes API class: only the named methods exist, and they are awaitable.

    ``spec`` makes a misspelled or missing method raise ``AttributeError`` instead of passing.
    """
    api = mocker.MagicMock(spec=api_class)
    # A bound method as the spec: the signature of an unbound one has ``self``, so
    # ``assert_awaited_once_with(name=..., namespace=...)`` could never match.
    signature_source = api_class(api_client=mocker.MagicMock())
    for method, result in async_methods.items():
        setattr(
            api,
            method,
            mocker.AsyncMock(
                spec=getattr(signature_source, method), return_value=result
            ),
        )
    mocker.patch.object(reconciler_module.kubeclient, patched_name, return_value=api)
    return api


@pytest.fixture
def networking_api(mocker: Any, fake_client: Any) -> Any:
    """``NetworkingV1Api`` with no resources of any kind."""
    empty = SimpleNamespace(items=[])
    return _api(
        mocker,
        kubeclient.NetworkingV1Api,
        "NetworkingV1Api",
        list_namespaced_network_policy=empty,
        list_namespaced_ingress=empty,
        delete_namespaced_ingress=None,
    )


@pytest.fixture
def core_api(mocker: Any, fake_client: Any) -> Any:
    empty = SimpleNamespace(items=[])
    return _api(
        mocker,
        kubeclient.CoreV1Api,
        "CoreV1Api",
        list_namespaced_service=empty,
        list_namespaced_secret=empty,
    )


@pytest.fixture
def custom_api(mocker: Any, fake_client: Any) -> Any:
    return _api(
        mocker,
        kubeclient.CustomObjectsApi,
        "CustomObjectsApi",
        delete_namespaced_custom_object=None,
    )


class TestListManagedResources:
    @pytest.mark.anyio
    async def test_returns_the_ingresses_of_the_deployment(
        self, networking_api: Any, core_api: Any
    ) -> None:
        networking_api.list_namespaced_ingress.return_value = SimpleNamespace(
            items=[_ingress("styrmin-svc-web"), _ingress("styrmin-svc-api")]
        )

        resources = await list_managed_resources(
            namespace=NAMESPACE, release_reference=RELEASE_REF, kind="Ingress"
        )

        assert sorted(r["metadata"]["name"] for r in resources) == [
            "styrmin-svc-api",
            "styrmin-svc-web",
        ]
        assert {r["kind"] for r in resources} == {"Ingress"}
        selector = networking_api.list_namespaced_ingress.call_args.kwargs[
            "label_selector"
        ]
        assert "app.kubernetes.io/managed-by=styrmin" in selector
        assert f"styrmin.io/release-reference={RELEASE_REF}" in selector
        assert networking_api.list_namespaced_ingress.call_args.kwargs["namespace"] == (
            NAMESPACE
        )

    @pytest.mark.anyio
    async def test_adds_the_kind_and_api_version_the_cluster_omits(
        self, networking_api: Any, core_api: Any
    ) -> None:
        item = _ingress()
        del item["kind"]
        del item["apiVersion"]
        networking_api.list_namespaced_ingress.return_value = SimpleNamespace(
            items=[item]
        )

        (resource,) = await list_managed_resources(
            namespace=NAMESPACE, release_reference=RELEASE_REF, kind="Ingress"
        )

        assert resource["kind"] == "Ingress"
        assert resource["apiVersion"] == "networking.k8s.io/v1"

    @pytest.mark.anyio
    async def test_a_listing_of_all_kinds_includes_the_ingresses(
        self, networking_api: Any, core_api: Any
    ) -> None:
        networking_api.list_namespaced_ingress.return_value = SimpleNamespace(
            items=[_ingress()]
        )

        resources = await list_managed_resources(
            namespace=NAMESPACE, release_reference=RELEASE_REF
        )

        assert [r["kind"] for r in resources] == ["Ingress"]

    @pytest.mark.anyio
    async def test_a_listing_of_another_kind_does_not_list_ingresses(
        self, networking_api: Any, core_api: Any
    ) -> None:
        await list_managed_resources(
            namespace=NAMESPACE, release_reference=RELEASE_REF, kind="Service"
        )

        core_api.list_namespaced_service.assert_awaited_once()
        networking_api.list_namespaced_ingress.assert_not_called()


class TestDeleteKubernetesResource:
    @pytest.mark.anyio
    async def test_deletes_an_ingress_through_the_networking_api(
        self, networking_api: Any, custom_api: Any
    ) -> None:
        await delete_kubernetes_resource(
            resource=_ingress("styrmin-svc-web"), namespace=NAMESPACE
        )

        networking_api.delete_namespaced_ingress.assert_awaited_once_with(
            name="styrmin-svc-web", namespace=NAMESPACE
        )
        custom_api.delete_namespaced_custom_object.assert_not_called()

    @pytest.mark.anyio
    async def test_ignores_a_404(self, networking_api: Any, custom_api: Any) -> None:
        networking_api.delete_namespaced_ingress.side_effect = ApiException(status=404)

        await delete_kubernetes_resource(resource=_ingress(), namespace=NAMESPACE)

        networking_api.delete_namespaced_ingress.assert_awaited_once()

    @pytest.mark.anyio
    async def test_raises_any_other_error(
        self, networking_api: Any, custom_api: Any
    ) -> None:
        networking_api.delete_namespaced_ingress.side_effect = ApiException(status=500)

        with pytest.raises(ApiException):
            await delete_kubernetes_resource(resource=_ingress(), namespace=NAMESPACE)


class TestComputeDiffForIngresses:
    def test_creates_an_ingress_that_is_desired_and_missing(self) -> None:
        desired = [_ingress("styrmin-svc-web")]

        to_create, to_update, to_delete = compute_diff(desired, [])

        assert to_create == desired
        assert to_update == []
        assert to_delete == []

    def test_updates_an_ingress_whose_spec_differs(self) -> None:
        desired = [_ingress(host="web-test.example.com")]
        actual = [_ingress(host="old.example.com")]

        to_create, to_update, to_delete = compute_diff(desired, actual)

        assert to_create == []
        assert to_update == desired
        assert to_delete == []

    def test_leaves_an_unchanged_ingress_alone(self) -> None:
        actual = _ingress()
        actual["metadata"]["resourceVersion"] = "123"
        actual["metadata"]["uid"] = "abc"
        actual["status"] = {"loadBalancer": {}}

        assert compute_diff([_ingress()], [actual]) == ([], [], [])

    def test_deletes_an_ingress_that_is_no_longer_desired(self) -> None:
        actual = [_ingress("styrmin-svc-web"), _ingress("styrmin-svc-api")]

        to_create, to_update, to_delete = compute_diff(
            [_ingress("styrmin-svc-web")], actual
        )

        assert to_create == []
        assert to_update == []
        assert [r["metadata"]["name"] for r in to_delete] == ["styrmin-svc-api"]

    def test_an_ingress_and_a_service_of_one_name_are_different_resources(self) -> None:
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "styrmin-svc-web", "namespace": NAMESPACE},
            "spec": {},
        }

        to_create, _, to_delete = compute_diff([_ingress()], [service])

        assert [r["kind"] for r in to_create] == ["Ingress"]
        assert [r["kind"] for r in to_delete] == ["Service"]


class _Recorder:
    """Records ``list_managed_resources`` and ``reconcile_resources`` calls of a reconcile loop."""

    def __init__(self, mocker: Any, *, actual: list[dict[str, Any]] | None = None):
        self.listed_kinds: list[str | None] = []
        self.reconciled: list[dict[str, Any]] = []
        actual = actual or []

        async def _list(**kwargs: Any) -> list[dict[str, Any]]:
            self.listed_kinds.append(kwargs.get("kind"))
            return [r for r in actual if r["kind"] == kwargs.get("kind")]

        async def _reconcile(**kwargs: Any) -> ReconcileResult:
            self.reconciled.append(kwargs)
            return ReconcileResult()

        self.list_managed_resources = _list
        self.reconcile_resources = _reconcile

    def reconciled_kinds(self, action: str) -> list[str]:
        return [r["kind"] for call in self.reconciled for r in call[action]]


class TestReconcileLoopsIncludeIngress:
    @pytest.mark.anyio
    async def test_the_helmrelease_timer_reconciles_ingresses(
        self, mocker: Any
    ) -> None:
        desired = [_ingress("styrmin-svc-web")]
        recorder = _Recorder(mocker)

        async def _fetch_context(_: str) -> object:
            return object()

        mocker.patch.object(helmrelease_module, "fetch_context", _fetch_context)
        mocker.patch.object(
            helmrelease_module, "build_desired_resources", lambda **_: desired
        )
        mocker.patch.object(
            helmrelease_module,
            "list_managed_resources",
            recorder.list_managed_resources,
        )
        mocker.patch.object(
            helmrelease_module, "reconcile_resources", recorder.reconcile_resources
        )

        await helmrelease_module.kopf_helmrelease_timer(
            body={},
            meta={
                "name": "hr",
                "labels": {LABEL_RELEASE_REFERENCE: RELEASE_REF},
                "annotations": {ANNOTATION_DEPLOYMENT_ID: "deadbeef"},
            },
            spec={},
            namespace=NAMESPACE,
            logger=_Logger(),
        )

        assert "Ingress" in recorder.listed_kinds
        assert recorder.reconciled_kinds("to_create") == ["Ingress"]

    @pytest.mark.anyio
    async def test_the_helmrelease_timer_deletes_a_stale_ingress(
        self, mocker: Any
    ) -> None:
        recorder = _Recorder(mocker, actual=[_ingress("styrmin-svc-gone")])

        async def _fetch_context(_: str) -> object:
            return object()

        mocker.patch.object(helmrelease_module, "fetch_context", _fetch_context)
        mocker.patch.object(
            helmrelease_module, "build_desired_resources", lambda **_: []
        )
        mocker.patch.object(
            helmrelease_module,
            "list_managed_resources",
            recorder.list_managed_resources,
        )
        mocker.patch.object(
            helmrelease_module, "reconcile_resources", recorder.reconcile_resources
        )

        await helmrelease_module.kopf_helmrelease_timer(
            body={},
            meta={
                "name": "hr",
                "labels": {LABEL_RELEASE_REFERENCE: RELEASE_REF},
                "annotations": {ANNOTATION_DEPLOYMENT_ID: "deadbeef"},
            },
            spec={},
            namespace=NAMESPACE,
            logger=_Logger(),
        )

        assert recorder.reconciled_kinds("to_delete") == ["Ingress"]

    @pytest.mark.anyio
    async def test_the_deployment_timer_reconciles_ingresses_of_a_ready_deployment(
        self, mocker: Any
    ) -> None:
        desired = [_ingress("styrmin-svc-web")]
        recorder = _Recorder(mocker)
        mocker.patch(
            "styrmin_backend.operator.pipeline.build_desired_resources_from_crd",
            lambda *_: desired,
        )
        mocker.patch.object(
            reconciler_module, "list_managed_resources", recorder.list_managed_resources
        )
        mocker.patch.object(
            reconciler_module, "reconcile_resources", recorder.reconcile_resources
        )
        mocker.patch.object(
            handlers_module,
            "_fail_on_component_container_guard",
            mocker.AsyncMock(return_value=False),
        )

        await handlers_module.kopf_styrmin_deployment_timer(
            body={"metadata": {}},
            spec={"releaseReference": RELEASE_REF},
            status={"phase": DeploymentPhase.READY.value},
            name="my-deployment",
            namespace=NAMESPACE,
            patch=SimpleNamespace(status={}),
            logger=_Logger(),
            stopped=_NotStopped(),
        )

        assert "Ingress" in recorder.listed_kinds
        assert recorder.reconciled_kinds("to_create") == ["Ingress"]

    @pytest.mark.anyio
    async def test_the_teardown_deletes_the_ingresses(
        self, mocker: Any, fake_client: Any, custom_api: Any
    ) -> None:
        """T019 (line 1162): an Ingress that Styrmin built is deleted with the deployment (FR-001)."""
        ingress = _ingress("styrmin-svc-web")
        recorder = _Recorder(mocker, actual=[ingress])
        deleted: list[dict[str, Any]] = []

        async def _delete(*, resource: dict[str, Any], namespace: str) -> None:
            deleted.append(resource)

        mocker.patch.object(
            reconciler_module, "list_managed_resources", recorder.list_managed_resources
        )
        mocker.patch.object(reconciler_module, "delete_kubernetes_resource", _delete)
        mocker.patch.object(
            handlers_module, "_delete_service_aliases", mocker.AsyncMock()
        )

        await handlers_module._teardown_owned_resources(
            namespace=NAMESPACE,
            release_reference=RELEASE_REF,
            deployment_id="deadbeef",
            deletion_requested=True,
            name="my-deployment",
            logger=_Logger(),
        )

        assert "Ingress" in recorder.listed_kinds
        assert deleted == [ingress]


class TestIngressDriftHandlers:
    """T020: the drift handlers act on the Ingress that Styrmin builds, never on a chart's Ingress.

    The kopf label filter (``managed-by: styrmin``) keeps a chart's Ingress (``managed-by: Helm``)
    away from the handlers. A handler also returns when the release-reference label is missing.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("handler_name", "change_type"),
        [
            ("kopf_on_ingress_update", "modified"),
            ("kopf_on_ingress_delete", "deleted"),
        ],
    )
    async def test_reconciles_the_drift_of_a_styrmin_ingress(
        self, mocker: Any, handler_name: str, change_type: str
    ) -> None:
        from styrmin_backend.operator.handlers import utility_resources

        reconcile = mocker.patch.object(
            utility_resources, "_reconcile_resource_drift", mocker.AsyncMock()
        )

        await getattr(utility_resources, handler_name)(
            body={},
            meta={
                "name": "styrmin-svc-web",
                "labels": _ingress()["metadata"]["labels"],
            },
            namespace=NAMESPACE,
            logger=_Logger(),
        )

        reconcile.assert_awaited_once_with(
            namespace=NAMESPACE,
            resource_kind="Ingress",
            resource_name="styrmin-svc-web",
            release_reference=RELEASE_REF,
            change_type=change_type,
            logger=mocker.ANY,
        )

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "handler_name", ["kopf_on_ingress_update", "kopf_on_ingress_delete"]
    )
    async def test_ignores_an_ingress_without_a_release_reference(
        self, mocker: Any, handler_name: str
    ) -> None:
        from styrmin_backend.operator.handlers import utility_resources

        reconcile = mocker.patch.object(
            utility_resources, "_reconcile_resource_drift", mocker.AsyncMock()
        )

        await getattr(utility_resources, handler_name)(
            body={},
            meta={
                "name": "chart-ingress",
                "labels": {"app.kubernetes.io/managed-by": "styrmin"},
            },
            namespace=NAMESPACE,
            logger=_Logger(),
        )

        reconcile.assert_not_called()

    @pytest.mark.anyio
    async def test_a_helm_ingress_is_not_listed_for_the_deployment(
        self, networking_api: Any, core_api: Any
    ) -> None:
        """The selector needs both Styrmin labels, so Helm's Ingress is outside the diff and is never deleted."""
        await list_managed_resources(
            namespace=NAMESPACE, release_reference=RELEASE_REF, kind="Ingress"
        )

        selector = networking_api.list_namespaced_ingress.call_args.kwargs[
            "label_selector"
        ].split(",")
        assert sorted(selector) == [
            "app.kubernetes.io/managed-by=styrmin",
            f"styrmin.io/release-reference={RELEASE_REF}",
        ]


class _NotStopped:
    is_set = False

    def __bool__(self) -> bool:
        return False

    async def wait(self, timeout: float) -> None:  # noqa: ARG002
        return None
