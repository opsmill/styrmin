"""Unit tests for cross-namespace service alias computation."""

import json
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from kubernetes_asyncio.client import (
    V1Namespace,
    V1NamespaceStatus,
    V1ObjectMeta,
    V1Service,
    V1ServiceSpec,
)
from kubernetes_asyncio.client.api_client import ApiException

from styrmin_backend.agent.service.kubernetes.exceptions import CustomResourceNotFound
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.agent.tasks import service_aliases
from styrmin_backend.agent.tasks.service_aliases import (
    StaleAlias,
    apply_service_aliases,
    build_external_name_service,
    compute_service_aliases,
    find_deleted_deployment_namespaces,
    find_departing_namespaces,
    owner_namespace,
    select_stale_aliases,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    ResolvedConfig,
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo


def _make_context(
    deployment_id: UUID,
    deployed_services: list[dict],
) -> GlobalContext:
    """Build a minimal GlobalContext for testing."""
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name="test-app",
            version="1.0.0",
            helm=HelmInfo(
                chart=ChartInfo(
                    id=uuid4(),
                    name="test-chart",
                    version="1.0.0",
                    values_template="",
                ),
                repository=RepositoryInfo(
                    id=uuid4(),
                    url="https://example.com/charts",
                ),
            ),
        ),
        deployed_services=deployed_services,
    )


class TestBuildExternalNameService:
    def test_manifest_structure(self) -> None:
        manifest = build_external_name_service(
            resolved_name="intent",
            target_namespace="styrmin-aaa",
            holder_namespace="styrmin-bbb",
            deployment_id="aaa",
        )
        assert manifest["apiVersion"] == "v1"
        assert manifest["kind"] == "Service"
        assert manifest["metadata"]["name"] == "intent"
        assert manifest["metadata"]["namespace"] == "styrmin-bbb"
        assert manifest["spec"]["type"] == "ExternalName"
        assert (
            manifest["spec"]["externalName"] == "intent.styrmin-aaa.svc.cluster.local"
        )

    def test_labels(self) -> None:
        manifest = build_external_name_service(
            resolved_name="web",
            target_namespace="styrmin-aaa",
            holder_namespace="styrmin-bbb",
            deployment_id="aaa",
        )
        labels = manifest["metadata"]["labels"]
        assert labels["app.kubernetes.io/managed-by"] == "styrmin"
        assert labels["styrmin.io/service-alias"] == "true"
        assert labels["styrmin.io/deployment-id"] == "aaa"


