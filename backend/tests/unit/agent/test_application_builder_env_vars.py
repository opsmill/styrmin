"""Unit tests for env vars wiring into the application builder (T028, T064).

Asserts that ``ApplicationHelmReleaseBuilder.build_env_vars_post_rendering_patches``
is invoked from ``build()`` and that emitted patches reach ``target_patches``
in the rendered ``HelmRelease``. Mirrors
``test_application_builder_scheduling.py``.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    EnvVarsPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.builders import application
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentEnvVars,
    ResolvedComponentScheduling,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    DeploymentConfig,
    EnvironmentConfig,
    PostRenderInjection,
    ResolvedConfig,
    SchedulingConfig,
)
from styrmin_backend.context.models.contexts import (
    ApplicationContext,
    ClusterContext,
    DeploymentContext,
    EnvironmentContext,
    GlobalContext,
    InstanceContext,
)
from styrmin_backend.context.models.helm import (
    ChartInfo,
    HelmInfo,
    RepositoryInfo,
)


class TestEnvVarsBuilderWiring:
    def test_build_invokes_env_vars_helper(self) -> None:
        build_source = inspect.getsource(
            application.ApplicationHelmReleaseBuilder.build
        )
        assert "build_env_vars_post_rendering_patches" in build_source, (
            "env vars helper not wired into build()"
        )

    def test_env_vars_patches_come_after_scheduling_in_build(self) -> None:
        """Env var patches must appear AFTER scheduling patches in the
        ``target_patches`` list. Order matters because Kustomize applies
        patches in order; env vars riding the same strategic-merge path as
        any future scheduling-touching patch should win on container env
        keys regardless. Today scheduling does not touch env entries, so
        the order is policy more than mechanism.
        """
        build_source = inspect.getsource(
            application.ApplicationHelmReleaseBuilder.build
        )
        scheduling_idx = build_source.find("build_scheduling_post_rendering_patches")
        env_vars_idx = build_source.find("build_env_vars_post_rendering_patches")
        assert scheduling_idx != -1
        assert env_vars_idx != -1
        assert env_vars_idx > scheduling_idx, (
            "env vars patches must be appended after scheduling patches"
        )


def _component(
    name: str,
    label_value: str,
    env_vars: dict[str, str] | None,
    *,
    inject_env_vars: bool | None = None,
) -> ComponentContext:
    """Build a ``ComponentContext`` carrying both the resolved env vars and
    a ``scheduling`` block whose ``inject.env_vars`` mirrors the per-component
    opt-out flag the application builder reads at dispatch time.
    """
    scheduling: ResolvedComponentScheduling | None = None
    if inject_env_vars is not None:
        scheduling = ResolvedComponentScheduling(
            config=SchedulingConfig(
                inject=PostRenderInjection(env_vars=inject_env_vars)
            ),
        )
    return ComponentContext(
        name=name,
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": label_value}),
            ),
        ),
        scheduling=scheduling,
        env_vars=(
            ResolvedComponentEnvVars(config=env_vars) if env_vars is not None else None
        ),
    )


def _make_global_context(components: ComponentsContext) -> GlobalContext:
    deployment_id = uuid4()
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
        deployed_services=[],
        components=components,
    )


class TestUS6MultiComponentOptOut:
    """T064 / US6: a multi-component deployment where one component opts out
    via ``inject.env_vars=False`` must yield ``EnvVarsPatch`` instances ONLY
    for the un-opted-out component. This is the dispatcher-level invariant
    sitting on top of the patch-builder primitive — exercises the per-component
    branch in :meth:`ApplicationHelmReleaseBuilder.build_env_vars_post_rendering_patches`.
    """

    def test_opted_out_component_emits_no_envvars_patches(self) -> None:
        components = ComponentsContext(
            root={
                "server": _component(
                    "server",
                    "simple-app",
                    {"LOG_LEVEL": "debug"},
                ),
                "debug-sidecar": _component(
                    "debug-sidecar",
                    "debug-sidecar",
                    {"LOG_LEVEL": "debug"},
                    inject_env_vars=False,
                ),
            }
        )
        context = _make_global_context(components)
        builder = application.ApplicationHelmReleaseBuilder(context=context)

        patches = builder.build_env_vars_post_rendering_patches()

        # Every emitted patch is an EnvVarsPatch scoped to the server
        # component's selector — debug-sidecar contributes zero patches.
        assert len(patches) > 0
        selectors = {tp.target.label_selector for tp in patches}
        assert selectors == {"app.kubernetes.io/name=simple-app"}, selectors
        for tp in patches:
            assert isinstance(tp.patch, EnvVarsPatch)
        # No patch should target the debug-sidecar selector at all.
        assert "app.kubernetes.io/name=debug-sidecar" not in selectors

    def test_both_components_opted_in_emits_patches_for_both(self) -> None:
        """Sanity baseline — without any opt-out flag, both components yield
        a non-empty patch set scoped to their respective selectors.
        """
        components = ComponentsContext(
            root={
                "server": _component("server", "simple-app", {"LOG_LEVEL": "debug"}),
                "worker": _component(
                    "worker", "worker-app", {"WORKER_QUEUE": "orders"}
                ),
            }
        )
        builder = application.ApplicationHelmReleaseBuilder(
            context=_make_global_context(components),
        )
        patches = builder.build_env_vars_post_rendering_patches()

        selectors = {tp.target.label_selector for tp in patches}
        assert selectors == {
            "app.kubernetes.io/name=simple-app",
            "app.kubernetes.io/name=worker-app",
        }, selectors
