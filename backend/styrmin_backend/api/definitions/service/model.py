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
            instance=instance,
        )


@strawberry.input
class ServiceNameOverride:
    """Input for overriding service names at deploy time."""

    driver_service_name: str
    override_name: str
