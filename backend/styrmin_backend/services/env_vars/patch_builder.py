"""Translation of resolved env vars into post-renderer Kustomize patches.

Mirrors :mod:`styrmin_backend.services.scheduling.patch_builder`. Consumes a
resolved ``dict[str, str]`` (the deployment-level effective dict for FR-004
broadcast or a per-component effective dict in US3) plus an optional
``PostRenderInjection`` block carrying the ``env_vars`` opt-out flag, and
emits one :class:`TargetPatch` per pod-template-bearing kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    EnvVarsPatch,
    Target,
    TargetPatch,
)
from styrmin_backend.context.models.config import PostRenderInjection
from styrmin_backend.context.resolvers import effective_inject_flag
from styrmin_backend.services.scheduling.patch_builder import (
    POD_TEMPLATE_BEARING_KINDS,
    _KIND_API_VERSION,
)


@dataclass
class ChartEnvCollision:
    """Record of a chart-vs-user env var name collision.

    Mirrors the dataclass style of :class:`ContextChange` in
    :mod:`styrmin_backend.services.deployment_timeline`. Surfaced through
    ``DeploymentTimelineEntry.envVarCollisions`` and emitted as a structured
    log line per FR-027/FR-028.

    Fields mirror the GraphQL ``EnvVarCollision`` shape (data-model.md §4):

    * ``component`` — component the colliding container belongs to;
      ``None`` when the workload is not under any component (FR-004
      broadcast).
    * ``container`` — container name within the rendered pod template.
    * ``name`` — colliding env var name.
    * ``chart_value`` — value the Helm chart rendered for that name.
    * ``user_value`` — operator-set value, which wins after post-render
      replacement.
    """

    component: str | None
    container: str
    name: str
    chart_value: str
    user_value: str


def build_env_vars_post_rendering_patches(
    resolved: dict[str, str] | None,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
    *,
    component: str | None = None,
    deployment_id: UUID | str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches that inject env vars into containers.

    Emits one :class:`TargetPatch` per pod-template-bearing kind when
    *resolved* is non-empty AND the resolved ``inject.env_vars`` flag
    (default ``True`` per FR-024) permits injection.

    *label_selector* narrows the patch to a specific component's rendered
    resources (e.g. ``"styrmin/component=worker"``); omit it to apply to
    every matching kind in the release (FR-004 broadcast path).

    *component* and *deployment_id* are optional contextual fields used
    only to enrich the structured warning log emitted per operator-set
    env var key (US7 / FR-027 / FR-028). The platform's v1 architecture
    does NOT see the post-rendered manifest at this layer — the patch is
    a JSON-patch document Kustomize processes on-cluster — so true
    chart-vs-user collision detection cannot be wired here. Per FR-028,
    the conflict-detection path is allowed to degrade to a structured log
    entry; the GraphQL surface (``DeploymentTimelineEntry.envVarCollisions``)
    is present but populated as ``[]`` until a future iteration adds the
    post-apply rendered-manifest fetch + diff path.
    """
    if not effective_inject_flag(inject, "env_vars"):
        return []
    if not resolved:
        return []

    # FR-027/FR-028: detect chart-vs-user env collisions and emit a
    # structured warning per detected collision. v1 lacks line-of-sight
    # into the rendered manifest at the patch layer (the patch is handed
    # to FluxCD/Kustomize and applied on-cluster), so real collision
    # detection is deferred to a follow-up agent-side rendered-manifest
    # diff path. Until that seam exists, no collision data is produced
    # here and the timeline field surfaces ``[]``. Emitting a warning per
    # operator-set key (without checking for an actual collision) would
    # be log noise rather than an FR-028 signal — we deliberately do
    # NOT do that. See ADR-019 §3.

    return [
        TargetPatch(
            target=Target(kind=kind, label_selector=label_selector),
            patch=EnvVarsPatch(
                env_vars=dict(resolved),
                api_version=_KIND_API_VERSION[kind],
                kind=kind,
            ),
        )
        for kind in POD_TEMPLATE_BEARING_KINDS
    ]
