"""The release-reference label of the Ingress that Styrmin builds is one stable value (#598).

Symptom (``specs/033-service-ingress-override/e2e-evidence.md``, "Failed run 1"): the label
``styrmin.io/release-reference`` of ``styrmin-svc-task-manager`` was ``styrmin-<uuid>`` before an
override and ``''`` after it was cleared.

Cause under test: two operator timers reconcile the same Ingress and pass different release
references to the builder, which writes that value as the label. The StyrminDeployment timer passes
``spec.releaseReference`` (the real one). The HelmRelease timer reads the label from the HelmRelease,
which a HelmRelease that the StyrminDeployment pipeline creates never has (``build`` of
``ApplicationHelmReleaseBuilder`` sets only ``managed-by`` and ``operator-managed``), so it passes
``''``. Each timer lists the Ingress by its own value, does not find the other timer's object, creates
it and replaces it (HTTP 409 path of ``apply_kubernetes_resource``), so the label flips on every pass.

The tests below run the real builder, the real reconcile code and both real timers against an
in-memory cluster that applies Kubernetes label selector rules. The HelmRelease handed to the timer
has the labels that the pipeline gives it, not the label that the older unit tests assumed.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from styrmin_backend.agent.service.kubernetes.resources.builders.utility import (
    UtilityResourceBuilder,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.ingress import (
    IngressUtility,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
    UtilityContext,
    UtilityKind,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.operator import reconciler as reconciler_module
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_ID,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
    LABEL_OPERATOR_MANAGED,
    LABEL_OPERATOR_MANAGED_VALUE,
    LABEL_RELEASE_REFERENCE,
)
from styrmin_backend.operator.crd.schema import DeploymentPhase
from styrmin_backend.operator.handlers import helmrelease as helmrelease_module
from styrmin_backend.operator.handlers import styrmin_deployment as handlers_module

DEPLOYMENT_ID = UUID("00000000-0000-0000-0000-0000000000aa")
NAMESPACE = f"styrmin-{DEPLOYMENT_ID}"
RELEASE_REF = f"styrmin-{DEPLOYMENT_ID}"
APP_NAME = "testapp"
SUFFIX = "test.styrmin.com"
INGRESS_NAME = "styrmin-svc-web"


class _Logger:
    def info(self, *_: Any, **__: Any) -> None: ...
    def warning(self, *_: Any, **__: Any) -> None: ...
    def debug(self, *_: Any, **__: Any) -> None: ...
    def error(self, *_: Any, **__: Any) -> None: ...
    def exception(self, *_: Any, **__: Any) -> None: ...


class _NotStopped:
    is_set = False

    def __bool__(self) -> bool:
        return False


def _context() -> GlobalContext:
    return GlobalContext(
        cluster=ClusterContext(
            config=ClusterConfig(ingress_class="traefik", fqdn_suffix=SUFFIX)
        ),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(ingress_class="traefik", fqdn_suffix=SUFFIX),
            deployment_id=DEPLOYMENT_ID,
            namespace=NAMESPACE,
            release_reference=RELEASE_REF,
        ),
        app=ApplicationContext(
            name=APP_NAME,
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=UUID(int=7), name=APP_NAME, version="1.0.0", values_template=""
                ),
                repository=RepositoryInfo(
                    id=UUID(int=8), url="oci://charts.example.com/test"
                ),
            ),
        ),
        utilities=[UtilityContext(kind=UtilityKind.INGRESS)],
        deployed_services=[
            {
                "driver_service_name": "web",
                "resolved_name": "web",
                "port": 8080,
                "kind": "http",
                "scope": "external",
                "deployment_id": str(DEPLOYMENT_ID),
                "component": "server",
                "ingress_class": "traefik",
                "fqdn_suffix": SUFFIX,
            }
        ],
    )


class _FakeCluster:
    """Namespaced objects by ``(kind, name)``, listed by label selector like the API server does."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.writes: list[tuple[str, str]] = []

    async def list_managed_resources(
        self,
        namespace: str,  # noqa: ARG002
        release_reference: str,
        kind: str | None = None,
        operator_managed_only: bool = False,
    ) -> list[dict[str, Any]]:
        selected = []
        for (object_kind, _), resource in self.objects.items():
            if kind is not None and object_kind != kind:
                continue
            labels = resource["metadata"].get("labels", {})
            # ``key=value`` matches only an object that has the label with that exact value
            # (an empty value included).
            if labels.get(LABEL_MANAGED_BY) != LABEL_MANAGED_BY_VALUE:
                continue
            if labels.get(LABEL_RELEASE_REFERENCE) != release_reference:
                continue
            if (
                operator_managed_only
                and labels.get(LABEL_OPERATOR_MANAGED) != LABEL_OPERATOR_MANAGED_VALUE
            ):
                continue
            selected.append(copy.deepcopy(resource))
        return selected

    async def apply_kubernetes_resource(
        self,
        resource: dict[str, Any],
        namespace: str,  # noqa: ARG002
    ) -> None:
        """Create the object, or replace it whole when it exists (the 409 path)."""
        key = (resource["kind"], resource["metadata"]["name"])
        self.objects[key] = copy.deepcopy(resource)
        self.writes.append(key)

    async def delete_kubernetes_resource(
        self,
        resource: dict[str, Any],
        namespace: str,  # noqa: ARG002
    ) -> None:
        self.objects.pop((resource["kind"], resource["metadata"]["name"]), None)

    def ingress_label(self) -> str | None:
        ingress = self.objects[("Ingress", INGRESS_NAME)]
        return ingress["metadata"]["labels"].get(LABEL_RELEASE_REFERENCE)

    def ingress_writes(self) -> int:
        return self.writes.count(("Ingress", INGRESS_NAME))


