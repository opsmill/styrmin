from typing import NoReturn

import jinja2
from prefect import task
from yaml import YAMLError, safe_load

from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import (
    Annotations,
    Labels,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    LabelPatch,
    SpecPatch,
    Target,
    TargetPatch,
    TemplateLabelPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.backup_annotations import (
    build_backup_volume_annotation_patches,
)
from styrmin_backend.services.driver.models.resources.backup import (
    ComponentBackupConfig,
)
from styrmin_backend.services.component_container.patch_builder import (
    build_component_container_patches,
)
from styrmin_backend.services.exceptions import (
    RetiredTemplateFilterError,
    SchedulingPatchRenderingError,
)
from styrmin_backend.services.scheduling.patch_builder import (
    build_affinity_patches,
    build_node_affinity_patches,
    build_resources_patches,
    build_runtime_class_patches,
    build_tolerations_patches,
    build_topology_spread_patches,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    PostRenderers,
    Values,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.exceptions import (
    ChartValuesTemplateRenderingError,
    InvalidChartValuesError,
)
from styrmin_backend.agent.service.kubernetes.resources.custom_resource import (
    HelmRelease,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import (
    Utility,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
from styrmin_backend.context.fqdn import to_fqdn_label
from styrmin_backend.context.models.config import (
    PostRenderInjection,
    SchedulingConfig,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.operator.config import (
    ANNOTATION_DEPLOYMENT_ID,
    LABEL_MANAGED_BY,
    LABEL_MANAGED_BY_VALUE,
    LABEL_OPERATOR_MANAGED,
    LABEL_OPERATOR_MANAGED_VALUE,
)

from .base import build_minimal_helm_release


def split_string(value: str, separator: str | None = None) -> list[str]:
    """Split a string into a list."""
    return value.split(separator)


def component_env_vars(*args: object, **kwargs: object) -> NoReturn:  # noqa: ARG001
    """Retired filter: Styrmin injects env vars by post-render patch (017 FR-007).

    Stays registered so a driver still calling it gets the typed error.
    """
    raise RetiredTemplateFilterError


def _resolved_container_override(components: object, name: str) -> dict | None:
    """Return the resolved ``container_override`` dict for component ``name``.

    Defensive read against the ``model_dump(exclude_none=True)`` rendering
    context: returns ``None`` when ``components`` is not a dict, the component
    is absent, or it has no resolved ``container_override`` block.
    """
    if not isinstance(components, dict):
        return None
    component = components.get(name)
    if not isinstance(component, dict):
        return None
    override = component.get("container_override")
    if not isinstance(override, dict):
        return None
    return override


def component_command(components: object, name: str) -> list[str]:
    """Resolved ``command`` override for component ``name``, or ``[]`` when unset.

    Empty-list marker contract (ADR-045): returns the resolved non-empty list
    when the user has set a ``command`` override, or **``[]``** when unset
    (component absent, no override block, or the ``command`` slot unset). The
    driver template emits it unconditionally
    (``command: {{ components | component_command("server") | tojson }}``); the
    chart guards with ``{{- with .Values.command }}``, and an empty list is
    falsy so the chart skips the key and the image/chart default applies
    (FR-007/US2 Sc.2, FR-009). The HelmRelease ``spec`` is replaced on update
    (ADR-057), so clearing also works when the key is omitted.
    """
    override = _resolved_container_override(components, name)
    if override is None:
        return []
    command = override.get("command")
    if not isinstance(command, list):
        return []
    return command


def component_args(components: object, name: str) -> list[str]:
    """Resolved ``args`` override for component ``name``, or ``[]`` when unset.

    Same empty-list-marker contract as :func:`component_command` for the
    ``args`` slot — returns the resolved list or ``[]``, consumed under a chart
    ``with`` guard.
    """
    override = _resolved_container_override(components, name)
    if override is None:
        return []
    args = override.get("args")
    if not isinstance(args, list):
        return []
    return args


def _validate_renders(patches: list[TargetPatch]) -> list[TargetPatch]:
    """Eagerly render each patch so serialisation failures raise before
    Kustomize gets them (spec US6 Scenario 3 / T054). Returns *patches*
    unchanged on success; raises :class:`SchedulingPatchRenderingError`
    carrying the failing resource kind and label selector otherwise.
    """
    for tp in patches:
        try:
            tp.patch.render_value()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — surface as typed error
            raise SchedulingPatchRenderingError(
                message=(
                    f"Failed to render scheduling patch for kind "
                    f"{tp.target.kind!r}: {exc!s}"
                ),
                kind=tp.target.kind,
                label_selector=tp.target.label_selector,
            ) from exc
    return patches


_SCHEDULING_PATCH_BUILDERS = (
    build_affinity_patches,
    build_resources_patches,
    build_tolerations_patches,
    build_topology_spread_patches,
    build_node_affinity_patches,
    build_runtime_class_patches,
)


def _build_all_scheduling_patches_for(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Invoke every feature's builder for a single resolved scheduling config."""
    patches: list[TargetPatch] = []
    for build in _SCHEDULING_PATCH_BUILDERS:
        patches.extend(
            _validate_renders(
                build(
                    resolved=resolved,
                    inject=inject,
                    label_selector=label_selector,
                )
            )
        )
    return patches


def get_jinja_environment(**kwargs: object) -> jinja2.Environment:
    """Create a Jinja2 environment with all custom filters registered."""
    env = jinja2.Environment(**kwargs)  # type: ignore[arg-type]
    env.filters["to_fqdn_label"] = to_fqdn_label
    env.filters["split"] = split_string
    env.filters["component_env_vars"] = component_env_vars
    env.filters["component_command"] = component_command
    env.filters["component_args"] = component_args
    return env


class SilentUndefined(jinja2.Undefined):
    """
    Dont break pageloads because vars arent there!
    """

    def _fail_with_undefined_error(self, *args, **kwargs) -> str:  # type: ignore[no-untyped-def, override]
        return ""


class ApplicationHelmReleaseBuilder:
    """A builder for HelmRelease custom resources.

    Example:
        >>> hr = builder.build_helm_release()
        >>> print(json.dumps(hr.render()))
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "metadata": {},
            "spec": {
                "chartRef": {
                    "name": "my-chart",
                    "namespace": "styrmin",
                    "kind": "HelmChart",
                },
                "install": {"remediation": {"retries": 3}},
                "interval": "1h",
                "releaseName": "my-release",
                "timeout": "5m",
                "upgrade": {"remediation": {"retries": 3}},
            },
        }

    The `labels` and `label_prefix` arguments can be used to apply labels to the resources.
    The `label_prefix` argument is used to prefix the labels. The default value is "styrmin".
    A `test` label with a "styrmin" prefix would end up as "styrmin/test" label on the resources.

    Args:
        context: The global context.
        labels: The labels to apply to the resources.
        label_prefix: The prefix to apply to the labels. Defaults to "styrmin".
    """

    def __init__(
        self,
        context: GlobalContext,
        label_prefix: str = "styrmin",
    ):
        self.context = context
        self.label_prefix = label_prefix

    @staticmethod
    @task
    def render_value_template(values_template: str, context: GlobalContext) -> dict:
        """Render the value template with the given context.

        Args:
            value_template (str): The value template to render.
            context (GlobalContext): The context to render the value template with.

        Returns:
            dict: The rendered value template.

        Rendering contract surfaced to driver templates:
            The Jinja rendering dict is produced by
            ``GlobalContext.model_dump(exclude_none=True)``. Driver
            ``values_template`` files consume the resolved env vars through
            two stable, named paths on this dict:

            - ``instance.config.env_vars`` (``dict[str, str]`` | absent) —
              the deployment-effective merged env vars (environment-scope
              values overlaid with deployment-scope values per the
              deepest-wins precedence in 008-deployment-env-vars).
            - ``components[<name>].env_vars.config`` (``dict[str, str]`` |
              absent) — the per-component effective merged env vars
              (env → deployment → component layers combined).

            Both paths use ``model_dump(exclude_none=True)`` semantics: the
            ``env_vars`` (and per-component ``env_vars.config``) keys are
            absent from the dict whenever no env vars are set at the
            relevant scope.

            These paths are read-only data (e.g. to build a ConfigMap).
            Styrmin injects env vars into each component's declared
            component container by post-render patch, not through the values
            template (see :meth:`build_component_container_post_rendering_patches` and
            ``dev/guides/driver-env-var-consumption.md``).
        """
        # Turn the context model into a dict
        context_dict: dict = context.model_dump(exclude_none=True)

        # When dedicated_ingress is enabled, strip ingress_class from the rendering
        # context so driver templates do not set spec.ingressClassName on Ingress
        # resources.  The dedicated controller uses annotation-based matching instead.
        if context.instance.config.dedicated_ingress is not None:
            for section in ("instance", "cluster", "environment", "deployment"):
                config = context_dict.get(section, {}).get("config", {})
                config.pop("ingress_class", None)

        # Render the value template using jinja
        environment = get_jinja_environment(undefined=SilentUndefined)
        template = environment.from_string(values_template)

        try:
            # TODO: Remove the temporary silencing of the UndefinedError
            values = template.render(context_dict)
        except jinja2.TemplateRuntimeError as e:
            raise ChartValuesTemplateRenderingError(
                f"Chart values template rendering failed: {e!s}"
            ) from e

        try:
            return safe_load(values)
        except YAMLError as e:
            raise InvalidChartValuesError(
                f"The chart values are not valid YAML: {e!s}"
            ) from e

    def build_components_state_post_rendering_patches(
        self, context: GlobalContext
    ) -> list[TargetPatch]:
        """Build the component state post rendering patches.

        Args:
            context (GlobalContext): The global context.

        Returns:
            list[TargetPatch]: The component state post rendering patches.
        """
        target_patches: list[TargetPatch] = []
        if context.components is None:
            return target_patches

        for component, component_definition in context.components.items():
            if component_definition.enabled is False:
                for kind in ["Deployment", "StatefulSet"]:
                    target_patches.append(
                        TargetPatch(
                            target=Target(
                                label_selector=component_definition.config.identifier.label.label_selectable(),
                                kind=kind,
                            ),
                            patch=SpecPatch(
                                specs={"replicas": 0},
                            ),
                        )
                    )
        return target_patches

    def build_target_for_label_patches(
        self, labels: dict[str, str], label_prefix: str = "styrmin"
    ) -> list[TargetPatch]:
        return [
            TargetPatch(
                target=Target(name=".*"),
                patch=LabelPatch(
                    labels=labels,
                    label_prefix=label_prefix,
                ),
            ),
            TargetPatch(
                target=Target(kind="Deployment"),
                patch=TemplateLabelPatch(
                    labels=labels,
                    label_prefix=label_prefix,
                ),
            ),
            TargetPatch(
                target=Target(kind="StatefulSet"),
                patch=TemplateLabelPatch(
                    labels=labels,
                    label_prefix=label_prefix,
                ),
            ),
        ]

    def build_target_for_component_labels(
        self, label_prefix: str = "styrmin"
    ) -> list[TargetPatch]:
        patches = []
        # Add component labels
        if self.context.components:
            for component, component_definition in self.context.components.items():
                patches.append(
                    TargetPatch(
                        target=Target(
                            label_selector=component_definition.config.identifier.label.label_selectable(),
                        ),
                        patch=LabelPatch(
                            labels={"component": component},
                            label_prefix=label_prefix,
                        ),
                    )
                )
                for kind in ("Deployment", "StatefulSet"):
                    patches.append(
                        TargetPatch(
                            target=Target(
                                label_selector=component_definition.config.identifier.label.label_selectable(),
                                kind=kind,
                            ),
                            patch=TemplateLabelPatch(
                                labels={"component": component},
                                label_prefix=label_prefix,
                            ),
                        )
                    )

        return patches

    def build_scheduling_post_rendering_patches(self) -> list[TargetPatch]:
        """Build Kustomize patches that inject resolved scheduling configuration.

        Dispatcher for the hierarchical pod scheduling feature. Each enabled
        feature group (US1 affinity, US2 resources, US3 tolerations /
        topology spread / node affinity, US4 runtime class) contributes its
        patches here; the US6 ``PostRenderInjection.inject.*`` opt-outs are
        honoured inside each builder.

        Per-component scheduling (read from ``context.components[*].scheduling``)
        patches are narrowed by the component's identifier label selector.
        When no components are declared, the deployment-level resolved
        scheduling (from ``context.instance.config.scheduling``) applies to
        every pod-template-bearing kind in the release.
        """
        patches: list[TargetPatch] = []

        if self.context.components is not None:
            for component_definition in self.context.components.root.values():
                if component_definition.scheduling is None:
                    continue
                resolved = component_definition.scheduling.config
                selector = (
                    component_definition.config.identifier.label.label_selectable()
                )
                patches.extend(
                    _build_all_scheduling_patches_for(
                        resolved=resolved,
                        inject=resolved.inject,
                        label_selector=selector,
                    )
                )
            return patches

        # No components declared — apply deployment-level scheduling broadly.
        instance_scheduling = self.context.instance.config.scheduling
        if instance_scheduling is None:
            return patches
        patches.extend(
            _build_all_scheduling_patches_for(
                resolved=instance_scheduling,
                inject=instance_scheduling.inject,
            )
        )
        return patches

    def build_component_container_post_rendering_patches(self) -> list[TargetPatch]:
        """Build Kustomize patches applying env vars and image overrides to each
        component's component container, with the missing-container guard (018)."""
        return build_component_container_patches(self.context)

    def build_backup_annotation_patches(self) -> list[TargetPatch]:
        """Extract backup configs from components and build Velero annotation patches."""
        if self.context.components is None:
            return []
        backup_configs: dict[str, ComponentBackupConfig] = {}
        label_selectors: dict[str, str] = {}
        for name, comp in self.context.components.items():
            extra = comp.config.__pydantic_extra__ or {}
            backup_raw = extra.get("backup")
            if backup_raw is None:
                continue
            config = ComponentBackupConfig.model_validate(backup_raw)
            backup_configs[name] = config
            label_selectors[name] = comp.config.identifier.label.label_selectable()
        return build_backup_volume_annotation_patches(backup_configs, label_selectors)

    def build(self, utilities: list[Utility]) -> HelmRelease:
        """Build a HelmRelease custom resource.

        The `ingress` argument can be used to apply ingress patches. By doing so, it configures the ingress resource
        using annotations.

        The `labels` argument can be used to apply labels to the resources.

        Args:
            release_reference: The reference to the release in the kubernetes cluster.
            chart_reference: The reference to the chart name.
            chart_values: The values to apply to the chart.
            ingress: Whether to apply ingress patches. Defaults to True.
            labels: Whether to apply labels. Defaults to True.
        """

        rh = build_minimal_helm_release(
            release_reference=self.context.instance.release_reference,
            chart_reference=get_kubernetes_reference(self.context.app.helm.chart.id),
        )

        # Add operator-managed labels and deployment-id annotation so the
        # kopf operator knows to take ownership of NetworkPolicy resources
        # for this deployment.
        rh.add_metadata(
            Labels(
                labels={
                    LABEL_MANAGED_BY: LABEL_MANAGED_BY_VALUE,
                    LABEL_OPERATOR_MANAGED: LABEL_OPERATOR_MANAGED_VALUE,
                }
            )
        )
        rh.add_metadata(
            Annotations(
                annotations={
                    ANNOTATION_DEPLOYMENT_ID: str(self.context.instance.deployment_id),
                }
            )
        )

        rh.add_spec(
            block=Values(
                value=self.render_value_template(
                    values_template=self.context.app.helm.chart.values_template,
                    context=self.context,
                )
            )
        )

        target_patches = []
        for utility in utilities:
            target_patches.extend(
                utility.build_app_post_rendering_patches(
                    self.context, self.context.instance.release_reference
                )
            )

        # Add label patches
        target_patches.extend(
            self.build_target_for_label_patches(
                labels=self.context.labels, label_prefix=self.label_prefix
            )
        )
        # Add components labels
        target_patches.extend(
            self.build_target_for_component_labels(label_prefix=self.label_prefix)
        )

        target_patches.extend(
            self.build_components_state_post_rendering_patches(self.context)
        )

        # Add backup volume annotation patches
        target_patches.extend(self.build_backup_annotation_patches())

        # Add scheduling post-renderer patches (affinity, resources,
        # tolerations, topology spread, runtime class) — dispatcher stub
        # that later user-story phases extend.
        target_patches.extend(self.build_scheduling_post_rendering_patches())

        # Component-container patches go last: they move the component container
        # to containers[0], so the scheduling ResourcesPatch must run first (017 research D-002).
        target_patches.extend(self.build_component_container_post_rendering_patches())

        if target_patches:
            rh.add_spec(PostRenderers(target_patches=target_patches))

        return rh
