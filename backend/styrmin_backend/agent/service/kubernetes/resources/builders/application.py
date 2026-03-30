import jinja2
from prefect import task
from yaml import YAMLError, safe_load

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
from styrmin_backend.context.models.contexts import GlobalContext

from .base import build_minimal_helm_release


def split_string(value: str, separator: str | None = None) -> list[str]:
    """Split a string into a list."""
    return value.split(separator)


def get_jinja_environment(**kwargs: object) -> jinja2.Environment:
    """Create a Jinja2 environment with all custom filters registered."""
    env = jinja2.Environment(**kwargs)  # type: ignore[arg-type]
    env.filters["to_fqdn_label"] = to_fqdn_label
    env.filters["split"] = split_string
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
        """
        # Turn the context model into a dict
        context_dict: dict = context.model_dump(exclude_none=True)

        # When dedicated_ingress is enabled, strip ingress_class from the rendering
        # context so driver templates do not set spec.ingressClassName on Ingress
        # resources.  The dedicated controller uses annotation-based matching instead.
        if context.instance.config.dedicated_ingress:
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

        if target_patches:
            rh.add_spec(PostRenderers(target_patches=target_patches))

        return rh
