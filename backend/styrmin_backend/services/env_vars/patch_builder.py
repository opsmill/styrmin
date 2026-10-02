"""Translation of resolved env vars to post-renderer patches.

For each component that declares a component container and has resolved env
vars, emits one :class:`ContainerEnvPatch` per workload kind, targeted by the
component's identifier label. The agent appends these to the HelmRelease
``spec.postRenderers`` after every other patch (017-post-render-env-vars
research D-002, D-009).
"""

from __future__ import annotations

from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ContainerEnvPatch,
    Target,
    TargetPatch,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.env_vars.exceptions import EnvVarPatchRenderingError

#: Workload kinds whose pod template receives env var patches.
ENV_VAR_PATCH_KINDS: tuple[str, ...] = ("Deployment", "StatefulSet")


def _validate_renders(patches: list[TargetPatch]) -> list[TargetPatch]:
    for tp in patches:
        try:
            tp.patch.render_value()
        except Exception as exc:  # noqa: BLE001 — surface as typed error
            raise EnvVarPatchRenderingError(
                message=(
                    f"Failed to render env var patch for kind {tp.target.kind!r}: {exc!s}"
                ),
                kind=tp.target.kind,
                label_selector=tp.target.label_selector,
            ) from exc
    return patches


def build_env_var_patches(context: GlobalContext) -> list[TargetPatch]:
    """Build env var post-render patches for every applicable component.

    Skips components without a component container, without resolved env
    vars, or whose env vars are orphaned. Disabled components still get
    patches; their replica count is governed by the component state patch.
    """
    patches: list[TargetPatch] = []
    if context.components is None:
        return patches

    for name, component in context.components.items():
        container = component.config.container
        env_vars = component.env_vars
        if container is None or env_vars is None:
            continue
        if env_vars.is_orphaned or not env_vars.config:
            continue

        selector = component.config.identifier.label.label_selectable()
        component_patches = [
            TargetPatch(
                target=Target(kind=kind, label_selector=selector),
                patch=ContainerEnvPatch(
                    container=container, env=dict(env_vars.config), kind=kind
                ),
            )
            for kind in ENV_VAR_PATCH_KINDS
        ]
        patches.extend(_validate_renders(component_patches))
        logger.info(
            "env_var_patches_built component={component} container={container} "
            "count={count}",
            component=name,
            container=container,
            count=len(env_vars.config),
        )
    return patches
