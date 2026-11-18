"""The ``services`` and ``deployed_services`` entries of a deployment's context.

The server builds them from the deployed services of the environment, and
``styrmin-driver`` builds them from the services that a driver declares. Both use
``build_service_entries``, so the entries have the same keys and values (ADR-0089).
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from styrmin_sdk.driver_format.context.fqdn import (
    compute_service_address,
    service_gets_ingress,
)
from styrmin_sdk.driver_format.context.models.config import ResolvedConfig, ServiceConfigBlock
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
    def scope(self) -> str: ...

    @property
    def component(self) -> str: ...

    @property
    def deployment_id(self) -> UUID: ...


def order_deployed_services[Row: ServiceRow](
    rows: Iterable[Row],
    *,
    deployment_id: UUID,
    declared_names: Sequence[str],
) -> list[Row]:
    """Order the services of an environment deterministically.

    The repository query has no ``ORDER BY``. The services of other deployments come first,
    by deployment id and service name. The services of this deployment come last, in the
    order in which its driver version declares them (the Ingress builder gives the
    application address to the first one). Because the services of this deployment come
    last, they win a ``services`` key that a peer shares with them. A service that the
    driver version does not declare sorts after the declared ones, by name.
    """
    declared_index = {name: index for index, name in enumerate(declared_names)}

    def sort_key(svc: Row) -> tuple[int, str, int, str]:
        if svc.deployment_id != deployment_id:
            return (0, str(svc.deployment_id), 0, svc.driver_service_name)
        return (
            1,
            "",
            declared_index.get(svc.driver_service_name, len(declared_index)),
            svc.driver_service_name,
        )

    return sorted(rows, key=sort_key)


def build_service_entries(
    rows: Iterable[ServiceRow],
    *,
    config: ResolvedConfig,
    service_overrides: Mapping[UUID, Mapping[str, ServiceConfigBlock]],
    declared_names: Sequence[str],
    app_name: str,
    deployment_id: UUID,
    environment_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """Build the ``services`` mapping and the ``deployed_services`` list of a context.

    Args:
        rows: The deployed services of the environment, the deployment's own included.
        config: The resolved configuration of the deployment.
        service_overrides: The service ingress overrides of each deployment that owns a
            service, keyed by deployment ID and then by driver service name. A service
            uses the override of the deployment that owns it (#598, FR-006).
        declared_names: The service names that the deployment's driver version declares, in order.
        app_name: The name of the deployment's application driver.
        deployment_id: The ID of the deployment whose context is built.
        environment_name: The name of the deployment's environment.

    Returns:
        The ``services`` mapping keyed by driver service name, the ``deployed_services``
        list, and whether the deployment owns at least one of the services.
    """
    services: dict[str, Any] = {}
    deployed_services: list[dict[str, Any]] = []
    has_own_services = False
    for svc in order_deployed_services(rows, deployment_id=deployment_id, declared_names=declared_names):
        # An override applies only to a service whose Ingress Styrmin builds.
        override = (
            service_overrides.get(svc.deployment_id, {}).get(svc.driver_service_name)
            if service_gets_ingress(svc.scope, svc.kind)
            else None
        )
        address = compute_service_address(
            config,
            override,
            service_host=svc.resolved_name,
            environment_name=environment_name,
            app_name=app_name,
            deployment_id=deployment_id,
        )
        ref = ServiceReference(
            host=svc.resolved_name,
            port=svc.port,
            kind=svc.kind,
            primary_fqdn=address.primary_fqdn,
            human_readable_fqdn=address.human_readable_fqdn,
            ingress_class=address.ingress_class,
            overridden=address.overridden,
        )
        services[svc.driver_service_name] = ref.model_dump()
        deployed_services.append(
            {
                "driver_service_name": svc.driver_service_name,
                "resolved_name": svc.resolved_name,
                "port": svc.port,
                "kind": svc.kind,
                "scope": svc.scope,
                "deployment_id": str(svc.deployment_id),
                "component": svc.component,
                "ingress_class": address.ingress_class,
                "fqdn_suffix": address.fqdn_suffix,
            }
        )
        if str(svc.deployment_id) == str(deployment_id):
            has_own_services = True
    return services, deployed_services, has_own_services
