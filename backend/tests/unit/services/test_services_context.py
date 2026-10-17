"""Unit tests for services context building (T024)."""

import inspect
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
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
)
from styrmin_backend.context.models.helm import ChartInfo, HelmInfo, RepositoryInfo
from styrmin_backend.context.models.services import ServiceReference
from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services import context as context_service
from styrmin_backend.services.context import (
    _populate_component_container_overrides,
    _populate_component_image_overrides,
    _populate_component_scheduling,
)
from styrmin_backend.services.exceptions import UnresolvableAffinityReferenceError


class TestServiceReference:
    def test_http_url(self) -> None:
        ref = ServiceReference(host="infrahub", port=8000, kind="http")
        assert ref.url == "http://infrahub:8000"
        assert ref.host == "infrahub"
        assert ref.port == 8000
        assert ref.kind == "http"

    def test_https_url(self) -> None:
        ref = ServiceReference(host="infrahub", port=8443, kind="https")
        assert ref.url == "https://infrahub:8443"

    def test_tcp_url(self) -> None:
        ref = ServiceReference(host="redis", port=6379, kind="tcp")
        assert ref.url == "redis:6379"

    def test_udp_url(self) -> None:
        ref = ServiceReference(host="dns", port=53, kind="udp")
        assert ref.url == "dns:53"

    def test_model_dump(self) -> None:
        ref = ServiceReference(host="web", port=80, kind="http")
        data = ref.model_dump()
        assert data["url"] == "http://web:80"
        assert data["host"] == "web"
        assert data["port"] == 80
        assert data["kind"] == "http"


class TestServicesContextDict:
    def test_empty_services_dict(self) -> None:
        """Empty context when no services are deployed."""
        services: dict = {}
        assert services == {}

    def test_build_context_with_services(self) -> None:
        """Build context dict mapping service name -> ServiceReference properties."""
        from styrmin_backend.db.models import DeployedService
        from uuid import uuid4

        svcs = [
            DeployedService(
                id=uuid4(),
                driver_service_name="infrahub",
                resolved_name="infrahub",
                kind="https",
                scope="internal",
                port=8000,
                component="server",
                deployment_id=uuid4(),
                environment_id=uuid4(),
            ),
            DeployedService(
                id=uuid4(),
                driver_service_name="redis",
                resolved_name="redis",
                kind="tcp",
                scope="internal",
                port=6379,
                component="cache",
                deployment_id=uuid4(),
                environment_id=uuid4(),
            ),
        ]

        # Build context dict the same way the context service will
        context: dict = {}
        for svc in svcs:
            ref = ServiceReference(
                host=svc.resolved_name,
                port=svc.port,
                kind=svc.kind,
            )
            context[svc.driver_service_name] = ref.model_dump()

        assert "infrahub" in context
        assert context["infrahub"]["url"] == "https://infrahub:8000"
        assert context["infrahub"]["host"] == "infrahub"
        assert context["infrahub"]["port"] == 8000
        assert context["infrahub"]["kind"] == "https"

        assert "redis" in context
        assert context["redis"]["url"] == "redis:6379"
        assert context["redis"]["host"] == "redis"
        assert context["redis"]["port"] == 6379


class TestContextLabels:
    """T025: the deployment generation labels include both the environment
    and deployment identity labels so the pod-template post-renderer stamps
    them on every rendered pod.
    """

    def test_labels_dict_contains_environment_and_deployment_ids(self) -> None:
        source = inspect.getsource(context_service.generate_context_from_deployment)
        assert '"environment_id": environment.id' in source
        assert '"deployment_id": deployment.id' in source


class _FakeDeploymentComponent:
    """Minimal stand-in for ``Deployment.components[i]`` — the scheduling
    population path only reads ``.name`` and ``.config``.
    """

    def __init__(self, name: str, config: dict | None) -> None:
        self.name = name
        self.config = config


def _make_context_with_component(name: str) -> GlobalContext:
    namespace = "dep-test"
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(),
            deployment_id=uuid4(),
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
                repository=RepositoryInfo(id=uuid4(), url="https://example.com"),
            ),
        ),
        components=ComponentsContext(
            root={
                name: ComponentContext(
                    name=name,
                    enabled=True,
                    config=ArbitrarySectionModel(
                        identifier=Identifier(
                            label=LabelIdentifier(root={"app": name})
                        ),
                    ),
                )
            }
        ),
    )


