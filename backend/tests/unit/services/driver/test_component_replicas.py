"""Driver-side ``replicas`` and ``singleton`` component keys (023, research D-002).

The keys are typed on load, so a bad value fails driver registration with the field path. The
model omits them from ``model_dump()`` at their defaults, so a declaration that uses neither key
is stored and rendered as before (critique E1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from loguru import logger
from styrmin_backend.context.models.components import (
    driver_version_label,
    parse_stored_replica_declaration,
)
from styrmin_backend.services.driver.exceptions import DriverLoadingError
from styrmin_backend.services.driver.loaders import get_local_driver_loader
from styrmin_backend.services.driver.models.resources.driver import (
    ArbitrarySectionModel,
    DriverSpec,
)

_SERVER_LABEL = {"app.kubernetes.io/name": "simple-app"}
_DATABASE_LABEL = {"app.kubernetes.io/name": "postgresql"}


def _driver_spec(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "simple-app"},
        "spec": {
            "version": "0.1.0",
            "supported_versions": ">=0.1,<1.0",
            "info": {"description": "Replica fields fixture"},
            "helm": {"main": {"location": "./src/helm", "version": "0.1.0"}},
            "components": {
                "server": server,
                "database": {"identifier": {"label": _DATABASE_LABEL}},
            },
        },
    }


def _server(**extra: Any) -> dict[str, Any]:
    return {"identifier": {"label": _SERVER_LABEL}, **extra}


def _load(tmp_path: Path, spec: dict[str, Any]) -> DriverSpec:
    """Register-path load: parse + deserialize + cross-field validation."""
    (tmp_path / "driver.styrmin.yml").write_text(yaml.safe_dump(spec))
    (tmp_path / "values.j2.yml").write_text("{}\n")
    driver = get_local_driver_loader(path=str(tmp_path)).load_driver()
    assert isinstance(driver.driver_spec, DriverSpec)
    return driver.driver_spec


def _server_declaration(spec: DriverSpec) -> ArbitrarySectionModel:
    assert spec.spec.components is not None
    return spec.spec.components.root["server"]


def test_replicas_loads(tmp_path: Path) -> None:
    server = _server_declaration(_load(tmp_path, _driver_spec(_server(replicas=2))))

    assert server.replicas == 2
    assert server.singleton is False


def test_singleton_loads(tmp_path: Path) -> None:
    server = _server_declaration(_load(tmp_path, _driver_spec(_server(singleton=True))))

    assert server.singleton is True
    assert server.replicas is None


def test_singleton_with_one_replica_loads(tmp_path: Path) -> None:
    spec = _driver_spec(_server(singleton=True, replicas=1))

    server = _server_declaration(_load(tmp_path, spec))

    assert server.singleton is True
    assert server.replicas == 1


def test_declaration_without_the_keys_reads_defaults(tmp_path: Path) -> None:
    server = _server_declaration(_load(tmp_path, _driver_spec(_server())))

    assert server.replicas is None
    assert server.singleton is False


def test_singleton_with_more_than_one_replica_fails_registration(
    tmp_path: Path,
) -> None:
    with pytest.raises(DriverLoadingError) as exc_info:
        _load(tmp_path, _driver_spec(_server(singleton=True, replicas=3)))

    message = str(exc_info.value)
    assert "spec.components.server:" in message
    assert "singleton" in message
    assert "replicas" in message


@pytest.mark.parametrize(
    "value",
    [0, -1, 2147483648, "2", True, 2.0],
    ids=["zero", "negative", "above-int32", "string", "bool", "float"],
)
def test_invalid_replicas_fails_registration_with_field_path(
    tmp_path: Path, value: object
) -> None:
    with pytest.raises(DriverLoadingError) as exc_info:
        _load(tmp_path, _driver_spec(_server(replicas=value)))

    assert "spec.components.server.replicas" in str(exc_info.value)


@pytest.mark.parametrize("value", ["yes", 1, "true"], ids=["yes", "int", "string"])
def test_non_bool_singleton_fails_registration_with_field_path(
    tmp_path: Path, value: object
) -> None:
    with pytest.raises(DriverLoadingError) as exc_info:
        _load(tmp_path, _driver_spec(_server(singleton=value)))

    assert "spec.components.server.singleton" in str(exc_info.value)


def test_dump_without_the_keys_equals_the_dump_before_the_change(
    tmp_path: Path,
) -> None:
    spec = _load(tmp_path, _driver_spec(_server(container="simple-app", port=8000)))

    assert spec.spec.components is not None
    # The shape ``applications.py`` stored before 023: fields plus extras, no new keys.
    assert spec.spec.components.model_dump() == {
        "server": {
            "identifier": {"label": _SERVER_LABEL},
            "container": "simple-app",
            "port": 8000,
        },
        "database": {"identifier": {"label": _DATABASE_LABEL}, "container": None},
    }
    assert (
        spec.spec.components.model_dump(mode="json")
        == spec.spec.components.model_dump()
    )


def test_dump_keeps_the_keys_when_set(tmp_path: Path) -> None:
    spec = _load(tmp_path, _driver_spec(_server(replicas=2, singleton=False)))

    dumped = _server_declaration(spec).model_dump()
    assert dumped["replicas"] == 2
    assert "singleton" not in dumped

    spec = _load(tmp_path, _driver_spec(_server(singleton=True)))
    dumped = _server_declaration(spec).model_dump()
    assert dumped["singleton"] is True
    assert "replicas" not in dumped


def test_dumped_declaration_round_trips(tmp_path: Path) -> None:
    spec = _load(tmp_path, _driver_spec(_server(replicas=1, singleton=True)))
    server = _server_declaration(spec)

    assert ArbitrarySectionModel.model_validate(server.model_dump()) == server


class TestParseStoredReplicaDeclaration:
    @pytest.fixture
    def warnings(self) -> Any:
        messages: list[str] = []
        sink = logger.add(messages.append, level="WARNING", format="{message}")
        yield messages
        logger.remove(sink)

    def test_valid_declaration_parses_unchanged(self, warnings: list[str]) -> None:
        declaration = parse_stored_replica_declaration(
            _server(replicas=2, container="simple-app"), component="server"
        )

        assert declaration.replicas == 2
        assert declaration.singleton is False
        assert warnings == []

    def test_invalid_stored_replicas_is_dropped_and_named(
        self, warnings: list[str]
    ) -> None:
        declaration = parse_stored_replica_declaration(
            _server(replicas="3", singleton=True, port=8000),
            component="server",
            driver_version=driver_version_label("adv-3"),
        )

        assert declaration.replicas is None
        # The valid key is kept: only the invalid one reads as unset.
        assert declaration.singleton is True
        assert len(warnings) == 1
        assert "replicas='3'" in warnings[0]
        assert "singleton" not in warnings[0]
        assert "server" in warnings[0]
        assert "driver version adv-3" in warnings[0]

    def test_invalid_stored_singleton_is_dropped_with_a_warning(
        self, warnings: list[str]
    ) -> None:
        declaration = parse_stored_replica_declaration(
            _server(singleton="yes", replicas=2), component="server"
        )

        assert declaration.singleton is False
        assert declaration.replicas == 2
        assert len(warnings) == 1
        assert "singleton='yes'" in warnings[0]

    def test_stored_contradiction_keeps_singleton(self, warnings: list[str]) -> None:
        declaration = parse_stored_replica_declaration(
            _server(singleton=True, replicas=3), component="server"
        )

        assert declaration.replicas is None
        assert declaration.singleton is True
        assert len(warnings) == 1
        assert "replicas=3" in warnings[0]

    def test_problems_outside_the_replica_keys_do_not_raise(
        self, warnings: list[str]
    ) -> None:
        # No identifier and an invalid container name: only the replica keys are read.
        declaration = parse_stored_replica_declaration(
            {"replicas": 2, "container": "Bad_Name"}, component="server"
        )

        assert declaration.replicas == 2
        assert warnings == []

    def test_does_not_mutate_the_stored_dict(self, warnings: list[str]) -> None:
        raw = _server(replicas="3")

        parse_stored_replica_declaration(raw, component="server")

        assert raw["replicas"] == "3"
