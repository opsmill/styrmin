from pathlib import Path
from types import NoneType
from typing import Any

import pytest
import yaml

from styrmin_backend.services.driver.deserializers import (
    DriverSpecDeserializer,
    get_deserializer,
)
from styrmin_backend.services.driver.exceptions import (
    DeserializationError,
)
from styrmin_backend.services.driver.models.resources.driver import DriverSpec
from styrmin_backend.services.driver.models.structure.resource import Role


def set_value(obj: dict, path: str, value: Any):
    """
    Set a value in a nested dictionary using a path and return the modified dictionary.
    """
    keys = path.split(".")
    for key in keys[:-1]:
        try:
            key = int(key)  # type: ignore[assignment]
        except ValueError:
            pass

        obj = obj[key]
    obj[keys[-1]] = value
    return obj


@pytest.fixture
def driver_spec():
    spec_path = (
        Path(__file__).parent
        / "fixtures"
        / "local_driver_directory"
        / "driver.styrmin.yml"
    )
    with open(spec_path) as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize(
    "role, expected_deserializer",
    [
        (Role.DRIVER_SPEC, DriverSpecDeserializer),
        (Role.VALUES_TEMPLATE, NoneType),
        (Role.ACTIONS_CODE, NoneType),
    ],
)
def test_deserializer_factory(role, expected_deserializer):
    """Test the deserializer factory."""
    deserializer = get_deserializer(role)
    assert isinstance(deserializer, expected_deserializer)


def test_deserializer_factory_with_invalid_role():
    """Test the deserializer factory with an invalid role."""
    with pytest.raises(ValueError):
        get_deserializer("invalid-role")


def test_deserialize_valid_driver_spec(driver_spec):
    """Test the deserialization of a valid application driver specification."""

    deserializer = DriverSpecDeserializer()
    data = deserializer.deserialize(data=driver_spec)

    assert isinstance(data, DriverSpec)


def test_deserialize_valid_driver_spec_with_actions(driver_spec):
    """Test that embedded actions are correctly deserialized."""

    deserializer = DriverSpecDeserializer()
    data = deserializer.deserialize(data=driver_spec)

    assert isinstance(data, DriverSpec)
    assert len(data.spec.actions) == 2
    assert data.spec.actions[0].name == "update_password"
    assert data.spec.actions[0].hook.value == "upgrade"
    assert data.spec.actions[1].name == "setup"
    assert data.spec.actions[1].hook.value == "setup"


def test_deserialize_driver_spec_without_actions():
    """Test that a driver spec without actions deserializes correctly."""
    spec_data = {
        "apiVersion": "styrmin.io/v1",
        "kind": "ApplicationDriver",
        "metadata": {"name": "no-actions"},
        "spec": {
            "version": "1",
            "supported_versions": ">=1.0,<2.0",
            "info": {"description": "Test driver"},
            "helm": {"main": {"location": "test-chart", "version": "1.0.0"}},
        },
    }
    deserializer = DriverSpecDeserializer()
    data = deserializer.deserialize(data=spec_data)

    assert isinstance(data, DriverSpec)
    assert data.spec.actions == []


@pytest.mark.parametrize(
    "path,value",
    [
        ("apiVersion", "wrong"),
        ("kind", "wrong"),
        ("metadata.name", 123),
        ("spec.version", 123),
        ("spec.info.icon", 123),
        ("spec.info.description", 123),
        ("spec.info.authors", 123),
        ("spec.info.license", 123),
        ("spec.info.links", 123),
        ("spec.helm.main.location", 123),
        ("spec.helm.main.version", 123),
    ],
)
def test_deserialize_invalid_driver_spec(path, value, driver_spec):
    """Test the deserialization of an invalid application driver specification."""

    # Change the value of the specified path
    path = set_value(obj=driver_spec, path=path, value=value)

    deserializer = DriverSpecDeserializer()
    with pytest.raises(DeserializationError):
        deserializer.deserialize(data=driver_spec)
