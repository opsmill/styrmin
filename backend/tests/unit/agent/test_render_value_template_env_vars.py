"""Unit tests for the env var rendering contract of
``ApplicationHelmReleaseBuilder.render_value_template``
(017-post-render-env-vars, T026, FR-007, FR-009, research D-008).

FR-007: Styrmin injects env vars by post-render patch, so the retired
``component_env_vars`` filter fails rendering with a typed error naming the
migration guide. FR-009: ``instance.config.env_vars`` and
``components[<name>].env_vars.config`` stay readable in the rendering context.
"""

from __future__ import annotations

from textwrap import dedent
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
    get_jinja_environment,
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
from styrmin_backend.context.models.helm import (
    ChartInfo,
    HelmInfo,
    RepositoryInfo,
)
from styrmin_backend.operator.pipeline import execute_phase_helmrelease
from styrmin_backend.services.exceptions import RetiredTemplateFilterError

MIGRATION_GUIDE = "https://styrmin.pages.dev/docs/drivers/migrating-env-vars"
RETIRED_FILTER_MESSAGE = (
    "The 'component_env_vars' template filter was removed: Styrmin now injects "
    "env vars into each component's declared component container. Deployment "
    "users: upgrade this deployment to a driver version that declares component "
    "containers. Driver authors: remove the filter from values.j2.yml and declare "
    "components.<name>.container in driver.styrmin.yml. Migration guide: "
    f"{MIGRATION_GUIDE}"
)
RETIRED_FILTER_TEMPLATE = (
    'extraEnv: {{ components | component_env_vars("server") | tojson }}\n'
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _component(
    name: str,
    label_value: str,
    env_vars: dict[str, str] | None,
) -> ComponentContext:
    """Build a minimal ``ComponentContext``. Mirrors the helper in
    ``test_application_builder_env_vars.py`` but trimmed to just the env-vars
    surface this test exercises.
    """
    return ComponentContext(
        name=name,
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": label_value}),
            ),
        ),
        env_vars=(
            ResolvedComponentEnvVars(config=env_vars) if env_vars is not None else None
        ),
    )


