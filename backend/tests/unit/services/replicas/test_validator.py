"""Unit tests for ``validate_replica_overrides`` (023 T015, research D-005).

An added or changed override on a component the driver version does not declare raises
``UNKNOWN_COMPONENT_REPLICA_OVERRIDE``; the stored value sent again is kept (orphaned). An
override above 1 on a singleton component raises ``SINGLETON_REPLICA_OVERRIDE``, changed or not.
An added or changed override above the server's maximum raises ``REPLICA_COUNT_ABOVE_MAXIMUM``;
the stored value sent again is kept.
"""

from __future__ import annotations

from typing import Any

import pytest

from styrmin_backend.services.driver.models.resources.driver import (
    ArbitrarySectionModel,
)
from styrmin_backend.services.replicas.exceptions import (
    ReplicaCountAboveMaximumError,
    SingletonReplicaOverrideError,
    UnknownComponentReplicaOverrideError,
)
from styrmin_backend.services.replicas.validator import (
    has_replica_overrides,
    validate_replica_overrides,
)

CHECKED_AGAINST = "driver simple-app version 4 (application version 1.0.0)"
MAX_REPLICA_COUNT = 20


def _declaration(name: str, **replica_keys: Any) -> ArbitrarySectionModel:
    return ArbitrarySectionModel.model_validate(
        {"identifier": {"label": {"app.kubernetes.io/name": name}}, **replica_keys}
    )


COMPONENTS = {
    "server": _declaration("server"),
    "worker": _declaration("worker", replicas=2),
    "database": _declaration("database", singleton=True),
}


def _config(**replicas: int | None) -> dict[str, Any]:
    return {
        "components": {name: {"replicas": count} for name, count in replicas.items()}
    }


def _validate(config: dict[str, Any] | None, stored: dict[str, Any] | None) -> None:
    validate_replica_overrides(
        config,
        components=COMPONENTS,
        stored_config=stored,
        checked_against=CHECKED_AGAINST,
        max_replica_count=MAX_REPLICA_COUNT,
    )


@pytest.mark.parametrize(
    "stored",
    [None, _config(), _config(ghost=3)],
    ids=["no-stored-config", "no-stored-override", "changed-stored-override"],
)
def test_new_override_on_unknown_component_is_rejected(
    stored: dict[str, Any] | None,
) -> None:
    with pytest.raises(UnknownComponentReplicaOverrideError) as excinfo:
        _validate(_config(ghost=2), stored)

    assert excinfo.value.error_code == "UNKNOWN_COMPONENT_REPLICA_OVERRIDE"
    assert excinfo.value.error_metadata == {
        "component_name": "ghost",
        "known_components": ["database", "server", "worker"],
        "checked_against": CHECKED_AGAINST,
    }
    assert "'ghost'" in str(excinfo.value)
    assert CHECKED_AGAINST in str(excinfo.value)


def test_unchanged_stored_override_on_undeclared_component_is_accepted() -> None:
    _validate(_config(ghost=2, server=3), _config(ghost=2))


@pytest.mark.parametrize(
    "stored", [None, _config(database=2)], ids=["added", "unchanged-stored"]
)
def test_override_above_one_on_singleton_is_rejected(
    stored: dict[str, Any] | None,
) -> None:
    with pytest.raises(SingletonReplicaOverrideError) as excinfo:
        _validate(_config(database=2), stored)

    assert excinfo.value.error_code == "SINGLETON_REPLICA_OVERRIDE"
    assert excinfo.value.error_metadata == {
        "component_name": "database",
        "requested_replicas": 2,
        "checked_against": CHECKED_AGAINST,
    }
    assert "'database'" in str(excinfo.value)


def test_override_of_one_on_singleton_is_accepted() -> None:
    _validate(_config(database=1), _config(database=2))


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"components": {}},
        {"components": {"database": {}, "ghost": {}}},
        _config(database=None, ghost=None),
    ],
    ids=["no-config", "empty-config", "no-components", "blocks-dropped", "null"],
)
def test_removal_is_accepted(config: dict[str, Any] | None) -> None:
    _validate(config, _config(database=2, ghost=3))


def test_override_on_declared_component_is_accepted() -> None:
    _validate(_config(server=5, worker=1), None)


@pytest.mark.parametrize(
    "stored",
    [None, _config(server=3), _config(server=25)],
    ids=["added", "changed", "lowered"],
)
def test_override_above_the_maximum_is_rejected(stored: dict[str, Any] | None) -> None:
    with pytest.raises(ReplicaCountAboveMaximumError) as excinfo:
        _validate(_config(server=21), stored)

    assert excinfo.value.error_code == "REPLICA_COUNT_ABOVE_MAXIMUM"
    assert excinfo.value.error_metadata == {
        "component_name": "server",
        "requested_replicas": 21,
        "max_replica_count": MAX_REPLICA_COUNT,
    }
    assert "STYRMIN_MAX_REPLICA_COUNT" in str(excinfo.value)


def test_override_at_the_maximum_is_accepted() -> None:
    _validate(_config(server=MAX_REPLICA_COUNT), None)


def test_unchanged_stored_override_above_the_maximum_is_kept() -> None:
    # An administrator lowered the maximum after the override was stored.
    _validate(_config(server=25), _config(server=25))


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (None, False),
        ({}, False),
        ({"components": {"server": {"env_vars": {"A": "1"}}}}, False),
        (_config(server=None), False),
        (_config(server=2), True),
    ],
    ids=["no-config", "empty", "other-override", "cleared", "set"],
)
def test_has_replica_overrides(config: dict[str, Any] | None, expected: bool) -> None:
    assert has_replica_overrides(config) is expected