@pytest.fixture
def cluster(mocker: Any) -> _FakeCluster:
    fake = _FakeCluster()
    context = _context()

    async def _fetch_context(_: str) -> GlobalContext:
        return context

    mocker.patch.object(helmrelease_module, "fetch_context", _fetch_context)
    mocker.patch.object(
        helmrelease_module, "list_managed_resources", fake.list_managed_resources
    )
    mocker.patch.object(
        reconciler_module, "list_managed_resources", fake.list_managed_resources
    )
    mocker.patch.object(
        reconciler_module, "apply_kubernetes_resource", fake.apply_kubernetes_resource
    )
    mocker.patch.object(
        reconciler_module, "delete_kubernetes_resource", fake.delete_kubernetes_resource
    )
    mocker.patch.object(
        handlers_module,
        "_fail_on_component_container_guard",
        mocker.AsyncMock(return_value=False),
    )
    return fake


async def _helmrelease_timer(logger: Any = None) -> None:
    """One pass of the HelmRelease timer on a HelmRelease that the StyrminDeployment pipeline created.

    That HelmRelease has the labels ``ApplicationHelmReleaseBuilder.build`` sets and no
    ``styrmin.io/release-reference`` label.
    """
    await helmrelease_module.kopf_helmrelease_timer(
        body={},
        meta={
            "name": RELEASE_REF,
            "labels": {
                LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
                LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
            },
            "annotations": {ANNOTATION_DEPLOYMENT_ID: str(DEPLOYMENT_ID)},
        },
        spec={},
        namespace=NAMESPACE,
        logger=logger or _Logger(),
    )


async def _deployment_timer() -> None:
    """One pass of the StyrminDeployment timer on a Ready deployment."""
    await handlers_module.kopf_styrmin_deployment_timer(
        body={"metadata": {}},
        spec={
            "releaseReference": RELEASE_REF,
            "context": _context().model_dump(mode="json", exclude_none=True),
        },
        status={"phase": DeploymentPhase.READY.value},
        name=NAMESPACE,
        namespace=NAMESPACE,
        patch=SimpleNamespace(status={}),
        logger=_Logger(),
        stopped=_NotStopped(),
    )


class TestTheBuilderLabel:
    def test_an_empty_release_reference_still_labels_with_the_one_of_the_instance(
        self,
    ) -> None:
        """A caller that has no release reference gets the one of the instance, never an empty label."""
        builder = UtilityResourceBuilder(context=_context())

        resources = builder.build(IngressUtility(), "", NAMESPACE)

        (ingress,) = [r for r in resources if r["kind"] == "Ingress"]
        assert ingress["metadata"]["labels"][LABEL_RELEASE_REFERENCE] == RELEASE_REF

    def test_a_given_release_reference_is_the_label(self) -> None:
        builder = UtilityResourceBuilder(context=_context())

        resources = builder.build(IngressUtility(), RELEASE_REF, NAMESPACE)

        (ingress,) = [r for r in resources if r["kind"] == "Ingress"]
        assert ingress["metadata"]["labels"][LABEL_RELEASE_REFERENCE] == RELEASE_REF


