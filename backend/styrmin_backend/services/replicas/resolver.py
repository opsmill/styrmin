"""Order of precedence for a component's replica count (023, research D-003).

Pure logic, no IO. The replica patch builder, the write checks and the GraphQL read field call
these two functions, so the order of precedence lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReplicaSource(StrEnum):
    """Where a component's replica count comes from."""

    OVERRIDE = "override"
    DRIVER_DEFAULT = "driver_default"
    # No replica patch: the chart's own count applies.
    CHART = "chart"


@dataclass(frozen=True)
class ResolvedReplicas:
    """The count Styrmin applies while the component runs, and its source.

    ``count`` is ``None`` only when ``source`` is ``CHART``. ``override_applies`` is true when a
    stored override is the source.
    """

    count: int | None
    source: ReplicaSource
    override_applies: bool


_CHART = ResolvedReplicas(
    count=None, source=ReplicaSource.CHART, override_applies=False
)


def resolve_replicas(
    *,
    declared_replicas: int | None,
    singleton: bool,
    override: int | None,
    is_orphaned: bool,
) -> ResolvedReplicas:
    """Resolve a component's replica count (FR-002, FR-007, data-model.md precedence table).

    An orphaned override never applies. A valid override wins. Otherwise the driver default
    applies: ``declared_replicas``, or 1 for a singleton that declares none. Otherwise the chart's
    count applies. An override above 1 on a singleton cannot be stored; if one is read, it is
    ignored and the singleton's count applies.
    """
    if is_orphaned:
        return _CHART
    if override is not None and not (singleton and override > 1):
        return ResolvedReplicas(
            count=override, source=ReplicaSource.OVERRIDE, override_applies=True
        )
    if declared_replicas is not None:
        return ResolvedReplicas(
            count=declared_replicas,
            source=ReplicaSource.DRIVER_DEFAULT,
            override_applies=False,
        )
    if singleton:
        return ResolvedReplicas(
            count=1, source=ReplicaSource.DRIVER_DEFAULT, override_applies=False
        )
    return _CHART


def replica_patch_count(resolved: ResolvedReplicas, *, enabled: bool) -> int | None:
    """Return the ``spec.replicas`` value to patch, or ``None`` for no patch.

    A stopped component is patched to 0 whatever its resolved count.
    """
    if not enabled:
        return 0
    return resolved.count
