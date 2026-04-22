"""Pydantic models for the hierarchical capability structure.

Capabilities are organized by category (e.g., storage, backup, ingress)
with sub-capabilities inside each category. They are derived from existing
configuration and persisted as JSON on Cluster and Environment models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StorageCapabilityDetail(BaseModel):
    """Detail for a storage sub-capability."""

    model_config = ConfigDict(extra="forbid")

    storage_class: str


class IngressCapabilityDetail(BaseModel):
    """Detail for an ingress sub-capability."""

    model_config = ConfigDict(extra="forbid")

    ingress_class: str
    fqdn_suffix: str


class BackupCapabilityDetail(BaseModel):
    """Detail for a backup sub-capability."""

    model_config = ConfigDict(extra="forbid")

    storage_location: str


class RuntimeClassCapabilityDetail(BaseModel):
    """Detail for an installed ``node.k8s.io/v1`` runtime class."""

    model_config = ConfigDict(extra="forbid")

    name: str


class Capabilities(BaseModel):
    """Root model representing the full capability set for a Cluster or Environment.

    Each category is optional — absent categories are omitted from serialized JSON.
    New categories can be added as optional fields without schema migrations.
    """

    model_config = ConfigDict(extra="forbid")

    storage: dict[str, StorageCapabilityDetail] | None = None
    backup: dict[str, BackupCapabilityDetail] | None = None
    ingress: dict[str, IngressCapabilityDetail] | None = None
    runtime_class: dict[str, RuntimeClassCapabilityDetail] | None = None


def capabilities_to_dict(capabilities: Capabilities) -> dict[str, Any] | None:
    """Serialize capabilities to a dict suitable for JSON storage, omitting None categories.

    Returns None if no capabilities are present.
    """
    data = capabilities.model_dump(exclude_none=True)
    return data if data else None
