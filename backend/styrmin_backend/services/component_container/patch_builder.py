"""Translation of component-container overrides (env vars, image) to post-renderer patches.

For each component with a component container and at least one applicable override, emits per
workload kind a :class:`ContainerEnvPatch` naming the container (with env entries when env vars
apply), then a :class:`ComponentContainerPatch` guard that sets the image override and fails the
render when the container is missing. The agent appends these to the HelmRelease
``spec.postRenderers`` after every other patch (018 contracts/post-render-patch.md, ADR-057).
"""

from __future__ import annotations

from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ComponentContainerPatch,
    ContainerEnvPatch,
    Target,
    TargetPatch,
)
from styrmin_backend.context.models.components import ComponentContext
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.component_container.exceptions import (
    ComponentContainerPatchRenderingError,
)
from styrmin_backend.services.image_overrides.reference import validate_reference

#: Workload kinds whose pod template receives component-container patches.
COMPONENT_CONTAINER_PATCH_KINDS: tuple[str, ...] = ("Deployment", "StatefulSet")


def _validate_renders(patches: list[TargetPatch]) -> list[TargetPatch]:
    for tp in patches:
        try:
            tp.patch.render_value()
        except Exception as exc:  # noqa: BLE001 — surface as typed error
            raise ComponentContainerPatchRenderingError(
                message=(
                    "Failed to render component-container patch for kind "
                    f"{tp.target.kind!r}: {exc!s}"
                ),
                kind=tp.target.kind,
                label_selector=tp.target.label_selector,
            ) from exc
    return patches


def _applicable_env(component: ComponentContext) -> dict[str, str]:
    env_vars = component.env_vars
    if env_vars is None or env_vars.is_orphaned:
        return {}
    return dict(env_vars.config)


def _resolved_image(name: str, component: ComponentContext, version: str) -> str | None:
    override = component.image_override
    if override is None or override.is_orphaned:
        return None
    return validate_reference(override.reference, version=version, component_name=name)


def build_component_container_patches(context: GlobalContext) -> list[TargetPatch]:
    """Build component-container post-render patches for every applicable component.

    Skips components without a component container or without an applicable override. Image
    overrides are substituted with ``context.app.version`` and validated, raising
    :class:`InvalidImageReferenceError` (reason ``after_substitution``) when the result is not a
    valid reference. Disabled components still get patches; their replica count is governed by
    the component state patch.
    """
    patches: list[TargetPatch] = []
    if context.components is None:
        return patches

    for name, component in context.components.items():
        container = component.config.container
        if container is None:
            continue
        env = _applicable_env(component)
        image = _resolved_image(name, component, context.app.version)
        if not env and image is None:
            continue

        selector = component.config.identifier.label.label_selectable()
        component_patches: list[TargetPatch] = []
        for kind in COMPONENT_CONTAINER_PATCH_KINDS:
            # The merge names the container; the guard then acts on containers/0.
            component_patches.append(
                TargetPatch(
                    target=Target(kind=kind, label_selector=selector),
                    patch=ContainerEnvPatch(container=container, env=env, kind=kind),
                )
            )
            component_patches.append(
                TargetPatch(
                    target=Target(kind=kind, label_selector=selector),
                    patch=ComponentContainerPatch(
                        component=name, container=container, image=image, kind=kind
                    ),
                )
            )
        patches.extend(_validate_renders(component_patches))
        logger.info(
            "component_container_patches_built component={component} "
            "container={container} env_var_count={env_var_count} "
            "image_override={image_override}",
            component=name,
            container=container,
            env_var_count=len(env),
            image_override=image is not None,
        )
    return patches