class TestComputeServiceAliases:
    def test_two_deployments_cross_aliases(self) -> None:
        """Two deployments should create aliases in each other's namespace."""
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        ns_b = get_kubernetes_reference(dep_b)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "executor",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # Should have 2 aliases:
        # 1. "executor" in ns_a (pointing to ns_b) — other service in our ns
        # 2. "intent" in ns_b (pointing to ns_a) — our service in other ns
        assert len(aliases) == 2

        names_and_namespaces = {
            (a["metadata"]["name"], a["metadata"]["namespace"]) for a in aliases
        }
        assert ("executor", ns_a) in names_and_namespaces
        assert ("intent", ns_b) in names_and_namespaces

    def test_aliases_carry_the_id_of_the_service_owner(self) -> None:
        """#491: each alias names the deployment whose service it resolves to."""
        dep_a = uuid4()
        dep_b = uuid4()
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                _service("intent", dep_a),
                _service("executor", dep_b),
            ],
        )

        owners = {
            a["metadata"]["name"]: a["metadata"]["labels"]["styrmin.io/deployment-id"]
            for a in compute_service_aliases(context)
        }

        assert owners == {"intent": str(dep_a), "executor": str(dep_b)}

    def test_single_deployment_no_aliases(self) -> None:
        """A single deployment alone should produce no aliases."""
        dep_a = uuid4()

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
            ],
        )

        aliases = compute_service_aliases(context)
        assert aliases == []

    def test_skips_self_aliases(self) -> None:
        """Should not create an alias for a service in its own namespace."""
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "intent",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "executor",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # No alias should point to ns_a with name "intent" in ns_a (self)
        for alias in aliases:
            if alias["metadata"]["name"] == "intent":
                assert alias["metadata"]["namespace"] != ns_a

    def test_multiple_services_per_deployment(self) -> None:
        """Multiple services per deployment generate aliases for each."""
        dep_a = uuid4()
        dep_b = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        ns_b = get_kubernetes_reference(dep_b)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "web",
                    "port": 8000,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "api",
                    "port": 8080,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "cache",
                    "port": 6379,
                    "kind": "tcp",
                    "deployment_id": str(dep_b),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # 3 aliases:
        # "cache" in ns_a (from dep_b)
        # "web" in ns_b (from dep_a)
        # "api" in ns_b (from dep_a)
        assert len(aliases) == 3

        names_and_namespaces = {
            (a["metadata"]["name"], a["metadata"]["namespace"]) for a in aliases
        }
        assert ("cache", ns_a) in names_and_namespaces
        assert ("web", ns_b) in names_and_namespaces
        assert ("api", ns_b) in names_and_namespaces

    def test_three_deployments(self) -> None:
        """Three deployments: our services aliased into both other namespaces."""
        dep_a = uuid4()
        dep_b = uuid4()
        dep_c = uuid4()
        ns_a = get_kubernetes_reference(dep_a)
        ns_b = get_kubernetes_reference(dep_b)
        ns_c = get_kubernetes_reference(dep_c)

        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "svc-a",
                    "port": 80,
                    "kind": "http",
                    "deployment_id": str(dep_a),
                },
                {
                    "resolved_name": "svc-b",
                    "port": 80,
                    "kind": "http",
                    "deployment_id": str(dep_b),
                },
                {
                    "resolved_name": "svc-c",
                    "port": 80,
                    "kind": "http",
                    "deployment_id": str(dep_c),
                },
            ],
        )

        aliases = compute_service_aliases(context)

        # In ns_a: "svc-b" and "svc-c" (other services)
        # In ns_b: "svc-a" (our service)
        # In ns_c: "svc-a" (our service)
        assert len(aliases) == 4

        names_and_namespaces = {
            (a["metadata"]["name"], a["metadata"]["namespace"]) for a in aliases
        }
        assert ("svc-b", ns_a) in names_and_namespaces
        assert ("svc-c", ns_a) in names_and_namespaces
        assert ("svc-a", ns_b) in names_and_namespaces
        assert ("svc-a", ns_c) in names_and_namespaces

    def test_empty_deployed_services(self) -> None:
        """No deployed services means no aliases."""
        dep_a = uuid4()
        context = _make_context(deployment_id=dep_a, deployed_services=[])
        aliases = compute_service_aliases(context)
        assert aliases == []

    def test_missing_deployment_id_skipped(self) -> None:
        """Services without deployment_id are safely skipped."""
        dep_a = uuid4()
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[
                {
                    "resolved_name": "orphan",
                    "port": 80,
                    "kind": "http",
                },
            ],
        )
        aliases = compute_service_aliases(context)
        assert aliases == []


def _service(resolved_name: str, deployment_id: UUID) -> dict:
    return {
        "resolved_name": resolved_name,
        "port": 8000,
        "kind": "http",
        "deployment_id": str(deployment_id),
    }


def _live_alias(
    name: str,
    namespace: str,
    target_namespace: str,
    owner: UUID | None,
    resource_version: str = "1",
) -> V1Service:
    labels = {"styrmin.io/service-alias": "true"}
    if owner is not None:
        labels["styrmin.io/deployment-id"] = str(owner)
    return V1Service(
        metadata=V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
            resource_version=resource_version,
        ),
        spec=V1ServiceSpec(
            type="ExternalName",
            external_name=f"{name}.{target_namespace}.svc.cluster.local",
        ),
    )


