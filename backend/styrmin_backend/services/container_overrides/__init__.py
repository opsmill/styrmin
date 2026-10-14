"""Component-scope container ``command``/``args`` override resolution and validation.

Per-component, optional, nullable ``command`` (entrypoint) and ``args`` slots set on a single
deployment (014). There is no layering: the resolved value is the component block's value or
"unset" (ADR-045 §1). Applicable values reach the component container through the post-render
merge patch built in :mod:`styrmin_backend.services.component_container` (ADR-069).

Modules:

* :mod:`validator` — :func:`validate_container_override` (non-empty list of strings,
  empty-string elements accepted, ``[]`` rejected, per-list size caps).
* :mod:`resolver` — :class:`ContainerOverridesResolver` (per-component lookup plus orphan
  detection; no merge).
* :mod:`exceptions` — :class:`~styrmin_backend.services.exceptions.ServiceError` subclasses
  surfaced through ``StructuredErrorExtension`` as ``extensions.code`` values.
"""

from styrmin_backend.services.container_overrides.exceptions import (
    ContainerOverrideSizeLimitExceededError,
    InvalidContainerArgsError,
    InvalidContainerCommandError,
    UnknownComponentContainerOverrideError,
)
from styrmin_backend.services.container_overrides.resolver import (
    ContainerOverridesResolver,
    ResolvedContainerOverrideEntry,
)
from styrmin_backend.services.container_overrides.validator import (
    validate_container_override,
)

__all__ = [
    "ContainerOverrideSizeLimitExceededError",
    "ContainerOverridesResolver",
    "InvalidContainerArgsError",
    "InvalidContainerCommandError",
    "ResolvedContainerOverrideEntry",
    "UnknownComponentContainerOverrideError",
    "validate_container_override",
]
