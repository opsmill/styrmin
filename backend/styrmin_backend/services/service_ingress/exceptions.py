"""Exception types for the per-service ingress override (#598, contracts/graphql-and-manifest.md).

Every exception subclasses :class:`ServiceError` (Constitution §IV) and carries a stable
``error_code`` that the GraphQL ``StructuredErrorExtension`` projects onto ``extensions.code``.
"""

from __future__ import annotations

from typing import Any, Literal

from styrmin_backend.services.exceptions import ServiceError


class DuplicateServiceNameError(ServiceError):
    """The ``services`` input list contains the same driver service name twice.

    Detected before the list is flattened to the stored ``dict`` keyed on the driver
    service name, so the second row cannot silently replace the first.
    """

    error_code = "DUPLICATE_SERVICE_NAME"
    default_message = "Duplicate service name in input list"

    def __init__(self, message: str = "", name: str = "") -> None:
        self.name = name
        super().__init__(
            message
            or (
                f"Service name {name!r} appears more than once in the services "
                "list; remove the duplicate before submitting."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {"name": self.name}


class UnknownServiceIngressOverrideError(ServiceError):
    """A write adds or changes an ingress override on a service the driver version does not declare.

    The service is checked against the driver version the deployment is bound to after the
    write. Not raised when the request clears the override.
    """

    error_code = "UNKNOWN_SERVICE_INGRESS_OVERRIDE"
    default_message = "Service ingress override targets an unknown service"

    def __init__(
        self,
        message: str = "",
        *,
        service_name: str = "",
        known_services: list[str] | None = None,
        checked_against: str = "",
    ) -> None:
        self.service_name = service_name
        self.known_services = sorted(known_services or [])
        self.checked_against = checked_against
        super().__init__(
            message
            or (
                f"Ingress override targets service {service_name!r}, which "
                f"{checked_against or 'the driver version'} does not declare. "
                f"Known services: [{', '.join(self.known_services)}]."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "known_services": self.known_services,
            "checked_against": self.checked_against,
        }


class ServiceIngressNotBuiltError(ServiceError):
    """A write adds or changes an ingress override on a service that Styrmin builds no Ingress for.

    Styrmin builds an Ingress only for a service with ``scope: external`` and kind ``http``
    or ``https``, so the override would have no effect on an internal service, or on an
    external service of kind ``tcp`` or ``udp``.
    """

    error_code = "SERVICE_INGRESS_NOT_BUILT"
    default_message = "Styrmin does not build an Ingress for this service"

    def __init__(
        self,
        message: str = "",
        *,
        service_name: str,
        scope: str,
        kind: str,
        checked_against: str = "",
    ) -> None:
        self.service_name = service_name
        self.scope = scope
        self.kind = kind
        self.checked_against = checked_against
        where = checked_against or "the driver version"
        if scope != "external":
            default = (
                f"Service {service_name!r} has scope {scope!r} in {where}, so Styrmin "
                "does not build its Ingress and an ingress override has no effect. Only a "
                "service with scope 'external' and kind 'http' or 'https' can have an "
                "ingress override."
            )
        else:
            default = (
                f"Service {service_name!r} has kind {kind!r} in {where}, so Styrmin does "
                "not build its Ingress and an ingress override has no effect. Only a "
                "service with scope 'external' and kind 'http' or 'https' can have an "
                "ingress override."
            )
        super().__init__(message or default)

    @property
    def error_metadata(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "scope": self.scope,
            "kind": self.kind,
            "checked_against": self.checked_against,
        }


DroppedReason = Literal["removed", "internal", "not_http_or_https"]
"""Why a driver version change would leave an override without an Ingress.

``removed``: the target version does not declare the service. ``internal``: it declares the
service with ``scope: internal``. ``not_http_or_https``: it declares the service external, with
a kind other than ``http`` or ``https`` (``tcp`` or ``udp``).
"""


class ServiceIngressOverrideWouldBeDroppedError(ServiceError):
    """A driver version change would leave a stored ingress override without a built Ingress.

    The target driver version removes the service (``reason`` ``removed``), declares it
    ``scope: internal`` (``internal``), or declares it external with kind ``tcp`` or ``udp``
    (``not_http_or_https``, with ``target_kind``). Raised before any pod changes, so the
    override is never dropped silently (FR-010). The request can clear the override.
    """

    error_code = "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED"
    default_message = "The driver version change would drop a service ingress override"

    def __init__(
        self,
        message: str = "",
        *,
        service_name: str,
        current_version: str,
        target_version: str,
        reason: DroppedReason,
        target_kind: str | None = None,
    ) -> None:
        if reason == "not_http_or_https" and not target_kind:
            raise ValueError(
                "target_kind is required for the reason 'not_http_or_https'"
            )
        self.service_name = service_name
        self.current_version = current_version
        self.target_version = target_version
        self.reason: DroppedReason = reason
        self.target_kind = target_kind
        outcomes: dict[str, str] = {
            "removed": "does not declare that service",
            "internal": "declares that service with scope 'internal', and Styrmin does not "
            "build an Ingress for an internal service",
            "not_http_or_https": f"declares that service with kind {target_kind!r}, and "
            "Styrmin builds an Ingress only for kind 'http' or 'https'",
        }
        super().__init__(
            message
            or (
                f"Service {service_name!r} has an ingress override, and driver version "
                f"{target_version} {outcomes[reason]}. Changing the driver version from "
                f"{current_version} to {target_version} would drop the override. Clear the "
                f"override of {service_name!r} in the same request, or keep a driver "
                "version that declares it external with kind 'http' or 'https'."
            )
        )

    @property
    def error_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "service_name": self.service_name,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "reason": self.reason,
        }
        if self.target_kind is not None:
            metadata["target_kind"] = self.target_kind
        return metadata