class TestSelectStaleAliases:
    def test_alias_of_an_old_override_is_stale(self) -> None:
        """#491: the alias named after the old override is deleted, the new one kept."""
        dep_a, dep_b = uuid4(), uuid4()
        ns_a, ns_b = get_kubernetes_reference(dep_a), get_kubernetes_reference(dep_b)
        context = _make_context(
            deployment_id=dep_a,
            deployed_services=[_service("after", dep_a), _service("peer", dep_b)],
        )
        live = [
            _live_alias("before", ns_b, ns_a, dep_a, resource_version="41"),
            _live_alias("after", ns_b, ns_a, dep_a),
            _live_alias("peer", ns_a, ns_b, dep_b),
        ]

        assert select_stale_aliases(context, live) == [
            StaleAlias(namespace=ns_b, name="before", resource_version="41")
        ]

    def test_aliases_of_other_deployments_are_kept(self) -> None:
        """A peer's alias with a name this deployment does not use is not this flow's to delete."""
        dep_a, dep_b = uuid4(), uuid4()
        ns_a, ns_b = get_kubernetes_reference(dep_a), get_kubernetes_reference(dep_b)
        context = _make_context(
            deployment_id=dep_a, deployed_services=[_service("intent", dep_a)]
        )
        live = [_live_alias("executor", ns_a, ns_b, dep_b)]

        assert select_stale_aliases(context, live) == []

    def test_current_name_kept_in_namespaces_this_flow_does_not_write(self) -> None:
        """A peer without services writes this deployment's aliases itself; they stay."""
        dep_a, dep_c = uuid4(), uuid4()
        ns_a, ns_c = get_kubernetes_reference(dep_a), get_kubernetes_reference(dep_c)
        context = _make_context(
            deployment_id=dep_a, deployed_services=[_service("intent", dep_a)]
        )
        live = [_live_alias("intent", ns_c, ns_a, dep_a)]

        assert select_stale_aliases(context, live) == []

    def test_unlabelled_alias_found_by_its_target_namespace(self) -> None:
        """Aliases created before the id label point into the owner's namespace."""
        dep_a, dep_b = uuid4(), uuid4()
        ns_a, ns_b = get_kubernetes_reference(dep_a), get_kubernetes_reference(dep_b)
        context = _make_context(
            deployment_id=dep_a, deployed_services=[_service("after", dep_a)]
        )
        live = [
            _live_alias("before", ns_b, ns_a, owner=None),
            _live_alias("peer", ns_a, ns_b, owner=None),
        ]

        assert [a.name for a in select_stale_aliases(context, live)] == ["before"]

    def test_all_aliases_stale_when_the_deployment_has_no_services(self) -> None:
        dep_a, dep_b = uuid4(), uuid4()
        ns_a, ns_b = get_kubernetes_reference(dep_a), get_kubernetes_reference(dep_b)
        context = _make_context(deployment_id=dep_a, deployed_services=[])
        live = [_live_alias("intent", ns_b, ns_a, dep_a)]

        assert [a.name for a in select_stale_aliases(context, live)] == ["intent"]


MODULE = "styrmin_backend.agent.tasks.service_aliases"


class TestOwnerNamespace:
    def test_owner_from_the_deployment_id_label(self) -> None:
        dep_a, dep_b = uuid4(), uuid4()
        ns_a, ns_b = get_kubernetes_reference(dep_a), get_kubernetes_reference(dep_b)
        alias = build_external_name_service("intent", ns_a, ns_b, str(dep_a))

        assert owner_namespace(alias) == ns_a

    def test_owner_from_the_external_name_without_the_label(self) -> None:
        alias = build_external_name_service("intent", "styrmin-a", "styrmin-b", "x")
        del alias["metadata"]["labels"]["styrmin.io/deployment-id"]

        assert owner_namespace(alias) == "styrmin-a"


def _namespace(phase: str | None) -> V1Namespace | None:
    if phase is None:
        return None
    return V1Namespace(
        metadata=V1ObjectMeta(name="styrmin-x"), status=V1NamespaceStatus(phase=phase)
    )


