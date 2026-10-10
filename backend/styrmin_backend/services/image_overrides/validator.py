"""Write-time validation of per-component image overrides (018, research D-008).

Runs on the raw config dict at the ``deploy`` / ``updateDeployment`` / ``updateDeploymentVersion``
boundary, before ``DeploymentConfig`` is built, so the typed errors name the component and the
substituted version.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from styrmin_backend.services.image_overrides.exceptions import (
    UnknownComponentImageOverrideError,
)
from styrmin_backend.services.image_overrides.reference import validate_reference


def _submitted_images(config: dict[str, Any] | None) -> Iterator[tuple[str, Any]]:
    """Yield ``(component, image)`` for every component block with a non-null ``image``."""
    components = (config or {}).get("components")
    if not isinstance(components, dict):
        return
    for name, block in components.items():
        if isinstance(block, dict) and block.get("image") is not None:
            yield name, block["image"]


def validate_image_override_targets(
    config: dict[str, Any] | None,
    known_names: Iterable[str],
    checked_against: str = "",
) -> None:
    """Reject an image override on a component the driver version does not declare.

    Raises :class:`UnknownComponentImageOverrideError`. Blocks without an ``image`` are left to
    the checks of their own slots.
    """
    known = set(known_names)
    for name, _image in _submitted_images(config):
        if name not in known:
            raise UnknownComponentImageOverrideError(
                component_name=name,
                known_components=list(known),
                checked_against=checked_against,
            )


def prevalidate_image_overrides(
    config: dict[str, Any] | None,
    *,
    version: str,
    stored_config: dict[str, Any] | None = None,
) -> None:
    """Validate every new or changed image override against the application ``version``.

    Entries equal to the ``stored_config`` value are skipped: they were validated when written,
    and applicable ones are re-validated on every version change, so re-checking them would only
    block unrelated edits on a deployment holding a stranded override.

    Raises :class:`InvalidImageReferenceError` naming the component (grammar, missing tag or
    digest, template expression, or ``after_substitution`` when only ``version`` breaks it).
    """
    stored = dict(_submitted_images(stored_config))
    for name, image in _submitted_images(config):
        if stored.get(name) == image:
            continue
        validate_reference(image, version=version, component_name=name)
