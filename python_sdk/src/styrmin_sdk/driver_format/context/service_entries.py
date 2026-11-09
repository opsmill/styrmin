"""The ``services`` and ``deployed_services`` entries of a deployment's context.

The server builds them from the deployed services of the environment, and
``styrmin-driver`` builds them from the services that a driver declares. Both use
``build_service_entries``, so the entries have the same keys and values (ADR-0089).
"""

from collections.abc import Iterable
from typing import Any, Protocol
from uuid import UUID

from styrmin_sdk.driver_format.context.fqdn import (
    compute_human_readable_fqdn,
    compute_primary_fqdn,
)
from styrmin_sdk.driver_format.context.models.services import ServiceReference


class ServiceRow(Protocol):
    """A deployed service, as the server stores it (``DeployedService``)."""

    @property
    def driver_service_name(self) -> str: ...

    @property
    def resolved_name(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def kind(self) -> str: ...

    @property
    def component(self) -> str: ...

    @property
    def deployment_id(self) -> UUID: ...


def build_service_entries(
    rows: Iterable[ServiceRow],
    *,
    app_name: str,
    deployment_id: UUID,
    environment_name: str,
    fqdn_suffix: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """Build the ``services`` mapping and the ``deployed_services`` list of a context.

    Args:
        rows: The deployed services of the environment, the deployment's own included.
        app_name: The name of the deployment's application driver.
        deployment_id: The ID of the deployment whose context is built.
        environment_name: The name of the deployment's environment.
        fqdn_suffix: The resolved FQDN suffix of the deployment, or ``None``.

    Returns:
        The ``services`` mapping keyed by driver service name, the ``deployed_services``
        list, and whether the deployment owns at least one of the services.
    """
    services: dict[str, Any] = {}
    deployed_services: list[dict[str, Any]] = []
    has_own_services = False
    for svc in rows:
        ref = ServiceReference(
            host=svc.resolved_name,
            port=svc.port,
            kind=svc.kind,
            primary_fqdn=compute_primary_fqdn(app_name, str(deployment_id), fqdn_suffix),
            human_readable_fqdn=compute_human_readable_fqdn(svc.resolved_name, environment_name, fqdn_suffix),
        )
        services[svc.driver_service_name] = ref.model_dump()
        deployed_services.append(
            {
                "resolved_name": svc.resolved_name,
                "port": svc.port,
                "kind": svc.kind,
                "deployment_id": str(svc.deployment_id),
                "component": svc.component,
            }
        )
        if str(svc.deployment_id) == str(deployment_id):
            has_own_services = True
    return services, deployed_services, has_own_services
