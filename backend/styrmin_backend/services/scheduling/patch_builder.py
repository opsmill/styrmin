"""Translation of resolved scheduling configuration to post-renderer patches.

Consumes a resolved :class:`SchedulingConfig` (plus per-component inject
flags) and emits a list of ``TargetPatch`` instances that the agent appends
to the existing FluxCD ``HelmRelease.spec.postRenderers`` pipeline. These
patches run after the Helm-rendered manifests and therefore win over any
values the driver's own chart templates may set for the same fields
(FR-015).
"""

from __future__ import annotations

from typing import Callable

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    AffinityPatch,
    NodeAffinityPatch,
    ResourcesPatch,
    RuntimeClassPatch,
    Target,
    TargetPatch,
    TolerationsPatch,
    TopologySpreadPatch,
)
from styrmin_backend.context.models.config import (
    PostRenderInjection,
    SchedulingConfig,
)
from styrmin_backend.context.resolvers import effective_inject_flag

#: Kinds that carry a pod template and therefore receive scheduling patches.
#: ``CronJob`` needs a different spec path (``spec.jobTemplate.spec.template``)
#: which each ``*Patch`` class handles by branching on ``kind``.
POD_TEMPLATE_BEARING_KINDS: tuple[str, ...] = (
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Job",
    "CronJob",
    "ReplicaSet",
)

_KIND_API_VERSION: dict[str, str] = {
    "Deployment": "apps/v1",
    "StatefulSet": "apps/v1",
    "DaemonSet": "apps/v1",
    "ReplicaSet": "apps/v1",
    "Job": "batch/v1",
    "CronJob": "batch/v1",
}


def _emit_patches(
    label_selector: str | None,
    make_patch: Callable[[str], object],
) -> list[TargetPatch]:
    return [
        TargetPatch(
            target=Target(kind=kind, label_selector=label_selector),
            patch=make_patch(kind),  # type: ignore[arg-type]
        )
        for kind in POD_TEMPLATE_BEARING_KINDS
    ]


def build_affinity_patches(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches that inject pod-affinity / pod-anti-affinity.

    Emits one :class:`TargetPatch` per pod-template-bearing kind when either
    ``resolved.pod_affinity`` or ``resolved.pod_anti_affinity`` is set AND
    the resolved ``inject.pod_affinity`` flag (default True) permits it.

    ``label_selector`` narrows the patch to a specific component's rendered
    resources (e.g. ``"infrahub/service=infrahub-server"``); omit to apply
    to every matching kind in the release.
    """
    if not effective_inject_flag(inject, "pod_affinity"):
        return []
    if resolved.pod_affinity is None and resolved.pod_anti_affinity is None:
        return []
    return _emit_patches(
        label_selector,
        lambda kind: AffinityPatch(
            pod_affinity=resolved.pod_affinity,
            pod_anti_affinity=resolved.pod_anti_affinity,
            api_version=_KIND_API_VERSION[kind],
            kind=kind,
        ),
    )


def build_resources_patches(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches that inject container resources.

    Emits one :class:`TargetPatch` per pod-template-bearing kind when
    ``resolved.resources`` is set AND the resolved ``inject.resources``
    flag (default True) permits it. Applies to every container in the
    pod template via strategic-merge wildcard (``name: "*"``).
    """
    if not effective_inject_flag(inject, "resources"):
        return []
    if resolved.resources is None:
        return []
    # An all-empty ResourceRequirements would produce a no-op patch with
    # ``resources: {}``. Skip it.
    if resolved.resources.requests is None and resolved.resources.limits is None:
        return []
    return _emit_patches(
        label_selector,
        lambda kind: ResourcesPatch(
            resources=resolved.resources,
            api_version=_KIND_API_VERSION[kind],
            kind=kind,
        ),
    )


def build_tolerations_patches(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches that inject pod tolerations."""
    if not effective_inject_flag(inject, "tolerations"):
        return []
    if not resolved.tolerations:
        return []
    return _emit_patches(
        label_selector,
        lambda kind: TolerationsPatch(
            tolerations=list(resolved.tolerations),
            api_version=_KIND_API_VERSION[kind],
            kind=kind,
        ),
    )


def build_topology_spread_patches(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches that inject topologySpreadConstraints."""
    if not effective_inject_flag(inject, "topology_spread"):
        return []
    if not resolved.topology_spread_constraints:
        return []
    return _emit_patches(
        label_selector,
        lambda kind: TopologySpreadPatch(
            constraints=list(resolved.topology_spread_constraints),
            api_version=_KIND_API_VERSION[kind],
            kind=kind,
        ),
    )


def build_node_affinity_patches(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches injecting nodeAffinity (scoped only to
    ``spec.template.spec.affinity.nodeAffinity`` so ``AffinityPatch`` for
    pod(anti-)affinity composes without clobber).
    """
    if not effective_inject_flag(inject, "node_affinity"):
        return []
    if resolved.node_affinity is None:
        return []
    # Skip an all-empty block (nothing to emit).
    if not resolved.node_affinity.required and not resolved.node_affinity.preferred:
        return []
    return _emit_patches(
        label_selector,
        lambda kind: NodeAffinityPatch(
            node_affinity=resolved.node_affinity,
            api_version=_KIND_API_VERSION[kind],
            kind=kind,
        ),
    )


def build_runtime_class_patches(
    resolved: SchedulingConfig,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches setting ``runtimeClassName``."""
    if not effective_inject_flag(inject, "runtime_class"):
        return []
    if resolved.runtime_class is None:
        return []
    return _emit_patches(
        label_selector,
        lambda kind: RuntimeClassPatch(
            runtime_class_name=resolved.runtime_class,
            api_version=_KIND_API_VERSION[kind],
            kind=kind,
        ),
    )
