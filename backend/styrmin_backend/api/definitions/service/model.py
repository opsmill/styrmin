"""Strawberry GraphQL types for service discovery."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

import strawberry

from styrmin_backend.db.models import DeployedService as DeployedServiceModel


@strawberry.enum
class ServiceKind(Enum):
    HTTP = "http"
    HTTPS = "https"
    TCP = "tcp"
    UDP = "udp"


@strawberry.enum
class ServiceScope(Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


@strawberry.type
class ServiceDefinition:
    """A service declared in a driver version."""

    name: str
    kind: str
    scope: str
    port: int
    component: str

    @classmethod
    def from_dict(cls, data: dict) -> ServiceDefinition:
        return cls(
            name=data["name"],
            kind=data["kind"],
            scope=data["scope"],
            port=data["port"],
            component=data["component"],
        )


@strawberry.type
class DeployedService:
    """A deployed (runtime) service instance within an environment."""

    id: UUID
    driver_service_name: str
    resolved_name: str
    kind: str
    scope: str
    port: int
    component: str
    primary_fqdn: str | None = None
    human_readable_fqdn: str | None = None
    primary_url: str | None = None
    human_readable_url: str | None = None
    ingress_class: str | None = strawberry.field(
        default=None,
        description=(
            "Effective ingress class of the Ingress that Styrmin builds for this "
            "service: the service's override, else the resolved class. Null for a "
            "service that is not external, and where the deployment is not read."
        ),
    )
    ingress_class_overridden: bool = strawberry.field(
        default=False,
        description=(
            "True when `ingressClass` comes from the service's ingress override."
        ),
    )
    fqdn_suffix_overridden: bool = strawberry.field(
        default=False,
        description=(
            "True when the suffix of `humanReadableFqdn` and `humanReadableUrl` "
            "comes from the service's ingress override."
        ),
    )

    instance: strawberry.Private[DeployedServiceModel]

    @strawberry.field
    def deployment_id(self) -> UUID:
        return self.instance.deployment_id

    @classmethod
    def from_instance(
        cls,
        instance: DeployedServiceModel,
        *,
        primary_fqdn: str | None = None,
        human_readable_fqdn: str | None = None,
        primary_url: str | None = None,
        human_readable_url: str | None = None,
        ingress_class: str | None = None,
        ingress_class_overridden: bool = False,
        fqdn_suffix_overridden: bool = False,
    ) -> DeployedService:
        return cls(
            id=instance.id,
            driver_service_name=instance.driver_service_name,
            resolved_name=instance.resolved_name,
            kind=instance.kind,
            scope=instance.scope,
            port=instance.port,
            component=instance.component,
            primary_fqdn=primary_fqdn,
            human_readable_fqdn=human_readable_fqdn,
            primary_url=primary_url,
            human_readable_url=human_readable_url,
            ingress_class=ingress_class,
            ingress_class_overridden=ingress_class_overridden,
            fqdn_suffix_overridden=fqdn_suffix_overridden,
            instance=instance,
        )


@strawberry.input
class ServiceNameOverride:
    """Input for overriding service names at deploy time."""

    driver_service_name: str
    override_name: str