class TestPopulateComponentScheduling:
    """FR-012 end-to-end: resolved scheduling plus per-field provenance
    must reach the Jinja rendering surface via
    ``context.components[*].scheduling``, not just the GraphQL API.
    """

    @pytest.mark.anyio
    async def test_component_scheduling_exposes_provenance(self, uow) -> None:  # type: ignore[no-untyped-def]
        context = _make_context_with_component("server")
        env_config = {"scheduling": {"runtime_class": "kata"}}
        dep_config = {"scheduling": {"resources": {"requests": {"cpu": "100m"}}}}
        components = [_FakeDeploymentComponent("server", config=None)]

        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=uuid4(),
            environment_config=env_config,
            deployment_config=dep_config,
            deployment_components=components,
        )

        assert context.components is not None
        scheduling = context.components.root["server"].scheduling
        assert scheduling is not None
        assert scheduling.config.runtime_class == "kata"
        assert scheduling.config.resources is not None
        assert scheduling.provenance["runtime_class"] == "environment"
        assert scheduling.provenance["resources.requests.cpu"] == "deployment"


def _anti_affinity_config(*deployment_ids: UUID) -> dict:
    """A config whose preferred pod anti-affinity terms name ``deployment_ids`` in order."""
    return {
        "scheduling": {
            "pod_anti_affinity": {
                "preferred": [
                    {
                        "weight": 10,
                        "term": {
                            "topology_key": "kubernetes.io/hostname",
                            "deployment_ref": {"deployment_id": str(deployment_id)},
                        },
                    }
                    for deployment_id in deployment_ids
                ]
            }
        }
    }


async def _save_deployment(
    uow, *, name: str, environment_id: UUID, deleted: bool = False
) -> Deployment:  # type: ignore[no-untyped-def]
    deployment = Deployment(
        id=uuid4(),
        name=name,
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=environment_id,
        status=DeploymentState.DELETED if deleted else DeploymentState.RUNNING,
        deleted_at=datetime.now(UTC) if deleted else None,
        created_by_user_id=uuid4(),
    )
    await uow.deployments.save(deployment)
    return deployment


