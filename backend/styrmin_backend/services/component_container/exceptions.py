"""The missing-component-container guard failure and its parser (018, research D-002 and D-004).

The post-render JSON6902 patch moves the component container to the temporary key
``/spec/template/spec/styrmin.io~1component-container~1<esc(N)>~1<esc(C)>`` and removes its
``image`` there. When the container is missing, the render fails with that key followed by
``/image`` in the message, which the operator turns into :class:`ComponentContainerNotFoundError`.
"""

from __future__ import annotations

import re
from typing import Any

from styrmin_backend.services.exceptions import ServiceError

GUARD_KEY_PREFIX = "styrmin.io~1component-container~1"

# Container names are DNS-1123 labels (no "~" or "/"), so the last "~1" splits component from container.
_GUARD_FAILURE_RE = re.compile(
    re.escape(GUARD_KEY_PREFIX)
    + r"(?P<component>[^/\s'\"]+)~1(?P<container>[^~/\s'\"]+)/image\b"
)


def _unescape_json_pointer(token: str) -> str:
    # RFC 6901 order: "~1" first, then "~0", so "~01" decodes to "~1".
    return token.replace("~1", "/").replace("~0", "~")


def parse_guard_failure(message: str) -> tuple[str, str] | None:
    """Return ``(component, container)`` from a guard failure message, or ``None`` for any other message."""
    match = _GUARD_FAILURE_RE.search(message)
    if match is None:
        return None
    return (
        _unescape_json_pointer(match.group("component")),
        _unescape_json_pointer(match.group("container")),
    )


class ComponentContainerNotFoundError(ServiceError):
    """A declared component container is missing from the component's rendered workload.

    Built by the operator from a HelmRelease guard failure; Styrmin never adds a container.
    """

    error_code = "COMPONENT_CONTAINER_NOT_FOUND"
    default_message = (
        "A declared component container was not found in its rendered workload"
    )

    def __init__(
        self, message: str = "", component_name: str = "", container: str = ""
    ) -> None:
        self.component_name = component_name
        self.container = container
        super().__init__(
            message
            or (
                f"Component {component_name!r}: component container {container!r} was not found "
                "in its rendered workload. Styrmin never adds a container; fix "
                f"components.{component_name}.container in the driver specification file."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"component_name": self.component_name, "container": self.container}
