"""Unit tests for container `command`/`args` exposure through
``ApplicationHelmReleaseBuilder.render_value_template`` (014-component-container-overrides).

Mirrors ``test_render_value_template_env_vars.py`` but verifies the
**empty-list-marker** contract (ADR-045 §2): the ``component_command`` /
``component_args`` Jinja filters return the resolved list when set, or **``[]``**
(never ``None``) when unset. The driver template emits the key unconditionally
and the chart's ``{{- with }}`` guard treats ``[]`` as falsy so the chart/image
default flows through. The always-present key (empty-list marker, not an omitted
key) is what lets a *cleared* override propagate under the operator's RFC 7386
JSON merge-patch HelmRelease apply.

Test cases (contracts/jinja-filters.md §Unit tests):

1. Both set → both keys rendered.
2. ``command`` set, ``args`` unset → ``command:`` is the list, ``args:`` is
   ``[]`` (present-but-empty; the chart's ``{{- with }}`` guard skips it so the
   chart default flows through). [US2 Sc.2]
3. Neither set → both keys present as ``[]``, no ``UndefinedError``.
4. Empty-string element ``["sh", "-c", ""]`` rendered verbatim. [US4 Sc.4]
5. Filters return ``[]`` (not ``None``) for absent component / missing block.
"""

from __future__ import annotations

from textwrap import dedent
from uuid import uuid4

from styrmin_backend.agent.service.kubernetes.resources.builders.application import (
    ApplicationHelmReleaseBuilder,
    component_args,
    component_command,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentContainerOverride,
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
    *,
    command: list[str] | None = None,
    args: list[str] | None = None,
    override_set: bool = True,
) -> ComponentContext:
    """Build a minimal ``ComponentContext`` carrying a container override.

    When ``override_set`` is False the ``container_override`` attribute is
    left ``None`` (the component declares no override at all), so the filters
    must fall through to ``None``.
    """
    override = (
        ResolvedComponentContainerOverride(command=command, args=args)
        if override_set
        else None
    )
    return ComponentContext(
        name=name,
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": label_value}),
            ),
        ),
        container_override=override,
    )


def _make_global_context(*, components: ComponentsContext) -> GlobalContext:
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


# Probe template — the canonical empty-list-marker driver pattern from
# contracts/jinja-filters.md. The keys are emitted UNCONDITIONALLY; the filter
# yields ``[]`` when unset (which the chart's ``{{- with }}`` guard skips), and
# the always-present key is what lets a cleared override propagate through the
# operator's JSON merge-patch HelmRelease apply (ADR-045).
PROBE_TEMPLATE = dedent(
    """
    name: probe
    command: {{ components | component_command("server") | tojson }}
    args: {{ components | component_args("server") | tojson }}
    """
).strip()


def _render(context: GlobalContext) -> dict:
    return ApplicationHelmReleaseBuilder.render_value_template(
        values_template=PROBE_TEMPLATE,
        context=context,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenderValueTemplateContainerOverrides:
    def test_both_set_render_into_template(self) -> None:
        """Both ``command`` and ``args`` set → both keys rendered. (US1/US2)."""
        components = ComponentsContext(
            root={
                "server": _component(
                    "server",
                    "simple-app",
                    command=["uvicorn", "simple_app.main:app"],
                    args=["--host", "0.0.0.0", "--port", "8000"],
                ),
            }
        )
        result = _render(_make_global_context(components=components))
        assert result["command"] == ["uvicorn", "simple_app.main:app"]
        assert result["args"] == ["--host", "0.0.0.0", "--port", "8000"]

    def test_command_set_args_unset_emits_empty_args(self) -> None:
        """``command`` set, ``args`` unset → ``command:`` is the list, ``args:``
        is ``[]`` (present-but-empty). The chart's ``{{- with }}`` guard skips
        ``[]`` so the chart default flows through, while the present key lets a
        later clear propagate under merge-patch (US2 Sc.2, FR-007, ADR-045).
        """
        components = ComponentsContext(
            root={
                "server": _component(
                    "server", "simple-app", command=["python", "-m", "worker"]
                ),
            }
        )
        result = _render(_make_global_context(components=components))
        assert result["command"] == ["python", "-m", "worker"]
        assert result["args"] == []

    def test_args_set_command_unset_emits_empty_command(self) -> None:
        """``args`` set, ``command`` unset → ``args:`` is the list, ``command:``
        is ``[]`` (US1 — the MVP override path).
        """
        components = ComponentsContext(
            root={
                "server": _component(
                    "server",
                    "simple-app",
                    args=[
                        "--host",
                        "0.0.0.0",
                        "--port",
                        "8000",
                        "--log-level",
                        "debug",
                    ],
                ),
            }
        )
        result = _render(_make_global_context(components=components))
        assert result["args"] == [
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--log-level",
            "debug",
        ]
        assert result["command"] == []

    def test_nothing_set_emits_empty_lists(self) -> None:
        """No override on the component → both keys present as ``[]``, no
        ``UndefinedError``. The chart's ``{{- with }}`` guard skips ``[]`` so
        the chart/image default applies.
        """
        components = ComponentsContext(
            root={"server": _component("server", "simple-app", override_set=False)}
        )
        result = _render(_make_global_context(components=components))
        assert result["command"] == []
        assert result["args"] == []

    def test_empty_string_element_rendered_verbatim(self) -> None:
        """Empty-string elements (``["sh", "-c", ""]``) render verbatim
        (US4 Sc.4 — mirrors Kubernetes).
        """
        components = ComponentsContext(
            root={
                "server": _component("server", "simple-app", command=["sh", "-c", ""]),
            }
        )
        result = _render(_make_global_context(components=components))
        assert result["command"] == ["sh", "-c", ""]

    def test_filters_return_empty_list_when_unset(self) -> None:
        """The filters return ``[]`` (the empty-list marker, never ``None``) for
        an absent component, a missing override block, or an unset slot — the
        always-present-list contract (ADR-045). The set slot returns its list.
        """
        components = ComponentsContext(
            root={
                "server": _component(
                    "server", "simple-app", command=["uvicorn", "app"]
                ),
                "bare": _component("bare", "bare-app", override_set=False),
            }
        )
        dumped = _make_global_context(components=components).model_dump(
            exclude_none=True
        )

        # ``server`` has a command but no args slot → command list, args [].
        assert component_command(dumped["components"], "server") == ["uvicorn", "app"]
        assert component_args(dumped["components"], "server") == []
        # ``bare`` has no override block at all → both [].
        assert component_command(dumped["components"], "bare") == []
        assert component_args(dumped["components"], "bare") == []
        # Absent component → both [].
        assert component_command(dumped["components"], "missing") == []
        assert component_args(dumped["components"], "missing") == []
        # Garbage inputs collapse to [] — never raise.
        assert component_command(None, "server") == []
        assert component_args("not-a-dict", "server") == []
