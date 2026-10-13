"""The component-container overrides that apply to a component in one instance context.

An override applies when the component declares a component container and the override is not
orphaned (``isApplicable`` on the read surface). The patch builder renders these overrides, and
the action primitives read them, so an action sees the overrides of the instance it runs for
before they reach the workload (#431).
"""

from __future__ import annotations

from styrmin_backend.context.models.components import ComponentContext
from styrmin_backend.services.image_overrides.reference import validate_reference


def applicable_env(component: ComponentContext) -> dict[str, str]:
    """Return the env vars injected into the component container, or ``{}`` when none apply."""
    env_vars = component.env_vars
    if component.config.container is None or env_vars is None or env_vars.is_orphaned:
        return {}
    return dict(env_vars.config)


def applicable_image(
    name: str, component: ComponentContext, version: str
) -> str | None:
    """Return the image override with ``{{ app.version }}`` set to ``version``, if one applies.

    Raises :class:`InvalidImageReferenceError` (reason ``after_substitution``) when the result
    is not a valid reference.
    """
    override = component.image_override
    if component.config.container is None or override is None or override.is_orphaned:
        return None
    return validate_reference(override.reference, version=version, component_name=name)
