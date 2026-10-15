"""Exception types for per-component replica counts (023, contracts/errors.md).

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries a stable
``error_code`` that the GraphQL ``StructuredErrorExtension`` projects onto ``extensions.code``.
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.context.models.config import MAX_REPLICA_COUNT
from styrmin_backend.services.exceptions import ServiceError


class InvalidReplicaCountError(ServiceError):
    """A replica override is not an integer from 1 to ``MAX_REPLICA_COUNT``.

    ``requested_replicas`` is the submitted value as given, so a ``bool``, a string or a float
    is reported as such.
    """

    error_code = "INVALID_REPLICA_COUNT"
    default_message = "The replica count is invalid"

    def __init__(
        self,
        message: str = "",
        *,
        component_name: str | None = None,
        requested_replicas: Any = None,
    ) -> None:
        self.component_name = component_name
        self.requested_replicas = requested_replicas
        subject = f" for component {component_name!r}" if component_name else ""
        super().__init__(
            message
            or (
                f"Replica count{subject} must be an integer from 1 to {MAX_REPLICA_COUNT}, "
                f"got {requested_replicas!r}. To run no pods, stop the component instead."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "requested_replicas": self.requested_replicas,
        }


class UnknownComponentReplicaOverrideError(ServiceError):
    """A write adds or changes a replica override on a component the driver version does not declare.

    Not raised for a removal or for the stored value sent again (an orphaned override is kept).
    """

    error_code = "UNKNOWN_COMPONENT_REPLICA_OVERRIDE"
    default_message = "Replica override targets an unknown component"

    def __init__(
        self,
        message: str = "",
        *,
        component_name: str = "",
        known_components: list[str] | None = None,
        checked_against: str = "",
    ) -> None:
        self.component_name = component_name
        self.known_components = sorted(known_components or [])
        self.checked_against = checked_against
        super().__init__(
            message
            or (
                f"Replica override targets component {component_name!r}, which "
                f"{checked_against or 'the driver version'} does not declare. "
                f"Known components: [{', '.join(self.known_components)}]."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "known_components": self.known_components,
            "checked_against": self.checked_against,
        }


class SingletonReplicaOverrideError(ServiceError):
    """A replica override above 1 targets a component the driver version marks ``singleton``.

    Raised for a stored value sent again too: the rule is checked against the driver version the
    deployment is bound to after the write.
    """

    error_code = "SINGLETON_REPLICA_OVERRIDE"
    default_message = "A singleton component runs exactly 1 replica"

    def __init__(
        self,
        message: str = "",
        *,
        component_name: str = "",
        requested_replicas: int = 0,
        checked_against: str = "",
    ) -> None:
        self.component_name = component_name
        self.requested_replicas = requested_replicas
        self.checked_against = checked_against
        super().__init__(
            message
            or (
                f"Component {component_name!r} is a singleton component in "
                f"{checked_against or 'the driver version'} and runs exactly 1 replica; the "
                f"requested count is {requested_replicas}. Set the override to 1 or clear it."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "requested_replicas": self.requested_replicas,
            "checked_against": self.checked_against,
        }
