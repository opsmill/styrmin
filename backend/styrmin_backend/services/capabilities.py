"""Capability derivation logic.

Computes hierarchical capabilities from existing cluster/environment
configuration and relationships. Results are persisted as JSON.
"""

from __future__ import annotations

from typing import Any

from styrmin_backend.context.models.capabilities import (
    BackupCapabilityDetail,
    Capabilities,
    IngressCapabilityDetail,
    StorageCapabilityDetail,
    capabilities_to_dict,
)
from styrmin_backend.context.models.config import ClusterConfig, EnvironmentConfig
from styrmin_backend.context.validators import (
    validate_cluster_config,
    validate_environment_config,
)
from styrmin_backend.db.models import Cluster, Environment


def compute_cluster_capabilities(cluster: Cluster) -> dict[str, Any] | None:
    """Compute capabilities for a cluster based on its configuration.

    Returns a dict suitable for JSON storage, or None if no capabilities.
    """
    config_dict = cluster.config or {}

    # Validate and parse config into typed model
    try:
        validate_cluster_config(config_dict)
        config = ClusterConfig.model_validate(config_dict)
    except Exception:
        return None

    capabilities = Capabilities()

    # Storage capability: derived from standard_storage
    if config.standard_storage is not None:
        capabilities.storage = {
            "standard": StorageCapabilityDetail(
                storage_class=config.standard_storage.storage_class,
            ),
        }

    # Ingress capability: requires both ingress_class (or dedicated_ingress) and fqdn_suffix
    ingress_class = config.ingress_class
    has_ingress = ingress_class is not None or config.dedicated_ingress is not None
    if has_ingress and config.fqdn_suffix is not None:
        effective_ingress_class = ingress_class or (
            config.dedicated_ingress.implementation
            if config.dedicated_ingress
            else "unknown"
        )
        capabilities.ingress = {
            "external": IngressCapabilityDetail(
                ingress_class=effective_ingress_class,
                fqdn_suffix=config.fqdn_suffix,
            ),
        }

    return capabilities_to_dict(capabilities)


def compute_environment_capabilities(environment: Environment) -> dict[str, Any] | None:
    """Compute capabilities for an environment based on its own configuration and relationships.

    This is an environment-scoped view — only capabilities actually usable
    in this environment are included, not the full set of cluster capabilities.

    Returns a dict suitable for JSON storage, or None if no capabilities.
    """
    config_dict = environment.config or {}

    # Validate and parse config into typed model
    try:
        validate_environment_config(config_dict)
        config = EnvironmentConfig.model_validate(config_dict)
    except Exception:
        return None

    capabilities = Capabilities()

    # Backup capability: derived from backup_storage_location assignment
    if environment.backup_storage_location is not None:
        capabilities.backup = {
            "velero": BackupCapabilityDetail(
                storage_location=environment.backup_storage_location.name,
            ),
        }

    # Ingress capability: requires both ingress_class (or dedicated_ingress) and fqdn_suffix
    ingress_class = config.ingress_class
    has_ingress = ingress_class is not None or config.dedicated_ingress is not None
    if has_ingress and config.fqdn_suffix is not None:
        effective_ingress_class = ingress_class or (
            config.dedicated_ingress.implementation
            if config.dedicated_ingress
            else "unknown"
        )
        capabilities.ingress = {
            "external": IngressCapabilityDetail(
                ingress_class=effective_ingress_class,
                fqdn_suffix=config.fqdn_suffix,
            ),
        }

    return capabilities_to_dict(capabilities)
