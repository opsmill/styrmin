"""Order of precedence for a component's replica count (023, research D-003, data-model.md).

One case per row of the data-model.md precedence table; "any" driver ``replicas`` rows are run
with more than one declared value.
"""

from __future__ import annotations

import dataclasses
from typing import NamedTuple

import pytest

from styrmin_backend.services.replicas.resolver import (
    ReplicaSource,
    ResolvedReplicas,
    replica_patch_count,
    resolve_replicas,
)


class Row(NamedTuple):
    override: int | None
    is_orphaned: bool
    declared_replicas: int | None
    singleton: bool
    expected: ResolvedReplicas


_ROWS: dict[str, Row] = {
    "override-wins-no-driver-default": Row(
        3, False, None, False, ResolvedReplicas(3, ReplicaSource.OVERRIDE, True)
    ),
    "override-wins-over-driver-default": Row(
        3, False, 2, False, ResolvedReplicas(3, ReplicaSource.OVERRIDE, True)
    ),
    "override-one-on-singleton": Row(
        1, False, None, True, ResolvedReplicas(1, ReplicaSource.OVERRIDE, True)
    ),
    "override-one-on-singleton-declaring-one": Row(
        1, False, 1, True, ResolvedReplicas(1, ReplicaSource.OVERRIDE, True)
    ),
    "defensive-override-above-one-on-singleton": Row(
        3, False, None, True, ResolvedReplicas(1, ReplicaSource.DRIVER_DEFAULT, False)
    ),
    "defensive-override-above-one-on-singleton-declaring-one": Row(
        3, False, 1, True, ResolvedReplicas(1, ReplicaSource.DRIVER_DEFAULT, False)
    ),
    "orphaned-override": Row(
        3, True, None, False, ResolvedReplicas(None, ReplicaSource.CHART, False)
    ),
    "driver-default": Row(
        None, False, 2, False, ResolvedReplicas(2, ReplicaSource.DRIVER_DEFAULT, False)
    ),
    "singleton-without-replicas": Row(
        None,
        False,
        None,
        True,
        ResolvedReplicas(1, ReplicaSource.DRIVER_DEFAULT, False),
    ),
    "singleton-declaring-one": Row(
        None, False, 1, True, ResolvedReplicas(1, ReplicaSource.DRIVER_DEFAULT, False)
    ),
    "chart": Row(
        None, False, None, False, ResolvedReplicas(None, ReplicaSource.CHART, False)
    ),
}


def _resolve(row: Row) -> ResolvedReplicas:
    return resolve_replicas(
        declared_replicas=row.declared_replicas,
        singleton=row.singleton,
        override=row.override,
        is_orphaned=row.is_orphaned,
    )


@pytest.mark.parametrize("row", list(_ROWS.values()), ids=list(_ROWS))
def test_precedence_table_row(row: Row) -> None:
    assert _resolve(row) == row.expected


@pytest.mark.parametrize("row", list(_ROWS.values()), ids=list(_ROWS))
def test_stopped_component_patches_zero(row: Row) -> None:
    assert replica_patch_count(_resolve(row), enabled=False) == 0


@pytest.mark.parametrize("row", list(_ROWS.values()), ids=list(_ROWS))
def test_running_component_patches_resolved_count(row: Row) -> None:
    resolved = _resolve(row)

    count = replica_patch_count(resolved, enabled=True)

    assert count == resolved.count
    if resolved.source is ReplicaSource.CHART:
        assert count is None
    else:
        assert isinstance(count, int)
        assert count >= 1


def test_resolved_replicas_is_frozen() -> None:
    resolved = ResolvedReplicas(2, ReplicaSource.DRIVER_DEFAULT, False)

    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.count = 3  # type: ignore[misc]


def test_replica_source_members() -> None:
    assert [member.name for member in ReplicaSource] == [
        "OVERRIDE",
        "DRIVER_DEFAULT",
        "CHART",
    ]