def _styrmin_deployment(
    *, deletion_requested: bool = False, deletion_timestamp: str | None = None
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": "styrmin-x", "namespace": "styrmin-x"}
    if deletion_timestamp:
        metadata["deletionTimestamp"] = deletion_timestamp
    return {"metadata": metadata, "spec": {"deletionRequested": deletion_requested}}


_ABSENT = CustomResourceNotFound("absent")


_STATE_TABLE = [
    pytest.param("Active", _styrmin_deployment(), False, False, id="running"),
    pytest.param(
        "Active",
        _styrmin_deployment(deletion_requested=True),
        True,
        True,
        id="deletion-requested",
    ),
    pytest.param(
        "Terminating",
        _styrmin_deployment(
            deletion_requested=True, deletion_timestamp="2026-10-16T10:00:00Z"
        ),
        True,
        True,
        id="namespace-terminating-after-request",
    ),
    pytest.param(None, _ABSENT, True, False, id="namespace-and-cr-gone"),
    pytest.param(
        "Active",
        _styrmin_deployment(deletion_timestamp="2026-10-16T10:00:00Z"),
        True,
        True,
        id="kubectl-delete",
    ),
    pytest.param("Active", _ABSENT, False, False, id="new-deployment-no-cr"),
    pytest.param(
        "Terminating",
        _styrmin_deployment(),
        True,
        False,
        id="namespace-terminating-without-request",
    ),
    pytest.param(
        "Terminating",
        _styrmin_deployment(deletion_timestamp="2026-10-16T10:00:00Z"),
        True,
        False,
        id="restore-deletes-the-cr-with-the-namespace",
    ),
    pytest.param("Terminating", _ABSENT, True, False, id="restore-cr-gone"),
]


class TestFindDepartingNamespaces:
    """One case per row of the state table in data-model.md (#503, research R-003, R-004).

    ``departing`` is the first read's answer; ``deleted`` the second read's, the teardown's rule.
    """

    @staticmethod
    async def _read(
        find: Any, phase: str | None, resource: Any
    ) -> tuple[set[str], AsyncMock, AsyncMock]:
        get_namespace = AsyncMock(return_value=_namespace(phase))
        get_resource = AsyncMock(
            side_effect=resource if isinstance(resource, Exception) else None,
            return_value=resource,
        )
        with (
            patch(f"{MODULE}.get_namespace", get_namespace),
            patch(f"{MODULE}.get_custom_resource", get_resource),
        ):
            result = await find(["styrmin-x"])
        return result, get_namespace, get_resource

    @pytest.mark.parametrize(
        ("phase", "resource", "departing", "deleted"), _STATE_TABLE
    )
    @pytest.mark.asyncio
    async def test_find_departing_namespaces_state_table(
        self, phase: str | None, resource: Any, departing: bool, deleted: bool
    ) -> None:
        result, get_namespace, get_resource = await self._read(
            find_departing_namespaces, phase, resource
        )

        assert result == ({"styrmin-x"} if departing else set())
        get_namespace.assert_awaited_once_with(name="styrmin-x")
        get_resource.assert_awaited_once_with(
            plural="styrmindeployments",
            name="styrmin-x",
            group="styrmin.io",
            version="v1alpha1",
            namespace="styrmin-x",
        )

    @pytest.mark.parametrize(
        ("phase", "resource", "departing", "deleted"), _STATE_TABLE
    )
    @pytest.mark.asyncio
    async def test_find_deleted_deployment_namespaces_state_table(
        self, phase: str | None, resource: Any, departing: bool, deleted: bool
    ) -> None:
        """Rule A: a namespace gone or terminating without a deletion request does not count."""
        result, get_namespace, get_resource = await self._read(
            find_deleted_deployment_namespaces, phase, resource
        )

        assert result == ({"styrmin-x"} if deleted else set())
        get_namespace.assert_awaited_once_with(name="styrmin-x")
        get_resource.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_find_departing_namespaces_reads_each_namespace_once(self) -> None:
        async def read_namespace(*, name: str) -> V1Namespace | None:
            return None if name == "styrmin-gone" else _namespace("Active")

        get_namespace = AsyncMock(side_effect=read_namespace)
        with (
            patch(f"{MODULE}.get_namespace", get_namespace),
            patch(f"{MODULE}.get_custom_resource", AsyncMock(side_effect=_ABSENT)),
        ):
            result = await find_departing_namespaces(
                ["styrmin-gone", "styrmin-live", "styrmin-gone"]
            )

        assert result == {"styrmin-gone"}
        assert sorted(c.kwargs["name"] for c in get_namespace.await_args_list) == [
            "styrmin-gone",
            "styrmin-live",
        ]

    @pytest.mark.parametrize("failing_read", ["namespace", "custom_resource"])
    @pytest.mark.asyncio
    async def test_find_departing_namespaces_raises_other_errors(
        self, failing_read: str
    ) -> None:
        error = ApiException(status=500)
        get_namespace = AsyncMock(
            side_effect=error if failing_read == "namespace" else None,
            return_value=_namespace("Active"),
        )
        get_resource = AsyncMock(
            side_effect=error if failing_read == "custom_resource" else None,
            return_value=_styrmin_deployment(),
        )
        with (
            patch(f"{MODULE}.get_namespace", get_namespace),
            patch(f"{MODULE}.get_custom_resource", get_resource),
            pytest.raises(ApiException) as raised,
        ):
            await find_departing_namespaces(["styrmin-x"])

        assert raised.value.status == 500


def _forbidden(body: dict[str, Any] | str) -> ApiException:
    exc = ApiException(status=403, reason="Forbidden")
    exc.body = body if isinstance(body, str) else json.dumps(body)
    return exc


def _stored(resource: dict, namespace: str) -> V1Service:
    """What the API server returns for a write: the alias with a resourceVersion."""
    name = resource["metadata"]["name"]
    return V1Service(
        metadata=V1ObjectMeta(
            name=name, namespace=namespace, resource_version=f"rv-{namespace}-{name}"
        )
    )


# (Namespace phase, StyrminDeployment) of a namespace; None for one that is missing.
_State = tuple[str | None, dict[str, Any] | None]
_TIMESTAMP = "2026-10-17T10:00:00Z"
RUNNING: _State = ("Active", _styrmin_deployment())
DELETION_REQUESTED: _State = ("Active", _styrmin_deployment(deletion_requested=True))
KUBECTL_DELETE: _State = ("Active", _styrmin_deployment(deletion_timestamp=_TIMESTAMP))
REQUESTED_AND_TERMINATING: _State = (
    "Terminating",
    _styrmin_deployment(deletion_requested=True, deletion_timestamp=_TIMESTAMP),
)
DEPARTING_REASON = (
    "is gone or terminating, or the deletion of its deployment was requested"
)


class _Cluster:
    """Fakes the cluster that the flow reads and writes.

    ``before`` and ``after`` give the state of each namespace before and after the flow's first
    write; a namespace that they do not name is running.
    """

    def __init__(
        self,
        before: dict[str, _State] | None = None,
        after: dict[str, _State] | None = None,
        failures: dict[tuple[str, str], ApiException] | None = None,
    ) -> None:
        self.before = before or {}
        self.after = self.before if after is None else after
        self.failures = failures or {}
        self.namespace_reads: list[tuple[bool, str]] = []
        self.resource_reads: list[tuple[bool, str]] = []
        self.apply_service = AsyncMock(side_effect=self._apply)
        self.delete_service = AsyncMock(return_value=True)
        self.logger = MagicMock()

    def _state(self, namespace: str) -> tuple[bool, _State]:
        after_first_write = self.apply_service.await_count > 0
        states = self.after if after_first_write else self.before
        return after_first_write, states.get(namespace, RUNNING)

    async def _get_namespace(self, *, name: str) -> V1Namespace | None:
        after_first_write, (phase, _) = self._state(name)
        self.namespace_reads.append((after_first_write, name))
        return _namespace(phase)

    async def _get_custom_resource(self, **kwargs: str) -> dict[str, Any]:
        assert kwargs["name"] == kwargs["namespace"]
        after_first_write, (_, resource) = self._state(kwargs["namespace"])
        self.resource_reads.append((after_first_write, kwargs["namespace"]))
        if resource is None:
            raise CustomResourceNotFound(kwargs["name"])
        return resource

    async def _apply(self, *, resource: dict, namespace: str) -> V1Service:
        key = (namespace, resource["metadata"]["name"])
        if key in self.failures:
            raise self.failures[key]
        return _stored(resource, namespace)

    async def run(
        self, aliases: list[dict], stale: list[StaleAlias] | None = None
    ) -> None:
        with ExitStack() as stack:
            for name, fake in (
                ("get_namespace", self._get_namespace),
                ("get_custom_resource", self._get_custom_resource),
                ("apply_service", self.apply_service),
                ("delete_service", self.delete_service),
            ):
                stack.enter_context(patch(f"{MODULE}.{name}", fake))
            stack.enter_context(
                patch(f"{MODULE}.get_run_logger", return_value=self.logger)
            )
            # Run the task bodies without the Prefect engine and its temporary server.
            for name in ("apply_single_alias", "delete_single_alias"):
                task = getattr(service_aliases, name)
                stack.enter_context(patch(f"{MODULE}.{name}", task.fn))
            await apply_service_aliases.fn(aliases=aliases, stale_aliases=stale)

    @property
    def reads(self) -> tuple[list[str], list[str]]:
        """The namespaces of the first read and of the second read, in sorted order."""
        assert sorted(self.resource_reads) == sorted(self.namespace_reads)
        return (
            sorted(ns for after, ns in self.namespace_reads if not after),
            sorted(ns for after, ns in self.namespace_reads if after),
        )

    @property
    def written(self) -> set[tuple[str, str]]:
        return {
            (c.kwargs["namespace"], c.kwargs["resource"]["metadata"]["name"])
            for c in self.apply_service.await_args_list
        }

    @property
    def deleted(self) -> set[tuple[str, str, str | None]]:
        return {
            (c.kwargs["namespace"], c.kwargs["name"], c.kwargs["resource_version"])
            for c in self.delete_service.await_args_list
        }

    @property
    def messages(self) -> list[str]:
        return [c.args[0] % c.args[1:] for c in self.logger.info.call_args_list]


class TestApplyServiceAliasesFlow:
    """A flow of deployment A while its peers B and C run or are being deleted (#503)."""

    @pytest.fixture
    def ids(self) -> dict[str, UUID]:
        return {"a": uuid4(), "b": uuid4(), "c": uuid4(), "d": uuid4()}

    @pytest.fixture
    def ns(self, ids: dict[str, UUID]) -> dict[str, str]:
        return {key: get_kubernetes_reference(value) for key, value in ids.items()}

    @pytest.fixture
    def aliases(self, ids: dict[str, UUID]) -> list[dict]:
        """A has a service of its own, so the flow writes into A, B and C."""
        context = _make_context(
            deployment_id=ids["a"],
            deployed_services=[
                _service("intent", ids["a"]),
                _service("executor", ids["b"]),
                _service("worker", ids["c"]),
            ],
        )
        return compute_service_aliases(context)

    @pytest.fixture
    def peer_aliases(self, ids: dict[str, UUID]) -> list[dict]:
        """A has no service of its own, so the flow writes only into A, aliases owned by B and C."""
        context = _make_context(
            deployment_id=ids["a"],
            deployed_services=[
                _service("executor", ids["b"]),
                _service("worker", ids["c"]),
            ],
        )
        return compute_service_aliases(context)

    @pytest.mark.asyncio
    async def test_apply_service_aliases_writes_every_alias_and_no_namespace(
        self, aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """FR-009: with no departing namespace, the flow writes as before #503."""
        cluster = _Cluster()

        await cluster.run(aliases)

        assert cluster.apply_service.await_count == len(aliases) == 4
        assert cluster.written == {
            (ns["a"], "executor"),
            (ns["a"], "worker"),
            (ns["b"], "intent"),
            (ns["c"], "intent"),
        }
        everyone = sorted([ns["a"], ns["b"], ns["c"]])
        assert cluster.reads == (everyone, everyone)
        cluster.delete_service.assert_not_awaited()
        # FR-008: the flow creates no namespace, so it imports no namespace writer.
        assert not hasattr(service_aliases, "apply_namespace")
        assert not hasattr(service_aliases, "apply_kubernetes_namespace")

    @pytest.mark.asyncio
    async def test_apply_service_aliases_reads_holders_and_owners_then_owners(
        self, peer_aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """The first read covers holders, owners and stale aliases; the second, the owners."""
        cluster = _Cluster()
        stale = [StaleAlias(namespace=ns["d"], name="old-intent", resource_version="5")]

        await cluster.run(peer_aliases, stale)

        assert cluster.written == {(ns["a"], "executor"), (ns["a"], "worker")}
        assert cluster.reads == (
            sorted([ns["a"], ns["b"], ns["c"], ns["d"]]),
            sorted([ns["b"], ns["c"]]),
        )
        assert cluster.deleted == {(ns["d"], "old-intent", "5")}

    @pytest.mark.asyncio
    async def test_apply_service_aliases_skips_a_peer_departing_before_the_flow(
        self, aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """FR-007, FR-008, SC-002: B's deletion was requested before the flow read it.

        A context built before the request and one built while B is DELETING both
        list B's services, so both give the flow this input.
        """
        cluster = _Cluster(before={ns["b"]: DELETION_REQUESTED})
        stale = [
            StaleAlias(namespace=ns["b"], name="old-intent", resource_version="3"),
            StaleAlias(namespace=ns["c"], name="old-intent", resource_version="4"),
        ]

        await cluster.run(aliases, stale)

        assert cluster.written == {(ns["a"], "worker"), (ns["c"], "intent")}
        assert cluster.deleted == {(ns["c"], "old-intent", "4")}
        assert {
            f"Skipping service alias executor in namespace {ns['a']}: "
            f"namespace {ns['b']} {DEPARTING_REASON}",
            f"Skipping service alias intent in namespace {ns['b']}: "
            f"namespace {ns['b']} {DEPARTING_REASON}",
            f"Keeping service alias old-intent in namespace {ns['b']}: "
            f"namespace {ns['b']} {DEPARTING_REASON}",
        } <= set(cluster.messages)

    @pytest.mark.asyncio
    async def test_apply_service_aliases_waits_for_a_peer_created_at_the_same_time(
        self, aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """FR-009: B was created just before A, and B's flow has not created B's namespace yet.

        A's context lists B but B's context does not list A, so only A's flow writes the pair.
        """
        cluster = _Cluster(before={ns["b"]: (None, None)})
        read_namespace = cluster._get_namespace

        async def created_by_b_flow(*, name: str) -> V1Namespace | None:
            if name == ns["b"] and (False, ns["b"]) in cluster.namespace_reads:
                cluster.before[ns["b"]] = RUNNING
            return await read_namespace(name=name)

        cluster._get_namespace = created_by_b_flow  # type: ignore[method-assign]
        with patch(f"{MODULE}.MISSING_NAMESPACE_POLL_SECONDS", 0):
            await cluster.run(aliases)

        assert cluster.written == {
            (ns["a"], "executor"),
            (ns["a"], "worker"),
            (ns["b"], "intent"),
            (ns["c"], "intent"),
        }
        assert sorted(
            ns_ for after, ns_ in cluster.resource_reads if not after
        ) == sorted([ns["a"], ns["b"], ns["b"], ns["c"]])
        assert not any(m.startswith("Skipping service alias") for m in cluster.messages)

    @pytest.mark.asyncio
    async def test_apply_service_aliases_skips_a_namespace_still_missing_after_the_wait(
        self, aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """B was deleted, and its namespace and StyrminDeployment are gone; A creates no namespace."""
        cluster = _Cluster(before={ns["b"]: (None, None)})
        stale = [StaleAlias(namespace=ns["d"], name="old-intent", resource_version="5")]

        with (
            patch(f"{MODULE}.MISSING_NAMESPACE_POLL_SECONDS", 0),
            patch(f"{MODULE}.MISSING_NAMESPACE_WAIT_SECONDS", 0.05),
        ):
            await cluster.run(aliases, stale)

        assert cluster.written == {(ns["a"], "worker"), (ns["c"], "intent")}
        assert cluster.deleted == {(ns["d"], "old-intent", "5")}
        first_read = {name for after, name in cluster.namespace_reads if not after}
        assert first_read == {ns["a"], ns["b"], ns["c"], ns["d"]}
        # The flow waits only for the namespaces of its aliases, not for those of stale aliases.
        assert [name for _, name in cluster.namespace_reads].count(ns["d"]) == 1
        assert (
            f"Namespaces {ns['b']} still do not exist after 0.05s" in cluster.messages
        )
        assert (
            f"Skipping service alias executor in namespace {ns['a']}: "
            f"namespace {ns['b']} {DEPARTING_REASON}"
        ) in cluster.messages

    @pytest.mark.asyncio
    async def test_apply_service_aliases_skips_a_departing_owner_of_a_flow_without_services(
        self, peer_aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """The first read covers B although no alias is written into B's namespace."""
        cluster = _Cluster(before={ns["b"]: DELETION_REQUESTED})

        await cluster.run(peer_aliases)

        assert cluster.written == {(ns["a"], "worker")}
        assert cluster.reads == (sorted([ns["a"], ns["b"], ns["c"]]), [ns["c"]])
        cluster.delete_service.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_service_aliases_deletes_a_write_that_raced_the_request(
        self, peer_aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """Research R-004: B's deletion was requested between the two reads.

        A has no service, so the second read must cover the owners, not the holder A.
        """
        cluster = _Cluster(after={ns["b"]: DELETION_REQUESTED})

        await cluster.run(peer_aliases)

        assert cluster.reads == (
            sorted([ns["a"], ns["b"], ns["c"]]),
            sorted([ns["b"], ns["c"]]),
        )
        assert cluster.deleted == {(ns["a"], "executor", f"rv-{ns['a']}-executor")}
        assert (
            f"Deleted service alias executor in namespace {ns['a']}: the deletion of "
            f"the deployment in {ns['b']} started after the flow's first read (#503)"
        ) in cluster.messages

    @pytest.mark.parametrize(
        ("state", "deleted"),
        [
            pytest.param(("Terminating", _styrmin_deployment()), False, id="restore"),
            pytest.param(
                ("Terminating", _styrmin_deployment(deletion_timestamp=_TIMESTAMP)),
                False,
                id="restore-deletes-the-cr-with-the-namespace",
            ),
            pytest.param(("Terminating", None), False, id="restore-cr-gone"),
            pytest.param((None, None), False, id="restore-namespace-gone"),
            pytest.param(KUBECTL_DELETE, True, id="kubectl-delete"),
            pytest.param(REQUESTED_AND_TERMINATING, True, id="requested-terminating"),
        ],
    )
    @pytest.mark.asyncio
    async def test_apply_service_aliases_second_read_follows_the_teardown_rule(
        self,
        peer_aliases: list[dict],
        ns: dict[str, str],
        state: _State,
        deleted: bool,
    ) -> None:
        """Rule A: only a deletion of B's deployment, not a restore of its namespace, deletes the write.

        Velero restores B's namespace and no flow runs, so a deleted alias would stay missing.
        """
        cluster = _Cluster(after={ns["b"]: state})

        await cluster.run(peer_aliases)

        assert cluster.written == {(ns["a"], "executor"), (ns["a"], "worker")}
        assert cluster.deleted == (
            {(ns["a"], "executor", f"rv-{ns['a']}-executor")} if deleted else set()
        )

    @pytest.mark.asyncio
    async def test_apply_service_aliases_deletes_a_write_whose_holder_is_also_deleted(
        self, aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """Rule B: the deletion of A and of B were both requested between the reads.

        On the ``kubectl delete styrmindeployment`` path the holder's namespace stays, so the
        flow deletes every write of a deleted owner, whatever namespace holds it.
        """
        cluster = _Cluster(
            after={ns["a"]: DELETION_REQUESTED, ns["b"]: REQUESTED_AND_TERMINATING}
        )

        await cluster.run(aliases)

        assert cluster.deleted == {
            (ns["a"], "executor", f"rv-{ns['a']}-executor"),
            (ns["b"], "intent", f"rv-{ns['b']}-intent"),
            (ns["c"], "intent", f"rv-{ns['c']}-intent"),
        }

    @pytest.mark.asyncio
    async def test_apply_service_aliases_logs_a_delete_that_deleted_nothing(
        self, peer_aliases: list[dict], ns: dict[str, str]
    ) -> None:
        """A 404 or 409 makes ``delete_service`` return False; the log says so."""
        cluster = _Cluster(after={ns["b"]: DELETION_REQUESTED})
        cluster.delete_service.return_value = False

        await cluster.run(peer_aliases)

        assert cluster.deleted == {(ns["a"], "executor", f"rv-{ns['a']}-executor")}
        assert (
            f"Did not delete service alias executor in namespace {ns['a']} of the "
            f"deleted deployment in {ns['b']}: the alias is gone, or another flow "
            "wrote it again (#503)"
        ) in cluster.messages
        assert not any(m.startswith("Deleted service alias") for m in cluster.messages)

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            pytest.param(
                _forbidden({"details": {"causes": [{"type": "NamespaceTerminating"}]}}),
                "403 (the namespace is terminating)",
                id="403-namespace-terminating",
            ),
            pytest.param(
                ApiException(status=404, reason="Not Found"),
                "404 (the namespace or the Service is gone)",
                id="404",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_apply_service_aliases_skips_a_namespace_that_is_gone(
        self, aliases: list[dict], ns: dict[str, str], error: ApiException, reason: str
    ) -> None:
        """Spec User Story 2 scenario 6: B's namespace refuses the write; A completes."""
        cluster = _Cluster(failures={(ns["b"], "intent"): error})

        await cluster.run(aliases)

        assert cluster.apply_service.await_count == 4
        assert (
            f"Skipping service alias {ns['b']}/intent: the write returned {reason}"
            in cluster.messages
        )
        cluster.delete_service.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_service_aliases_raises_on_an_rbac_403(
        self, aliases: list[dict], ns: dict[str, str]
    ) -> None:
        rbac = _forbidden(
            'services is forbidden: User "system:serviceaccount:styrmin:agent" '
            'cannot create resource "services"'
        )
        cluster = _Cluster(failures={(ns["b"], "intent"): rbac})

        with pytest.raises(ApiException) as raised:
            await cluster.run(aliases)

        assert raised.value is rbac
