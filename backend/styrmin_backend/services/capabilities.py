"""Capability derivation logic.

Computes hierarchical capabilities from existing cluster/environment
configuration and relationships. Results are persisted as JSON.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import ValidationError

from styrmin_backend.context.models.capabilities import (
    BackupCapabilityDetail,
    Capabilities,
    IngressCapabilityDetail,
    StorageCapabilityDetail,
    capabilities_to_dict,
)
from styrmin_backend.context.models.config import (
    ClusterConfig,
    EnvironmentConfig,
)
from styrmin_backend.db.models import Cluster, Environment


def _derive_ingress(
    config: ClusterConfig | EnvironmentConfig,
) -> dict[str, IngressCapabilityDetail] | None:
    """Derive ingress capability if an ingress controller (ingress_class or dedicated_ingress) and fqdn_suffix are both present."""
    has_ingress = (
        config.ingress_class is not None or config.dedicated_ingress is not None
    )
    if not has_ingress or config.fqdn_suffix is None:
        return None

    effective_class = config.ingress_class or (
        config.dedicated_ingress.implementation
        if config.dedicated_ingress
        else "unknown"
    )
    return {
        "external": IngressCapabilityDetail(
            ingress_class=effective_class,
            fqdn_suffix=config.fqdn_suffix,
        ),
    }


def compute_cluster_capabilities(cluster: Cluster) -> dict[str, Any] | None:
    """Compute capabilities for a cluster based on its configuration.

    Returns a dict suitable for JSON storage, or None if no capabilities.
    """
    try:
        config = ClusterConfig.model_validate(cluster.config or {})
    except ValidationError:
        logger.warning(
            "Invalid cluster config for '{}', skipping capability derivation",
            cluster.name,
        )
        return None

    capabilities = Capabilities()

    if config.standard_storage is not None:
        capabilities.storage = {
            "standard": StorageCapabilityDetail(
                storage_class=config.standard_storage.storage_class,
            ),
        }

    capabilities.ingress = _derive_ingress(config)

    return capabilities_to_dict(capabilities)


def compute_environment_capabilities(environment: Environment) -> dict[str, Any] | None:
    """Compute capabilities for an environment based on its own configuration and relationships.

    This is an environment-scoped view — only capabilities actually usable
    in this environment are included, not the full set of cluster capabilities.

    Returns a dict suitable for JSON storage, or None if no capabilities.
    """
    try:
        config = EnvironmentConfig.model_validate(environment.config or {})
    except ValidationError:
        logger.warning(
            "Invalid environment config for '{}', skipping capability derivation",
            environment.name,
        )
        return None

    capabilities = Capabilities()

    if environment.backup_storage_location is not None:
        capabilities.backup = {
            "velero": BackupCapabilityDetail(
                storage_location=environment.backup_storage_location.name,
            ),
        }

    capabilities.ingress = _derive_ingress(config)

    return capabilities_to_dict(capabilities)
