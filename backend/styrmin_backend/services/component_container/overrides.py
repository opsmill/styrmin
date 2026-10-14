"""The component-container overrides that apply to a component in one instance context.

One rule, :func:`override_applies`, decides whether a stored override reaches the workload: the
component declares a component container and the override is not orphaned. The patch builder,
the action primitives and the ``isApplicable`` read fields all use it.
:func:`applicable_overrides` collects the env vars, image, ``command`` and ``args`` that pass
the rule, so an action sees the overrides of the instance it runs for before they reach the
workload (#431, 022 research D-002).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from styrmin_backend.context.models.components import ComponentContext
from styrmin_backend.services.image_overrides.reference import validate_reference


def override_applies(container: str | None, is_orphaned: bool) -> bool:
    """Return whether an override reaches the component container.

    True only when the component declares a component container and the override is not
    orphaned.
    """
    return container is not None and not is_orphaned


@dataclass(frozen=True)
class ApplicableOverrides:
    """The overrides of one component that reach its component container."""

    env: dict[str, str] = field(default_factory=dict)
    image: str | None = None
    command: list[str] | None = None
    args: list[str] | None = None

    @property
    def is_empty(self) -> bool:
        """True when no env var, image, ``command`` or ``args`` override applies."""
        return (
            not self.env
            and self.image is None
            and self.command is None
            and self.args is None
        )


def applicable_overrides(
    name: str, component: ComponentContext, version: str
) -> ApplicableOverrides:
    """Return the overrides that apply to ``component``.

    The image override has ``{{ app.version }}`` set to ``version``. Raises
    :class:`InvalidImageReferenceError` (reason ``after_substitution``) when the result is not a
    valid reference.
    """
    container = component.config.container

    env: dict[str, str] = {}
    env_vars = component.env_vars
    if env_vars is not None and override_applies(container, env_vars.is_orphaned):
        env = dict(env_vars.config)

    image: str | None = None
    image_override = component.image_override
    if image_override is not None and override_applies(
        container, image_override.is_orphaned
    ):
        image = validate_reference(
            image_override.reference, version=version, component_name=name
        )

    command: list[str] | None = None
    args: list[str] | None = None
    container_override = component.container_override
    if container_override is not None and override_applies(
        container, container_override.is_orphaned
    ):
        if container_override.command is not None:
            command = list(container_override.command)
        if container_override.args is not None:
            args = list(container_override.args)

    return ApplicableOverrides(env=env, image=image, command=command, args=args)