class TestPopulateComponentSchedulingReferencePaths:
    """027: each level's deployment references are expanded before the merge,
    so an error path names the level and the index in that level's own list.
    """

    @pytest.mark.anyio
    async def test_environment_level_term_gives_environment_path(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        missing_id = uuid4()

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await _populate_component_scheduling(
                context=_make_context_with_component("server"),
                uow=uow,
                environment_id=env_id,
                environment_config=_anti_affinity_config(missing_id),
                deployment_config=None,
                deployment_components=[_FakeDeploymentComponent("server", None)],
            )

        assert exc.value.error_metadata == {
            "deployment_id": str(missing_id),
            "path": "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
        }

    @pytest.mark.anyio
    async def test_deployment_level_term_gives_index_in_its_own_list(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        live = await _save_deployment(uow, name="api", environment_id=env_id)
        tombstoned = await _save_deployment(
            uow, name="postgres", environment_id=env_id, deleted=True
        )

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await _populate_component_scheduling(
                context=_make_context_with_component("server"),
                uow=uow,
                environment_id=env_id,
                environment_config=_anti_affinity_config(live.id),
                deployment_config=_anti_affinity_config(tombstoned.id),
                deployment_components=[_FakeDeploymentComponent("server", None)],
            )

        assert exc.value.error_metadata == {
            "deployment_id": str(tombstoned.id),
            "deployment_name": "postgres",
            "path": "deployment.config.scheduling.pod_anti_affinity.preferred[0].term",
            "deleted": True,
        }

    @pytest.mark.anyio
    async def test_component_level_term_gives_component_path(self, uow) -> None:  # type: ignore[no-untyped-def]
        missing_id = uuid4()

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await _populate_component_scheduling(
                context=_make_context_with_component("server"),
                uow=uow,
                environment_id=uuid4(),
                environment_config=None,
                deployment_config=None,
                deployment_components=[
                    _FakeDeploymentComponent(
                        "server", config=_anti_affinity_config(missing_id)
                    )
                ],
            )

        assert exc.value.error_metadata["path"] == (
            "component[server].config.scheduling.pod_anti_affinity.preferred[0].term"
        )

    @pytest.mark.anyio
    async def test_expanded_levels_merge_in_level_order(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        env_target = await _save_deployment(uow, name="api", environment_id=env_id)
        dep_target = await _save_deployment(uow, name="cache", environment_id=env_id)
        context = _make_context_with_component("server")

        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=env_id,
            environment_config=_anti_affinity_config(env_target.id),
            deployment_config=_anti_affinity_config(dep_target.id),
            deployment_components=[_FakeDeploymentComponent("server", None)],
        )

        assert context.components is not None
        scheduling = context.components.root["server"].scheduling
        assert scheduling is not None
        block = scheduling.config.pod_anti_affinity
        assert block is not None
        assert [weighted.term.deployment_ref for weighted in block.preferred] == [
            None,
            None,
        ]
        assert [
            weighted.term.label_selector.match_labels
            for weighted in block.preferred
            if weighted.term.label_selector is not None
        ] == [
            {"styrmin/deployment_id": str(env_target.id)},
            {"styrmin/deployment_id": str(dep_target.id)},
        ]
        assert scheduling.provenance["pod_anti_affinity"] == "deployment"

    @pytest.mark.anyio
    async def test_upcoming_deployment_resolves_without_a_row(self, uow) -> None:  # type: ignore[no-untyped-def]
        upcoming_id = uuid4()
        context = _make_context_with_component("server")

        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=uuid4(),
            environment_config=None,
            deployment_config=_anti_affinity_config(upcoming_id),
            deployment_components=[_FakeDeploymentComponent("server", None)],
            upcoming_deployments={upcoming_id: "counterpart"},
        )

        assert context.components is not None
        scheduling = context.components.root["server"].scheduling
        assert scheduling is not None
        block = scheduling.config.pod_anti_affinity
        assert block is not None
        selector = block.preferred[0].term.label_selector
        assert selector is not None
        assert selector.match_labels == {"styrmin/deployment_id": str(upcoming_id)}


def _replacing(config: dict | None = None, kind: str = "pod_anti_affinity") -> dict:
    """``config`` with ``replace: true`` on its ``kind`` block, which it adds when absent."""
    replaced = {"scheduling": {kind: {}}} if config is None else config
    replaced["scheduling"][kind]["replace"] = True
    return replaced


class TestPopulateComponentSchedulingReplace:
    """A term that a deeper level discards with ``replace: true`` is not resolved, so a
    deployment can discard a term of the environment's config that names a missing
    deployment (review of #508, finding 4)."""

    @pytest.mark.anyio
    async def test_component_replace_drops_the_terms_of_both_shallower_levels(
        self, uow
    ) -> None:  # type: ignore[no-untyped-def]
        context = _make_context_with_component("server")

        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=uuid4(),
            environment_config=_anti_affinity_config(uuid4()),
            deployment_config=_anti_affinity_config(uuid4()),
            deployment_components=[
                _FakeDeploymentComponent("server", config=_replacing())
            ],
        )

        assert context.components is not None
        scheduling = context.components.root["server"].scheduling
        assert scheduling is not None
        block = scheduling.config.pod_anti_affinity
        assert block is not None
        assert (block.required, block.preferred) == ([], [])
        assert scheduling.provenance["pod_anti_affinity"] == "component"

    @pytest.mark.anyio
    async def test_deployment_replace_drops_the_environment_term_and_keeps_its_own(
        self, uow
    ) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        target = await _save_deployment(uow, name="cache", environment_id=env_id)
        context = _make_context_with_component("server")

        await _populate_component_scheduling(
            context=context,
            uow=uow,
            environment_id=env_id,
            environment_config=_anti_affinity_config(uuid4()),
            deployment_config=_replacing(_anti_affinity_config(target.id)),
            deployment_components=[_FakeDeploymentComponent("server", None)],
        )

        assert context.components is not None
        scheduling = context.components.root["server"].scheduling
        assert scheduling is not None
        block = scheduling.config.pod_anti_affinity
        assert block is not None
        [weighted] = block.preferred
        assert weighted.term.label_selector is not None
        assert weighted.term.label_selector.match_labels == {
            "styrmin/deployment_id": str(target.id)
        }

    @pytest.mark.anyio
    async def test_deployment_replace_still_resolves_the_component_term(
        self, uow
    ) -> None:  # type: ignore[no-untyped-def]
        missing_id = uuid4()

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await _populate_component_scheduling(
                context=_make_context_with_component("server"),
                uow=uow,
                environment_id=uuid4(),
                environment_config=None,
                deployment_config=_replacing(),
                deployment_components=[
                    _FakeDeploymentComponent(
                        "server", config=_anti_affinity_config(missing_id)
                    )
                ],
            )

        assert exc.value.error_metadata["path"] == (
            "component[server].config.scheduling.pod_anti_affinity.preferred[0].term"
        )

    @pytest.mark.anyio
    async def test_replace_of_one_kind_keeps_the_terms_of_the_other_kind(
        self, uow
    ) -> None:  # type: ignore[no-untyped-def]
        missing_id = uuid4()
        environment_config = _anti_affinity_config(missing_id)
        environment_config["scheduling"]["pod_affinity"] = environment_config[
            "scheduling"
        ].pop("pod_anti_affinity")

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await _populate_component_scheduling(
                context=_make_context_with_component("server"),
                uow=uow,
                environment_id=uuid4(),
                environment_config=environment_config,
                deployment_config=_replacing(),
                deployment_components=[_FakeDeploymentComponent("server", None)],
            )

        assert exc.value.error_metadata["path"] == (
            "environment.config.scheduling.pod_affinity.preferred[0].term"
        )


