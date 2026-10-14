"""The retired ``component_command`` and ``component_args`` filters (022 T018, FR-005).

Styrmin applies container ``command`` and ``args`` overrides by post-render patch, so a
``values.j2.yml`` that still calls either filter fails rendering with ``RETIRED_TEMPLATE_FILTER``
and a message naming the filter and the container override migration guide. Mirrors
``TestRetiredComponentEnvVarsFilter`` in ``test_render_value_template_env_vars.py``.
"""

from __future__ import annotations

from collections.abc import Callable
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
from styrmin_backend.operator.pipeline import execute_phase_helmrelease
from styrmin_backend.services.exceptions import RetiredTemplateFilterError

MIGRATION_GUIDE = "https://styrmin.pages.dev/docs/drivers/migrating-container-overrides"
RETIRED_FILTERS = ["component_command", "component_args"]
ENV_VARS_MIGRATION_GUIDE = "https://styrmin.pages.dev/docs/drivers/migrating-env-vars"
ENV_VARS_MESSAGE = (
    "The 'component_env_vars' template filter was removed: Styrmin now injects "
    "env vars into each component's declared component container. Deployment "
    "users: upgrade this deployment to a driver version that declares component "
    "containers. Driver authors: remove the filter from values.j2.yml and declare "
    "components.<name>.container in driver.styrmin.yml. Migration guide: "
    f"{ENV_VARS_MIGRATION_GUIDE}"
)


def _expected_message(filter_name: str) -> str:
    # contracts/errors.md, RETIRED_TEMPLATE_FILTER (extended).
    return (
        f"The '{filter_name}' template filter was removed: Styrmin now applies "
        "container command and args overrides to each component's declared component "
        "container. Deployment users: move this deployment to a driver version that "
        "no longer calls the filter. Driver authors: remove the filter from "
        "values.j2.yml and declare components.<name>.container in driver.styrmin.yml. "
        f"Migration guide: {MIGRATION_GUIDE}"
    )


def _plain_template(filter_name: str) -> str:
    return f'command: {{{{ components | {filter_name}("server") | tojson }}}}\n'


def _if_template(filter_name: str) -> str:
    # The infrahub drivers called the filters inside `{% if %}` (ADR-045 §5).
    return (
        f'{{%- if components | {filter_name}("server") %}}\n'
        f'args: {{{{ components | {filter_name}("server") | tojson }}}}\n'
        "{%- else %}\n"
        "args: null\n"
        "{%- endif %}\n"
    )


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _component(
    *, override: ResolvedComponentContainerOverride | None
) -> ComponentContext:
    return ComponentContext(
        name="server",
        enabled=True,
        config=ArbitrarySectionModel(
            identifier=Identifier(
                label=LabelIdentifier(root={"app.kubernetes.io/name": "simple-app"}),
            ),
            container="simple-app",
        ),
        container_override=override,
    )


def _make_global_context(
    *,
    override: ResolvedComponentContainerOverride | None,
    values_template: str = "",
) -> GlobalContext:
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
                    values_template=values_template,
                ),
                repository=RepositoryInfo(
                    id=uuid4(),
                    url="https://example.com/charts",
                ),
            ),
        ),
        deployed_services=[],
        components=ComponentsContext(root={"server": _component(override=override)}),
    )


def _assert_retired_filter_error(
    error: RetiredTemplateFilterError, filter_name: str
) -> None:
    assert error.error_code == "RETIRED_TEMPLATE_FILTER"
    assert error.error_metadata == {
        "filter": filter_name,
        "migration_guide": MIGRATION_GUIDE,
    }
    message = str(error)
    assert filter_name in message
    assert MIGRATION_GUIDE in message
    assert message == _expected_message(filter_name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filter_name", RETIRED_FILTERS)
class TestRetiredContainerOverrideFilters:
    """A ``values.j2.yml`` calling ``component_command`` or ``component_args`` aborts rendering."""

    @pytest.mark.parametrize(
        "override",
        [
            ResolvedComponentContainerOverride(
                command=["uvicorn", "app"], args=["--port", "8000"]
            ),
            ResolvedComponentContainerOverride(args=["--port", "8000"]),
            None,
        ],
        ids=["override-set", "args-only", "no-override"],
    )
    @pytest.mark.parametrize(
        "template", [_plain_template, _if_template], ids=["plain", "inside-if"]
    )
    def test_template_calling_filter_raises_typed_error(
        self,
        filter_name: str,
        override: ResolvedComponentContainerOverride | None,
        template: Callable[[str], str],
    ) -> None:
        """Raises whatever the context holds, so an unmigrated driver fails on its
        next render even when no override is set.
        """
        context = _make_global_context(override=override)

        with pytest.raises(RetiredTemplateFilterError) as exc_info:
            ApplicationHelmReleaseBuilder.render_value_template(
                values_template=template(filter_name), context=context
            )

        _assert_retired_filter_error(exc_info.value, filter_name)

    def test_filter_stays_registered(self, filter_name: str) -> None:
        """Unregistering would give Jinja's generic "no filter named" error at
        compile time instead of the typed error pointing at the migration guide.
        """
        environment = get_jinja_environment()

        assert filter_name in environment.filters
        environment.from_string(_plain_template(filter_name))
        environment.from_string(_if_template(filter_name))

    async def test_operator_records_message_without_applying_helm_release(
        self, filter_name: str
    ) -> None:
        """The operator pipeline keeps the message (code and metadata are not
        carried by ``PhaseResult``) and never applies the HelmRelease.
        """
        context = _make_global_context(
            override=ResolvedComponentContainerOverride(args=["--port", "8000"]),
            values_template=_if_template(filter_name),
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
            f"Failed to create HelmRelease: {_expected_message(filter_name)}"
        ]
        applied = [call.kwargs["plurals"] for call in upsert.await_args_list]
        assert "helmreleases" not in applied


class TestRetiredEnvVarsFilterMessageUnchanged:
    """Adding the container override filters leaves the env var error as it was."""

    @pytest.mark.parametrize(
        "error",
        [
            RetiredTemplateFilterError(),
            RetiredTemplateFilterError(filter_name="component_env_vars"),
        ],
        ids=["defaults", "explicit-filter-name"],
    )
    def test_env_vars_message_and_guide(
        self, error: RetiredTemplateFilterError
    ) -> None:
        assert str(error) == ENV_VARS_MESSAGE
        assert error.error_metadata == {
            "filter": "component_env_vars",
            "migration_guide": ENV_VARS_MIGRATION_GUIDE,
        }
