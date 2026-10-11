from pathlib import Path
from types import NoneType
from typing import Any

import jinja2
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
from styrmin_backend.services.driver.models.resources.parameters import (
    DriverParameterKind,
)
from styrmin_backend.services.driver.models.resources.services import (
    ServiceKind,
    ServiceScope,
)
from styrmin_backend.services.driver.models.structure.resource import Role

# Path to the real infrahub-mcp Driver artifacts (driver/examples/infrahub-mcp/).
# test file lives at backend/tests/unit/services/driver/, so walk up to repo root.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_INFRAHUB_MCP_DIR = _REPO_ROOT / "driver" / "examples" / "infrahub-mcp"


def _find_key_recursive(tree: Any, target: str) -> bool:
    """Return True if ``target`` appears as a dict key anywhere in ``tree``."""
    if isinstance(tree, dict):
        if target in tree:
            return True
        return any(_find_key_recursive(v, target) for v in tree.values())
    if isinstance(tree, list):
        return any(_find_key_recursive(item, target) for item in tree)
    return False


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
        # An invalid spec.info.icon or spec.info.links is dropped with a
        # warning instead (see test_driver_info.py).
        ("spec.info.description", 123),
        ("spec.info.authors", 123),
        ("spec.info.license", 123),
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


# ---------------------------------------------------------------------------
# infrahub-mcp Driver (015) — deserialize + values render contract.
# Tests load the REAL artifacts under driver/examples/infrahub-mcp/.
# US1 declares only the `infrahub_address` parameter; later chunks (US2/US3)
# extend these same functions to add mcp_read_only / mcp_log_level.
# ---------------------------------------------------------------------------


def test_deserialize_infrahub_mcp_driver_spec():
    """The real infrahub-mcp manifest deserializes to the US1 contract."""
    with open(_INFRAHUB_MCP_DIR / "driver.styrmin.yml") as f:
        raw = yaml.safe_load(f)

    result = DriverSpecDeserializer().deserialize(data=raw)

    assert isinstance(result, DriverSpec)
    assert result.metadata.name == "infrahub-mcp"

    # No actions block => no actions.py required (FR-005).
    assert result.spec.actions == []

    # Exactly one `server` Component with the confirmed selector label.
    assert result.spec.components is not None
    components = result.spec.components.root
    assert list(components.keys()) == ["server"]
    assert components["server"].identifier.label.root == {
        "app.kubernetes.io/name": "infrahub-mcp"
    }

    # Exactly one Service: infrahub-mcp / http / internal / 8001 / server.
    assert result.spec.services is not None
    assert len(result.spec.services) == 1
    service = result.spec.services[0]
    assert service.name == "infrahub-mcp"
    assert service.kind == ServiceKind.HTTP
    assert service.scope == ServiceScope.INTERNAL
    assert service.port == 8001
    assert service.component == "server"

    # `infrahub_address` is a required (no-default) string parameter.
    assert result.spec.parameters is not None
    params = {p.name: p for p in result.spec.parameters}
    assert "infrahub_address" in params
    assert params["infrahub_address"].kind == DriverParameterKind.STRING
    assert params["infrahub_address"].default is None

    # `mcp_read_only` is an optional boolean parameter, default False (US2).
    assert "mcp_read_only" in params
    assert params["mcp_read_only"].kind == DriverParameterKind.BOOLEAN
    assert params["mcp_read_only"].default is False

    # `mcp_log_level` is an enum parameter with four levels, default "info" (US3).
    assert "mcp_log_level" in params
    assert params["mcp_log_level"].kind == DriverParameterKind.ENUM
    assert params["mcp_log_level"].values == ["debug", "info", "warning", "error"]
    assert params["mcp_log_level"].default == "info"


def test_render_infrahub_mcp_values():
    """Rendering the real values.j2.yml yields the US1 rendered-values contract."""
    template_text = (_INFRAHUB_MCP_DIR / "values.j2.yml").read_text()

    # Default case: mcp_read_only False, mcp_log_level "info" (validator-applied
    # defaults — see the parameter-validator tests in test_parameters.py).
    context = {
        "parameters": {
            "infrahub_address": "https://infrahub.example.com",
            "mcp_read_only": False,
            "mcp_log_level": "info",
        },
    }
    rendered_text = jinja2.Template(template_text).render(**context)

    # Valid YAML.
    rendered = yaml.safe_load(rendered_text)

    assert rendered["fullnameOverride"] == "styrmin-infrahub-mcp"
    assert rendered["mcp"]["authMode"] == "token-passthrough"
    assert rendered["infrahub"]["address"] == "https://infrahub.example.com"

    # mcp_read_only flows to mcp.readOnly; default is False (US2).
    assert rendered["mcp"]["readOnly"] is False
    # mcp_log_level flows to mcp.logLevel; default is "info" (US3).
    assert rendered["mcp"]["logLevel"] == "info"

    # token-passthrough stores no credential: no apiToken key anywhere (FR-006).
    assert not _find_key_recursive(rendered, "apiToken")

    # Supplied values flow through: read-only True and a valid enum level (US2/US3).
    overridden_context = {
        "parameters": {
            "infrahub_address": "https://infrahub.example.com",
            "mcp_read_only": True,
            "mcp_log_level": "debug",
        },
    }
    overridden = yaml.safe_load(
        jinja2.Template(template_text).render(**overridden_context)
    )
    assert overridden["mcp"]["readOnly"] is True
    assert overridden["mcp"]["logLevel"] == "debug"
