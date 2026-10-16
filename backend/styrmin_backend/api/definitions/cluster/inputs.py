"""Strawberry input type for the ``updateCluster`` mutation (021-cluster-config-update).

``UpdateClusterInput`` mirrors ``ClusterConfig`` field by field, except
``scheduling``, which a cluster does not take (#482). It reuses the leaf inputs
of :mod:`styrmin_backend.api.definitions.config.inputs` (ADR-012, research D2).
"""

from __future__ import annotations

from typing import Any

import strawberry

from styrmin_backend.api.definitions.config.inputs import (
    DedicatedIngressInput,
    ExternalDnsEndpointsType,
    ExternalUrlScheme,
    FastStorageInput,
    StandardStorageInput,
    _convert_value,
)


@strawberry.input(
    description=(
        "Full-replacement input for cluster configuration updates. Submit the "
        "complete desired configuration; any field omitted (null) is removed "
        "from the stored config, except ingressClass and runtimeClass, which "
        'default to "traefik" and "default" as on createCluster.'
    )
)
class UpdateClusterInput:
    ingress_class: str | None = None
    runtime_class: str | None = None
    fqdn_suffix: str | None = None
    external_url_scheme: ExternalUrlScheme | None = None
    external_url_port: int | None = None
    external_dns_endpoints_type: ExternalDnsEndpointsType | None = None
    dedicated_ingress: DedicatedIngressInput | None = None
    standard_storage: StandardStorageInput | None = None
    fast_storage: FastStorageInput | None = None
    db_size: str | None = None
    backup_ttl: str | None = None


def update_cluster_input_to_dict(input: UpdateClusterInput) -> dict[str, Any]:
    """Convert an :class:`UpdateClusterInput` into the snake_case dict that ``ClusterConfig`` validates.

    Top-level ``None`` fields are omitted, so the update clears them (full replacement).
    """
    converted = _convert_value(input)
    return converted if isinstance(converted, dict) else {}


__all__ = ["UpdateClusterInput", "update_cluster_input_to_dict"]
