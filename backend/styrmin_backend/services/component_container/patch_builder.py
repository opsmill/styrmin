"""Translation of component-container overrides to post-renderer patches.

For each component with at least one applicable override (env vars, image, ``command`` or
``args``), emits per workload kind a :class:`ContainerMergePatch` naming the container, with the
env entries, ``command`` and ``args`` that apply, then a :class:`ComponentContainerPatch` guard
that sets the image override and fails the render when the container is missing. The agent
appends these to the HelmRelease ``spec.postRenderers`` after every other patch (022
contracts/post-render-patch.md, ADR-057).
"""

from __future__ import annotations

from loguru import logger

from styrmin_backend.agent.service.kubernetes.resources.blocks.patches import (
    ComponentContainerPatch,
    ContainerMergePatch,
    Target,
    TargetPatch,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.component_container.exceptions import (
    ComponentContainerPatchRenderingError,
)
from styrmin_backend.services.component_container.overrides import (
    applicable_overrides,
)

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


def build_component_container_patches(context: GlobalContext) -> list[TargetPatch]:
    """Build component-container post-render patches for every applicable component.

    Skips components with no applicable override, which includes every component without a
    component container. Image overrides are substituted with ``context.app.version`` and
    validated, raising :class:`InvalidImageReferenceError` (reason ``after_substitution``) when
    the result is not a valid reference. Disabled components still get patches; the component
    replica patch (:func:`build_component_replica_patches`) scales them to 0.
    """
    patches: list[TargetPatch] = []
    if context.components is None:
        return patches

    for name, component in context.components.items():
        container = component.config.container
        if container is None:
            continue
        overrides = applicable_overrides(name, component, context.app.version)
        if overrides.is_empty:
            continue

        selector = component.config.identifier.label.label_selectable()
        component_patches: list[TargetPatch] = []
        for kind in COMPONENT_CONTAINER_PATCH_KINDS:
            # The merge names the container; the guard then acts on containers/0.
            component_patches.append(
                TargetPatch(
                    target=Target(kind=kind, label_selector=selector),
                    patch=ContainerMergePatch(
                        container=container,
                        env=overrides.env,
                        command=overrides.command,
                        args=overrides.args,
                        kind=kind,
                    ),
                )
            )
            component_patches.append(
                TargetPatch(
                    target=Target(kind=kind, label_selector=selector),
                    patch=ComponentContainerPatch(
                        component=name,
                        container=container,
                        image=overrides.image,
                        kind=kind,
                    ),
                )
            )
        patches.extend(_validate_renders(component_patches))
        logger.info(
            "component_container_patches_built component={component} "
            "container={container} env_var_count={env_var_count} "
            "image_override={image_override} command_set={command_set} "
            "args_set={args_set}",
            component=name,
            container=container,
            env_var_count=len(overrides.env),
            image_override=overrides.image is not None,
            command_set=overrides.command is not None,
            args_set=overrides.args is not None,
        )
    return patches
