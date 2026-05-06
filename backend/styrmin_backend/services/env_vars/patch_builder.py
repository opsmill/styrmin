"""Translation of resolved env vars into post-renderer Kustomize patches.

Mirrors :mod:`styrmin_backend.services.scheduling.patch_builder`. Consumes a
resolved ``dict[str, str]`` (the deployment-level effective dict for FR-004
broadcast or a per-component effective dict in US3) plus an optional
``PostRenderInjection`` block carrying the ``env_vars`` opt-out flag, and
emits one :class:`TargetPatch` per pod-template-bearing kind.
"""

from __future__ import annotations

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


def build_env_vars_post_rendering_patches(
    resolved: dict[str, str] | None,
    inject: PostRenderInjection | None = None,
    label_selector: str | None = None,
) -> list[TargetPatch]:
    """Build strategic-merge patches that inject env vars into containers.

    Emits one :class:`TargetPatch` per pod-template-bearing kind when
    *resolved* is non-empty AND the resolved ``inject.env_vars`` flag
    (default ``True`` per FR-024) permits injection.

    *label_selector* narrows the patch to a specific component's rendered
    resources (e.g. ``"styrmin/component=worker"``); omit it to apply to
    every matching kind in the release (FR-004 broadcast path).
    """
    if not effective_inject_flag(inject, "env_vars"):
        return []
    if not resolved:
        return []
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
