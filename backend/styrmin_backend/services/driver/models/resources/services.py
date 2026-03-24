"""Provides the validation models for driver service definitions.

Driver services allow driver authors to declare network services that their
application exposes, enabling automatic service discovery between applications
deployed in the same environment.

Example in styrmin_driver.yaml:
    ```yaml
    spec:
      services:
        - name: infrahub
          kind: https
          scope: internal
          port: 8000
          component: server
        - name: infrahub-cache
          kind: tcp
          scope: internal
          port: 6379
          component: cache
    ```
"""

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class ServiceKind(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    TCP = "tcp"
    UDP = "udp"


class ServiceScope(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


# DNS label: lowercase alphanumeric + hyphens, max 63 chars, no leading/trailing hyphens
_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def validate_dns_label(name: str) -> str:
    """Validate that a string is a valid DNS label."""
    if not _DNS_LABEL_RE.match(name):
        raise ValueError(
            f"'{name}' is not a valid DNS label. Must be lowercase alphanumeric "
            "with hyphens, max 63 characters, no leading/trailing hyphens."
        )
    return name


class ServiceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ServiceKind
    scope: ServiceScope
    port: int
    component: str

    @field_validator("name", mode="after")
    @classmethod
    def validate_name_dns_label(cls, value: str) -> str:
        return validate_dns_label(value)

    @field_validator("port", mode="after")
    @classmethod
    def validate_port_range(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {value}")
        return value


def validate_service_names_unique(
    services: list[ServiceDefinition],
) -> list[ServiceDefinition]:
    """Validate that service names are unique within a list."""
    names = [s.name for s in services]
    duplicates = [name for name in names if names.count(name) > 1]
    if duplicates:
        raise ValueError(f"Duplicate service names: {sorted(set(duplicates))}")
    return services
