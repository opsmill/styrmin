"""Unit tests for env-vars exposure through ``ApplicationBuilder.render_value_template``.

Phase 2 / T004 — verifies FR-001 + FR-002 of 010-driver-env-var-consumption:
the platform exposes the deployment-effective env-vars dict to driver templates
as ``instance.config.env_vars`` and per-component env-vars as
``components[<name>].env_vars.config``. Both fields ride through
``render_value_template`` via ``GlobalContext.model_dump(exclude_none=True)``
into the Jinja rendering dict.

These tests are the safety net for Phase 4's deletion of the broken
post-render injection layer: deleting that layer is only safe when the
template-context exposure path is verified to work. If any of these tests
fail against the pre-deletion codebase, do NOT proceed to Phase 4.

Test cases:
1. Both scopes set: deployment + per-component env vars render correctly.
2. Deployment-only set: per-component lists render empty (defensive ``or {}``).
3. Per-component-only set: deployment list renders empty.
4. Nothing set anywhere: both lists empty, no Jinja UndefinedError.
"""

from __future__ import annotations

from textwrap import dedent
from uuid import uuid4

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
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


# Probe template — exercises both consumption surfaces with the defensive
# ``or {}`` accessor pattern documented in FR-003 and demonstrated by the
# simple-app driver example in research §3.
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
# T004 — FR-001 / FR-002 verification cases
# ---------------------------------------------------------------------------


class TestRenderValueTemplateEnvVarsExposure:
    """Verify env vars set on the resolved ``GlobalContext`` reach driver
    templates through ``ApplicationHelmReleaseBuilder.render_value_template``.
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
        """Edge case from spec.md — no env vars set at any scope. Rendering
        the probe template MUST NOT raise on undefined keys; both lists
        render empty. This is the load-bearing "templates won't blow up
        when operators haven't set anything" guarantee from FR-003.
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
        """Regression-pin on FR-003 / the ``model_dump(exclude_none=True)``
        contract. When env vars are set, the dumped dict exposes
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