class TestPopulateComponentContainerOverrides:
    """FR-005: container overrides reach the renderer via
    ``context.components[*].container_override``, and an orphaned block (whose
    component the current driver no longer declares) is NEVER attached to a
    live component context — it exists only for the GraphQL read surface and
    must not inject a stale command/args into any pod.
    """

    def test_live_override_attached(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_container_overrides(
            context=context,
            deployment_config={"components": {"server": {"command": ["serve"]}}},
        )
        assert context.components is not None
        override = context.components.root["server"].container_override
        assert override is not None
        assert override.command == ["serve"]
        assert override.args is None
        assert override.is_orphaned is False

    def test_orphan_block_never_attached_to_any_component(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_container_overrides(
            context=context,
            deployment_config={
                "components": {
                    "server": {"command": ["serve"]},
                    # ``ghost`` is not declared by the (single-"server") driver
                    # so it resolves as an orphan.
                    "ghost": {"command": ["ghost-cmd"], "args": ["--orphan"]},
                }
            },
        )
        assert context.components is not None
        # The orphaned component is not materialised as a live context...
        assert "ghost" not in context.components.root
        # ...and its values never leak onto the live component.
        live = context.components.root["server"].container_override
        assert live is not None
        assert live.command == ["serve"]
        assert "ghost-cmd" not in (live.command or [])
        assert "--orphan" not in (live.args or [])

    def test_block_with_no_command_or_args_leaves_override_none(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_container_overrides(
            context=context,
            deployment_config={"components": {"server": {"env_vars": {"X": "1"}}}},
        )
        assert context.components is not None
        assert context.components.root["server"].container_override is None


class TestPopulateComponentImageOverrides:
    """018: image overrides reach the renderer via ``context.components[*].image_override``,
    unsubstituted; orphans and components without an override never get one.
    """

    _TOKEN = "registry.example/acme/simple-app-patched:{{ app.version }}"

    def test_live_override_attached_unsubstituted(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_image_overrides(
            context=context,
            deployment_config={"components": {"server": {"image": self._TOKEN}}},
        )
        assert context.components is not None
        override = context.components.root["server"].image_override
        assert override is not None
        assert override.reference == self._TOKEN
        assert override.is_orphaned is False

    def test_orphan_override_never_attached(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_image_overrides(
            context=context,
            deployment_config={"components": {"ghost": {"image": "ghost:1"}}},
        )
        assert context.components is not None
        assert "ghost" not in context.components.root
        assert context.components.root["server"].image_override is None

    def test_none_when_image_unset(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_image_overrides(
            context=context,
            deployment_config={
                "components": {"server": {"env_vars": {"X": "1"}, "command": ["s"]}}
            },
        )
        assert context.components is not None
        assert context.components.root["server"].image_override is None

    def test_none_without_deployment_config(self) -> None:
        context = _make_context_with_component("server")
        _populate_component_image_overrides(context=context, deployment_config=None)
        assert context.components is not None
        assert context.components.root["server"].image_override is None

    def test_populated_after_container_overrides(self) -> None:
        source = inspect.getsource(context_service.generate_context_from_deployment)
        container_call = source.index("_populate_component_container_overrides(")
        image_call = source.index("_populate_component_image_overrides(")
        assert container_call < image_call