def _make_global_context(
    *,
    instance_env_vars: dict[str, str] | None,
    components: ComponentsContext,
    values_template: str = "",
) -> GlobalContext:
    """Build a synthetic ``GlobalContext`` with env vars set at the deployment
    (instance.config) scope and arbitrary per-component scope. Mirrors the
    minimal-valid-context shape from ``test_application_builder_env_vars.py``.
    """
    deployment_id = uuid4()
    namespace = get_kubernetes_reference(deployment_id)
    return GlobalContext(
        cluster=ClusterContext(config=ClusterConfig()),
        environment=EnvironmentContext(name="test", config=EnvironmentConfig()),
        deployment=DeploymentContext(config=DeploymentConfig()),
        instance=InstanceContext(
            config=ResolvedConfig(env_vars=instance_env_vars),
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
                    values_template=values_template,
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


# Probe template — reads both env var paths with the defensive ``or {}``
# accessor pattern.
PROBE_TEMPLATE = dedent(
    """
    deployment_env_vars:
    {%- for name, value in (instance.config.env_vars or {}).items() %}
      - name: {{ name }}
        value: "{{ value }}"
    {%- endfor %}
    worker_env_vars:
    {%- if components.worker is defined and components.worker.env_vars %}
    {%- for name, value in (components.worker.env_vars.config or {}).items() %}
      - name: {{ name }}
        value: "{{ value }}"
    {%- endfor %}
    {%- endif %}
    """
).strip()


def _render(context: GlobalContext) -> dict:
    """Drive ``render_value_template`` and parse its YAML output."""
    return ApplicationHelmReleaseBuilder.render_value_template(
        values_template=PROBE_TEMPLATE,
        context=context,
    )


# ---------------------------------------------------------------------------
# FR-007 — the retired ``component_env_vars`` filter fails loudly
# ---------------------------------------------------------------------------


def _assert_retired_filter_error(error: RetiredTemplateFilterError) -> None:
    assert error.error_code == "RETIRED_TEMPLATE_FILTER"
    assert error.error_metadata == {
        "filter": "component_env_vars",
        "migration_guide": MIGRATION_GUIDE,
    }
    assert str(error) == RETIRED_FILTER_MESSAGE


class TestRetiredComponentEnvVarsFilter:
    """A ``values.j2.yml`` calling ``component_env_vars`` aborts rendering."""

    @pytest.mark.parametrize(
        "server_env_vars",
        [{"LOG_LEVEL": "debug"}, {}, None],
        ids=["env-vars-set", "env-vars-empty", "no-env-vars-block"],
    )
    def test_template_calling_filter_raises_typed_error(
        self, server_env_vars: dict[str, str] | None
    ) -> None:
        """Raises whatever the context holds, so an unmigrated driver fails
        before any user sets env vars rather than silently dropping them later.
        """
        context = _make_global_context(
            instance_env_vars=None,
            components=ComponentsContext(
                root={"server": _component("server", "server-app", server_env_vars)}
            ),
        )

        with pytest.raises(RetiredTemplateFilterError) as exc_info:
            ApplicationHelmReleaseBuilder.render_value_template(
                values_template=RETIRED_FILTER_TEMPLATE, context=context
            )

        _assert_retired_filter_error(exc_info.value)

    def test_filter_stays_registered(self) -> None:
        """Unregistering would give Jinja's generic "no filter named" error at
        compile time instead of the typed error pointing at the migration guide.
        """
        environment = get_jinja_environment()

        assert "component_env_vars" in environment.filters
        environment.from_string(RETIRED_FILTER_TEMPLATE)

    async def test_operator_records_message_without_applying_helm_release(
        self,
    ) -> None:
        """The operator pipeline keeps the message (code and metadata are not
        carried by ``PhaseResult``) and never applies the HelmRelease.
        """
        context = _make_global_context(
            instance_env_vars=None,
            components=ComponentsContext(
                root={"server": _component("server", "server-app", None)}
            ),
            values_template=RETIRED_FILTER_TEMPLATE,
        )
        upsert = AsyncMock()

        with patch(
            "styrmin_backend.agent.service.kubernetes.primitives.upsert_custom_resource",
            upsert,
        ):
            result = await execute_phase_helmrelease(
                crd_spec={"context": context.model_dump(mode="json")},
                namespace=context.instance.namespace,
            )

        assert result.success is False
        assert result.errors == [
            f"Failed to create HelmRelease: {RETIRED_FILTER_MESSAGE}"
        ]
        applied = [call.kwargs["plurals"] for call in upsert.await_args_list]
        assert "helmreleases" not in applied


# ---------------------------------------------------------------------------
# FR-009 — env vars stay readable in the rendering context
# ---------------------------------------------------------------------------


class TestRenderValueTemplateEnvVarsExposure:
    """Env vars on the resolved ``GlobalContext`` stay readable by driver
    templates as data (e.g. ConfigMap content), not for injection.
    """

    def test_both_scopes_set_render_into_template(self) -> None:
        """Deployment-scope env vars + per-component env vars both reach
        the rendered output. (US1 acceptance scenario 1 + 3.)
        """
        components = ComponentsContext(
            root={
                "worker": _component(
                    "worker",
                    "worker-app",
                    {"WORKER_QUEUE": "orders", "LOG_LEVEL": "debug"},
                ),
            }
        )
        context = _make_global_context(
            instance_env_vars={"LOG_LEVEL": "info"},
            components=components,
        )

        result = _render(context)

        assert result["deployment_env_vars"] == [
            {"name": "LOG_LEVEL", "value": "info"},
        ]
        # Worker carries its own env vars exactly as resolved (the merge
        # happens upstream in ``EnvVarsResolver``; this test exercises only
        # the rendering exposure).
        assert {entry["name"] for entry in result["worker_env_vars"]} == {
            "WORKER_QUEUE",
            "LOG_LEVEL",
        }
        worker_by_name = {e["name"]: e["value"] for e in result["worker_env_vars"]}
        assert worker_by_name == {"WORKER_QUEUE": "orders", "LOG_LEVEL": "debug"}

    def test_deployment_only_per_component_absent(self) -> None:
        """Deployment-scope env vars set; component carries no env vars
        (``ComponentContext.env_vars is None``). Defensive ``or {}`` /
        ``is defined`` accessors render an empty list without raising.
        """
        components = ComponentsContext(
            root={"worker": _component("worker", "worker-app", None)}
        )
        context = _make_global_context(
            instance_env_vars={"LOG_LEVEL": "info"},
            components=components,
        )

        result = _render(context)

        assert result["deployment_env_vars"] == [
            {"name": "LOG_LEVEL", "value": "info"},
        ]
        # YAML ``key:\n`` with no list items parses to None — semantically
        # equivalent to "empty / no entries" for a driver template.
        assert result["worker_env_vars"] in (None, [])

    def test_per_component_only_deployment_absent(self) -> None:
        """Per-component env vars set; deployment scope unset
        (``ResolvedConfig.env_vars is None``). With ``exclude_none=True``,
        the ``env_vars`` key is absent from the dump; defensive ``or {}``
        in the probe template handles it.
        """
        components = ComponentsContext(
            root={
                "worker": _component(
                    "worker", "worker-app", {"WORKER_QUEUE": "orders"}
                ),
            }
        )
        context = _make_global_context(
            instance_env_vars=None,
            components=components,
        )

        result = _render(context)

        assert result["deployment_env_vars"] in (None, [])
        assert result["worker_env_vars"] == [
            {"name": "WORKER_QUEUE", "value": "orders"},
        ]

    def test_nothing_set_anywhere_renders_without_raising(self) -> None:
        """No env vars set at any scope: rendering the probe template does
        not raise on undefined keys and both lists render empty.
        """
        components = ComponentsContext(
            root={"worker": _component("worker", "worker-app", None)}
        )
        context = _make_global_context(
            instance_env_vars=None,
            components=components,
        )

        result = _render(context)

        assert result["deployment_env_vars"] in (None, [])
        assert result["worker_env_vars"] in (None, [])

    def test_dump_shape_carries_env_vars_through(self) -> None:
        """Regression-pin on the ``model_dump(exclude_none=True)`` contract. When env vars are set, the dumped dict exposes
        ``instance.config.env_vars`` and
        ``components.worker.env_vars.config`` exactly — keys that the
        rendering probe (and real driver templates) read by name.
        """
        components = ComponentsContext(
            root={
                "worker": _component(
                    "worker", "worker-app", {"WORKER_QUEUE": "orders"}
                ),
            }
        )
        context = _make_global_context(
            instance_env_vars={"LOG_LEVEL": "info"},
            components=components,
        )

        dumped = context.model_dump(exclude_none=True)

        assert dumped["instance"]["config"]["env_vars"] == {"LOG_LEVEL": "info"}
        assert dumped["components"]["worker"]["env_vars"]["config"] == {
            "WORKER_QUEUE": "orders",
        }
