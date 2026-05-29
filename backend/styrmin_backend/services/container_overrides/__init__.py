"""Component-scope container ``command``/``args`` override resolution & validation.

Per-component, optional, nullable ``command`` (entrypoint) and ``args`` slots
settable on a single deployment with **zero driver-source changes**
(014-component-container-overrides). A faithful port of the deployment env-vars
precedent (008/010, ADR-013) with two deliberate divergences, both flowing from
the component-scope-only contract (FR-003):

* **No layering.** Env-vars merge ``environment → deployment → component``
  per-key. ``command``/``args`` have no broader scope — the resolved value is
  simply the component block's value or "unset". Resolution is a direct lookup,
  not a merge (research.md D2).
* **Omit-marker filter.** The driver-consumption filters return the list **or
  ``None``** (never ``[]``), because ``[]`` is a meaningful Kubernetes value
  distinct from "unset"; the driver template guards with a conditional so the
  chart default flows through when unset (research.md D8).

Modules:

* :mod:`validator` — :func:`validate_container_override` (non-empty
  list-of-string, empty-string elements accepted, ``[]`` rejected).
* :mod:`resolver` — :class:`ContainerOverridesResolver` (per-component direct
  lookup plus orphan detection; no merge).
* :mod:`exceptions` — :class:`~styrmin_backend.services.exceptions.ServiceError`
  subclasses surfaced through ``StructuredErrorExtension`` as precise
  ``extensions.code`` values.

See ``specs/014-component-container-overrides/`` for the feature spec and
``dev/adr/adr-045-container-override-no-layering-and-omit-marker.md`` for the
divergences from ADR-013.
"""

from styrmin_backend.services.container_overrides.exceptions import (
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
    "ContainerOverridesResolver",
    "InvalidContainerArgsError",
    "InvalidContainerCommandError",
    "ResolvedContainerOverrideEntry",
    "UnknownComponentContainerOverrideError",
    "validate_container_override",
]
