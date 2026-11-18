from prefect import task
from styrmin_sdk.driver_format.rendering import (
    SilentUndefined as SilentUndefined,
    get_jinja_environment as get_jinja_environment,
    render_values,
)

from styrmin_backend.agent.service.kubernetes.resources.blocks.metadata import (
    Annotations,
    Labels,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    MetadataLabelsMergePatch,
    Target,
    TargetPatch,
    TemplateLabelPatch,
)
from styrmin_backend.agent.service.kubernetes.resources.blocks.spec import (
    PostRenderers,
    Values,
)
from styrmin_backend.agent.service.kubernetes.resources.builders.backup_annotations import (
    build_backup_volume_annotation_patches,
)
from styrmin_backend.agent.service.kubernetes.resources.custom_resource import (
    HelmRelease,
)
from styrmin_backend.agent.service.kubernetes.resources.utilities.base import (
    Utility,
)
from styrmin_backend.agent.service.kubernetes.utils import get_kubernetes_reference
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
from styrmin_backend.services.component_container.patch_builder import (
    build_component_container_patches,
)
from styrmin_backend.services.driver.models.resources.backup import (
    ComponentBackupConfig,
)
from styrmin_backend.services.exceptions import (
    SchedulingPatchRenderingError,
)
from styrmin_backend.services.replicas.patch_builder import (
    build_component_replica_patches,
)
from styrmin_backend.services.scheduling.patch_builder import (
    build_affinity_patches,
    build_node_affinity_patches,
    build_resources_patches,
    build_runtime_class_patches,
    build_tolerations_patches,
    build_topology_spread_patches,
)

from .base import build_minimal_helm_release


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

        The render moved to ``styrmin_sdk.driver_format.rendering.render_values``
        (ADR-0089), which documents the rendering contract. This Prefect task keeps
        the agent's call site.
        """
        return render_values(values_template=values_template, context=context)

    def build_target_for_label_patches(
        self, labels: dict[str, str], label_prefix: str = "styrmin"
    ) -> list[TargetPatch]:
        return [
            TargetPatch(
                target=Target(name=".*"),
                patch=MetadataLabelsMergePatch(
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
                        patch=MetadataLabelsMergePatch(
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
        """Build Kustomize patches applying env var, image, command and args overrides
        to each component's component container, with the missing-container guard."""
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

        # Replica patches: 0 for a stopped component, else the resolved count (023 D-004).
        target_patches.extend(build_component_replica_patches(self.context))

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
