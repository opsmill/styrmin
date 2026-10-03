"""Unit tests for ``build_component_container_patches`` (018-component-image-overrides, T007).

Pins contracts/post-render-patch.md: per workload kind, a strategic merge naming the component
container (with env entries when env vars apply) followed by the JSON6902 guard, which also sets
the image when an override applies. The env cases moved here from the 017 env-var builder tests;
the scope cases resolve env vars through the context service before building.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import yaml
from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ComponentContainerPatch,
    ContainerEnvPatch,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentEnvVars,
    ResolvedComponentImageOverride,
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
from styrmin_backend.services.component_container.exceptions import (
    ComponentContainerPatchRenderingError,
)
from styrmin_backend.services.component_container.patch_builder import (
    build_component_container_patches,
)
from styrmin_backend.services.context import _populate_component_env_vars
from styrmin_backend.services.image_overrides.exceptions import (
    InvalidImageReferenceError,
)

_SAME_AS_NAME = "<component name>"
_PATCHED = "registry.example/acme/simple-app-patched:0.1.0"


def _component(  # noqa: PLR0913
    name: str,
    *,
    label: str | None = None,
    container: str | None = _SAME_AS_NAME,
    env_vars: dict[str, str] | None = None,
    enabled: bool = True,
    is_orphaned: bool = False,
    image: str | None = None,
    image_orphaned: bool = False,
) -> ComponentContext:
    return ComponentContext(
        name=name,
        enabled=enabled,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": label or name})
            ),
            container=name if container == _SAME_AS_NAME else container,
        ),
        env_vars=(
            ResolvedComponentEnvVars(config=env_vars, is_orphaned=is_orphaned)
            if env_vars is not None
            else None
        ),
        image_override=(
            ResolvedComponentImageOverride(reference=image, is_orphaned=image_orphaned)
            if image is not None
            else None
        ),
    )


def _context(
    *components: ComponentContext, declare: bool = True, version: str = "1.0.0"
) -> GlobalContext:
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(env_vars={"DEPLOYMENT_ONLY": "x"}),
            deployment_id=deployment_id,
            namespace=namespace,
            release_reference=namespace,
        ),
        app=ApplicationContext(
            name="test-app",
            version=version,
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
        deployed_services=[],
        components=(
            ComponentsContext(root={c.name: c for c in components}) if declare else None
        ),
    )


def _env_patches(context: GlobalContext) -> list[ContainerEnvPatch]:
    return [
        tp.patch
        for tp in build_component_container_patches(context)
        if isinstance(tp.patch, ContainerEnvPatch)
    ]


def _guard_patches(context: GlobalContext) -> list[ComponentContainerPatch]:
    return [
        tp.patch
        for tp in build_component_container_patches(context)
        if isinstance(tp.patch, ComponentContainerPatch)
    ]


@pytest.fixture
def loguru_records() -> Iterator[list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []
    sink_id = logger.add(lambda m: captured.append(m.record), level="INFO")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


class TestEnvOnly:
    def test_merge_then_guard_per_kind(self) -> None:
        context = _context(
            _component(
                "server",
                label="simple-app",
                container="simple-app",
                env_vars={"LOG_LEVEL": "debug"},
            )
        )

        patches = build_component_container_patches(context)

        assert [(tp.target.kind, type(tp.patch)) for tp in patches] == [
            ("Deployment", ContainerEnvPatch),
            ("Deployment", ComponentContainerPatch),
            ("StatefulSet", ContainerEnvPatch),
            ("StatefulSet", ComponentContainerPatch),
        ]
        for tp in patches:
            assert tp.target.label_selector == "app.kubernetes.io/name=simple-app"
            assert tp.target.name is None
            assert tp.patch.kind == tp.target.kind
            assert tp.patch.container == "simple-app"
            if isinstance(tp.patch, ContainerEnvPatch):
                assert tp.patch.env == {"LOG_LEVEL": "debug"}
            else:
                assert isinstance(tp.patch, ComponentContainerPatch)
                assert tp.patch.component == "server"
                assert tp.patch.image is None

    def test_rendered_merge_carries_resolved_env(self) -> None:
        context = _context(_component("server", env_vars={"A": "1", "B": "2"}))

        doc = yaml.safe_load(
            build_component_container_patches(context)[0].render_value()["patch"]
        )

        container = doc["spec"]["template"]["spec"]["containers"][0]
        assert container["name"] == "server"
        assert [e["name"] for e in container["env"]] == ["A", "B"]

    def test_rendered_guard_restores_the_chart_image(self) -> None:
        context = _context(_component("server", env_vars={"A": "1"}))

        ops = yaml.safe_load(
            build_component_container_patches(context)[1].render_value()["patch"]
        )

        assert [op["op"] for op in ops] == ["move", "copy", "remove", "move", "move"]

    def test_disabled_component_still_gets_patches(self) -> None:
        context = _context(_component("server", env_vars={"A": "1"}, enabled=False))

        assert len(build_component_container_patches(context)) == 4

    def test_only_components_with_container_and_override_get_patches(self) -> None:
        context = _context(
            _component("server", env_vars={"A": "1"}),
            _component("database", container=None, env_vars={"A": "1"}),
            _component("cache", env_vars=None),
            _component("worker", env_vars={"B": "2"}),
        )

        selectors = [
            tp.target.label_selector
            for tp in build_component_container_patches(context)
        ]

        assert (
            selectors
            == ["app.kubernetes.io/name=server"] * 4
            + ["app.kubernetes.io/name=worker"] * 4
        )


class TestImageOverride:
    def test_image_only_gets_name_only_merge_and_image_guard(self) -> None:
        context = _context(
            _component(
                "server", label="simple-app", container="simple-app", image=_PATCHED
            )
        )

        patches = build_component_container_patches(context)

        assert [(tp.target.kind, type(tp.patch)) for tp in patches] == [
            ("Deployment", ContainerEnvPatch),
            ("Deployment", ComponentContainerPatch),
            ("StatefulSet", ContainerEnvPatch),
            ("StatefulSet", ComponentContainerPatch),
        ]
        assert [p.env for p in _env_patches(context)] == [{}, {}]
        assert [p.image for p in _guard_patches(context)] == [_PATCHED, _PATCHED]
        merge = yaml.safe_load(patches[0].render_value()["patch"])
        assert merge["spec"]["template"]["spec"]["containers"] == [
            {"name": "simple-app"}
        ]

    def test_env_and_image_share_one_merge_and_one_guard_per_kind(self) -> None:
        context = _context(
            _component("server", env_vars={"LOG_LEVEL": "debug"}, image=_PATCHED)
        )

        assert len(build_component_container_patches(context)) == 4
        assert [p.env for p in _env_patches(context)] == [{"LOG_LEVEL": "debug"}] * 2
        assert [p.image for p in _guard_patches(context)] == [_PATCHED] * 2

    def test_app_version_token_resolves_from_context(self) -> None:
        context = _context(
            _component("server", image="registry.example/acme/app:{{ app.version }}"),
            version="0.2.0",
        )

        assert [p.image for p in _guard_patches(context)] == [
            "registry.example/acme/app:0.2.0"
        ] * 2

    def test_invalid_after_substitution_raises_typed_error(self) -> None:
        context = _context(
            _component("server", image="app:{{ app.version }}"),
            version="1.0.0+build",
        )

        with pytest.raises(InvalidImageReferenceError) as excinfo:
            build_component_container_patches(context)

        assert excinfo.value.error_code == "INVALID_IMAGE_REFERENCE"
        assert excinfo.value.error_metadata == {
            "component_name": "server",
            "reference": "app:{{ app.version }}",
            "reason": "after_substitution",
            "application_version": "1.0.0+build",
        }

    def test_orphan_image_is_skipped(self) -> None:
        context = _context(_component("server", image=_PATCHED, image_orphaned=True))

        assert build_component_container_patches(context) == []

    def test_orphan_image_with_env_vars_gets_env_only_guard(self) -> None:
        context = _context(
            _component(
                "server", env_vars={"A": "1"}, image=_PATCHED, image_orphaned=True
            )
        )

        assert [p.image for p in _guard_patches(context)] == [None, None]

    def test_orphaned_env_vars_with_image_get_name_only_merge(self) -> None:
        context = _context(
            _component("server", env_vars={"A": "1"}, is_orphaned=True, image=_PATCHED)
        )

        assert [p.env for p in _env_patches(context)] == [{}, {}]
        assert [p.image for p in _guard_patches(context)] == [_PATCHED] * 2

    def test_image_on_component_without_container_is_not_applied_nor_validated(
        self,
    ) -> None:
        context = _context(
            _component("server", container=None, image="app:{{ app.version }}"),
            version="1.0.0+build",
        )

        assert build_component_container_patches(context) == []


class TestNoOverrides:
    def test_context_without_overrides_yields_no_patches(self) -> None:
        # SC-002 golden: nothing new is emitted for a deployment without overrides.
        context = _context(
            _component("server"),
            _component("database", container=None),
            _component("worker", label="worker", container="worker-main"),
        )

        assert build_component_container_patches(context) == []


def _env_by_selector(context: GlobalContext) -> dict[str | None, dict[str, str]]:
    return {
        tp.target.label_selector: tp.patch.env
        for tp in build_component_container_patches(context)
        if isinstance(tp.patch, ContainerEnvPatch)
    }


class TestResolvedScopes:
    """017 US2: resolution merges env -> deployment -> component before the build."""

    def test_deepest_scope_wins_per_component(self) -> None:
        context = _context(_component("server"), _component("database"))

        _populate_component_env_vars(
            context=context,
            environment_config={"env_vars": {"LOG_LEVEL": "info", "REGION": "eu"}},
            deployment_config={
                "env_vars": {"LOG_LEVEL": "warn"},
                "components": {"server": {"env_vars": {"LOG_LEVEL": "debug"}}},
            },
        )

        assert _env_by_selector(context) == {
            "app.kubernetes.io/name=server": {"LOG_LEVEL": "debug", "REGION": "eu"},
            "app.kubernetes.io/name=database": {"LOG_LEVEL": "warn", "REGION": "eu"},
        }

    def test_deployment_scope_skips_component_without_container(self) -> None:
        context = _context(_component("server"), _component("database", container=None))

        _populate_component_env_vars(
            context=context,
            environment_config=None,
            deployment_config={"env_vars": {"LOG_LEVEL": "debug"}},
        )

        assert context.components is not None
        database = context.components.root["database"]
        assert database.env_vars is not None
        assert database.env_vars.config == {"LOG_LEVEL": "debug"}
        assert _env_by_selector(context) == {
            "app.kubernetes.io/name=server": {"LOG_LEVEL": "debug"},
        }

    def test_stored_values_on_component_that_lost_its_container_emit_none(
        self,
    ) -> None:
        # 017 FR-005: a driver upgrade dropped the container; stored values stay resolved.
        context = _context(_component("server", container=None))

        _populate_component_env_vars(
            context=context,
            environment_config=None,
            deployment_config={
                "components": {"server": {"env_vars": {"LOG_LEVEL": "debug"}}}
            },
        )

        assert context.components is not None
        server = context.components.root["server"]
        assert server.env_vars is not None
        assert server.env_vars.config == {"LOG_LEVEL": "debug"}
        assert server.env_vars.is_orphaned is False
        assert build_component_container_patches(context) == []


class TestSkips:
    def test_component_without_container_gets_none(self) -> None:
        context = _context(_component("server", container=None, env_vars={"A": "1"}))

        assert build_component_container_patches(context) == []

    def test_component_without_env_vars_gets_none(self) -> None:
        context = _context(_component("server", env_vars=None))

        assert build_component_container_patches(context) == []

    def test_component_with_empty_env_vars_config_gets_none(self) -> None:
        context = _context(_component("server", env_vars={}))

        assert build_component_container_patches(context) == []

    def test_orphaned_env_vars_get_none(self) -> None:
        context = _context(_component("server", env_vars={"A": "1"}, is_orphaned=True))

        assert build_component_container_patches(context) == []

    def test_no_components_declared_gets_empty_list(self) -> None:
        assert build_component_container_patches(_context(declare=False)) == []

    def test_empty_components_gets_empty_list(self) -> None:
        assert build_component_container_patches(_context()) == []


class TestRenderFailure:
    @pytest.mark.parametrize("patch_type", [ContainerEnvPatch, ComponentContainerPatch])
    def test_serialisation_failure_raises_typed_operation_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        patch_type: type[ContainerEnvPatch | ComponentContainerPatch],
    ) -> None:
        def _boom(self: object) -> str:
            raise yaml.representer.RepresenterError("cannot represent")

        monkeypatch.setattr(patch_type, "render_value", _boom)
        context = _context(_component("server", env_vars={"A": "1"}, image=_PATCHED))

        with pytest.raises(ComponentContainerPatchRenderingError) as excinfo:
            build_component_container_patches(context)

        assert excinfo.value.error_code == "OPERATION_FAILED"
        assert excinfo.value.error_metadata == {
            "kind": "Deployment",
            "label_selector": "app.kubernetes.io/name=server",
        }
        assert "Deployment" in str(excinfo.value)


class TestLogging:
    def test_logs_one_line_per_component_without_values(
        self, loguru_records: list[dict[str, Any]]
    ) -> None:
        context = _context(
            _component("server", env_vars={"SECRET_TOKEN": "s3cr3t-value", "B": "2"}),
            _component("worker", image=_PATCHED),
            _component("database", container=None, env_vars={"A": "1"}),
        )

        build_component_container_patches(context)

        lines = [
            r
            for r in loguru_records
            if "component_container_patches_built" in r["message"]
        ]
        assert [line["extra"] for line in lines] == [
            {
                "component": "server",
                "container": "server",
                "env_var_count": 2,
                "image_override": False,
            },
            {
                "component": "worker",
                "container": "worker",
                "env_var_count": 0,
                "image_override": True,
            },
        ]
        for line in lines:
            assert "s3cr3t-value" not in line["message"]
            assert _PATCHED not in line["message"]
