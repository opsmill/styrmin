"""Unit tests for ``build_env_var_patches`` (017-post-render-env-vars, T007, T022).

Pins research D-009: one ``ContainerEnvPatch`` per workload kind for each
component that declares a component container and has resolved env vars, and
the skips that keep containerless or empty components untouched. The scope
cases resolve env vars through the context service before building (FR-004).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import yaml
from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
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
from styrmin_backend.services.context import _populate_component_env_vars
from styrmin_backend.services.env_vars.exceptions import EnvVarPatchRenderingError
from styrmin_backend.services.env_vars.patch_builder import build_env_var_patches

_SAME_AS_NAME = "<component name>"


def _component(
    name: str,
    *,
    label: str | None = None,
    container: str | None = _SAME_AS_NAME,
    env_vars: dict[str, str] | None = None,
    enabled: bool = True,
    is_orphaned: bool = False,
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
    )


def _context(*components: ComponentContext, declare: bool = True) -> GlobalContext:
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
        deployed_services=[],
        components=(
            ComponentsContext(root={c.name: c for c in components}) if declare else None
        ),
    )


@pytest.fixture
def loguru_records() -> Iterator[list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []
    sink_id = logger.add(lambda m: captured.append(m.record), level="INFO")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


class TestEmittedPatches:
    def test_component_with_container_and_env_vars_gets_two_patches(self) -> None:
        context = _context(
            _component(
                "server",
                label="simple-app",
                container="simple-app",
                env_vars={"LOG_LEVEL": "debug"},
            )
        )

        patches = build_env_var_patches(context)

        assert [tp.target.kind for tp in patches] == ["Deployment", "StatefulSet"]
        for tp in patches:
            assert tp.target.label_selector == "app.kubernetes.io/name=simple-app"
            assert tp.target.name is None
            assert isinstance(tp.patch, ContainerEnvPatch)
            assert tp.patch.kind == tp.target.kind
            assert tp.patch.container == "simple-app"
            assert tp.patch.env == {"LOG_LEVEL": "debug"}

    def test_rendered_patch_carries_resolved_env(self) -> None:
        context = _context(
            _component("server", env_vars={"A": "1", "B": "2"}),
        )

        doc = yaml.safe_load(build_env_var_patches(context)[0].render_value()["patch"])

        container = doc["spec"]["template"]["spec"]["containers"][0]
        assert container["name"] == "server"
        assert [e["name"] for e in container["env"]] == ["A", "B"]

    def test_disabled_component_still_gets_patches(self) -> None:
        context = _context(_component("server", env_vars={"A": "1"}, enabled=False))

        assert len(build_env_var_patches(context)) == 2

    def test_only_components_with_container_and_env_vars_get_patches(self) -> None:
        context = _context(
            _component("server", env_vars={"A": "1"}),
            _component("database", container=None, env_vars={"A": "1"}),
            _component("cache", env_vars=None),
            _component("worker", env_vars={"B": "2"}),
        )

        selectors = [tp.target.label_selector for tp in build_env_var_patches(context)]

        assert selectors == [
            "app.kubernetes.io/name=server",
            "app.kubernetes.io/name=server",
            "app.kubernetes.io/name=worker",
            "app.kubernetes.io/name=worker",
        ]


def _env_by_selector(context: GlobalContext) -> dict[str | None, dict[str, str]]:
    return {
        tp.target.label_selector: tp.patch.env
        for tp in build_env_var_patches(context)
        if isinstance(tp.patch, ContainerEnvPatch)
    }


class TestResolvedScopes:
    """US2: resolution merges env -> deployment -> component before the build."""

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


class TestSkips:
    def test_component_without_container_gets_none(self) -> None:
        context = _context(_component("server", container=None, env_vars={"A": "1"}))

        assert build_env_var_patches(context) == []

    def test_component_without_env_vars_gets_none(self) -> None:
        context = _context(_component("server", env_vars=None))

        assert build_env_var_patches(context) == []

    def test_component_with_empty_env_vars_config_gets_none(self) -> None:
        context = _context(_component("server", env_vars={}))

        assert build_env_var_patches(context) == []

    def test_orphaned_env_vars_get_none(self) -> None:
        context = _context(_component("server", env_vars={"A": "1"}, is_orphaned=True))

        assert build_env_var_patches(context) == []

    def test_no_components_declared_gets_empty_list(self) -> None:
        assert build_env_var_patches(_context(declare=False)) == []

    def test_empty_components_gets_empty_list(self) -> None:
        assert build_env_var_patches(_context()) == []


class TestRenderFailure:
    def test_serialisation_failure_raises_typed_operation_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(self: ContainerEnvPatch) -> str:
            raise yaml.representer.RepresenterError("cannot represent")

        monkeypatch.setattr(ContainerEnvPatch, "render_value", _boom)
        context = _context(_component("server", env_vars={"A": "1"}))

        with pytest.raises(EnvVarPatchRenderingError) as excinfo:
            build_env_var_patches(context)

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
            _component("database", container=None, env_vars={"A": "1"}),
        )

        build_env_var_patches(context)

        lines = [r for r in loguru_records if "env_var_patches_built" in r["message"]]
        assert len(lines) == 1
        assert lines[0]["extra"] == {
            "component": "server",
            "container": "server",
            "count": 2,
        }
        assert "s3cr3t-value" not in lines[0]["message"]
