"""Write-time checks of per-component replica overrides (023, research D-005 and D-006).

Runs on the raw config dict on ``deploy``, ``updateDeployment`` and ``updateDeploymentVersion``,
against the driver version the deployment is bound to after the write, before any task, flow run
or ingress dispatch. The count itself (an integer from 1 to 2147483647) is checked by
``ComponentConfigBlock`` (``INVALID_REPLICA_COUNT``), which callers run first.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from styrmin_backend.context.models.components import ReplicaDeclaration
from styrmin_backend.services.replicas.exceptions import (
    ReplicaCountAboveMaximumError,
    SingletonReplicaOverrideError,
    UnknownComponentReplicaOverrideError,
)


def has_replica_overrides(config: dict[str, Any] | None) -> bool:
    """Whether any component block of ``config`` sets ``replicas``."""
    return next(_replica_overrides(config), None) is not None


def _replica_overrides(config: dict[str, Any] | None) -> Iterator[tuple[str, Any]]:
    """Yield ``(component, replicas)`` for every component block with a non-null ``replicas``."""
    components = (config or {}).get("components")
    if not isinstance(components, dict):
        return
    for name, block in components.items():
        if isinstance(block, dict) and block.get("replicas") is not None:
            yield name, block["replicas"]


def validate_replica_overrides(
    config: dict[str, Any] | None,
    *,
    components: Mapping[str, ReplicaDeclaration],
    stored_config: dict[str, Any] | None,
    checked_against: str,
    max_replica_count: int,
) -> None:
    """Reject replica overrides the driver version cannot apply.

    ``components`` maps each component the driver version declares to its declaration.

    Raises:
        UnknownComponentReplicaOverrideError: An override on an undeclared component is added
            or changed. The stored value sent again is kept, so an orphaned override survives.
        SingletonReplicaOverrideError: An override above 1 targets a singleton component, also
            when it equals the stored value.
        ReplicaCountAboveMaximumError: An added or changed override is above
            ``max_replica_count``.
    """
    stored = dict(_replica_overrides(stored_config))
    for name, replicas in _replica_overrides(config):
        declaration = components.get(name)
        if declaration is None:
            if name not in stored or stored[name] != replicas:
                raise UnknownComponentReplicaOverrideError(
                    component_name=name,
                    known_components=list(components),
                    checked_against=checked_against,
                )
            continue
        if declaration.singleton and isinstance(replicas, int) and replicas > 1:
            raise SingletonReplicaOverrideError(
                component_name=name,
                requested_replicas=replicas,
                checked_against=checked_against,
            )
        changed = name not in stored or stored[name] != replicas
        if changed and isinstance(replicas, int) and replicas > max_replica_count:
            raise ReplicaCountAboveMaximumError(
                component_name=name,
                requested_replicas=replicas,
                max_replica_count=max_replica_count,
            )