class TestTheTimersAgree:
    @pytest.mark.anyio
    async def test_the_helmrelease_timer_creates_the_ingress_with_the_instance_reference(
        self, cluster: _FakeCluster
    ) -> None:
        await _helmrelease_timer()

        assert cluster.ingress_label() == RELEASE_REF

    @pytest.mark.anyio
    async def test_the_deployment_timer_creates_the_ingress_with_the_instance_reference(
        self, cluster: _FakeCluster
    ) -> None:
        await _deployment_timer()

        assert cluster.ingress_label() == RELEASE_REF

    @pytest.mark.anyio
    async def test_the_helmrelease_timer_leaves_the_label_of_the_deployment_timer(
        self, cluster: _FakeCluster
    ) -> None:
        await _deployment_timer()
        writes_before = cluster.ingress_writes()

        await _helmrelease_timer()

        assert cluster.ingress_label() == RELEASE_REF
        assert cluster.ingress_writes() == writes_before

    @pytest.mark.anyio
    async def test_the_deployment_timer_leaves_the_label_of_the_helmrelease_timer(
        self, cluster: _FakeCluster
    ) -> None:
        await _helmrelease_timer()
        writes_before = cluster.ingress_writes()

        await _deployment_timer()

        assert cluster.ingress_label() == RELEASE_REF
        assert cluster.ingress_writes() == writes_before

    @pytest.mark.anyio
    async def test_alternating_passes_write_the_ingress_once_and_keep_one_label(
        self, cluster: _FakeCluster
    ) -> None:
        labels = []
        for _ in range(4):
            await _helmrelease_timer()
            labels.append(cluster.ingress_label())
            await _deployment_timer()
            labels.append(cluster.ingress_label())

        assert set(labels) == {RELEASE_REF}
        assert cluster.ingress_writes() == 1

    @pytest.mark.anyio
    async def test_the_helmrelease_timer_deletes_an_ingress_that_is_no_longer_desired(
        self, cluster: _FakeCluster, mocker: Any
    ) -> None:
        """The timer must see the Ingress, or it never deletes one that the deployment no longer wants."""
        await _deployment_timer()
        assert ("Ingress", INGRESS_NAME) in cluster.objects
        context = _context()
        context.deployed_services = []

        async def _fetch_context(_: str) -> GlobalContext:
            return context

        mocker.patch.object(helmrelease_module, "fetch_context", _fetch_context)

        await _helmrelease_timer()

        assert ("Ingress", INGRESS_NAME) not in cluster.objects

    @pytest.mark.anyio
    async def test_an_ingress_with_an_empty_label_is_relabelled_once(
        self, cluster: _FakeCluster
    ) -> None:
        """An Ingress that the flapping left with an empty label converges to the instance's value."""
        ingress = next(
            r
            for r in UtilityResourceBuilder(context=_context()).build(
                IngressUtility(), RELEASE_REF, NAMESPACE
            )
            if r["kind"] == "Ingress"
        )
        ingress["metadata"]["labels"][LABEL_RELEASE_REFERENCE] = ""
        await cluster.apply_kubernetes_resource(ingress, NAMESPACE)

        for _ in range(3):
            await _helmrelease_timer()
            await _deployment_timer()

        assert cluster.ingress_label() == RELEASE_REF
        assert cluster.ingress_writes() == 2  # the seed and one relabelling


class TestTheHelmReleaseTimerSurvivesAContextThatCannotBeBuilt:
    """An external service with no FQDN suffix makes the builder raise ``ValueError`` (#598).

    The StyrminDeployment timer catches it and logs it with the traceback. The HelmRelease timer
    called the builder with no ``try``, so the error escaped the timer and the NetworkPolicy,
    Service and Secret reconcile of that deployment was skipped with no log line of ours.
    """

    @pytest.mark.anyio
    async def test_the_error_is_logged_with_its_traceback_and_does_not_escape(
        self, cluster: _FakeCluster, mocker: Any
    ) -> None:
        context = _context()
        context.instance.config.fqdn_suffix = None
        context.cluster.config.fqdn_suffix = None

        async def _fetch_context(_: str) -> GlobalContext:
            return context

        mocker.patch.object(helmrelease_module, "fetch_context", _fetch_context)
        logger = mocker.MagicMock()

        await _helmrelease_timer(logger=logger)

        logger.exception.assert_called_once()
        assert cluster.writes == []
