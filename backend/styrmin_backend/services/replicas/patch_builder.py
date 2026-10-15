"""Translation of each component's replica count to post-render patches (023, research D-004).

For each component and each kind in :data:`REPLICA_PATCH_KINDS`, emits at most one JSON6902
``add`` on ``/spec/replicas``: 0 when the component is stopped, the resolved count while it runs,
and none when the chart's count applies. ``ApplicationHelmReleaseBuilder.build()`` places these
after the component label patches and before the backup, scheduling and component container
patches (contracts/post-render-patch.md).
"""

from __future__ import annotations

from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    SpecPatch,
    Target,
    TargetPatch,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.replicas.resolver import (
    replica_patch_count,
    resolve_replicas,
)

#: Workload kinds whose ``spec.replicas`` is patched; never Job, CronJob or DaemonSet (ADR-057).
REPLICA_PATCH_KINDS: tuple[str, ...] = ("Deployment", "StatefulSet")


def build_component_replica_patches(context: GlobalContext) -> list[TargetPatch]:
    """Build the ``spec.replicas`` post-render patches for every component.

    One patch per kind per component, so no two patches write ``/spec/replicas`` on the same
    workload. A component needs no component container to be patched (FR-003).
    """
    patches: list[TargetPatch] = []
    if context.components is None:
        return patches

    for name, component in context.components.items():
        # ``context.components`` holds declared components only, so none is orphaned.
        resolved = resolve_replicas(
            declared_replicas=component.config.replicas,
            singleton=component.config.singleton,
            override=component.replica_override,
            is_orphaned=False,
        )
        count = replica_patch_count(resolved, enabled=component.enabled)
        if count is None:
            continue

        selector = component.config.identifier.label.label_selectable()
        patches.extend(
            TargetPatch(
                target=Target(kind=kind, label_selector=selector),
                patch=SpecPatch(specs={"replicas": count}),
            )
            for kind in REPLICA_PATCH_KINDS
        )
        logger.debug(
            "component_replica_patch_built component={component} replicas={replicas} "
            "source={source} enabled={enabled}",
            component=name,
            replicas=count,
            source=resolved.source.value,
            enabled=component.enabled,
        )
    return patches
